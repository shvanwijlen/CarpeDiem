"""Top-level AIS service, tying together EmtrakReader, VesselTracker and
AisStreamClient into the three concurrent asyncio tasks main.py needs to
start. Also ports the periodic proximity-list logging from
printVesselsByProximity() (PRINT_INTERVAL_MS=5000 in the original).
"""
from __future__ import annotations

import asyncio

from carpediem.display_data import display_data
from carpediem.logging_setup import log
from carpediem.ais.aisstream_client import AisStreamClient
from carpediem.ais.emtrak_reader import EmtrakReader
from carpediem.ais.vessel_tracker import VesselTracker, VesselProximity

PRINT_INTERVAL_SECONDS = 5


def log_vessel_proximity(r: VesselProximity) -> None:
    """Shared with main.py's fake-mode output, so real and fake AIS data
    are logged in the same format."""
    name = r.vessel.name or "(name unknown)"
    look = f"{'R' if (r.relative_bearing_deg or 0) >= 0 else 'L'}{abs(r.relative_bearing_deg):.0f}deg" \
        if r.relative_bearing_deg is not None else "?"
    sog_kmh = (r.vessel.sog_knots or 0) * 1.852
    log(9, f"MMSI {r.vessel.mmsi}  {name}  dist {r.distance_km:.2f} km  "
            f"brg {r.bearing_deg:.0f} deg  look {look}  "
            f"SOG {sog_kmh:.1f} km/h  COG {r.vessel.cog_deg or 0:.0f} deg")


class AisService:
    def __init__(self) -> None:
        self.tracker = VesselTracker()
        self.reader = EmtrakReader(self.tracker)
        self.aisstream = AisStreamClient(self.tracker, self.reader.own_position)

    def nearby_vessels(self, apply_range_filter: bool = False) -> list[VesselProximity]:
        """For the future display renderer: the current sorted-by-distance
        proximity list. Empty list if we don't have an own-ship fix yet."""
        if not self.reader.own_fix.has_fix:
            return []
        return self.tracker.nearby(
            self.reader.own_fix.lat,
            self.reader.own_fix.lon,
            own_cog=self.reader.own_fix.cog,
            own_speed_kmh=(self.reader.own_fix.sog_knots or 0) * 1.852,
            apply_range_filter=apply_range_filter,
        )

    async def _print_loop(self) -> None:
        """Port of the PRINT_INTERVAL_MS block in loop(): periodic prune +
        log of the proximity list, plus the em-trak stale-data warnings."""
        while True:
            await asyncio.sleep(PRINT_INTERVAL_SECONDS)

            if self.reader.data_is_stale():
                log(9, "em-trak: no data received recently - connection may be stale")

            self.tracker.prune_stale()

            if not self.reader.own_fix.has_fix:
                log(9, "AIS: waiting for own GPS fix...")
                continue

            results = self.nearby_vessels()
            log(9, f"---- Nearby vessels ({len(results)}) ---- "
                    f"own Class B reports sent: type18={self.reader.own_reports_type18} "
                    f"type19={self.reader.own_reports_type19} other={self.reader.own_reports_other}")
            for r in results:
                log_vessel_proximity(r)

            own_speed_knots = self.reader.own_fix.sog_knots
            behind_and_faster = 0
            faster_than_10 = 0
            other = 0
            for r in results:
                if (r.relative_bearing_deg is not None and abs(r.relative_bearing_deg) > 90
                        and r.vessel.sog_knots is not None and own_speed_knots is not None
                        and r.vessel.sog_knots > own_speed_knots):
                    behind_and_faster += 1
                elif (r.vessel.sog_knots or 0) * 1.852 > 10:
                    faster_than_10 += 1
                else:
                    other += 1
            display_data.update("VesselsBehindMe", behind_and_faster, source="A")
            display_data.update("VesselsFasterThan10", faster_than_10, source="A")
            display_data.update("VesselsOther", other, source="A")

    async def run_forever(self) -> None:
        """Starts all 3 AIS-related tasks and runs until cancelled. Call
        this as one asyncio task from main.py."""
        await asyncio.gather(
            self.reader.run_forever(),
            self.aisstream.run_forever(),
            self._print_loop(),
        )
