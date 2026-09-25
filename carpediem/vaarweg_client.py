"""Finds the next bridge/lock ahead of the boat (Main page's center
banner, display_data field "NextObject"), via Rijkswaterstaat's public
"Blauwe Golf, Verbindend" (BGV) REST API - no API key needed, plain HTTPS
GET returning JSON. See config.py's VaarwegConfig docstring and
BGV.IRS.informatiewebservice.v1.11.pdf (in the project's vaarwegen
reference folder) for the full spec; verified live against the real
endpoint while building this - e.g.
GET https://api.vaarweginformatie.nl/bgv/information/bridge/52.20/4.45/52.14/4.60
returns real bridges including "Zijlbrug" near Leiden, and
GET .../bridge/details/<isrs> returns its live bridgeStatus.

Own position/course/speed come from display_data's Lat/Lng/Course/Speed
fields - the same fields the Main page's compass already reads - rather
than a direct reference to AisService, matching this app's usual poller
pattern (each client reads config/display_data, not other clients).
Deliberately not disabled by config.flags.do_fake (see FeatureFlags'
docstring) - fake_data.py populates those same fields with illustrative
values, and this client's whole job is cross-referencing whatever
position is current against the real API, fake or not, so it needs to
keep working in fake mode to be testable without actually being underway.

Algorithm: bridges are re-queried each poll within a bounding box around
the current position (the API can't geofilter any other way, and there
are too many nationwide to fetch in full every poll); locks have no
geofilter in this API at all, but there are only ~50 nationwide, so the
full list is fetched once and cached (locks don't move). Each candidate's
distance and bearing from own position are computed (haversine /
great-circle bearing, reusing ais/vessel_tracker.py's already-verified
functions), the bearing expressed relative to own course, and the
nearest candidate within range AND within the ahead half-angle wins. Its
live status (bridgeStatus/lockStatus) is fetched with one extra detail
request - only for that single winner, not every candidate, to keep this
to two or three requests per poll against a public government API.

That same detail request also carries a bridge's vertical clearance:
bridgeDetails.bridgeOpenings is a list of doorvaartopeningen (one per
separately-operable span/opening a bridge may have, e.g. a main span plus
a smaller one), each with its own heightClosed - the clearance in meters
while the bridge is down, i.e. the number that actually matters for
deciding whether you need it to open at all. A bridge with several
openings is passable if ANY one of them is tall enough, so the opening
with the greatest heightClosed is the one reported. Locks have no such
structure (lockDetails carries no bridgeOpenings), so clearance is always
None for a lock.

Known gap: the live `bridge` bounding-box endpoint only lists ~400
bridges (those with a live status feed) - small, phone-operated ones like
Pier-Christiaanbrug (Echtenerbrug) never appear in it, however wide the
box. Rijkswaterstaat's own website does know them all, so
scripts/build_vaarweg_bridges.py extracts its full list (~6600 bridges,
with the same ISRS codes) into data/vaarweg_bridges.json, which
_fetch_bridges() merges with the live results (deduped by ISRS). For such
a bridge _fetch_status() still asks BGV by ISRS and simply gets no status
or clearance back.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp

from carpediem.ais.vessel_tracker import bearing_to, distance_km
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

_KM_PER_DEG_LAT = 111.32
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# VHF channel / phone number per bridge/lock - not available from the
# live BGV API at all, only from Rijkswaterstaat's "Bedieningstijden"
# PDF, extracted once by scripts/build_vaarweg_contacts.py into this
# static file (see that script's docstring for why this is offline
# rather than a live lookup).
_CONTACTS_PATH = Path(__file__).resolve().parent / "data" / "vaarweg_contacts.json"

# Full bridge list, built offline by scripts/build_vaarweg_bridges.py (see
# module docstring's "Known gap"): [isrs, name, lat, lon] per bridge.
_BRIDGES_PATH = Path(__file__).resolve().parent / "data" / "vaarweg_bridges.json"


def _load_contacts() -> Dict[str, Dict[str, str]]:
    try:
        return json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(9, f"Vaarweg: couldn't load {_CONTACTS_PATH}, VHF/phone won't be shown: {exc!r}")
        return {}


@dataclass
class _Candidate:
    isrs: str
    name: str
    lat: float
    lon: float
    kind: str  # "bridge" | "lock"


def _load_bridges() -> List[_Candidate]:
    try:
        raw = json.loads(_BRIDGES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(9, f"Vaarweg: couldn't load {_BRIDGES_PATH}, only live-listed bridges will be found: {exc!r}")
        return []
    return [_Candidate(isrs=i, name=n, lat=la, lon=lo, kind="bridge") for i, n, la, lo in raw]


def _relative_angle(a_deg: float, b_deg: float) -> float:
    """a - b, wrapped to (-180, 180] - e.g. how far off dead-ahead (b) a
    bearing (a) is, signed (+right/-left), same convention
    ais/vessel_tracker.py's relative_bearing_deg already uses."""
    return ((a_deg - b_deg + 540.0) % 360.0) - 180.0


