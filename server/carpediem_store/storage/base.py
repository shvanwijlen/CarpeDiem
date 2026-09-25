"""The storage interface every datastore implements.

The rest of the service (HTTP routes, auth, cleanup schedule) only ever talks
to this, so swapping SQLite for e.g. Postgres/Supabase means adding one class
next to sqlite.py and registering it in __init__.py - nothing else changes.
(A Cloudflare Worker + KV/D1 store doesn't go through this at all: it
re-implements the same HTTP API from server/README.md, and the Pi and phone
can't tell the difference.)

All times are Unix epoch seconds on the *server's* clock. Payloads are the
JSON objects the Pi pushed ({"sent_at", "data", "vessels", "system"}).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class StoredState:
    received_at: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class StoredSnapshot:
    received_at: float
    jpeg: bytes


class Storage(ABC):
    @abstractmethod
    async def open(self) -> None:
        """Connect / create the schema. Called once before serving."""

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def put_state(self, received_at: float, payload: dict[str, Any], keep_history: bool) -> None:
        """Replace the latest state; also append it to history if keep_history."""

    @abstractmethod
    async def get_state(self) -> Optional[StoredState]:
        """The latest state, or None if nothing has been pushed yet."""

    @abstractmethod
    async def history(self, since: float, until: float, limit: int) -> list[StoredState]:
        """History rows with since <= received_at <= until, newest first."""

    @abstractmethod
    async def put_snapshot(self, name: str, received_at: float, jpeg: bytes) -> None:
        """Replace the latest snapshot for camera `name`."""

    @abstractmethod
    async def get_snapshot(self, name: str) -> Optional[StoredSnapshot]: ...

    @abstractmethod
    async def delete_history_before(self, cutoff: float) -> int:
        """Delete history rows older than `cutoff`; returns how many. Must never
        touch the latest state or the latest snapshots."""

    @abstractmethod
    async def history_count(self) -> int: ...
