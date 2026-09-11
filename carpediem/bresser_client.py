"""Polls ProWeatherLive's public station API (https://pro-weather.com) for
the boat's Bresser 7-in-1 weather station readings, rather than decoding
its 433MHz broadcast directly - the station has WiFi and already uploads
there. No auth: the endpoint is public unless the station owner disables
it in their ProWeatherLive settings (see config.bresser's docstring).

Feeds the same Bresser* display_data fields the HMI weather page already
reads (BresserTemperature, BresserHumidity, ...) and the top bar's "WX"
indicator (the pre-existing "Weather" field - see hmi/topbar.py/hmi_qt/topbar.py).
There's no per-sensor battery status in this API's response shape, so
BresserSensorBatteryStatus is left alone (stays None) - nothing here
claims to know it.
"""
from __future__ import annotations

import aiohttp
import asyncio

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

_API_BASE = "https://pro-weather.com/api/v1"
_REQUEST_TIMEOUT_SECONDS = 10.0


class BresserClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def run_forever(self) -> None:
        if not config.bresser.configured:
            log(9, "Bresser: BRESSER_SUBDOMAIN not set - skipping (see .env.example)")
            return
        while True:
            try:
                await self._poll_once()
                display_data.update("Weather", 1, source="S")
            except Exception as exc:  # noqa: BLE001 - anything here means "station unreachable"
                log(9, f"Bresser: poll failed: {exc}")
                display_data.update("Weather", 0, source="S")
            await asyncio.sleep(config.bresser.poll_interval_seconds)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _poll_once(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        url = f"{_API_BASE}/{config.bresser.subdomain}/current"
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
        async with self._session.get(url, timeout=timeout) as resp:
            if resp.status == 403:
                raise RuntimeError("public API disabled for this station - "
                                    "enable it under the station's ProWeatherLive settings")
            if resp.status == 404:
                raise RuntimeError(f"station '{config.bresser.subdomain}' not found, "
                                    "unpublished, or has no current reading yet")
            resp.raise_for_status()
            data = await resp.json()

        obs = data.get("observation") or {}
        temperature = (obs.get("temperature") or {}).get("celsius")
        humidity = obs.get("humidity")
        wind = obs.get("wind") or {}
        wind_speed = (wind.get("speed") or {}).get("kmh")
        wind_direction = (wind.get("direction") or {}).get("degrees")
        wind_gust = (obs.get("windGust") or {}).get("kmh")
        rain_today = ((obs.get("rain") or {}).get("today") or {}).get("mm")
        solar = (obs.get("solar") or {}).get("wm2")
        uv_index = (obs.get("uv") or {}).get("index")

        self._update("BresserTemperature", temperature)
        self._update("BresserHumidity", humidity)
        self._update("BresserWindDirection", wind_direction)
        self._update("BresserWindAverageSpeed", wind_speed)
        self._update("BresserWindGustSpeed", wind_gust)
        self._update("BresserRainfall", rain_today)
        self._update("BresserLightIntensity", solar)
        self._update("BresserUVindex", uv_index)

        if not config.flags.do_fake:
            log(9, f"Bresser: received {temperature}C, {humidity}% RH, "
                   f"wind {wind_speed} km/h @ {wind_direction} deg, rain {rain_today} mm")

    @staticmethod
    def _update(field: str, value) -> None:
        # The API returns null for a sensor the station doesn't have -
        # leave display_data at its existing value (None by default)
        # rather than overwriting a real prior reading with None.
        if value is not None:
            display_data.update(field, value, source="P")