class VaarwegClient:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._locks: List[_Candidate] = []
        self._locks_fetched_at: float = 0.0
        self._contacts = _load_contacts()
        self._static_bridges = _load_bridges()

    async def run_forever(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(9, f"Vaarweg: poll failed: {exc!r}")
                display_data.update("NextObject", None, source="V")
            await asyncio.sleep(config.vaarweg.poll_interval_seconds)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _poll_once(self) -> None:
        own_lat = display_data.get("Lat")
        own_lon = display_data.get("Lng")
        own_course = display_data.get("Course")
        own_speed_kmh = display_data.get("Speed")
        if own_lat is None or own_lon is None or own_course is None:
            # No fix yet, or (in real operation) genuinely stopped - a
            # boat not moving has no reliable COG, same reason
            # ais/service.py falls back to DEFAULT_OWN_COG_DEG for the
            # radar. Nothing sensible to compute either way.
            log(9, "Vaarweg: no position/course fix yet - nothing to look up")
            display_data.update("NextObject", None, source="V")
            return

        range_km = max(config.vaarweg.min_range_km,
                        (own_speed_kmh or 0.0) * config.vaarweg.lookahead_minutes / 60.0)

        session = self._ensure_session()
        bridges = await self._fetch_bridges(session, own_lat, own_lon, range_km)
        locks = await self._get_locks(session)

        best: Optional[Tuple[float, _Candidate]] = None
        for cand in bridges + locks:
            d = distance_km(own_lat, own_lon, cand.lat, cand.lon)
            if d > range_km:
                continue
            brg = bearing_to(own_lat, own_lon, cand.lat, cand.lon)
            rel = _relative_angle(brg, own_course)
            if abs(rel) > config.vaarweg.ahead_half_angle_deg:
                continue
            if best is None or d < best[0]:
                best = (d, cand)

        if best is None:
            display_data.update("NextObject", None, source="V")
            display_data.update("NextObjectStatus", None, source="V")
            display_data.update("NextObjectClearanceM", None, source="V")
            return

        distance, cand = best
        status, clearance_m = await self._fetch_status(session, cand)
        text = cand.name
        contact = self._contact_suffix(cand.name)
        if contact:
            text += f" - {contact}"
        text += f" - {distance:.1f} KM"
        if clearance_m is not None:
            text += f" - {clearance_m:.1f} M"
        display_data.update("NextObject", text, source="V")
        # Raw status (e.g. "OPEN", "BLOCKED") goes out separately rather
        # than appended to the text above - a long bridge name plus a long
        # status string doesn't fit the banner, so the UI shows status as a
        # color indicator instead (see main_page.py's _next_object_color()).
        display_data.update("NextObjectStatus", status, source="V")
        display_data.update("NextObjectClearanceM", clearance_m, source="V")
        log(9, f"Vaarweg: next object is '{cand.name}' ({cand.kind}), {distance:.2f} km ahead, "
               f"status={status}, clearance_m={clearance_m}, contact={contact}")

    def _contact_suffix(self, name: str) -> Optional[str]:
        """VHF channel if published, else phone number if that's all
        there is (per Rijkswaterstaat's own data - plenty of smaller
        bridges/locks are radio-operated by phone call rather than VHF),
        else nothing shown at all."""
        info = self._contacts.get(name)
        if not info:
            return None
        vhf = info.get("vhf")
        if vhf:
            return f"VHF {vhf}"
        phone = info.get("phone")
        if phone:
            return f"TEL {phone}"
        return None

    async def _fetch_bridges(self, session: aiohttp.ClientSession, lat: float, lon: float,
                              range_km: float) -> List[_Candidate]:
        dlat = range_km / _KM_PER_DEG_LAT
        dlon = range_km / (_KM_PER_DEG_LAT * max(0.1, math.cos(math.radians(lat))))
        top, left, bottom, right = lat + dlat, lon - dlon, lat - dlat, lon + dlon
        url = f"{config.vaarweg.base_url}/bridge/{top}/{left}/{bottom}/{right}"
        try:
            async with session.get(url, timeout=_REQUEST_TIMEOUT) as resp:
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001 - one bad request shouldn't kill the poll
            log(9, f"Vaarweg: bridge lookup failed: {exc!r}")
            data = {}
        bridges = [
            _Candidate(isrs=d["isrs"], name=d.get("name") or d["isrs"],
                       lat=d["latitude"], lon=d["longitude"], kind="bridge")
            for d in data.get("commonData", []) or []
        ]
        live_isrs = {b.isrs for b in bridges}
        bridges.extend(c for c in self._static_bridges
                       if c.isrs not in live_isrs and bottom <= c.lat <= top and left <= c.lon <= right)
        return bridges

    async def _get_locks(self, session: aiohttp.ClientSession) -> List[_Candidate]:
        if self._locks and (time.monotonic() - self._locks_fetched_at) < config.vaarweg.locks_cache_seconds:
            return self._locks
        url = f"{config.vaarweg.base_url}/lock"
        try:
            async with session.get(url, timeout=_REQUEST_TIMEOUT) as resp:
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001 - stale cache beats nothing
            log(9, f"Vaarweg: lock list refresh failed, keeping previous list: {exc!r}")
            return self._locks
        self._locks = [
            _Candidate(isrs=d["isrs"], name=d.get("name") or d["isrs"],
                       lat=d["latitude"], lon=d["longitude"], kind="lock")
            for d in data.get("commonData", []) or []
        ]
        self._locks_fetched_at = time.monotonic()
        return self._locks

    async def _fetch_status(self, session: aiohttp.ClientSession,
                             cand: _Candidate) -> Tuple[Optional[str], Optional[float]]:
        """Returns (status, clearance_m) - clearance_m is the tallest
        heightClosed across a bridge's openings (None for a lock, or a
        bridge with no openings data published)."""
        path = "bridge" if cand.kind == "bridge" else "lock"
        url = f"{config.vaarweg.base_url}/{path}/details/{cand.isrs}"
        try:
            async with session.get(url, timeout=_REQUEST_TIMEOUT) as resp:
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001 - status is a nice-to-have, not worth failing over
            log(9, f"Vaarweg: status lookup for '{cand.name}' failed: {exc!r}")
            return None, None
        details = data.get("bridgeDetails" if cand.kind == "bridge" else "lockDetails")
        if not details:
            return None, None
        status = details.get("bridgeStatus" if cand.kind == "bridge" else "lockStatus")
        status = status.replace("_", " ") if status else None

        clearance_m = None
        if cand.kind == "bridge":
            heights = [o["heightClosed"] for o in details.get("bridgeOpenings") or []
                       if o.get("heightClosed") is not None]
            if heights:
                clearance_m = max(heights)
        return status, clearance_m
