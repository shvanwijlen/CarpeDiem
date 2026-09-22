"""Lightweight read-only HTTP JSON API exposing the shared display_data
store, for external consumers over the NordVPN Meshnet overlay - an
Arduino sketch driving a Waveshare e-ink display first, and eventually an
iPhone app. No authentication - see config.py's WebServerConfig for why
that's an acceptable tradeoff here.

Built on aiohttp.web rather than a separate framework like Flask:
aiohttp is already a project dependency (used for the various HTTP API
clients - bresser_rtl_client.py aside), and being async lets this run as
just another task in the same asyncio event loop as everything else in
main.py, rather than needing its own thread/process the way a sync WSGI
server would.

GET /api/data returns the full display_data snapshot as one flat JSON
object ({internal_label: value, ...} - see display_data.py for the field
list). Consumers pick out whichever fields they care about; nothing here
curates a subset - "expose all data elements" was the actual ask, and
letting the Arduino/iPhone side decide what to use avoids having to keep
a second, duplicate list of fields in sync with display_data.py's.

GET /api/cam/<name>/snapshot.jpg and GET /api/cam/<name>/live.jpg give the
phone app the same two camera tiers the Qt Cam page has (see
hmi_qt/pages/cam_page.py's docstring): a still image written to disk by
ring_client.py's background poll (only if RING_FETCH_SNAPSHOTS is on), and
an on-demand real-time feed. Live View is a bounded WebRTC session
(ring_client.watch_live()/ring_live_view.py) - the same mechanism the Qt
Cam page drives directly in-process; here it's bridged to plain polled
JPEGs (_encode_jpeg() below) so a phone that has no WebRTC stack can just
poll an <Image> at a couple of frames a second. A session is started
lazily on the first live.jpg request for a camera and stopped again by
_cam_idle_reaper() once nobody's polled it for a while - see there.
"""
from __future__ import annotations

import asyncio
import difflib
import hmac
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Optional

from aiohttp import web

from carpediem.ais.service import DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log
from carpediem.ring_client import snapshot_key
from carpediem.sysmetrics_monitor import summary_rows, sysmetrics_monitor

if TYPE_CHECKING:
    from carpediem.ais.service import AisService
    from carpediem.ring_client import RingClient

# Live View tuning - see the module docstring above and _cam_idle_reaper()/
# _handle_cam_live() below.
LIVE_IDLE_TIMEOUT_SECONDS = 12.0   # stop an unpolled Live View session after this long
LIVE_REAPER_INTERVAL_SECONDS = 4.0
LIVE_FIRST_FRAME_WAIT_SECONDS = 4.0  # how long a request waits before answering "connecting"
JPEG_QUALITY = 70


