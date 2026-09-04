"""AISstream.io WebSocket client - port of connectAisStream(),
sendAisStreamSubscription(), onAisStreamMessage(), onAisStreamEvent() and
the resubscribe-on-drift logic from ais_nearby_vessels_7.ino.

Uses the `websockets` library's async client instead of ArduinoWebsockets,
fitting the asyncio architecture the rest of this port uses. TLS
certificate validation is left at Python's default (verified) - the
original called setInsecure() to skip cert validation, which was almost
certainly a memory/flash-space workaround on the ESP32 rather than a
deliberate choice; the Pi doesn't need that trade-off.
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional, Tuple

import websockets

from carpediem.config import config
from carpediem.logging_setup import log
from carpediem.ais.vessel_tracker import VesselTracker

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
BBOX_MARGIN_DEG = 1.0  # roughly ~110km lat / less in lon, generous margin
RESUB_THRESHOLD_DEG = 0.5  # resubscribe once we've drifted this far from the last box
RECONNECT_INTERVAL_SECONDS = 5

OwnPositionGetter = Callable[[], Optional[Tuple[float, float]]]


class AisStreamClient:
    def __init__(self, tracker: VesselTracker, get_own_position: OwnPositionGetter) -> None:
        self._tracker = tracker
        self._get_own_position = get_own_position
        self._sub_lat: Optional[float] = None
        self._sub_lon: Optional[float] = None

    def _build_subscription(self, lat: float, lon: float) -> str:
        return json.dumps({
            "APIKey": config.aisstream.api_key,
            "BoundingBoxes": [[
                [lat - BBOX_MARGIN_DEG, lon - BBOX_MARGIN_DEG],
                [lat + BBOX_MARGIN_DEG, lon + BBOX_MARGIN_DEG],
            ]],
            "FilterMessageTypes": ["ShipStaticData"],
        })

    def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("MessageType") != "ShipStaticData":
            return

        mmsi = msg.get("MetaData", {}).get("MMSI")
        name = msg.get("Message", {}).get("ShipStaticData", {}).get("Name")
        if not mmsi or not name:
            return

        trimmed = name.rstrip()  # AISstream names can carry the same trailing-space padding as raw AIS text fields
        if trimmed:
            self._tracker.set_name_from_aisstream(int(mmsi), trimmed)

    async def run_forever(self) -> None:
        """AISstream.io needs a real bounding box and the subscription has
        to go out within 3s of connecting, so - same as the original -
        this waits until an own-ship GPS fix is available before
        connecting at all."""
        if not config.aisstream.configured:
            log(9, "AISstream.io: no API key configured, skipping vessel-name lookups")
            return

        while True:
            own_pos = self._get_own_position()
            if own_pos is None:
                await asyncio.sleep(1)
                continue

            try:
                await self._run_one_connection(*own_pos)
            except Exception as exc:  # noqa: BLE001 - keep retrying
                log(9, f"AISstream.io: connection error, will retry: {exc}")

            await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)

    async def _run_one_connection(self, lat: float, lon: float) -> None:
        log(9, "AISstream.io: connecting...")
        async with websockets.connect(AISSTREAM_URL) as ws:
            log(9, "AISstream.io: connection opened")
            await ws.send(self._build_subscription(lat, lon))
            self._sub_lat, self._sub_lon = lat, lon
            log(9, "AISstream.io: connected and subscribed")

            while True:
                recv_task = asyncio.ensure_future(ws.recv())
                done, pending = await asyncio.wait({recv_task}, timeout=5)

                if recv_task in done:
                    raw = recv_task.result()
                    self._handle_message(raw)
                else:
                    recv_task.cancel()

                own_pos = self._get_own_position()
                if own_pos is not None and self._sub_lat is not None:
                    lat_drift = abs(own_pos[0] - self._sub_lat)
                    lon_drift = abs(own_pos[1] - self._sub_lon)
                    if lat_drift > RESUB_THRESHOLD_DEG or lon_drift > RESUB_THRESHOLD_DEG:
                        await ws.send(self._build_subscription(*own_pos))
                        self._sub_lat, self._sub_lon = own_pos
