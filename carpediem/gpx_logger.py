"""Records the boat's track for one full run of the app - from startup to
shutdown - and writes it out as a standard GPX file on shutdown, viewable
in any GPX-compatible chartplotter, phone app, or web tool.

Position comes from display_data's Lat/Lng fields - the same fields the
Main page's compass and vaarweg_client.py already read - so this doesn't
care whether the fix is real GPS/AIS or fake_data.py's illustrative value
(deliberately not disabled by config.flags.do_fake - see FeatureFlags'
docstring).

Filename convention (per the user's own preference): always starts with
"carpe diem", then the run's start date as YYYYMMDD, then start and end
time (local, HHMMSS-HHMMSS - local because that's what the filename is
for: a human skimming a folder of past trips), then the nearest city if
one could be resolved, e.g.:

    carpe diem_20260913_143201-161045_Leiden.gpx

The city comes from one reverse-geocode lookup against OpenStreetMap's
free Nominatim API (no key needed), done once against the run's first fix
- a boat doesn't cross into a different city fast enough for this to need
repeating, and Nominatim's usage policy (max ~1 request/second, no heavy
automated use) is trivially satisfied by "once per app run" regardless.
If that lookup fails (no internet yet, Nominatim unreachable, no
city/town/village in the result) the file is still written, just without
a city in the name - this is best-effort labelling, not something worth
blocking the track on.

Track points use UTC timestamps internally (GPX's own spec expects UTC
<time> elements for interoperability with other tools), independent of
the local-time filename above.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from xml.sax.saxutils import escape

import aiohttp

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Nominatim's usage policy requires a User-Agent identifying the
# application (no personal/contact info needed for this occasional,
# once-per-run call).
_USER_AGENT = "CarpeDiem-BoatHMI/1.0"

# Preference order for which address component reads as "the nearest
# city" - Nominatim's address breakdown doesn't always have "city" (rural
# stretches of Dutch waterway are often just a "village" or "municipality").
_CITY_ADDRESS_KEYS = ("city", "town", "village", "municipality", "hamlet", "county")

_INVALID_FILENAME_CHARS = '\\/:*?"<>|'


def _sanitize_for_filename(name: str) -> str:
    return "".join(c for c in name if c not in _INVALID_FILENAME_CHARS).strip()


@dataclass
class _TrackPoint:
    lat: float
    lon: float
    time_utc: datetime


class GpxLogger:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._points: List[_TrackPoint] = []
        self._start_time = datetime.now()
        self._city: Optional[str] = None
        self._city_lookup_attempted = False

    async def run_forever(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(9, f"Gpx: tick failed: {exc!r}")
            await asyncio.sleep(config.gpx.poll_interval_seconds)

    async def close(self) -> None:
        await self._write_gpx()
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _tick(self) -> None:
        lat = display_data.get("Lat")
        lon = display_data.get("Lng")
        if lat is None or lon is None:
            log(10, "Gpx: no position fix yet - nothing to record")
            return
        self._points.append(_TrackPoint(lat=float(lat), lon=float(lon), time_utc=datetime.now(timezone.utc)))
        if not self._city_lookup_attempted:
            await self._lookup_city(float(lat), float(lon))

    async def _lookup_city(self, lat: float, lon: float) -> None:
        self._city_lookup_attempted = True  # only ever try once - see module docstring
        session = self._ensure_session()
        params = {"format": "jsonv2", "lat": str(lat), "lon": str(lon), "zoom": "10", "addressdetails": "1"}
        try:
            async with session.get(config.gpx.reverse_geocode_url, params=params,
                                    headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT) as resp:
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001 - city is a nice-to-have, not worth failing the track over
            log(9, f"Gpx: reverse geocode failed, filename will have no city: {exc!r}")
            return
        address = data.get("address") or {}
        for key in _CITY_ADDRESS_KEYS:
            name = address.get(key)
            if name:
                self._city = _sanitize_for_filename(name)
                log(9, f"Gpx: nearest city is '{self._city}'")
                return
        log(9, "Gpx: reverse geocode returned no usable city/town/village name")

    async def _write_gpx(self) -> None:
        if len(self._points) < config.gpx.min_points_to_write:
            log(9, f"Gpx: only {len(self._points)} point(s) recorded this run, not writing a track file")
            return
        end_time = datetime.now()
        filename = self._build_filename(end_time)
        out_dir = Path(config.gpx.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / filename
        path.write_text(self._to_gpx_xml(filename), encoding="utf-8")
        log(9, f"Gpx: wrote {len(self._points)} track point(s) to {path}")

    def _build_filename(self, end_time: datetime) -> str:
        date_str = self._start_time.strftime("%Y%m%d")
        start_str = self._start_time.strftime("%H%M%S")
        end_str = end_time.strftime("%H%M%S")
        name = f"carpe diem_{date_str}_{start_str}-{end_str}"
        if self._city:
            name += f"_{self._city}"
        return name + ".gpx"

    def _to_gpx_xml(self, filename: str) -> str:
        track_name = filename[: -len(".gpx")]
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gpx version="1.1" creator="CarpeDiem" xmlns="http://www.topografix.com/GPX/1/1">',
            "  <trk>",
            f"    <name>{escape(track_name)}</name>",
            "    <trkseg>",
        ]
        for p in self._points:
            lines.append(f'      <trkpt lat="{p.lat:.6f}" lon="{p.lon:.6f}">')
            lines.append(f'        <time>{p.time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}</time>')
            lines.append("      </trkpt>")
        lines.append("    </trkseg>")
        lines.append("  </trk>")
        lines.append("</gpx>")
        return "\n".join(lines) + "\n"
