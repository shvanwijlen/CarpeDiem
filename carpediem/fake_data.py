"""Port of SetFakeData(). Used when config.flags.do_fake is True, so the
screen/display side of the app can be developed away from the boat.

The old sentinel -123456789.0 ("not applicable in this mode") is now just
None - see display_data.py for why.
"""
from __future__ import annotations

from carpediem.display_data import display_data

_FAKE_VALUES = {
    "Active input source": 1,  # 0=Unknown;1=Grid;2=Generator;3=Shore power;240=Not connected
    "Grid (W)": 45,
    "AC Loads (W)": 26,
    "Battery SOC (%)": 65,
    "Battery0 Voltage (V)": 12.4,
    "Battery0 Power (W)": 23,
    "Battery0 Current (A)": 2.97234,
    "Battery Time to Go (System)": 47.87,  # is 0 when on grid power
    "Battery Time to Go (Batt)": None,
    "DC Power (W)": None,
    "DC Current (A)": None,
    "PV Power (W)": 89,
    "Starter battery (V)": 26.37,
    "Electronics bay (C)": 21.1,
    "Engine room (C)": 25.719999,
    "Lat": 52.171959,
    "Lng": 4.515833,
    "Speed": 8.45,
    "Course": 271,
    "Master Bedroom Temp": 20.5,
    "Master Bedroom Humidity": 71,
    "Engine Room Temp": 19.6,
    "Engine Room Humidity": 78,
    "Watertank SB Temp": 18.5,
    "Watertank SB Humidity": 44,
    "Watertank PS Temp": 33.9,
    "Watertank PS Humidity": 87.4,
    "Toilet Temp": 12.56,
    "Toilet Humidity": 88,
    "P RHT 900F0A Temp": 23.6,
    "P RHT 900F0A Humidity": 66,
    "Voorin Temp": 34.6,
    "Voorin Humidity": 78.6,
    "Kajuit Temp": 21.5,
    "Kajuit Humidity": 97.2,
    "Buitenkraan Temp": None,
    "Buitenkraan Humidity": None,
    "AIS": 1,
    "MQTT": 0,
    "MODBUS": 1,
    "BLE": 1,
}


def set_fake_data() -> None:
    for label, value in _FAKE_VALUES.items():
        display_data.update(label, value, source="F")
