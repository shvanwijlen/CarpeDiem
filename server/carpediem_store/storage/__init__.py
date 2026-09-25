"""Storage backends, chosen with STORAGE_BACKEND. To add one (Postgres/Supabase,
...): subclass Storage in a new module here and register it below."""
from __future__ import annotations

from ..config import ConfigError, StoreConfig
from .base import Storage, StoredSnapshot, StoredState
from .sqlite import SqliteStorage

__all__ = ["Storage", "StoredSnapshot", "StoredState", "create_storage"]


def create_storage(cfg: StoreConfig) -> Storage:
    if cfg.storage_backend == "sqlite":
        return SqliteStorage(cfg.sqlite_path)
    raise ConfigError(f"unknown STORAGE_BACKEND {cfg.storage_backend!r} (available: sqlite)")
