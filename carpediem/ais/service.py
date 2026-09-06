"""Top-level AIS service, tying together EmtrakReader, VesselTracker and
AisStreamClient into the three concurrent asyncio tasks main.py needs to
start. Also ports the periodic proximity-list logging from
printVesselsByProximity() (PRINT_INTERVAL_MS=5000 in the original).
"""
from __future__ import annotations

import asyncio

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log
from carpediem.ais.aisstream_client import AisStreamClient
from carpediem.ais.emtrak_reader import EmtrakReader
from carpediem.ais.vessel_tracker import VesselTracker, VesselProximity

PRINT_INTERVAL_SECONDS = 5
DEFAULT_OWN_COG_DEG = 244.0  # used when em-trak reports no COG (e.g. lying in port, not moving)
FAST_VESSEL_THRESHOLD_KMH = 7  # lowered from 10 for testing - raise back to 10 when done

"""
brg  — absolute compass bearing from your boat to the target vessel, true-north referenced (0-360 deg). Fixed to geography: spinning your own boat in place does not change it.
look — the same direction, but relative to your own course (own_cog) instead of true north: a signed number of degrees, positive = to the right/starboard of your heading, negative = to the left/port. Computed in vessel_tracker.py:166-167 as ((brg - own_cog + 540) % 360) - 180. Since own_cog defaults to 244 deg when em-trak reports no COG (e.g. lying in port), look is relative to that assumed heading while stationary.
SOG  — the target vessel's speed over ground, km/h (converted from AIS knots).
COG  — the target vessel's course over ground, degrees true.

Example: a vessel sits due east of you (brg = 090).
- Steering north (COG = 000): east is 90 deg to your right -> look = 90 (dead abeam, starboard).
- Steering east (COG = 090): same vessel is now dead ahead -> look = 0.
- Steering west (COG = 270): now dead behind you -> look = 180 (or -180).
"""


def log_vessel_proximity(r: VesselProximity) -> None:
    """Shared with main.py's fake-mode output, so real and fake AIS data
    are logged in the same format."""
    name = r.vessel.name or "(name unknown)"
    look = f"{r.relative_bearing_deg:.0f}" if r.relative_bearing_deg is not None else None
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
            own_cog=self.reader.own_fix.cog if self.reader.own_fix.cog is not None else DEFAULT_OWN_COG_DEG,
            own_speed_kmh=(self.reader.own_fix.sog_knots or 0) * 1.852,
            apply_range_filter=apply_range_filter,
            max_range_km=config.ais.max_range_km,
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
                elif (r.vessel.sog_knots or 0) * 1.852 > FAST_VESSEL_THRESHOLD_KMH:
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
