"""Polls Weather Underground's PWS API (api.weather.com/v2/pws/observations
/current) for the boat's Bresser 7-in-1 weather station readings - an
alternative to bresser_client.py's ProWeatherLive source, added because
this station's ProWeatherLive public subdomain wasn't findable. Needs the
Bresser gateway/app to already be uploading to Weather Underground (most
WiFi weather station gateways, including Bresser's, support this
alongside whatever else they're sending to) and a free Wunderground API
key - see config.py's WundergroundConfig.

Feeds the same Bresser* display_data fields bresser_client.py does (see
that module's docstring) - the two are independent, optional, and safe to
run together (whichever last completed a poll wins, harmlessly).
"""
from __future__ import annotations

import asyncio

import aiohttp

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

_API_URL = "https://api.weather.com/v2/pws/observations/current"
_REQUEST_TIMEOUT_SECONDS = 10.0


class WundergroundClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def run_forever(self) -> None:
        if not config.wunderground.configured:
            log(9, "Wunderground: WUNDERGROUND_STATION_ID/WUNDERGROUND_API_KEY not set - "
                   "skipping (see .env.example)")
            return
        while True:
            try:
                await self._poll_once()
                display_data.update("Weather", 1, source="S")
            except Exception as exc:  # noqa: BLE001 - anything here means "station unreachable"
                log(9, f"Wunderground: poll failed: {exc}")
                display_data.update("Weather", 0, source="S")
            await asyncio.sleep(config.wunderground.poll_interval_seconds)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _poll_once(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        params = {
            "stationId": config.wunderground.station_id,
            "format": "json",
            "units": "m",
            "apiKey": config.wunderground.api_key,
        }
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
        async with self._session.get(_API_URL, params=params, timeout=timeout) as resp:
            if resp.status == 401:
                raise RuntimeError("API key rejected - check WUNDERGROUND_API_KEY")
            resp.raise_for_status()
            data = await resp.json()

        observations = data.get("observations") or []
        if not observations:
            # Also what an unverified "Data Expired" response (no
            # observation from this station in the last 60 minutes,
            # per Weather Underground's docs) is expected to look like.
            raise RuntimeError(f"no observations returned for station '{config.wunderground.station_id}' "
                                "(station may not have reported in the last 60 minutes)")
        obs = observations[0]
        metric = obs.get("metric") or {}

        temperature = metric.get("temp")
        humidity = obs.get("humidity")
        wind_direction = obs.get("winddir")
        wind_speed = metric.get("windSpeed")
        wind_gust = metric.get("windGust")
        rain_today = metric.get("precipTotal")
        solar = obs.get("solarRadiation")
        uv_index = obs.get("uv")

        self._update("BresserTemperature", temperature)
        self._update("BresserHumidity", humidity)
        self._update("BresserWindDirection", wind_direction)
        self._update("BresserWindAverageSpeed", wind_speed)
        self._update("BresserWindGustSpeed", wind_gust)
        self._update("BresserRainfall", rain_today)
        self._update("BresserLightIntensity", solar)
        self._update("BresserUVindex", uv_index)

        if not config.flags.do_fake:
            log(9, f"Wunderground: received {temperature}C, {humidity}% RH, "
                   f"wind {wind_speed} km/h @ {wind_direction} deg, rain {rain_today} mm")

    @staticmethod
    def _update(field: str, value) -> None:
        # A sensor the station doesn't have comes back as null - leave
        # display_data at its existing value rather than clobbering a real
        # prior reading with None.
        if value is not None:
            display_data.update(field, value, source="W")
