"""SQLite storage - one file on the NAS volume, no extra service to run.

Uses the stdlib sqlite3 on a worker thread (asyncio.to_thread) behind a lock:
the write rate is a handful of small rows a minute, so a single connection is
plenty and keeps this dependency-free.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from .base import Storage, StoredSnapshot, StoredState

T = TypeVar("T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    received_at REAL NOT NULL,
    payload     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_received_at ON history (received_at);
CREATE TABLE IF NOT EXISTS snapshot (
    name        TEXT PRIMARY KEY,
    received_at REAL NOT NULL,
    jpeg        BLOB NOT NULL
);
"""


class SqliteStorage(Storage):
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        def locked() -> T:
            with self._lock:
                assert self._db is not None, "SqliteStorage used before open()"
                return fn(self._db)
        return await asyncio.to_thread(locked)

    async def open(self) -> None:
        def _open() -> sqlite3.Connection:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            # auto_vacuum only takes effect on a database with no tables yet,
            # so it must come first; INCREMENTAL lets cleanup hand freed pages
            # back to the NAS (see delete_history_before).
            db.execute("PRAGMA auto_vacuum = INCREMENTAL")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.executescript(_SCHEMA)
            return db
        self._db = await asyncio.to_thread(_open)

    async def close(self) -> None:
        if self._db is not None:
            await asyncio.to_thread(self._db.close)
            self._db = None

    async def put_state(self, received_at: float, payload: dict[str, Any], keep_history: bool) -> None:
        body = json.dumps(payload, separators=(",", ":"))

        def _put(db: sqlite3.Connection) -> None:
            db.execute("BEGIN")
            db.execute(
                "INSERT INTO state (id, received_at, payload) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET received_at = excluded.received_at, payload = excluded.payload",
                (received_at, body))
            if keep_history:
                db.execute("INSERT INTO history (received_at, payload) VALUES (?, ?)", (received_at, body))
            db.execute("COMMIT")
        await self._run(_put)

    async def get_state(self) -> Optional[StoredState]:
        row = await self._run(lambda db: db.execute("SELECT received_at, payload FROM state WHERE id = 1").fetchone())
        return StoredState(row[0], json.loads(row[1])) if row else None

    async def history(self, since: float, until: float, limit: int) -> list[StoredState]:
        rows = await self._run(lambda db: db.execute(
            "SELECT received_at, payload FROM history WHERE received_at >= ? AND received_at <= ? "
            "ORDER BY received_at DESC LIMIT ?", (since, until, limit)).fetchall())
        return [StoredState(r[0], json.loads(r[1])) for r in rows]

    async def put_snapshot(self, name: str, received_at: float, jpeg: bytes) -> None:
        await self._run(lambda db: db.execute(
            "INSERT INTO snapshot (name, received_at, jpeg) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET received_at = excluded.received_at, jpeg = excluded.jpeg",
            (name, received_at, jpeg)))

    async def get_snapshot(self, name: str) -> Optional[StoredSnapshot]:
        row = await self._run(lambda db: db.execute(
            "SELECT received_at, jpeg FROM snapshot WHERE name = ?", (name,)).fetchone())
        return StoredSnapshot(row[0], bytes(row[1])) if row else None

    async def delete_history_before(self, cutoff: float) -> int:
        def _delete(db: sqlite3.Connection) -> int:
            deleted = db.execute("DELETE FROM history WHERE received_at < ?", (cutoff,)).rowcount
            if deleted:
                db.execute("PRAGMA incremental_vacuum")
            return deleted
        return await self._run(_delete)

    async def history_count(self) -> int:
        return (await self._run(lambda db: db.execute("SELECT COUNT(*) FROM history").fetchone()))[0]
