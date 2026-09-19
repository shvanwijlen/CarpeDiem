"""Corrects the Bresser 7-in-1 wind vane's raw direction reading for how
it's actually mounted on this boat: the 7-in-1 isn't designed for a moving
platform - it's a fixed vane with no internal compass, rigidly bolted to
the hull rather than a compass-stabilized masthead unit. It was calibrated
once, while moored, with the boat sitting at config.wind_calibration.course_deg
(259 degrees - see that config's docstring): at that moment the vane's raw
output was aligned to read the TRUE wind direction. Since the vane rotates
WITH the boat afterwards, its raw reading silently drifts by exactly
however far the boat's current course has rotated away from that
calibration heading - so it needs correcting twice, for two different
things worth knowing:

- WindspeedCalculatedRecalibrated: the TRUE (absolute/compass) wind
  direction right now, valid no matter the current course. Derivation:
  the raw reading equals true wind minus however far the boat has swung
  since calibration, i.e. raw(t) = true_wind(t) - (course(t) -
  calibration), so rearranged:

      recalibrated = (raw + course - calibration) mod 360

- WindspeedCalculatedAsExperienced: where the wind is coming from right
  now, relative to the boat's own current bow/heading (i.e. "as
  experienced" aboard while underway, independent of true compass
  bearing) - the true wind direction above minus the current course:

      as_experienced = (recalibrated - course) mod 360

  which algebraically reduces to (raw - calibration) mod 360: a rigidly-
  mounted vane's raw reading is already relative to the bow at all times
  except for the fixed calibration-time offset, so - unlike Recalibrated -
  this one doesn't actually depend on the live course at all. Computed via
  the subtraction above anyway (not the reduced form) so the relationship
  to Recalibrated/Course stays visible in the code, matching how the
  Weather page labels this field "RELATIVE TO COURSE".

Runs continuously in both real and fake-data mode - previously only fake
mode had a value here at all, and it was a hand-picked illustrative
number (see fake_data.py's git history), not a real calculation. Skips
recomputing (leaving the previous reading in place) whenever
BresserWindDirection or Course isn't available yet - e.g. before the first
GPS/AIS fix, or before the Bresser source (Wunderground/RTL) has reported
anything.
"""
from __future__ import annotations

import asyncio

from carpediem.config import config
from carpediem.display_data import display_data

_TICK_INTERVAL_SECONDS = 5.0


def _recalibrate(raw_dir_deg: float, course_deg: float, calibration_course_deg: float) -> tuple[float, float]:
    recalibrated = (raw_dir_deg + course_deg - calibration_course_deg) % 360.0
    as_experienced = (recalibrated - course_deg) % 360.0
    return recalibrated, as_experienced


def tick() -> None:
    raw_dir = display_data.get("BresserWindDirection")
    course = display_data.get("Course")
    if raw_dir is None or course is None:
        return
    recalibrated, as_experienced = _recalibrate(float(raw_dir), float(course), config.wind_calibration.course_deg)
    display_data.update("WindspeedCalculatedRecalibrated", recalibrated, source="C")
    display_data.update("WindspeedCalculatedAsExperienced", as_experienced, source="C")


async def run_forever() -> None:
    while True:
        tick()
        await asyncio.sleep(_TICK_INTERVAL_SECONDS)
