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

watch_live()/stop_live_view() are the Cam page's "level 3": a real-time
WebRTC Live View session (the same mechanism the Ring app itself uses),
for the cameras where fetch_snapshot_now() structurally can't work at all
(Ring's own support confirms the 3rd Gen Stick Up Cam Battery has no
Snapshot API support - see fetch_snapshot_now()'s docstring). The actual
WebRTC peer connection lives in ring_live_view.py, kept separate since it
needs a real WebRTC client library (aiortc) this module otherwise has no
reason to depend on. Each camera gets its own independent RingLiveView -
all 4 can be watched simultaneously - since a Pi decoding 4 video streams
at once alongside the rest of this app is a real, currently-unverified
resource question, not a code one; if that turns out to be too heavy,
the fix is at the Cam page's call site (watch fewer at once), not here.
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Callable, Optional

import aiohttp
from ring_doorbell import Auth, Ring

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

if TYPE_CHECKING:
    # Only for the type hint below - watch_live() imports the real thing
    # lazily at runtime so aiortc stays an optional dependency (see there).
    from carpediem.ring_live_view import FrameCallback

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
        self._live_views: dict = {}  # cam_name -> RingLiveView, created lazily - see watch_live()

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
        """Full shutdown - stops every live view too. Session-refresh
        failures (see _reset_session()) deliberately do *not* call this:
        with several cameras potentially live at once, a transient hiccup
        refreshing the aiohttp session shouldn't tear down every other
        camera's still-working video feed."""
        for live_view in self._live_views.values():
            await live_view.stop()
        self._live_views.clear()
        await self._reset_session()

    async def _reset_session(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._ring = None

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
            # Auth may have been revoked / gone stale - drop the session
            # (not the whole client, and not any live views - see
            # _reset_session()'s docstring) so the next poll starts clean
            # instead of retrying a dead one.
            await self._reset_session()
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
        # for a battery/sleep-cycling camera to wake, capture and upload,
        # so we pass more patience for that case.
        #
        # Separately: Ring's own support has confirmed the 3rd Gen Stick
        # Up Cam (Battery) doesn't support on-demand snapshots at all -
        # https://community.ring.com/t/3rd-generation-stick-up-cam-battery-version-and-does-not-have-the-snapshot-feature/43963
        # For those, the timestamp-check endpoint returns an empty
        # "timestamps" list, and ring_doorbell indexes [0] unconditionally
        # instead of handling that, raising IndexError. That's a hardware/
        # platform limitation, not a timing issue - retrying a slow-to-wake
        # camera helps, but retrying an IndexError never will, so it fails
        # fast instead of burning a second ~16s attempt on a camera model
        # that will never succeed.
        try:
            data = await cam.async_get_snapshot(retries=8, delay=2)
        except IndexError:
            log(9, f"Ring: '{key}' has no snapshot timestamps at all - this camera model likely "
                   f"doesn't support on-demand snapshots (known Ring limitation on the 3rd Gen "
                   f"Stick Up Cam Battery); not retrying")
            return False
        except Exception as exc:  # noqa: BLE001 - one camera's snapshot failing shouldn't skip the rest
            log(9, f"Ring: snapshot fetch for '{key}' raised: {exc!r}")
            return False
        if not data:
            log(9, f"Ring: snapshot fetch for '{key}' returned no data even after {8 * 2}s of "
                   f"polling (camera may be offline/asleep, or doesn't support snapshots)")
            return False
        config.ring.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = config.ring.snapshot_dir / f"{key}.jpg"
        path.write_bytes(data)
        log(9, f"Ring: snapshot for '{key}' saved to {path} ({len(data)} bytes)")
        return True

    async def fetch_snapshot_now(self, cam_name: str) -> bool:
        """One-off snapshot fetch for a single camera, bypassing both the
        fetch_snapshots config gate and the poll interval - used by the Cam
        page's tap-to-fetch. Works even in fake-data mode (where do_ring is
        normally forced off) since it's a direct, explicit user action, not
        the background poll loop; still needs a real cached Ring token to
        succeed, same as everything else in this module."""
        cam = await self._get_camera(cam_name)
        if cam is None:
            return False
        battery_field = config.ring.camera_field_map[cam_name]
        return await self._fetch_snapshot(cam, battery_field)

    async def watch_live(self, cam_name: str, on_frame: "FrameCallback", *,
                         on_ended: Optional[Callable[[], None]] = None) -> bool:
        """Start (or restart) a real-time WebRTC "Live View" session for
        one camera - see ring_live_view.py's docstring for why this exists
        alongside fetch_snapshot_now(): the Snapshot API doesn't work on
        every camera model, Live View does. Independent per camera - watch
        several at once by calling this for each; it doesn't stop any
        other camera's session."""
        cam = await self._get_camera(cam_name)
        if cam is None:
            return False
        live_view = self._live_views.get(cam_name)
        if live_view is None:
            try:
                from carpediem.ring_live_view import RingLiveView
            except ImportError as exc:
                log(9, f"Ring: live view unavailable - aiortc isn't installed ({exc!r}); "
                       f"see requirements.txt's Live View section")
                return False
            live_view = RingLiveView()
            self._live_views[cam_name] = live_view
        return await live_view.start(cam_name, cam, on_frame, on_ended=on_ended)

    async def stop_live_view(self, cam_name: str) -> None:
        live_view = self._live_views.get(cam_name)
        if live_view is not None:
            await live_view.stop()

    async def _get_camera(self, cam_name: str):
        """Shared by fetch_snapshot_now() and watch_live(): get/refresh a
        session and look up one camera by name, logging exactly why on
        any failure."""
        battery_field = config.ring.camera_field_map.get(cam_name)
        if battery_field is None:
            log(9, f"Ring: unknown camera '{cam_name}' (known: {list(config.ring.camera_field_map)})")
            return None
        try:
            ring = await self._ensure_ring()
            await ring.async_update_data()
        except Exception as exc:  # noqa: BLE001 - report failure, don't crash the caller
            log(9, f"Ring: couldn't get a session for '{cam_name}': {exc!r}")
            await self._reset_session()
            return None
        cameras = {c.name: c for c in ring.devices().all_devices}
        cam = cameras.get(cam_name)
        if cam is None:
            log(9, f"Ring: camera '{cam_name}' not found in account (have: {list(cameras)})")
            return None
        return cam
