"""Polls Ring's cloud API for camera battery levels, via the unofficial
ring-doorbell package (Ring has no official public API - this is the same
reverse-engineered client Home Assistant's Ring integration is built on).

Auth is handled out-of-band: run scripts/ring_auth_setup.py once,
interactively, to do the password + 2FA handshake and cache a refresh
token to config.ring.token_file. This client only ever reads that cached
token - if it's missing or Ring rejects it (revoked, expired, account
locked, ...), "Cam" is reported as 0 and polling keeps retrying, same
pattern as the other subsystem status flags (see display_data.py).
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


def _load_cached_token() -> dict | None:
    if not config.ring.token_file.exists():
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
        cameras = {cam.name: cam for group in devices.values() for cam in group}
        for cam_name, field in config.ring.camera_field_map.items():
            cam = cameras.get(cam_name)
            if cam is None:
                log(9, f"Ring: camera '{cam_name}' not found in account (have: {list(cameras)})")
                continue
            if cam.battery_life is None:
                continue
            display_data.update(field, cam.battery_life, source="R")
