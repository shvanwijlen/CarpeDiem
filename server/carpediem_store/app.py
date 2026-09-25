"""HTTP API of the CarpeDiem store (v1). The wire contract is what matters:
the Pi and the phone only know these routes, so any server that implements
them - this one on the Synology, or later a Cloudflare Worker / Supabase edge
function - is interchangeable. See server/README.md for the full description.

    PUT  /v1/state                      Pi -> store   (write key)
    GET  /v1/state                      phone <- store (read key)
    GET  /v1/history?since=&until=&limit=              (read key)
    PUT  /v1/cam/<name>/snapshot        JPEG body      (write key)
    GET  /v1/cam/<name>/snapshot.jpg                   (read key)
    GET  /health                        unauthenticated liveness probe

Keys travel in an `X-API-Key` header. GET needs the read key, PUT the write
key. Timestamps are Unix seconds on the store's own clock, and the store
computes `age_seconds` itself, so neither the Pi's nor the phone's clock has
to be right for the "is this data old?" decision.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import re
import time
from typing import Callable

from aiohttp import web

from .config import StoreConfig
from .storage import Storage

log = logging.getLogger("carpediem_store")

MAX_STATE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_HISTORY_LIMIT = 1000
_CAM_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")

Clock = Callable[[], float]


def _authorized(request: web.Request, cfg: StoreConfig) -> bool:
    expected = cfg.read_api_key if request.method in ("GET", "HEAD") else cfg.write_api_key
    supplied = request.headers.get("X-API-Key", "")
    # Constant-time, so response timing can't be used to guess a key.
    return hmac.compare_digest(supplied.encode(), expected.encode())


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def create_app(cfg: StoreConfig, storage: Storage, clock: Clock = time.time) -> web.Application:
    @web.middleware
    async def auth(request: web.Request, handler):
        if request.path.startswith("/v1/") and not _authorized(request, cfg):
            which = "read" if request.method in ("GET", "HEAD") else "write"
            return _error(f"missing or wrong {which} API key", 401)
        return await handler(request)

    app = web.Application(middlewares=[auth], client_max_size=MAX_SNAPSHOT_BYTES)
    last_history_at = 0.0  # in-memory only: after a restart the first push is simply kept

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def put_state(request: web.Request) -> web.Response:
        nonlocal last_history_at
        body = await request.read()
        if len(body) > MAX_STATE_BYTES:
            return _error("state too large", 413)
        try:
            incoming = await request.json()
        except ValueError:
            return _error("body must be JSON", 400)
        if not isinstance(incoming, dict) or not isinstance(incoming.get("data"), dict):
            return _error('expected {"data": {...}, "vessels": {...}?, "system": {...}?}', 400)
        for optional in ("vessels", "system"):
            if incoming.get(optional) is not None and not isinstance(incoming[optional], dict):
                return _error(f"'{optional}' must be an object", 400)

        now = clock()
        payload = {
            "sent_at": incoming.get("sent_at"),
            "data": incoming["data"],
            "vessels": incoming.get("vessels"),
            "system": incoming.get("system"),
        }
        keep_history = cfg.history_interval_seconds > 0 and now - last_history_at >= cfg.history_interval_seconds
        await storage.put_state(now, payload, keep_history)
        if keep_history:
            last_history_at = now
        return web.json_response({"ok": True, "server_time": now})

    async def get_state(_: web.Request) -> web.Response:
        now = clock()
        stored = await storage.get_state()
        if stored is None:
            body = {"server_time": now, "received_at": None, "age_seconds": None,
                    "sent_at": None, "data": {}, "vessels": None, "system": None}
        else:
            body = {"server_time": now, "received_at": stored.received_at,
                    "age_seconds": max(0.0, now - stored.received_at), **stored.payload}
        response = web.json_response(body, headers={"Cache-Control": "no-store"})
        response.enable_compression()
        return response

    async def get_history(request: web.Request) -> web.Response:
        try:
            since = float(request.query.get("since", 0))
            until = float(request.query.get("until", clock()))
            limit = min(int(request.query.get("limit", 100)), MAX_HISTORY_LIMIT)
        except ValueError:
            return _error("since/until must be numbers (Unix seconds), limit a whole number", 400)
        rows = await storage.history(since, until, max(limit, 1))
        response = web.json_response({"states": [{"received_at": r.received_at, **r.payload} for r in rows]})
        response.enable_compression()
        return response

    def _cam_name(request: web.Request) -> str | None:
        name = request.match_info["name"]
        return name if _CAM_NAME.match(name) else None

    async def put_snapshot(request: web.Request) -> web.Response:
        name = _cam_name(request)
        if name is None:
            return _error("camera name must be 1-32 characters of a-z 0-9 _ -", 400)
        jpeg = await request.read()
        if not jpeg.startswith(b"\xff\xd8"):
            return _error("body must be a JPEG image", 400)
        await storage.put_snapshot(name, clock(), jpeg)
        return web.json_response({"ok": True})

    async def get_snapshot(request: web.Request) -> web.Response:
        name = _cam_name(request)
        if name is None:
            return _error("camera name must be 1-32 characters of a-z 0-9 _ -", 400)
        stored = await storage.get_snapshot(name)
        if stored is None:
            return _error("no snapshot stored for this camera yet", 404)
        return web.Response(body=stored.jpeg, content_type="image/jpeg", headers={
            "Cache-Control": "no-store",
            "X-Snapshot-Age-Seconds": f"{max(0.0, clock() - stored.received_at):.0f}",
        })

    app.router.add_get("/health", health)
    app.router.add_put("/v1/state", put_state)
    app.router.add_get("/v1/state", get_state)
    app.router.add_get("/v1/history", get_history)
    app.router.add_put("/v1/cam/{name}/snapshot", put_snapshot)
    app.router.add_get("/v1/cam/{name}/snapshot.jpg", get_snapshot)

    async def lifecycle(app: web.Application):
        await storage.open()
        cleanup_task = asyncio.create_task(_cleanup_loop(cfg, storage, clock)) if cfg.cleanup_enabled else None
        if cfg.cleanup_enabled:
            log.info("cleanup: deleting history older than %d days, checked every %d min",
                     cfg.retention_days, cfg.cleanup_interval_minutes)
        else:
            log.info("cleanup: RETENTION_DAYS=-1, history is never deleted")
        yield
        if cleanup_task is not None:
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task
        await storage.close()

    app.cleanup_ctx.append(lifecycle)
    return app


async def run_cleanup(cfg: StoreConfig, storage: Storage, clock: Clock = time.time) -> int:
    """One cleanup pass. Returns the number of history rows deleted (0 when
    RETENTION_DAYS=-1)."""
    if not cfg.cleanup_enabled:
        return 0
    cutoff = clock() - cfg.retention_days * 86400
    deleted = await storage.delete_history_before(cutoff)
    if deleted:
        log.info("cleanup: deleted %d history rows older than %d days", deleted, cfg.retention_days)
    return deleted


async def _cleanup_loop(cfg: StoreConfig, storage: Storage, clock: Clock) -> None:
    while True:
        try:
            await run_cleanup(cfg, storage, clock)
        except Exception:  # noqa: BLE001 - a failed pass must not stop the schedule
            log.exception("cleanup failed, will retry")
        await asyncio.sleep(cfg.cleanup_interval_minutes * 60)
