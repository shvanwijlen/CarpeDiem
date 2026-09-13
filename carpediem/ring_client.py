"""Polls Ring's cloud API for camera battery levels and per-camera
connection status ("online"/"offline"), via the unofficial
ring-doorbell package (Ring has no official public API - this is the same
reverse-engineered client Home Assistant's Ring integration is built on).

Auth is handled out-of-band: run scripts/ring_auth_setup.py once,
interactively, to do the password + 2FA handshake and cache a refresh
token to config.ring.token_file. This client only ever reads that cached
token - if it's missing or Ring rejects it (revoked, expired, account
locked, ...), "Cam" is reported as 0 and polling keeps retrying, same
pattern as the other subsystem status flags (see display_data.py).

Snapshot fetching (config.ring.fetch_snapshots, off by default) is the
Cam page's "level 2": a still JPEG per camera, written to
config.ring.snapshot_dir/<key>.jpg each poll, where <key> is the battery
field name with the "RingBattery" prefix stripped and lowercased (e.g.
"RingBatterySalon" -> "salon.jpg") - the Cam page derives the same key
from camera_field_map so the two stay in sync without a shared constant.
Off by default since a boat's internet is often metered and a JPEG per
camera every poll is a lot more data than the battery/connection poll.
"""
from __future__ import annotations

import asyncio
import json

import aiohttp
from ring_doorbell import Auth, Ring

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

USER_AGENT = "CarpeDiem/1.0"


def snapshot_key(battery_field: str) -> str:
    """"RingBatterySalon" -> "salon" - the file-name stem shared between
    the snapshot writer here and the Cam page's reader, so both derive it
    from the same camera_field_map value instead of a separate constant."""
    return battery_field.replace("RingBattery", "").lower()


def _load_cached_token() -> dict | None:
    log(9, f"Ring : starting up... Looking fore cached token at {config.ring.token_file}")
    if not config.ring.token_file.exists():
        log(9, f"Ring : token file not found at {config.ring.token_file} - run scripts/ring_auth_setup.py once to authenticate")
        return None
    try:
        return json.loads(config.ring.token_file.read_text())
    except (ValueError, OSError) as exc:
        log(9, f"Ring: failed to read cached token file: {exc}")
        return None


def _save_token(token: dict) -> None:
    config.ring.token_file.write_text(json.dumps(token))


