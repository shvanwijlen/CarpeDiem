"""Store settings, read from environment variables (docker-compose passes
them in from server/.env). Pure parsing - nothing here touches disk or the
network, so bad values fail fast at startup with a readable message."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class ConfigError(ValueError):
    pass


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from None


@dataclass(frozen=True)
class StoreConfig:
    host: str = "0.0.0.0"
    port: int = 8090

    # Two separate secrets so the phone can only read: a leaked phone key
    # can't be used to overwrite the boat's data. Both are required - unlike
    # the Pi's LAN-only API, this service is meant to be reachable from the
    # internet (the Pi pushes to it from the boat, the phone reads from
    # anywhere), so there is no "open" mode.
    read_api_key: str = ""
    write_api_key: str = ""

    # Which Storage implementation to use - see storage/__init__.py.
    storage_backend: str = "sqlite"
    sqlite_path: str = "/data/carpediem.db"

    # Automatic cleanup of stored history. -1 = never delete anything;
    # N >= 1 = delete history older than N days. The single "latest" state
    # and latest camera snapshots are never deleted, so a phone opened after
    # a long outage still shows the last known data (flagged as old).
    retention_days: int = 30
    cleanup_interval_minutes: int = 60

    # How often a pushed state is also kept as a history row. The Pi pushes
    # every few seconds; keeping every push would grow the database by
    # hundreds of MB per day. 0 = keep no history at all.
    history_interval_seconds: int = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "StoreConfig":
        env = os.environ if env is None else env
        cfg = cls(
            host=env.get("STORE_HOST", "").strip() or cls.host,
            port=_int(env, "STORE_PORT", cls.port),
            read_api_key=env.get("READ_API_KEY", "").strip(),
            write_api_key=env.get("WRITE_API_KEY", "").strip(),
            storage_backend=(env.get("STORAGE_BACKEND", "").strip() or cls.storage_backend).lower(),
            sqlite_path=env.get("SQLITE_PATH", "").strip() or cls.sqlite_path,
            retention_days=_int(env, "RETENTION_DAYS", cls.retention_days),
            cleanup_interval_minutes=_int(env, "CLEANUP_INTERVAL_MINUTES", cls.cleanup_interval_minutes),
            history_interval_seconds=_int(env, "HISTORY_INTERVAL_SECONDS", cls.history_interval_seconds),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.read_api_key or not self.write_api_key:
            raise ConfigError(
                "READ_API_KEY and WRITE_API_KEY must both be set (this service is reachable from the "
                "internet, so it has no unauthenticated mode). Generate each with: "
                'python -c "import secrets; print(secrets.token_urlsafe(24))"')
        if self.read_api_key == self.write_api_key:
            raise ConfigError("READ_API_KEY and WRITE_API_KEY must differ - the phone should only be able to read")
        if self.retention_days == 0 or self.retention_days < -1:
            raise ConfigError("RETENTION_DAYS must be -1 (never clean up) or a number of days >= 1")
        if self.cleanup_interval_minutes < 1:
            raise ConfigError("CLEANUP_INTERVAL_MINUTES must be >= 1")
        if self.history_interval_seconds < 0:
            raise ConfigError("HISTORY_INTERVAL_SECONDS must be >= 0 (0 = keep no history)")
        if not 1 <= self.port <= 65535:
            raise ConfigError("STORE_PORT must be 1-65535")

    @property
    def cleanup_enabled(self) -> bool:
        return self.retention_days > 0
