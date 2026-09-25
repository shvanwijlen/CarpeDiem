"""Pushes the Pi's data to a remote datastore, which the phone app reads from.

The boat's Pi initiates every connection (outbound HTTPS only), so nothing
on the boat has to be reachable from outside and no VPN is needed. The phone
never talks to the Pi for its regular data; it reads the store.

What the datastore is stays swappable: Publisher only knows the PublishBackend
interface below. HttpStoreBackend speaks the HTTP API in server/ (the store
that runs on the Synology NAS), and anything else that implements the same API
- e.g. a Cloudflare Worker with KV/D1 - works with it unchanged. A datastore
with its own wire protocol (Supabase REST, ...) is one more PublishBackend
subclass, registered in BACKENDS.

Each cycle sends one JSON document - {"sent_at", "data", "vessels", "system"},
built by api_payloads.py, so it's identical to what the local /api/* routes
return - plus any camera snapshot the Ring poll has written since last time.
A failed push is just retried next cycle: the store always holds the latest
state, so there is nothing to queue up or replay.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import aiohttp

from carpediem.api_payloads import data_payload, system_payload, vessels_payload
from carpediem.config import config
from carpediem.logging_setup import log
from carpediem.publish_status import FAILURES_BEFORE_ALERT, publish_status
from carpediem.ring_client import snapshot_key

if TYPE_CHECKING:
    from carpediem.ais.service import AisService

MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024  # the store's own limit - see server/carpediem_store/app.py
# Log the first failure, then only every Nth repeat, so a boat with no
# internet for a day doesn't fill the log with one identical line per push.
LOG_EVERY_NTH_FAILURE = 30


def _describe(exc: Exception) -> str:
    """"ClientConnectorError: Cannot connect to host ...", or just "TimeoutError" when the exception has no message."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


class PublishBackend(ABC):
    @abstractmethod
    async def push_state(self, payload: dict[str, Any]) -> None:
        """Send the latest state. Raises on any failure."""

    @abstractmethod
    async def push_snapshot(self, name: str, jpeg: bytes) -> None:
        """Send the latest JPEG for camera `name`. Raises on any failure."""

    @abstractmethod
    async def close(self) -> None: ...


class HttpStoreBackend(PublishBackend):
    """The CarpeDiem store HTTP API (server/README.md): PUT /v1/state and
    PUT /v1/cam/<name>/snapshot, authenticated with the store's write key."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self._base_url = base_url
        self._headers = {"X-API-Key": api_key}
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
        return self._session

    async def push_state(self, payload: dict[str, Any]) -> None:
        # allow_nan=False: fail loudly here rather than send JSON a non-Python store would reject.
        body = gzip.compress(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode())
        async with self._get_session().put(
            f"{self._base_url}/v1/state", data=body,
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
        ) as resp:
            await self._check(resp)

    async def push_snapshot(self, name: str, jpeg: bytes) -> None:
        async with self._get_session().put(
            f"{self._base_url}/v1/cam/{name}/snapshot", data=jpeg, headers={"Content-Type": "image/jpeg"},
        ) as resp:
            await self._check(resp)

    @staticmethod
    async def _check(resp: aiohttp.ClientResponse) -> None:
        if resp.status == 401:
            raise RuntimeError("store rejected the API key - PUBLISH_API_KEY must be the store's WRITE_API_KEY")
        if resp.status >= 400:
            raise RuntimeError(f"store answered HTTP {resp.status}: {(await resp.text())[:200]}")

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


def _make_http_store() -> PublishBackend:
    return HttpStoreBackend(config.publish.url, config.publish.api_key, config.publish.request_timeout_seconds)


# PUBLISH_BACKEND value -> factory. "synology" and "http" are the same client
# under two names (see PublishConfig).
BACKENDS = {
    "synology": _make_http_store,
    "http": _make_http_store,
}


class Publisher:
    def __init__(self, ais_service: "AisService | None" = None) -> None:
        self._ais_service = ais_service
        self._backend: PublishBackend | None = None
        self._snapshot_mtimes: dict[str, float] = {}  # camera key -> mtime of the file last pushed

    def build_payload(self) -> dict[str, Any]:
        return {
            "sent_at": time.time(),
            "data": data_payload(),
            "vessels": vessels_payload(self._ais_service),
            "system": system_payload(),
        }

    async def run_forever(self) -> None:
        cfg = config.publish
        # From here on the SYS lamp watches the pushes (see publish_status.py).
        publish_status.enabled = True
        factory = BACKENDS.get(cfg.backend)
        if factory is None:
            message = f"unknown PUBLISH_BACKEND '{cfg.backend}' (available: none, {', '.join(BACKENDS)})"
            log(9, f"Publisher: {message} - not publishing")
            publish_status.mark_failed(message, alert_now=True)
            return
        if not cfg.url.startswith(("http://", "https://")) or not cfg.api_key:
            message = "PUBLISH_URL (http:// or https://) and PUBLISH_API_KEY must both be set"
            log(9, f"Publisher: {message} - not publishing")
            publish_status.mark_failed(message, alert_now=True)
            return
        self._backend = factory()
        log(9, f"Publisher: pushing to {cfg.backend} store at {cfg.url} every {cfg.interval_seconds:g}s")

        snapshot_failures = 0
        while True:
            try:
                await self._backend.push_state(self.build_payload())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any failure just means "try again next cycle"
                publish_status.mark_failed(_describe(exc))
                failures = publish_status.consecutive_failures
                if failures == 1 or failures % LOG_EVERY_NTH_FAILURE == 0:
                    log(9, f"Publisher: push failed ({failures} in a row), will retry: {publish_status.last_error}")
                if failures == FAILURES_BEFORE_ALERT:
                    log(9, f"Publisher: {failures} pushes in a row failed - the SYS lamp turns purple until one gets through")
            else:
                if publish_status.consecutive_failures:
                    log(9, f"Publisher: store reachable again after {publish_status.consecutive_failures} failed push(es)")
                publish_status.mark_ok()
                # Camera snapshots ride along, but their trouble (say, one oversized file) is not
                # "can't reach the store", so it is logged separately and doesn't drive the lamp.
                try:
                    await self._push_new_snapshots()
                    snapshot_failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    snapshot_failures += 1
                    if snapshot_failures == 1 or snapshot_failures % LOG_EVERY_NTH_FAILURE == 0:
                        log(9, f"Publisher: snapshot push failed ({snapshot_failures} in a row), will retry: "
                               f"{_describe(exc)}")
            await asyncio.sleep(cfg.interval_seconds)

    async def _push_new_snapshots(self) -> None:
        """Pushes every camera snapshot file that has been (re)written since it was last pushed."""
        assert self._backend is not None
        for battery_field in config.ring.camera_field_map.values():
            key = snapshot_key(battery_field)
            path = config.ring.snapshot_dir / f"{key}.jpg"
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue  # no snapshot on disk (yet)
            if mtime <= self._snapshot_mtimes.get(key, 0.0):
                continue
            jpeg = await asyncio.to_thread(path.read_bytes)
            if len(jpeg) > MAX_SNAPSHOT_BYTES:
                log(9, f"Publisher: snapshot '{key}' is {len(jpeg)} bytes, over the store's limit - skipping")
                self._snapshot_mtimes[key] = mtime
                continue
            await self._backend.push_snapshot(key, jpeg)
            self._snapshot_mtimes[key] = mtime
            log(10, f"Publisher: pushed snapshot '{key}' ({len(jpeg)} bytes)")

    async def close(self) -> None:
        if self._backend is not None:
            await self._backend.close()
            self._backend = None