class RingClient:
    """Maintains a Ring cloud session and polls camera battery levels on a
    fixed interval, writing results into the shared display_data store."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._ring: Ring | None = None

    async def run_forever(self) -> None:
        while True:
            try:
                await self._poll_once()
                display_data.update("Cam", 1, source="S")
            except Exception as exc:  # noqa: BLE001 - anything here means "cameras unreachable"
                log(9, f"Ring: poll failed: {exc}")
                display_data.update("Cam", 0, source="S")
            await asyncio.sleep(config.ring.poll_interval_seconds)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # -- internals -------------------------------------------------------
    async def _ensure_ring(self) -> Ring:
        if self._ring is not None:
            return self._ring
        token = _load_cached_token()
        if token is None:
            raise RuntimeError(
                f"no cached Ring token at {config.ring.token_file} - "
                "run scripts/ring_auth_setup.py once to authenticate"
            )
        self._session = aiohttp.ClientSession()
        auth = Auth(USER_AGENT, token, _save_token, http_client_session=self._session)
        self._ring = Ring(auth)
        await self._ring.async_create_session()
        return self._ring

    async def _poll_once(self) -> None:
        try:
            ring = await self._ensure_ring()
            await ring.async_update_data()
        except Exception:
            # Auth may have been revoked / gone stale - drop the session so
            # the next poll starts clean instead of retrying a dead one.
            await self.close()
            self._ring = None
            raise

        devices = ring.devices()
        cameras = {cam.name: cam for cam in devices.all_devices}
        connection_fields = config.ring.camera_connection_field_map
        for cam_name, battery_field in config.ring.camera_field_map.items():
            cam = cameras.get(cam_name)
            if cam is None:
                log(9, f"Ring: camera '{cam_name}' not found in account (have: {list(cameras)})")
                continue
            if cam.battery_life is not None:
                display_data.update(battery_field, cam.battery_life, source="R")
            if cam.connection_status is not None:
                display_data.update(connection_fields[cam_name], cam.connection_status, source="R")
            if config.ring.fetch_snapshots:
                await self._fetch_snapshot(cam, battery_field)

    async def _fetch_snapshot(self, cam, battery_field: str) -> bool:
        key = snapshot_key(battery_field)
        # ring_doorbell's async_get_snapshot() polls a "is there a newer
        # timestamp yet" endpoint (retries x delay seconds, 3x1s by
        # default) and only then downloads the image - too tight a window
        # for a battery/sleep-cycling camera to wake, capture and upload.
        # Passing bigger retries/delay gives it more patience. Separately,
        # ring_doorbell has a real bug here: if that timestamp-check
        # response ever comes back with an empty "timestamps" list, it
        # indexes [0] unconditionally and raises IndexError instead of
        # retrying - not something we can fix in a third-party library, so
        # we retry the *whole call* a couple of times ourselves, since a
        # fresh attempt can get a populated response even when one attempt
        # hit the empty-list case.
        last_exc: Exception | None = None
        for attempt in range(1, 3):
            log(9, f"Ring: requesting snapshot from Ring's API for '{key}' (attempt {attempt}/2)...")
            try:
                data = await cam.async_get_snapshot(retries=8, delay=2)
            except Exception as exc:  # noqa: BLE001 - one camera's snapshot failing shouldn't skip the rest
                last_exc = exc
                log(9, f"Ring: snapshot fetch attempt {attempt} for '{key}' raised: {exc!r}")
                continue
            if not data:
                log(9, f"Ring: snapshot fetch attempt {attempt} for '{key}' returned no data "
                       f"(camera may be offline/asleep)")
                continue
            config.ring.snapshot_dir.mkdir(parents=True, exist_ok=True)
            path = config.ring.snapshot_dir / f"{key}.jpg"
            path.write_bytes(data)
            log(9, f"Ring: snapshot for '{key}' saved to {path} ({len(data)} bytes)")
            return True
        if last_exc is not None:
            log(9, f"Ring: snapshot fetch for '{key}' failed after 2 attempts, last error: {last_exc!r}")
        else:
            log(9, f"Ring: snapshot fetch for '{key}' failed after 2 attempts - no data both times")
        return False

    async def fetch_snapshot_now(self, cam_name: str) -> bool:
        """One-off snapshot fetch for a single camera, bypassing both the
        fetch_snapshots config gate and the poll interval - used by the Cam
        page's tap-to-fetch. Works even in fake-data mode (where do_ring is
        normally forced off) since it's a direct, explicit user action, not
        the background poll loop; still needs a real cached Ring token to
        succeed, same as everything else in this module."""
        battery_field = config.ring.camera_field_map.get(cam_name)
        if battery_field is None:
            log(9, f"Ring: fetch_snapshot_now - unknown camera '{cam_name}' "
                   f"(known: {list(config.ring.camera_field_map)})")
            return False
        try:
            ring = await self._ensure_ring()
            await ring.async_update_data()
        except Exception as exc:  # noqa: BLE001 - report failure, don't crash the tap handler
            log(9, f"Ring: fetch_snapshot_now - couldn't get a session: {exc!r}")
            await self.close()
            self._ring = None
            return False
        cameras = {c.name: c for c in ring.devices().all_devices}
        cam = cameras.get(cam_name)
        if cam is None:
            log(9, f"Ring: fetch_snapshot_now - camera '{cam_name}' not found in account "
                   f"(have: {list(cameras)})")
            return False
        return await self._fetch_snapshot(cam, battery_field)
