"""Port of SetFakeData(). Used when config.flags.do_fake is True, so the
screen/display side of the app can be developed away from the boat.

The old sentinel -123456789.0 ("not applicable in this mode") is now just
None - see display_data.py for why.

Values below are a real snapshot captured from the boat on 2026-09-06
(lying in port at Marina Nieuwe Meer, own GPS fix but no COG - see
ais/service.py's DEFAULT_OWN_COG_DEG), rather than made-up numbers, so
screen/layout work against fake data sees realistic magnitudes, real MMSI
variety, and the actual set of sensors this boat doesn't have installed
(the Bresser weather station, BME280, spare-room temp/humidity sensors -
all None on the real unit, so None here too).
"""
from __future__ import annotations

from carpediem.ais.service import AisService
from carpediem.display_data import display_data

# Fake AIS traffic - a real nearby-vessel snapshot (own ship lying in port,
# 40 real targets from em-trak + AISstream.io) used to populate the real
# VesselTracker / OwnShipFix that EmtrakReader/AisStreamClient would
# otherwise fill from the em-trak unit + the AISstream.io API. Row 0 is
# CARPE DIEM herself (own ship); the rest are the nearby vessels. Target
# lat/lon are reconstructed from that snapshot's own-ship position plus
# each vessel's logged bearing/distance (the log itself only records
# bearing+distance, not lat/lon) - close enough for fake-data purposes,
# not surveyed positions.
# (mmsi, lat decimal, lon decimal, speed knots, COG deg or None, name or None)
_FAKE_AIS_VESSELS = [
    (244371971, 52.171967, 4.515800, 0.03, None, "CARPE DIEM"),  # own ship - no COG while lying in port
    (244700238, 52.171429, 4.515862, 0.0, 0, None),
    (244095552, 52.167380, 4.515800, 3.78, 178, None),
    (244650944, 52.160366, 4.515800, 0.0, 13, None),
    (244009320, 52.161133, 4.501500, 0.0, 292, "AMARONE"),
    (244060141, 52.159261, 4.504789, 4.59, 355, "COCOSMACROON"),
    (244710057, 52.156245, 4.511741, 0.0, 360, None),
    (244070815, 52.159253, 4.500185, 2.70, 2, None),
    (244260467, 52.156851, 4.503784, 3.73, 42, "SASKIA"),
    (244014995, 52.155341, 4.521560, 0.0, 0, "HALO"),
    (244850783, 52.188560, 4.504865, 0.0, 0, None),
    (244710596, 52.154461, 4.521865, 0.0, 360, "CORMORAAN"),
    (244030105, 52.153665, 4.513714, 0.11, 360, None),
    (244026030, 52.190369, 4.502435, 0.0, 360, "CYGNE"),
    (244000266, 52.186395, 4.491426, 0.81, 360, None),
    (244690728, 52.191172, 4.502502, 0.0, 360, None),
    (244131506, 52.190716, 4.500216, 0.0, 360, "DE BEER"),
    (244780740, 52.191337, 4.502387, 0.0, 360, None),
    (244746863, 52.191437, 4.501659, 1.67, 221, None),
    (244861965, 52.161368, 4.484642, 0.0, 360, "ANTOINETTE CHRISTINA"),
    (244391236, 52.190698, 4.497440, 0.0, 360, None),
    (244311844, 52.190775, 4.497364, 0.0, 360, None),
    (244710595, 52.161280, 4.483051, 0.0, 0, None),
    (244869866, 52.194413, 4.504605, 0.0, 132, None),
    (244180251, 52.194415, 4.503190, 0.0, 360, None),
    (244810824, 52.149573, 4.535204, 0.0, 159, None),
    (244987437, 52.189960, 4.545156, 0.0, 360, "SABOT"),
    (244002047, 52.149335, 4.535410, 0.0, 360, "ZEEAREND"),
    (244620395, 52.149768, 4.536686, 0.0, 8, None),
    (244864056, 52.146896, 4.524484, 5.08, 152, None),
    (244377338, 52.198238, 4.509776, 0.0, 360, None),
    (244180300, 52.198999, 4.513489, 4.91, 252, None),
    (244034517, 52.198977, 4.511168, 0.0, 360, None),
    (244060482, 52.196485, 4.536183, 0.0, 360, None),
    (244060840, 52.196645, 4.536316, 0.0, 360, None),
    (244376276, 52.152949, 4.549032, 4.81, 226, "LEIDSE KEIJZER"),
    (244260064, 52.156119, 4.554081, 4.32, 224, None),
    (244010283, 52.197977, 4.540303, 0.0, 360, None),
    (244615508, 52.197977, 4.540303, 0.0, 360, "JOLLY ROGER"),
    (244110037, 52.203074, 4.527519, 6.21, 301, "BREAKWATER"),
    (244700602, 52.141087, 4.540339, 0.0, 360, None),
    (244393997, 52.200946, 4.552749, 0.0, 360, "BONA SPES 4"),
]


