"""Logging, ported from the sketch's custom `myLog()` + hand-rolled SD-card
file rotation/retention/disk-usage-cleanup code (checkDiskUsage,
manageLogs, rotateLogFile, deleteOldestFile, deleteOldFiles, ~250 lines
across the original .ino).

On the Arduino, all of that existed because the SD card was raw SPI
storage with no filesystem-level rotation support. The Raspberry Pi just
has a normal filesystem (which happens to live on an SD card), so this
whole subsystem collapses to Python's standard logging.handlers - no
custom card-detect/rotate/retention code needed at all.

What's kept from the original design:
- a rotating log file (equivalent to MAX_LOG_SIZE + auto-rotate)
- old-file retention/cleanup (equivalent to RETENTION_DAYS / deleteOldFiles)
- a verbosity threshold, so `log(9, ...)` still means "only show if the
  configured verbosity is >= 9", same idea as the sketch's ShowLogLevel.

What's dropped as unneeded on a normal filesystem:
- card-present detection, disk-usage-percent-based emergency deletion,
  manual file listing/rotation via serial menu commands (1-9 in
  ProcessIncomingSerial) - there's no removable card to babysit anymore.
"""
from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

from carpediem.config import config

_LOGGER_NAME = "carpediem"


def setup_logging() -> logging.Logger:
    """Call once at startup. Returns the configured root app logger."""
    log_cfg = config.log
    log_cfg.dir.mkdir(parents=True, exist_ok=True)
    log_file = log_cfg.dir / "carpediem.log"

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.max_bytes,
        backupCount=log_cfg.backup_count,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    _cleanup_old_logs(log_cfg.dir, log_cfg.retention_days)

    return logger


def _cleanup_old_logs(log_dir: Path, retention_days: int) -> None:
    """Equivalent of deleteOldFiles(): remove rotated log files older than
    retention_days. The active carpediem.log is never touched here."""
    cutoff = time.time() - retention_days * 86400
    for path in log_dir.glob("carpediem.log.*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass  # best-effort cleanup, never fatal


# ---------------------------------------------------------------------
# myLog()-compatible helper, for readability when porting call sites 1:1.
# New code should just use `logging.getLogger("carpediem")` directly.
# ---------------------------------------------------------------------
_VERBOSITY = 9  # equivalent of the sketch's `int ShowLogLevel`


def set_verbosity(level: int) -> None:
    global _VERBOSITY
    _VERBOSITY = level


def log(level: int, *args) -> None:
    """Port of myLog(level, ...args). Timestamps/formatting are now handled
    by the logging Formatter, so this just does the verbosity filtering and
    message joining the sketch did by hand."""
    if level > _VERBOSITY:
        return
    message = " ".join(str(a) for a in args)
    logging.getLogger(_LOGGER_NAME).info(message)
