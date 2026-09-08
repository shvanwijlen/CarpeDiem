"""Small helpers shared across pages."""
from __future__ import annotations

import time

_PROCESS_START = time.monotonic()


def system_uptime_seconds() -> float:
    """Time since the Raspberry Pi itself booted (not just this process) -
    read from /proc/uptime on Linux. Falls back to this process's own
    running time on platforms without /proc (e.g. Windows, for local dev),
    which is close enough there since the app isn't running as a boot
    service on a dev machine anyway."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except OSError:
        return time.monotonic() - _PROCESS_START


def format_duration(total_seconds: float) -> str:
    total_seconds = max(0, int(total_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
