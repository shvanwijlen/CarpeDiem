"""The JSON the Pi exposes about itself - shared by web_server.py (the local
GET /api/* routes) and publisher.py (what gets pushed to the data store), so
the phone gets identical content whichever way it arrives.
"""
from __future__ import annotations

import math
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from carpediem.ais.service import DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.sysmetrics_monitor import summary_rows, sysmetrics_monitor

if TYPE_CHECKING:
    from carpediem.ais.service import AisService


def data_payload() -> dict[str, Any]:
    """Every display_data field as one flat {internal_label: value} object.
    NaN/Infinity become null: they aren't valid JSON, and a store that isn't
    Python (e.g. a Cloudflare Worker) would reject the whole push."""
    out: dict[str, Any] = {}
    for label, field in display_data.snapshot().items():
        v = field.value
        out[label] = None if isinstance(v, float) and not math.isfinite(v) else v
    return out


def vessels_payload(ais_service: "AisService | None") -> dict[str, Any]:
    """Nearby AIS vessels for a radar view - lives outside display_data
    (it's a list, not a scalar field). The `category` mirrors hmi_qt's
    main_page._refresh_radar() color logic: moored (~stationary), overtaking
    (behind us and faster - the danger case), fast (above
    FAST_VESSEL_THRESHOLD_KMH), else ok."""
    payload: dict[str, Any] = {"max_range_km": config.ais.max_range_km, "vessels": []}
    if ais_service is None:
        return payload
    own = ais_service.reader.own_fix
    own_speed_knots = own.sog_knots or 0.0
    own_cog = own.cog if own.cog is not None else DEFAULT_OWN_COG_DEG
    for r in ais_service.nearby_vessels():
        if r.relative_bearing_deg is None:
            continue
        sog_knots = r.vessel.sog_knots or 0.0
        if sog_knots < 0.2:
            category, heading = "moored", 0.0
        else:
            if abs(r.relative_bearing_deg) > 90 and sog_knots > own_speed_knots:
                category = "overtaking"
            elif sog_knots * 1.852 > FAST_VESSEL_THRESHOLD_KMH:
                category = "fast"
            else:
                category = "ok"
            heading = ((r.vessel.cog_deg - own_cog) % 360
                       if r.vessel.cog_deg is not None else r.relative_bearing_deg)
        payload["vessels"].append({
            "mmsi": r.vessel.mmsi,
            "name": r.vessel.name,
            "bearing_deg": r.relative_bearing_deg,
            "distance_km": r.distance_km,
            "speed_knots": r.vessel.sog_knots,
            "heading_deg": heading,
            "category": category,
        })
    return payload


def system_payload() -> dict[str, Any]:
    """CPU/memory/disk health of the Pi itself - what feeds the HMI top bar's
    SYS lamp. Not a display_data field because sysmetrics_monitor.py
    deliberately keeps host stats out of it (they aren't boat telemetry).
    status is "ok" | "warn" | "crit", or null when the monitor is off
    (CARPEDIEM_CHECK_SYSMETRICS=false) or hasn't sampled yet."""
    metrics = sysmetrics_monitor.latest
    if metrics is None:
        return {"status": None}
    payload = asdict(metrics)
    # Pre-formatted lines (value text + level + bar fraction) so the phone
    # shows exactly what the Pi's own popup does, thresholds included.
    payload["rows"] = [asdict(r) for r in summary_rows(metrics)]
    return payload