_FAKE_VALUES = {
    "Active input source": 1,  # 0=Unknown;1=Grid;2=Generator;3=Shore power;240=Not connected
    "Grid (W)": 57,
    "AC Loads (W)": 48,
    "Battery SOC (%)": 100,
    "Battery0 Voltage (V)": 13.61,
    "Battery0 Power (W)": 5.44,
    "Battery0 Current (A)": 0.4,
    "Battery Power (W)": 4.08,
    "Battery Current (A)": 0.3,
    "Battery1 Voltage (V)": 26.36,
    "Battery1 Power (W)": None,
    "Battery1 Current (A)": None,
    "Battery Time to Go (System)": None,
    "Battery Time to Go (Batt)": None,
    "Battery system SOC (%)": 100, #redundant as we use the SOC data for display from another source, but we keep it here for completeness # the use of term "system" is misleading but oh well
    "Battery system Voltage (V)": 13.6, #redundant as we use the voltage data for display from another source, but we keep it here for completeness    # the use of term "system" is misleading but oh well
    "DC Power (W)": None,
    "DC Current (A)": None,
    "PV Power (W)": 24,
    "Starter battery (V)": 26.36,
    "Electronics bay (C)": 29.41,
    "Engine room (C)": 20.12,
    "Lat": 52.171967,
    "Lng": 4.515800,
    "Speed": 12.048152,
    # Real snapshot had no COG (lying in port, not moving) - 180 is an
    # illustrative value (not from the boat) so the Main page's compass
    # rose has something to show during HMI screen development.
    "Course": 180,
    "VesselsBehindMe": 5,
    "VesselsFasterThan10": 3,
    "VesselsOther": 32,
    "NextObject": None,
    "Master Bedroom Temp": 21.68,
    "Master Bedroom Humidity": 63,
    "Engine Room Temp": 21.12,
    "Engine Room Humidity": 61,
    "Watertank SB Temp": 20.43,
    "Watertank SB Humidity": 62,
    "Watertank PS Temp": 20.94,
    "Watertank PS Humidity": 60,
    "RuuviConsoleTemp": 32.82,
    "RuuviConsoleHumidity": 34.22,
    "RuuviWatertankPSTemp": 26.89,
    "RuuviWatertankPSHumidity": 45.8,
    "Toilet Temp": 19.73,
    "Toilet Humidity": 73,
    "P RHT 900F0A Temp": 24.08,
    "P RHT 900F0A Humidity": 52,
    "Voorin Temp": 26.09,
    "Voorin Humidity": 53,
    "Kajuit Temp": 26.54,
    "Kajuit Humidity": 53,
    "Buitenkraan Temp": None,
    "Buitenkraan Humidity": None,
    "BresserTemperature": None,  # not installed on this boat - real unit reports None too
    "BresserHumidity": None,
    "BresserWindDirection": None,
    "BresserWindGustSpeed": None,
    "BresserWindAverageSpeed": None,
    "BresserRainfall": None,
    "BresserLightIntensity": None,
    "BresserUVindex": None,
    "BresserSensorBatteryStatus": None,
    "BME280-Barometer": None,  # not installed on this boat - real unit reports None too
    "BME280-Humidity": None,
    "BME280-Temperature": None,
    # Both None on the real snapshot too (Bresser not installed on this
    # boat), but the Main page's compass rose needs values to plot its two
    # wind-direction markers - 90 is the exact worked example from the
    # Screen design v02.xlsx "Claude prompts" tab (Bresser=126, course=180,
    # calibration=216 => (126+180-216) mod 360 = 90); 55 for "as
    # experienced" is just a distinct illustrative value, not derived from
    # a real formula (none was specified).
    "WindspeedCalculatedRecalibrated": 90,
    "WindspeedCalculatedAsExperienced": 55,
    "RingBatterySalon": 76,
    "RingBatteryBakboord": 90,
    "RingBatteryStuurboord": 90,
    "RingConnectionSalon": "online",
    "RingConnectionBakboord": "online",
    "RingConnectionStuurboord": "online",
    "AIS": 1,
    "MQTT": 1,
    "MODBUS": 1,
    "BLE": 1,
    "Weather": None,
    "Cam": 1,
    "Display": 0,
    # Note: no "WiFi" entry here - wifi_monitor.py runs a real connectivity
    # check even in fake mode (see status_monitor.py), it isn't faked.
    "AISstream": 1,
    "AISAntenna": 1,
    "Weather433": None,  # not wired up yet
    "Weather280": None,  # not wired up yet
    "WebServer": None,  # not wired up yet
}


def _populate_fake_ais(ais_service: AisService) -> None:
    """Fills the same VesselTracker + OwnShipFix the real AIS pipeline
    populates from the em-trak unit / AISstream.io, so downstream code
    (nearby_vessels(), _print_loop()'s formatting) needs no fake-mode
    special-casing."""
    _, own_lat, own_lon, own_speed_knots, own_cog, _ = _FAKE_AIS_VESSELS[0]
    own_fix = ais_service.reader.own_fix
    own_fix.lat = own_lat
    own_fix.lon = own_lon
    own_fix.sog_knots = own_speed_knots
    own_fix.cog = own_cog

    # Same illustrative override as "Course"/"Speed" in _FAKE_VALUES above
    # (real snapshot had no COG while lying in port) - kept in sync so the
    # Main and AIS pages don't show two different "my course"/"my speed"
    # numbers in fake mode.
    own_fix.cog = _FAKE_VALUES["Course"]
    own_fix.sog_knots = _FAKE_VALUES["Speed"] / 1.852

    for mmsi, lat, lon, speed_knots, cog_deg, name in _FAKE_AIS_VESSELS[1:]:
        ais_service.tracker.update_position(mmsi, lat, lon, speed_knots, cog_deg)
        if name is not None:
            ais_service.tracker.set_name(mmsi, name)

    # Illustrative sent/received message counters (the real snapshot has
    # no equivalent - these are purely a live tally since process start,
    # see emtrak_reader.py) - S:628 (412+216+0) / R:74672 matches the
    # Screen design v02.xlsx "A" tab's example data exactly.
    ais_service.reader.own_reports_type18 = 412
    ais_service.reader.own_reports_type19 = 216
    ais_service.reader.own_reports_other = 0
    ais_service.reader.received_reports = 74672


def set_fake_data(ais_service: AisService | None = None) -> None:
    for label, value in _FAKE_VALUES.items():
        display_data.update(label, value, source="F")
    if ais_service is not None:
        _populate_fake_ais(ais_service)
