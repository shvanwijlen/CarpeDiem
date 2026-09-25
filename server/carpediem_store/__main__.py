"""`python -m carpediem_store` - what the Docker image runs."""
from __future__ import annotations

import logging
import sys

from aiohttp import web

from . import __version__
from .app import create_app
from .config import ConfigError, StoreConfig
from .storage import create_storage


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = StoreConfig.from_env()
        storage = create_storage(cfg)
    except ConfigError as exc:
        sys.exit(f"carpediem_store: configuration error: {exc}")
    logging.getLogger("carpediem_store").info(
        "CarpeDiem store %s: %s storage, listening on %s:%d", __version__, cfg.storage_backend, cfg.host, cfg.port)
    web.run_app(create_app(cfg, storage), host=cfg.host, port=cfg.port, print=None)


if __name__ == "__main__":
    main()
