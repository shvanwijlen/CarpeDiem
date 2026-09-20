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
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING

from aiohttp import web

from carpediem.ais.service import DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log
from carpediem.sysmetrics_monitor import sysmetrics_monitor

if TYPE_CHECKING:
    from carpediem.ais.service import AisService


class WebServer:
    def __init__(self, ais_service: AisService | None = None) -> None:
        self._runner: web.AppRunner | None = None
        self._ais_service = ais_service

    async def run_forever(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_root)
        app.router.add_get("/api/data", self._handle_data)
        app.router.add_get("/api/vessels", self._handle_vessels)
        app.router.add_get("/api/system", self._handle_system)

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
        display_data.update("WebServer", 1, source="S")
        log(9, f"WebServer: listening on {config.webserver.host}:{config.webserver.port} (GET /api/data)")

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
        return web.json_response(asdict(metrics))

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        display_data.update("WebServer", 0, source="S")
