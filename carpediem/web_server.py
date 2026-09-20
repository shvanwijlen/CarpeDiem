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

from aiohttp import web

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log


class WebServer:
    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None

    async def run_forever(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_root)
        app.router.add_get("/api/data", self._handle_data)

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

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        display_data.update("WebServer", 0, source="S")
