"""Port of SetFakeData(). Used when config.flags.do_fake is True, so the
screen/display side of the app can be developed away from the boat.

The old sentinel -123456789.0 ("not applicable in this mode") is now just
None - see display_data.py for why.
"""
from __future__ import annotations

from carpediem.ais.service import AisService
from carpediem.display_data import display_data

# Fake AIS traffic, moored at Grou, used to populate the real VesselTracker
# / OwnShipFix that EmtrakReader/AisStreamClient would otherwise fill from
# the em-trak unit + the AISstream.io API. Row 0 is CARPE DIEM herself (own
# ship); the rest are the nearby vessels.
# (mmsi, lat DMS, lon DMS, speed knots, bearing/COG deg, name)
_FAKE_AIS_VESSELS = [
    (244371971, (52, 10, 18.96, "N"), (4, 30, 56.82, "E"), 0, 300, "CARPE DIEM"),
    (244670657, (52, 10, 18.66, "N"), (4, 30, 59.49, "E"), 0, 220, "TRITON"),
    (244700238, (52, 10, 17.37, "N"), (4, 30, 57.32, "E"), 0, 110, "ZEEWOLF"),
    (244070819, (52, 9, 34.52, "N"), (4, 29, 28.18, "E"), 5, 269, "IRMA LA DOUCE"),
    (244830385, (52, 9, 36.12, "N"), (4, 30, 54.39, "E"), 9, 314, "ALPA"),
]


def _dms_to_decimal(degrees: int, minutes: int, seconds: float, hemisphere: str) -> float:
    value = degrees + minutes / 60.0 + seconds / 3600.0
    return -value if hemisphere in ("S", "W") else value


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
    "Weather": 1,
    "NextObject": "Spanjaardsbrug VHF 18",
}


def _populate_fake_ais(ais_service: AisService) -> None:
    """Fills the same VesselTracker + OwnShipFix the real AIS pipeline
    populates from the em-trak unit / AISstream.io, so downstream code
    (nearby_vessels(), _print_loop()'s formatting) needs no fake-mode
    special-casing."""
    own_mmsi, own_lat_dms, own_lon_dms, own_speed_knots, own_cog, own_name = _FAKE_AIS_VESSELS[0]
    own_fix = ais_service.reader.own_fix
    own_fix.lat = _dms_to_decimal(*own_lat_dms)
    own_fix.lon = _dms_to_decimal(*own_lon_dms)
    own_fix.sog_knots = own_speed_knots
    own_fix.cog = own_cog

    for mmsi, lat_dms, lon_dms, speed_knots, cog_deg, name in _FAKE_AIS_VESSELS[1:]:
        ais_service.tracker.update_position(
            mmsi, _dms_to_decimal(*lat_dms), _dms_to_decimal(*lon_dms), speed_knots, cog_deg)
        ais_service.tracker.set_name(mmsi, name)


def set_fake_data(ais_service: AisService | None = None) -> None:
    for label, value in _FAKE_VALUES.items():
        display_data.update(label, value, source="F")
    if ais_service is not None:
        _populate_fake_ais(ais_service)