def _encode_jpeg(frame) -> bytes:
    """RGB ndarray -> JPEG bytes. Pillow is imported lazily here, same
    pattern as aiortc in ring_client.watch_live() - it's only needed if a
    client actually hits /api/cam/<name>/live.jpg."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(frame, "RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


@web.middleware
async def _api_key_middleware(request: web.Request, handler):
    """Enforces config.webserver.api_key on every /api/ route (read at request
    time, so it can't be bypassed by ordering). "/" stays open - it only says
    what this is. Constant-time comparison so response timing can't be used
    to guess the key."""
    key = config.webserver.api_key
    if key and request.path.startswith("/api/"):
        supplied = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied.encode(), key.encode()):
            return web.json_response({"error": "missing or wrong API key"}, status=401)
    return await handler(request)


class WebServer:
    def __init__(self, ais_service: AisService | None = None, ring_client: "RingClient | None" = None) -> None:
        self._runner: web.AppRunner | None = None
        self._ais_service = ais_service
        self._ring_client = ring_client

        # Live View relay state - see _handle_cam_live()/_cam_idle_reaper().
        self._cam_frames: dict[str, bytes] = {}  # cam_name -> latest JPEG
        self._cam_frame_events: dict[str, asyncio.Event] = {}  # set once a session's first frame arrives
        self._cam_starting: set[str] = set()  # cam_names with a start-session task in flight
        self._cam_last_poll: dict[str, float] = {}  # cam_name -> monotonic time of its last live.jpg request
        self._cam_reaper_task: Optional[asyncio.Task] = None

    async def run_forever(self) -> None:
        app = web.Application(middlewares=[_api_key_middleware])
        app.router.add_get("/", self._handle_root)
        app.router.add_get("/api/data", self._handle_data)
        app.router.add_get("/api/vessels", self._handle_vessels)
        app.router.add_get("/api/system", self._handle_system)
        app.router.add_get("/api/fake", self._handle_fake_list)
        app.router.add_post("/api/fake", self._handle_fake_set)
        app.router.add_delete("/api/fake", self._handle_fake_reset)
        app.router.add_get("/api/cam/{name}/snapshot.jpg", self._handle_cam_snapshot)
        app.router.add_get("/api/cam/{name}/live.jpg", self._handle_cam_live)

        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, config.webserver.host, config.webserver.port)
            await site.start()
        except Exception as exc:  # noqa: BLE001 - e.g. the port's already in use
            log(9, f"WebServer: failed to listen on {config.webserver.host}:{config.webserver.port}: {exc}")
            display_data.update("WebServer", 0, source="S")
            await runner.cleanup()
            return

        self._runner = runner
        self._cam_reaper_task = asyncio.create_task(self._cam_idle_reaper())
        display_data.update("WebServer", 1, source="S")
        log(9, f"WebServer: listening on {config.webserver.host}:{config.webserver.port} (GET /api/data) - "
               + ("API key required" if config.webserver.api_key else "no API key set (open to anyone who can reach this port)"))

        # aiohttp's TCPSite serves requests via the event loop in the
        # background - this task just needs to stay alive (so main.py's
        # task list has something to cancel) until close() tears it down.
        await asyncio.Event().wait()

    async def _handle_root(self, request: web.Request) -> web.Response:
        return web.Response(text="CarpeDiem data API - see GET /api/data\n")

    async def _handle_data(self, request: web.Request) -> web.Response:
        snapshot = display_data.snapshot()
        payload = {label: field.value for label, field in snapshot.items()}
        return web.json_response(payload)

    async def _handle_vessels(self, request: web.Request) -> web.Response:
        """Nearby AIS vessels for a radar view - lives outside display_data
        (it's a list, not a scalar field), so it's its own endpoint. The
        `category` mirrors hmi_qt's main_page._refresh_radar() color logic:
        moored (~stationary), overtaking (behind us and faster - the
        danger case), fast (above FAST_VESSEL_THRESHOLD_KMH), else ok."""
        payload: dict = {"max_range_km": config.ais.max_range_km, "vessels": []}
        svc = self._ais_service
        if svc is not None:
            own = svc.reader.own_fix
            own_speed_knots = own.sog_knots or 0.0
            own_cog = own.cog if own.cog is not None else DEFAULT_OWN_COG_DEG
            for r in svc.nearby_vessels():
                if r.relative_bearing_deg is None:
                    continue
                sog_knots = r.vessel.sog_knots or 0.0
                if sog_knots < 0.2:
                    category, heading = "moored", 0.0
                else:
                    if abs(r.relative_bearing_deg) > 90 and sog_knots > own_speed_knots:
                        category = "overtaking"
                    elif sog_knots * 1.852 > FAST_VESSEL_THRESHOLD_KMH:
                        category = "fast"
                    else:
                        category = "ok"
                    heading = ((r.vessel.cog_deg - own_cog) % 360
                               if r.vessel.cog_deg is not None else r.relative_bearing_deg)
                payload["vessels"].append({
                    "mmsi": r.vessel.mmsi,
                    "name": r.vessel.name,
                    "bearing_deg": r.relative_bearing_deg,
                    "distance_km": r.distance_km,
                    "speed_knots": r.vessel.sog_knots,
                    "heading_deg": heading,
                    "category": category,
                })
        return web.json_response(payload)

    async def _handle_system(self, request: web.Request) -> web.Response:
        """CPU/memory/disk health of the Pi itself - what feeds the HMI
        top bar's SYS lamp. Its own endpoint rather than a display_data
        field because sysmetrics_monitor.py deliberately keeps these
        host stats out of display_data (they aren't boat telemetry).
        status is "ok" | "warn" | "crit", or null when the monitor is off
        (CARPEDIEM_CHECK_SYSMETRICS=false) or hasn't sampled yet."""
        metrics = sysmetrics_monitor.latest
        if metrics is None:
            return web.json_response({"status": None})
        payload = asdict(metrics)
        # Pre-formatted lines (value text + level + bar fraction) so the phone
        # shows exactly what the Pi's own popup does, thresholds included.
        payload["rows"] = [asdict(r) for r in summary_rows(metrics)]
        return web.json_response(payload)

    # -- camera feeds: a disk snapshot (level 2) and an on-demand Live View
    # relay (level 3) - see the module docstring and _cam_idle_reaper(). --

    async def _handle_cam_snapshot(self, request: web.Request) -> web.StreamResponse:
        cam_name = request.match_info["name"]
        if cam_name not in config.ring.camera_field_map:
            return web.json_response({"error": f"unknown camera '{cam_name}'"}, status=404)
        key = snapshot_key(config.ring.camera_field_map[cam_name])
        path = config.ring.snapshot_dir / f"{key}.jpg"
        if not path.is_file():
            return web.json_response(
                {"error": "no snapshot on disk yet (RING_FETCH_SNAPSHOTS may be off, or none has arrived yet)"},
                status=404)
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def _handle_cam_live(self, request: web.Request) -> web.Response:
        cam_name = request.match_info["name"]
        if cam_name not in config.ring.camera_field_map:
            return web.json_response({"error": f"unknown camera '{cam_name}'"}, status=404)
        if self._ring_client is None:
            return web.json_response({"error": "Ring isn't configured on this Pi"}, status=503)

        self._cam_last_poll[cam_name] = time.monotonic()

        if cam_name not in self._cam_frames and cam_name not in self._cam_starting:
            self._cam_starting.add(cam_name)
            # Created here, synchronously, rather than inside the scheduled
            # task below - the wait a few lines down fetches this same
            # Event object immediately, before _start_cam_live has even had
            # a chance to run. If _start_cam_live created its own Event
            # instead, it would overwrite this one in the dict and set()
            # that new object while this request is still awaiting the old
            # one - a deadlock until the timeout, every single time.
            self._cam_frame_events[cam_name] = asyncio.Event()
            asyncio.ensure_future(self._start_cam_live(cam_name))

        if cam_name not in self._cam_frames:
            event = self._cam_frame_events.get(cam_name)
            if event is not None:
                try:
                    await asyncio.wait_for(event.wait(), timeout=LIVE_FIRST_FRAME_WAIT_SECONDS)
                except asyncio.TimeoutError:
                    pass

        frame = self._cam_frames.get(cam_name)
        if frame is None:
            return web.json_response({"error": "connecting"}, status=503)
        return web.Response(body=frame, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def _start_cam_live(self, cam_name: str) -> None:
        try:
            ok = await self._ring_client.watch_live(
                cam_name,
                lambda arr, name=cam_name: self._on_cam_frame(name, arr),
                on_ended=lambda name=cam_name: self._on_cam_ended(name),
            )
            if not ok:
                log(10, f"WebServer: live view for '{cam_name}' failed to start "
                       f"(see earlier Ring: log lines above for why)")
        finally:
            self._cam_starting.discard(cam_name)
            # Wakes up any live.jpg request still waiting on the first frame,
            # whether or not the session actually came up - a request that
            # was waiting just falls through to the "connecting" response.
            event = self._cam_frame_events.get(cam_name)
            if event is not None:
                event.set()

    def _on_cam_frame(self, cam_name: str, array) -> None:
        try:
            self._cam_frames[cam_name] = _encode_jpeg(array)
        except Exception as exc:  # noqa: BLE001 - one bad frame shouldn't kill the session
            log(10, f"WebServer: failed to JPEG-encode a frame for '{cam_name}': {exc!r}")
            return
        event = self._cam_frame_events.get(cam_name)
        if event is not None:
            event.set()

    def _on_cam_ended(self, cam_name: str) -> None:
        log(10, f"WebServer: live view for '{cam_name}' ended")
        self._cam_frames.pop(cam_name, None)
        self._cam_last_poll.pop(cam_name, None)

    async def _cam_idle_reaper(self) -> None:
        """Stops a camera's Live View session once nothing has polled
        live.jpg for it in a while - the phone-app equivalent of the Qt Cam
        page's hideEvent (there it's page visibility; here it's polling
        activity, since an HTTP API has no notion of "the client closed the
        view"). Keeps a phone that wandered off the Cam screen from leaving
        a WebRTC session (and the Pi CPU decoding it) running forever."""
        while True:
            await asyncio.sleep(LIVE_REAPER_INTERVAL_SECONDS)
            now = time.monotonic()
            stale = [name for name, last in self._cam_last_poll.items()
                     if now - last > LIVE_IDLE_TIMEOUT_SECONDS]
            for cam_name in stale:
                log(10, f"WebServer: no live.jpg poll for '{cam_name}' in "
                       f"{LIVE_IDLE_TIMEOUT_SECONDS:.0f}s - stopping its Live View session")
                self._cam_last_poll.pop(cam_name, None)
                self._cam_frames.pop(cam_name, None)
                self._cam_frame_events.pop(cam_name, None)
                if self._ring_client is not None:
                    await self._ring_client.stop_live_view(cam_name)

    # -- changing the fake data table at runtime (scripts/set_fake_value.py) --
    # Only while CARPEDIEM_DO_FAKE=true (this can never touch real boat data)
    # and only from the Pi itself, since this API has no authentication.

    _LOCAL_ADDRS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

    def _fake_guard(self, request: web.Request) -> web.Response | None:
        if not config.flags.do_fake:
            return web.json_response(
                {"error": "only available in fake mode (CARPEDIEM_DO_FAKE=true) - refusing to touch real data"},
                status=403)
        if request.remote not in self._LOCAL_ADDRS:
            return web.json_response({"error": "only accepted from the Pi itself (localhost)"}, status=403)
        return None

    async def _handle_fake_list(self, request: web.Request) -> web.Response:
        return self._fake_guard(request) or web.json_response({"changed": display_data.overrides()})

    async def _handle_fake_set(self, request: web.Request) -> web.Response:
        """POST {"label": "Battery SOC (%)", "value": 15}. The value is pinned:
        anything that would normally overwrite it (the wind calculation,
        Wunderground, ...) is remembered but ignored until it's reset."""
        blocked = self._fake_guard(request)
        if blocked:
            return blocked
        try:
            body = await request.json()
            label, value = body["label"], body["value"]
        except Exception:  # noqa: BLE001 - malformed JSON / missing keys
            return web.json_response({"error": 'expected JSON {"label": "...", "value": ...}'}, status=400)
        if not isinstance(label, str) or isinstance(value, (list, dict)):
            return web.json_response({"error": "label must be a string; value a number, string, boolean or null"}, status=400)
        if not display_data.set_override(label, value):
            labels = list(display_data.all_labels())
            close = difflib.get_close_matches(label, labels, n=5, cutoff=0.5)
            close += [lb for lb in labels if label.lower() in lb.lower() and lb not in close][:5]
            return web.json_response({"error": f"unknown field '{label}'", "suggestions": close}, status=404)
        log(9, f"WebServer: fake value set: {label} = {value!r}")
        return web.json_response({"label": label, "value": value, "changed": len(display_data.overrides())})

    async def _handle_fake_reset(self, request: web.Request) -> web.Response:
        """DELETE /api/fake?label=X un-pins one field (back to the original
        fake value, or whatever a live producer has written since);
        without ?label=, un-pins everything."""
        blocked = self._fake_guard(request)
        if blocked:
            return blocked
        label = request.query.get("label")
        if label is None:
            return web.json_response({"reset": display_data.release_all_overrides()})
        if not display_data.release_override(label):
            return web.json_response({"error": f"'{label}' hasn't been changed"}, status=404)
        return web.json_response({"reset": 1, "label": label})

    async def close(self) -> None:
        if self._cam_reaper_task is not None:
            self._cam_reaper_task.cancel()
            self._cam_reaper_task = None
        if self._ring_client is not None:
            for cam_name in list(self._cam_last_poll):
                await self._ring_client.stop_live_view(cam_name)
        self._cam_frames.clear()
        self._cam_last_poll.clear()
        self._cam_frame_events.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        display_data.update("WebServer", 0, source="S")
