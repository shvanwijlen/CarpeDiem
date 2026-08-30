"""Port of the BLE scanning + parseTeltonikaAdv() code that reads
Teltonika Blue Puck temperature/humidity beacons.

Simplification vs the original: ArduinoBLE only hands you raw
advertisement bytes, so the sketch hand-parsed AD structures byte-by-byte
looking for a Service Data (0x16) block with UUID 0x2A6E/0x2A6F. bleak
(via BlueZ on the Pi) already parses AD structures for us and exposes
`AdvertisementData.service_data` as a {uuid: bytes} dict, so that manual
byte-walking loop is gone - we just look up the two UUIDs directly.

Field naming still depends on each puck's advertised BLE name matching an
existing display_data field (e.g. a puck named "Watertank SB" produces
"Watertank SB Temp" / "Watertank SB Humidity" - see display_data.py's
field list), exactly like the original. One resilience improvement: BLE
advertisements are sometimes split across multiple packets, so a given
callback firing may have service data but no name in that same packet.
We now cache the last-seen name per MAC address so a name-less packet
can still be attributed correctly, instead of being silently dropped.
"""
from __future__ import annotations

import struct
from typing import Dict, Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from carpediem.display_data import display_data
from carpediem.logging_setup import log

# Teltonika Blue Puck devices (MAC addresses), ported 1:1 from knownDevices[]
KNOWN_DEVICES = {
    "F3:06:2D:7C:87:AF",
    "FC:F1:E2:2A:95:C5",
    "C0:BB:A1:89:54:F4",
    "C2:D6:33:33:3B:31",
    "ED:2D:13:21:8C:58",
    "F3:86:A8:30:7B:AE",
    "F1:B1:FD:48:2B:78",
    "EA:4F:38:E0:93:D9",
    "F7:F7:21:2D:12:D4",
}

_UUID_TEMPERATURE = "00002a6e-0000-1000-8000-00805f9b34fb"
_UUID_HUMIDITY = "00002a6f-0000-1000-8000-00805f9b34fb"


class BleScanner:
    def __init__(self) -> None:
        self._scanner: Optional[BleakScanner] = None
        self._last_name: Dict[str, str] = {}

    async def start(self) -> None:
        log(9, "BLE: starting scan for Teltonika Blue Pucks...")
        self._scanner = BleakScanner(detection_callback=self._on_detection)
        try:
            await self._scanner.start()
            display_data.update("BLE", 1, source="S")
        except Exception as exc:  # noqa: BLE001
            log(9, f"BLE: failed to start scan: {exc}")
            display_data.update("BLE", 0, source="S")
            self._scanner = None

    async def stop(self) -> None:
        if self._scanner is not None:
            await self._scanner.stop()
            self._scanner = None

    def _on_detection(self, device: BLEDevice, adv: AdvertisementData) -> None:
        address = device.address.upper()
        if address not in KNOWN_DEVICES:
            return

        name = adv.local_name or self._last_name.get(address)
        if adv.local_name:
            self._last_name[address] = adv.local_name
        if not name:
            log(10, f"BLE: known device {address} seen, but no name yet - skipping this packet")
            return

        log(10, f"BLE device found: name={name}; address={address}")
        self._parse_service_data(name, adv.service_data or {})

    def _parse_service_data(self, name: str, service_data: Dict[str, bytes]) -> None:
        temp_bytes = service_data.get(_UUID_TEMPERATURE)
        if temp_bytes and len(temp_bytes) >= 2:
            raw = struct.unpack_from("<h", temp_bytes, 0)[0]  # int16, little-endian
            temperature = raw / 100.0
            display_data.update(f"{name} Temp", temperature, source="B")

        hum_bytes = service_data.get(_UUID_HUMIDITY)
        if hum_bytes:
            if len(hum_bytes) == 1:
                humidity = hum_bytes[0] * 1.0
            elif len(hum_bytes) >= 2:
                raw = struct.unpack_from("<H", hum_bytes, 0)[0]  # uint16, little-endian
                humidity = raw / 100.0
            else:
                return
            display_data.update(f"{name} Humidity", humidity, source="B")
