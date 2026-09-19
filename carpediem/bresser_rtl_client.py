"""Local RTL-SDR direct decode of the boat's Bresser 7-in-1 weather
station, via the `rtl_433` binary - an alternative to wunderground_client.py's
cloud API poll. See config.py's BresserRtlConfig/FeatureFlags.use_bresser_rtl
for picking between the two; both write the same Bresser* display_data
fields, so enabling both at once just means whichever last decoded/polled a
reading wins, same as the two cloud clients used to.

Frequency is 868.3 MHz, not the more commonly-assumed 433.92 MHz ISM band -
see scripts/rtl433_sniff.py's docstring. Confirmed against a real capture
(model "Bresser-7in1"):

    {'id': 25751, 'temperature_C': 19.7, 'humidity': 76, 'wind_max_m_s': 7.4,
     'wind_avg_m_s': 6.7, 'wind_dir_deg': 300, 'rain_mm': 139.4,
     'light_lux': 25816.0, 'uv': 2.2, 'battery_ok': 1, 'mic': 'CRC'}

Unlike the cloud clients (request/response on a fixed poll interval), the
station broadcasts on its own schedule (roughly every 10-35s per the
capture above), so this runs rtl_433 as a long-lived subprocess emitting
one JSON line per decoded transmission and updates display_data as each
line arrives, rather than polling. wind_max_m_s/wind_avg_m_s are converted
m/s -> km/h to match the units wunderground_client.py's metric.windGust/
windSpeed already use for the same BresserWindGustSpeed/
BresserWindAverageSpeed fields.

If the rtl_433 subprocess dies (dongle unplugged, USB glitch, ...),
run_forever() relaunches it after _RESTART_DELAY_SECONDS, same retry
pattern as the other clients. If no Bresser-7in1 packet has been seen for
_STALE_AFTER_SECONDS even though rtl_433 is still running, the reading is
considered stale (station out of range / dead battery / rtl_433 lost lock
on 868.3MHz for some other decoded device drowning it out) and
Weather/Weather433 flip to 0.
"""
from __future__ import annotations

import asyncio
import json
import shutil

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

RTL_433_BIN = "rtl_433"
FREQUENCY_HZ = 868_300_000  # Bresser 7-in-1 (EU) FSK frequency - see scripts/rtl433_sniff.py's docstring
_MODEL = "Bresser-7in1"
_RESTART_DELAY_SECONDS = 5.0
_STALE_AFTER_SECONDS = 300.0
_MS_TO_KMH = 3.6


class BresserRtlClient:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._warned_missing_binary = False
        self._stale_logged = False

    async def run_forever(self) -> None:
        while True:
            if shutil.which(RTL_433_BIN) is None:
                if not self._warned_missing_binary:
                    log(9, f"BresserRTL: '{RTL_433_BIN}' not found on PATH - will keep checking "
                           f"(install with: sudo apt install rtl-433)")
                    self._warned_missing_binary = True
                display_data.update("Weather", 0, source="T")
                display_data.update("Weather433", 0, source="T")
            else:
                self._warned_missing_binary = False
                try:
                    await self._run_once()
                except Exception as exc:  # noqa: BLE001 - keep retrying, same pattern as the other clients
                    log(9, f"BresserRTL: rtl_433 subprocess failed, will retry: {exc}")
                    display_data.update("Weather", 0, source="T")
                    display_data.update("Weather433", 0, source="T")
            await asyncio.sleep(_RESTART_DELAY_SECONDS)

    async def _run_once(self) -> None:
        proc = await asyncio.create_subprocess_exec(
            RTL_433_BIN, "-f", str(FREQUENCY_HZ), "-F", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._proc = proc
        assert proc.stdout is not None
        log(9, f"BresserRTL: listening on {FREQUENCY_HZ / 1e6:.3f} MHz via {RTL_433_BIN}")

        try:
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=_STALE_AFTER_SECONDS)
                except asyncio.TimeoutError:
                    if not self._stale_logged:
                        log(9, f"BresserRTL: no {_MODEL} packet in {_STALE_AFTER_SECONDS:.0f}s - "
                               f"marking Weather433 stale (station out of range or dead battery?)")
                        self._stale_logged = True
                    display_data.update("Weather", 0, source="T")
                    display_data.update("Weather433", 0, source="T")
                    continue
                if not line:
                    break  # rtl_433 exited on its own - _run_once() returns, run_forever() relaunches it
                self._handle_line(line.decode("utf-8", errors="replace").strip())
        finally:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()
            self._proc = None

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            msg = json.loads(line)
        except ValueError:
            return  # rtl_433's own startup/status text, not JSON - same as scripts/rtl433_sniff.py

        if msg.get("model") != _MODEL:
            return  # some other 868MHz device rtl_433 also decodes - not ours

        station_id = msg.get("id")
        wanted_id = config.bresser_rtl.station_id
        if wanted_id and station_id != wanted_id:
            return  # a neighboring, identical-model Bresser station - see BresserRtlConfig's docstring

        self._stale_logged = False

        wind_gust_ms = msg.get("wind_max_m_s")
        wind_avg_ms = msg.get("wind_avg_m_s")

        self._update("BresserTemperature", msg.get("temperature_C"))
        self._update("BresserHumidity", msg.get("humidity"))
        self._update("BresserWindDirection", msg.get("wind_dir_deg"))
        self._update("BresserWindGustSpeed", wind_gust_ms * _MS_TO_KMH if wind_gust_ms is not None else None)
        self._update("BresserWindAverageSpeed", wind_avg_ms * _MS_TO_KMH if wind_avg_ms is not None else None)
        self._update("BresserRainfall", msg.get("rain_mm"))
        self._update("BresserLightIntensity", msg.get("light_lux"))
        self._update("BresserUVindex", msg.get("uv"))
        self._update("BresserSensorBatteryStatus", msg.get("battery_ok"))

        display_data.update("Weather", 1, source="T")
        display_data.update("Weather433", 1, source="T")

        if not config.flags.do_fake:
            log(9, f"BresserRTL: received {msg.get('temperature_C')}C, {msg.get('humidity')}% RH, "
                   f"wind {wind_avg_ms} m/s @ {msg.get('wind_dir_deg')} deg, rain {msg.get('rain_mm')} mm "
                   f"(id={station_id})")

    @staticmethod
    def _update(field: str, value) -> None:
        # A field the decoder didn't report this time comes back as missing/
        # None - leave display_data at its existing value rather than
        # clobbering a real prior reading with None, same as wunderground_client.py.
        if value is not None:
            display_data.update(field, value, source="T")

    async def close(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()
        self._proc = None
