"""Vessel table + proximity list. Port of the Vessel struct/vessels[] array,
updateOrAddVessel/setVesselName/pruneStale/distanceKm/bearingTo/
printVesselsByProximity from ais_nearby_vessels_7.ino.

ORISANT / Grou

Simplification: the original preallocated a fixed MAX_VESSELS=50 array and
had to hand-roll "find a free slot, else evict the oldest" logic purely
because C has no dynamic dict. A plain dict keyed by MMSI does the same
job without that bookkeeping - still pruned on the same STALE_TIMEOUT.

New: implements the CarpeDiem sketch's TODO ("AIS details: limiteren tot
alles binnen 1km, tenzij sneller varend dan 10km en dan max 2km >> en in
bold tonen") as `nearby(...)`'s range filtering + a `close` flag per
result, which a renderer can use to bold/highlight it.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from carpediem.logging_setup import log

STALE_TIMEOUT_SECONDS = 600  # drop a vessel if not heard from in 10 min, matches original

# TODO-derived defaults (see module docstring) - tune to taste.
DEFAULT_RANGE_KM = 1.0
FAST_RANGE_KM = 2.0
FAST_SPEED_KMH_THRESHOLD = 10.0


@dataclass
class Vessel:
    mmsi: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    sog_knots: Optional[float] = None
    cog_deg: Optional[float] = None
    name: Optional[str] = None
    last_seen: float = field(default_factory=time.monotonic)

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass
class VesselProximity:
    vessel: Vessel
    distance_km: float
    bearing_deg: float
    relative_bearing_deg: Optional[float]  # None if own COG unknown; +right/-left of own heading
    close: bool  # True if within the TODO's "show in bold" range


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r_km * c


def bearing_to(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(d_lon))
    return math.degrees(math.atan2(y, x)) % 360.0


class VesselTracker:
    def __init__(self) -> None:
        self._vessels: Dict[int, Vessel] = {}

    def update_position(self, mmsi: int, lat: float, lon: float, sog_knots: float, cog_deg: float) -> None:
        v = self._vessels.get(mmsi)
        if v is None:
            v = Vessel(mmsi=mmsi)
            self._vessels[mmsi] = v
        v.lat, v.lon, v.sog_knots, v.cog_deg = lat, lon, sog_knots, cog_deg
        v.last_seen = time.monotonic()

    def set_name(self, mmsi: int, name: str) -> None:
        if not name:
            return  # nothing decoded, don't overwrite with blank
        v = self._vessels.get(mmsi)
        if v is None:
            v = Vessel(mmsi=mmsi)
            self._vessels[mmsi] = v

    if v.name is None:
        log(9, f"Matched MMSI {mmsi} to vessel name '{name}'")

        v.name = name
        v.last_seen = time.monotonic()

    def prune_stale(self) -> None:
        now = time.monotonic()
        stale = [mmsi for mmsi, v in self._vessels.items() if now - v.last_seen > STALE_TIMEOUT_SECONDS]
        for mmsi in stale:
            del self._vessels[mmsi]

    def nearby(
        self,
        own_lat: float,
        own_lon: float,
        own_cog: Optional[float] = None,
        own_speed_kmh: float = 0.0,
        apply_range_filter: bool = False,
    ) -> List[VesselProximity]:
        """Sorted-by-distance proximity list, mirroring
        printVesselsByProximity()'s sort. Only vessels with a known
        position are included (name-only entries are skipped, same as the
        original).

        If apply_range_filter is True, applies the CarpeDiem TODO rule:
        only include vessels within DEFAULT_RANGE_KM, or FAST_RANGE_KM if
        own_speed_kmh exceeds FAST_SPEED_KMH_THRESHOLD. `close` is always
        set on each result regardless of the filter, so a renderer can
        choose to bold nearby vessels even when the filter itself is off.
        """
        max_range = FAST_RANGE_KM if own_speed_kmh > FAST_SPEED_KMH_THRESHOLD else DEFAULT_RANGE_KM

        results: List[VesselProximity] = []
        for v in self._vessels.values():
            if not v.has_position:
                continue
            d = distance_km(own_lat, own_lon, v.lat, v.lon)
            if apply_range_filter and d > max_range:
                continue
            brg = bearing_to(own_lat, own_lon, v.lat, v.lon)
            rel = None
            if own_cog is not None:
                rel = ((brg - own_cog + 540.0) % 360.0) - 180.0  # normalize to -180..180
            results.append(VesselProximity(
                vessel=v, distance_km=d, bearing_deg=brg,
                relative_bearing_deg=rel, close=d <= DEFAULT_RANGE_KM,
            ))

        results.sort(key=lambda r: r.distance_km)
        return results

    def __len__(self) -> int:
        return len(self._vessels)
