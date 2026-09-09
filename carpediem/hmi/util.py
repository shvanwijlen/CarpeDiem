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


def decimal_to_dms(value: float, positive_hemisphere: str, negative_hemisphere: str) -> str:
    """52.171967 -> '52°10\'19.08"N' (or the matching lon form) - the AIS
    page's own lat/lon spec example uses this format rather than the
    decimal degrees display_data stores "Lat"/"Lng" as."""
    hemisphere = positive_hemisphere if value >= 0 else negative_hemisphere
    value = abs(value)
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    return f"{degrees}°{minutes:02d}'{seconds:05.2f}\"{hemisphere}"


_COMPASS_POINTS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def compass_abbr(degrees: float) -> str:
    """210 -> 'SSW' - the 16-point compass abbreviation the Weather page's
    wind circles show alongside the numeric degree, matching how the
    VEVOR/Bresser-style console the spec pointed at labels wind direction."""
    idx = int((degrees % 360) / 22.5 + 0.5) % 16
    return _COMPASS_POINTS[idx]
