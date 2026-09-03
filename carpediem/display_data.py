"""Port of `struct DisplayInfoStruct DisplayInfo[]` + `UpdateDisplayTable()`.

Design changes from the original:
- The sentinel value -123456789.0 ("not yet read") is replaced by Python's
  `None` - it means the same thing but can't be confused with a real
  reading and doesn't need every consumer to know the magic number.
- It's a dict keyed by internal_label instead of a linear-scan array, so
  updates are O(1) instead of O(n) (numDisplayTopics is 41 entries, not
  that it mattered at Arduino loop speeds, but it's simpler this way).
- It's protected by a lock, because unlike the single-threaded Arduino
  loop(), the Python port updates this from several concurrent tasks
  (Modbus polling, MQTT callback, BLE scanning, AIS/GPS reading).
- The weird `if pSource == "T": delay(15000)` behaviour for an unmatched
  label (a debug leftover in the original that would silently freeze the
  whole board for 15s) is dropped - an unmatched label now just logs a
  warning once.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from carpediem.logging_setup import log

# (internal_label, display_label) - ported 1:1 from the sketch's DisplayInfo[]
_FIELD_DEFINITIONS = [
    ("Active input source", "Grid Status"),  # 0=Unknown;1=Grid;2=Generator;3=Shore power;240=Not connected
    ("Grid (W)", "Grid (W)"),
    ("AC Loads (W)", "AC Loads (W)"),
    ("Battery SOC (%)", "Battery SOC (%)"),
    ("Battery0 Voltage (V)", "Battery0 Voltage (V)"),
    ("Battery0 Power (W)", "Battery0 Power (W)"),
    ("Battery0 Current (A)", "Battery0 Current (A)"),
    # The following 4 fields did not exist in the original DisplayInfo[]
    # array, even though the MQTT topic table (myVictronMQTT[]) already
    # subscribed to battery/278/Dc/1/* and system/0/Dc/Battery/Power - the
    # mqtt callback() had working code paths for these values, they just
    # had nowhere to land, so they were silently dropped. Added here so
    # that data isn't thrown away; see mqtt_client.py for the mapping.
    ("Battery Power (W)", "Battery Power (W)"),
    ("Battery Current (A)", "Battery Current (A)"),
    ("Battery1 Voltage (V)", "Battery1 Voltage (V)"),
    ("Battery1 Power (W)", "Battery1 Power (W)"),
    ("Battery1 Current (A)", "Battery1 Current (A)"),
    ("Battery Time to Go (System)", "TTG (System)"),
    ("Battery Time to Go (Batt)", "TTG (Batt)"),
    ("DC Power (W)", "DC Power (W)"),
    ("DC Current (A)", "DC Current (A)"),
    ("PV Power (W)", "PV Power (W)"),
    ("Starter battery (V)", "Starter battery (V)"),
    ("Electronics bay (C)", "Electronics bay (C)"),
    ("Engine room (C)", "Engine room (C)"),
    ("Lat", "Lat"),
    ("Lng", "Lng"),
    ("Speed", "Speed"),
    ("Course", "Course"),
    ("Master Bedroom Temp", "Master Bedroom Temp"),
    ("Master Bedroom Humidity", "Master Bedroom Humidity"),
    ("Engine Room Temp", "Engine Room Temp"),
    ("Engine Room Humidity", "Engine Room Humidity"),
    ("Watertank SB Temp", "Watertank SB Temp"),
    ("Watertank SB Humidity", "Watertank SB Humidity"),
    ("Watertank PS Temp", "Watertank PS Temp"),
    ("Watertank PS Humidity", "Watertank PS Humidity"),
    ("Toilet Temp", "Toilet Temp"),
    ("Toilet Humidity", "Toilet Humidity"),
    ("P RHT 900F0A Temp", "Washcabin Temp"),
    ("P RHT 900F0A Humidity", "Washcabin Humidity"),
    ("Voorin Temp", "Voorin Temp"),
    ("Voorin Humidity", "Voorin Humidity"),
    ("Kajuit Temp", "Kajuit Temp"),
    ("Kajuit Humidity", "Kajuit Humidity"),
    ("Buitenkraan Temp", "Buitenkraan Temp"),
    ("Buitenkraan Humidity", "Buitenkraan Humidity"),
    ("BresserTemperature", "Outside temperature"), 
    ("BresserHumidity", "Electronics Bay Humidity"),
    ("BresserWindDirection", "Wind direction"),
    ("BresserWindGustSpeed", "Wind Gust Speed"),
    ("BresserWindAverageSpeed", "Wind Average Speed"), 
    ("BresserRainfall", "Rain fall (cumm, mm)"), 
    ("BresserLightIntensity", "Light Intensity"), 
    ("BresserUVindex", "UV index"), 
    ("BresserSensorBatteryStatus", "Bresser Sensor Battery Status"),
    ("BME280-Barometer", "Barometer"), 
    ("BME280-Humidity", "Elecs Bay Humidity"), 
    ("BME280-Temperature", "Elecs Bay Temperature"), 
    ("WindspeedCalculatedRecalibrated", "WindspeedCalculatedRecalibrated"), 
    ("WindspeedCalculatedAsExperienced", "WindspeedCalculatedAsExperienced"),
    ("AIS", "AIS"),
    ("MQTT", "MQTT"),
    ("MODBUS", "MODBUS"),
    ("BLE", "BLE"),
    ("Weather", "Weather"),
    ("NextObject", "Next object"),
    # Note: no "WiFi" entry - that was ESP32-WiFi-connect status, which has
    # no equivalent on the Pi (the OS manages the network, not this app).
]


@dataclass
class DisplayField:
    internal_label: str
    display_label: str
    value: Optional[Any] = None
    last_source: Optional[str] = None


class DisplayDataStore:
    """Thread-safe port of the DisplayInfo[] array + UpdateDisplayTable()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fields: Dict[str, DisplayField] = {
            internal: DisplayField(internal, display)
            for internal, display in _FIELD_DEFINITIONS
        }
        self._warned_unknown: set[str] = set()

    def update(self, internal_label: str, value: Any, source: str = "") -> None:
        """Port of UpdateDisplayTable(pLabel, pValue, pSource)."""
        with self._lock:
            field = self._fields.get(internal_label)
            if field is None:
                if internal_label not in self._warned_unknown:
                    log(9, f"UpdateDisplayTable: unknown label '{internal_label}', ignoring")
                    self._warned_unknown.add(internal_label)
                return
            field.value = value
            field.last_source = source

    def get(self, internal_label: str) -> Optional[Any]:
        with self._lock:
            field = self._fields.get(internal_label)
            return field.value if field else None

    def snapshot(self) -> Dict[str, DisplayField]:
        """A point-in-time copy, safe to iterate/render without holding the lock."""
        with self._lock:
            return {k: DisplayField(v.internal_label, v.display_label, v.value, v.last_source)
                    for k, v in self._fields.items()}

    def all_labels(self) -> Iterable[str]:
        return self._fields.keys()


# Module-level singleton, mirroring the sketch's single global DisplayInfo[].
display_data = DisplayDataStore()
