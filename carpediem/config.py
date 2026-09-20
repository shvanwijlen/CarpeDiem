"""Central configuration, loaded from environment variables / .env.

This replaces arduino_secrets.h / arduino_secrets_home.h and the block of
`bool DoWiFi / DoBLE / DoMODBUS / DoMQTT / DoGPS / DoFake / DoShow` globals
at the top of the Arduino sketch.

Nothing here talks to hardware or the network - it's pure config parsing,
which makes it easy to unit test and easy to reason about what DoFake
actually overrides.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present (never committed - see .gitignore). Real deployments
# (systemd service, docker, etc.) can instead set these as real env vars.
load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _str(name: str, default: str = "") -> str:
    val = os.getenv(name)
    return val if val is not None else default


@dataclass
class FeatureFlags:
    """Equivalent of the sketch's DoWiFi/DoBLE/DoMODBUS/DoMQTT/DoGPS/DoFake/DoShow.

    DoWiFi has no Python equivalent - the Pi's network is managed by the OS,
    not by this app, so it's simply not a flag here.
    """

    do_fake: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_FAKE", True))
    do_modbus: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_MODBUS", True))
    do_mqtt: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_MQTT", True))
    do_ble: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_BLE", True))
    do_ais: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_AIS", True))
    do_ring: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_RING", True))
    do_wunderground: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_WUNDERGROUND", True))
    do_vaarweg: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_VAARWEG", True))
    do_gpx_log: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_GPX_LOG", True))
    do_show: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_SHOW", True))

    use_rtc: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_RTC", False))
    use_matrix: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_MATRIX", False))
    use_hmi: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_HMI", False))
    check_hdmi: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_HDMI", True))
    check_wifi: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_WIFI", True))
    check_sysmetrics: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_SYSMETRICS", True))
    use_ups_monitor: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_UPS_MONITOR", False))
    use_bme280: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_BME280", False))
    # Local RTL-SDR direct decode of the Bresser 7-in-1 station, as an
    # alternative to do_wunderground - see bresser_rtl_client.py. Despite the
    # "use_" naming (matching use_bme280's "local hardware" naming), this
    # IS forced off under CARPEDIEM_DO_FAKE - see __post_init__ below: unlike
    # use_ups_monitor/use_matrix/etc, RTL reception only works within range
    # of the boat's own antenna, so it's not meaningfully "testable on the
    # bench" away from the boat the way those are.
    use_bresser_rtl: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_BRESSER_RTL", False))
    # Read-only JSON API exposing display_data - see web_server.py. On by
    # default (unlike the hardware flags above): it's a pure software
    # service with no real-world side effects, so there's no reason not to
    # have it running, including in fake mode - useful for developing the
    # Arduino/iPhone consumers against fake data without needing the boat.
    use_webserver: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_WEBSERVER", True))

    def __post_init__(self) -> None:
        # Mirrors the sketch's `if (DoFake) { DoBLE=false; DoMODBUS=false;
        # DoMQTT=false; DoGPS=false; DoShow=true; SetFakeData(); }` block:
        # fake mode always wins over the individual flags for anything that
        # touches real boat hardware/network, but display output stays on.
        if self.do_fake:
            self.do_modbus = False
            self.do_mqtt = False
            self.do_ble = False
            self.do_ais = False
            self.do_ring = False
            # Weather source pair: opposite of the boat-network subsystems
            # above. do_wunderground is a plain internet API call, reachable
            # from anywhere (e.g. developing at home) - forced ON in fake
            # mode so there's still real Bresser weather data to look at.
            # use_bresser_rtl needs the boat's own RTL-SDR dongle/antenna in
            # range of the actual station, which a dev machine away from the
            # boat never has - forced OFF, unlike the "testable on the
            # bench" hardware flags below.
            self.do_wunderground = True
            self.use_bresser_rtl = False
            # BME280: real hardware reads only make sense with the sensor
            # actually wired up on the boat/bench in front of you - forced
            # off in fake mode so fake_data.py's illustrative
            # sparkfun_elec_bay_temperature/humidity values show instead of
            # a real (or, with nothing wired up, silently-failing) reading.
            self.use_bme280 = False
            # self.do_show = True # always use .env variable ss I may or may not want to see the display on a dev machine with no boat network at all and log the data elements to the console instead
            self.use_rtc = False
            self.check_hdmi = False
            # use_ups_monitor, use_matrix, use_hmi, check_sysmetrics and
            # use_webserver are deliberately NOT forced off here: they're
            # local hardware/OS state on the Pi itself (or, for the
            # HMI/webserver, useful to run on a dev machine with no boat
            # network at all), unrelated to "on the boat's network or not" -
            # you should be able to test the PLD/matrix/touchscreen/CPU-
            # load/data-API on the bench with CARPEDIEM_DO_FAKE still on.
            #
            # check_wifi is also deliberately left alone: in fake mode the
            # status matrix still shows a real WiFi check (heart only once
            # WiFi is actually up), everything else is assumed fine - see
            # status_monitor.py.
            #
            # do_vaarweg is also deliberately NOT forced off: it looks up
            # the next bridge/lock from Lat/Lng/Course/Speed in
            # display_data against a real government API - those fields
            # come from fake_data.py in fake mode, but the lookup itself
            # is real, so it needs to keep running to be testable without
            # actually being underway. See vaarweg_client.py.
            #
            # do_gpx_log is the same story: it records whatever Lat/Lng is
            # currently in display_data (real or fake) and does one real
            # reverse-geocoding lookup against a live API at startup - both
            # the file-writing and the geocoding call need to stay
            # exercisable without actually being underway. See
            # gpx_logger.py. A fake-mode run just produces a short,
            # single-point/stationary track, which is harmless.


@dataclass
class CerboConfig:
    host: str = field(default_factory=lambda: _str("CERBO_HOST", "192.168.1.228"))
    port: int = field(default_factory=lambda: _int("CERBO_PORT", 502))


@dataclass
class MqttConfig:
    host: str = field(default_factory=lambda: _str("MQTT_HOST", "venus.local"))
    port: int = field(default_factory=lambda: _int("MQTT_PORT", 1883))
    portal_id: str = field(default_factory=lambda: _str("VRM_PORTAL_ID"))


@dataclass
class EmtrakConfig:
    host: str = field(default_factory=lambda: _str("EMTRAK_HOST", "192.168.2.1"))
    port: int = field(default_factory=lambda: _int("EMTRAK_PORT", 5000))


@dataclass
class AisStreamConfig:
    """AISstream.io (https://aisstream.io) - free WebSocket feed used for
    vessel-name lookups. Superseded the earlier VesselAPI idea (rate/key
    limits made that impractical for continuous use - see the CarpeDiem
    sketch's own TODO comment); AISstream.io has no such quota."""
    api_key: str = field(default_factory=lambda: _str("AISSTREAM_API_KEY"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class AisConfig:
    """General AIS nearby-vessel tracking settings (distinct from
    AisStreamConfig, which is only about the aisstream.io name-lookup
    feed)."""

    max_range_km: float = field(default_factory=lambda: _float("CARPEDIEM_AIS_MAX_RANGE_KM", 5.0))


@dataclass
class RingConfig:
    """Ring cloud API access (battery level only, for now) via the
    unofficial ring-doorbell package - Ring has no official public API.

    Auth is a two-step dance: the first login needs a password + a 2FA
    code, which this always-on service can't prompt for. Run
    scripts/ring_auth_setup.py once, interactively, to do that handshake -
    it caches the resulting refresh token to token_file, and RingClient
    only ever needs that cached token afterwards.
    """
    username: str = field(default_factory=lambda: _str("RING_USERNAME"))
    password: str = field(default_factory=lambda: _str("RING_PASSWORD"))
    token_file: Path = field(default_factory=lambda: Path(_str("RING_TOKEN_FILE", "./ring_token.cache")))
    poll_interval_seconds: float = field(default_factory=lambda: _float("RING_POLL_INTERVAL_SECONDS", 600.0))  # 10 min

    # Optional, off by default: also fetch a still snapshot per camera
    # each poll (same interval as battery/connection above) for the Cam
    # page's "live feed" tile. Off by default because a boat's internet
    # is often metered (satellite/cellular) and a JSON status poll is a
    # few bytes vs. a JPEG per camera every poll_interval_seconds.
    fetch_snapshots: bool = field(default_factory=lambda: _bool("RING_FETCH_SNAPSHOTS", False))
    snapshot_dir: Path = field(default_factory=lambda: Path(_str("RING_SNAPSHOT_DIR", "./ring_snapshots")))

    # Ring device name (as shown in the Ring app) -> display_data internal_label.
    # Console is a wired Pan-Tilt cam - the Ring API still reports a
    # battery_life for it (typically pinned at 100, no real cell behind
    # it), so the field is populated the same as the battery cameras; the
    # Cam page can decide later whether to show/ignore it for this one.
    camera_field_map: dict[str, str] = field(default_factory=lambda: {
        _str("RING_CAM_SALON_NAME", "Salon"): "RingBatterySalon",
        _str("RING_CAM_BAKBOORD_NAME", "Bakboord"): "RingBatteryBakboord",
        _str("RING_CAM_STUURBOORD_NAME", "Stuurboord"): "RingBatteryStuurboord",
        _str("RING_CAM_CONSOLE_NAME", "Console"): "RingBatteryConsole",
    })

    @property
    def camera_connection_field_map(self) -> dict[str, str]:
        """Same camera-name keys as camera_field_map, derived rather than
        configured separately so a renamed camera only needs updating in
        one place. E.g. "RingBatterySalon" -> "RingConnectionSalon"."""
        return {
            name: battery_field.replace("RingBattery", "RingConnection")
            for name, battery_field in self.camera_field_map.items()
        }


@dataclass
class WundergroundConfig:
    """Weather Underground's PWS API (api.weather.com/v2/pws/observations/current)
    - the boat's Bresser 7-in-1 weather station has WiFi and can upload
    there (check the gateway/app's upload settings if it isn't already
    enabled). This used to be the second of two cloud sources for the same
    readings, alongside a ProWeatherLive-based bresser_client.py - that one
    was removed (its public subdomain was never reliable for this station)
    in favor of BresserRtlConfig/bresser_rtl_client.py, which decodes the
    station's own 868MHz broadcast directly instead of going through any
    cloud API. See CARPEDIEM_USE_BRESSER_RTL in .env.example for picking
    between this and the local RTL-SDR source.

    station_id is the PWS ID assigned when you register the station at
    wunderground.com (looks like "KXXTOWN123"). api_key is a free personal
    key from your Wunderground account (Member Settings -> API Keys) - the
    PWS API needs one even though the endpoint is otherwise about reading
    back your own station's data.
    """
    station_id: str = field(default_factory=lambda: _str("WUNDERGROUND_STATION_ID"))
    api_key: str = field(default_factory=lambda: _str("WUNDERGROUND_API_KEY"))
    poll_interval_seconds: float = field(default_factory=lambda: _float("WUNDERGROUND_POLL_INTERVAL_SECONDS", 300.0))

    @property
    def configured(self) -> bool:
        return bool(self.station_id) and bool(self.api_key)


@dataclass
class BresserRtlConfig:
    """Local RTL-SDR direct decode of the boat's Bresser 7-in-1 station -
    see bresser_rtl_client.py and scripts/rtl433_sniff.py (the throwaway
    diagnostic this is based on). Needs the rtl_433 binary (`sudo apt
    install rtl-433`) and an RTL-SDR dongle + antenna wired up. The 868.3MHz
    frequency the Bresser 7-in-1 (EU) transmits its FSK broadcast on is
    hardcoded in bresser_rtl_client.py, not exposed here - see that module's
    docstring for why 433.92MHz (the more commonly-assumed ISM frequency)
    is wrong for this device.

    station_id optionally filters rtl_433's decoded 'id' field so a
    neighboring, identical-model Bresser station (same model name, same
    frequency) never gets mistaken for this boat's own one while docked
    near another Bresser owner - 0 (default/unset) means "accept whichever
    Bresser-7in1 packet comes in, no filtering". Find your station's real
    id by running scripts/rtl433_sniff.py (now retuned to 868.3MHz) and
    reading the 'id' field back.
    """
    station_id: int = field(default_factory=lambda: _int("BRESSER_RTL_STATION_ID", 0))


@dataclass
class VaarwegConfig:
    """Next-bridge-or-lock lookup (Main page's center banner) via
    Rijkswaterstaat's public "Blauwe Golf, Verbindend" (BGV) REST API -
    https://api.vaarweginformatie.nl/bgv/information/, documented in
    BGV.IRS.informatiewebservice.v1.11.pdf - plain HTTPS GET, JSON
    response, no API key. See vaarweg_client.py.

    min_range_km/lookahead_minutes together set the search radius: how
    far the boat would travel in lookahead_minutes at its current speed,
    but never less than min_range_km (a stopped or very slow boat still
    gets a sensible "what's nearby" radius rather than an ever-shrinking
    one). ahead_half_angle_deg is how far either side of dead-ahead an
    object can be and still count as "ahead" - 90 matches the same
    ahead-vs-behind convention the Main page's AIS radar already uses
    (see main_page.py's `abs(r.relative_bearing_deg) > 90`).
    """
    poll_interval_seconds: float = field(default_factory=lambda: _float("VAARWEG_POLL_INTERVAL_SECONDS", 30.0))
    min_range_km: float = field(default_factory=lambda: _float("VAARWEG_MIN_RANGE_KM", 3.0))
    lookahead_minutes: float = field(default_factory=lambda: _float("VAARWEG_LOOKAHEAD_MINUTES", 30.0))
    ahead_half_angle_deg: float = field(default_factory=lambda: _float("VAARWEG_AHEAD_HALF_ANGLE_DEG", 90.0))
    locks_cache_seconds: float = field(default_factory=lambda: _float("VAARWEG_LOCKS_CACHE_SECONDS", 600.0))
    base_url: str = field(default_factory=lambda: _str(
        "VAARWEG_BASE_URL", "https://api.vaarweginformatie.nl/bgv/information"))


@dataclass
class GpxConfig:
    """One GPX track file per run of the app, from startup to shutdown -
    see gpx_logger.py. poll_interval_seconds is how often the current
    Lat/Lng (real GPS/AIS fix, or fake_data.py's value in fake mode) gets
    appended as a track point; min_points_to_write skips writing a file
    at all for a run that never got a single fix (e.g. killed immediately
    after starting).

    The nearest-city name for the filename comes from one reverse-geocode
    lookup against OpenStreetMap's free Nominatim API, done once against
    the first fix of the run (a boat doesn't cross into a different city
    fast enough for this to need repeating) - a bare hostname/path here
    rather than the vaarweg pattern of a versioned spec doc, since
    Nominatim's reverse endpoint is simple enough not to need one.
    """
    poll_interval_seconds: float = field(default_factory=lambda: _float("GPX_POLL_INTERVAL_SECONDS", 15.0))
    min_points_to_write: int = field(default_factory=lambda: _int("GPX_MIN_POINTS_TO_WRITE", 1))
    output_dir: Path = field(default_factory=lambda: Path(_str("GPX_OUTPUT_DIR", "./gpx_tracks")))
    reverse_geocode_url: str = field(default_factory=lambda: _str(
        "GPX_REVERSE_GEOCODE_URL", "https://nominatim.openstreetmap.org/reverse"))


@dataclass
class BleConfig:
    """Teltonika Blue Puck BLE scan cadence (see ble_client.py). Temp/
    humidity readings change slowly, so there's no need to keep the
    Bluetooth radio scanning continuously - scan_window_seconds is how
    long each scan listens before stopping again (long enough to hear
    from every known puck at least once - they advertise every few
    seconds).

    The gap between scans is speed-adaptive rather than a single fixed
    interval, to save house-battery power while at anchor/moored (the
    Pi's Bluetooth radio isn't free) without going stale while underway:
    above moving_speed_threshold (Speed display field, km/h) the boat is
    assumed underway with the engine/alternator running, so it polls
    every moving_poll_interval_seconds; at or below it - including before
    the first GPS/AIS fix, when Speed is still None - it's assumed at
    rest and polls only every stationary_poll_interval_seconds."""
    moving_poll_interval_seconds: float = field(
        default_factory=lambda: _float("BLE_MOVING_POLL_INTERVAL_SECONDS", 300.0))  # 5 min
    stationary_poll_interval_seconds: float = field(
        default_factory=lambda: _float("BLE_STATIONARY_POLL_INTERVAL_SECONDS", 21600.0))  # 6 hours
    moving_speed_threshold: float = field(default_factory=lambda: _float("BLE_MOVING_SPEED_THRESHOLD", 1.0))
    scan_window_seconds: float = field(default_factory=lambda: _float("BLE_SCAN_WINDOW_SECONDS", 60.0))


@dataclass
class SysMetricsConfig:
    """CPU/memory/disk thresholds for the top bar's SYS status LED (the
    "spare"/unused 8th indicator slot) - see sysmetrics_monitor.py. Status
    is green below the warn threshold, orange from warn up to crit, red at
    or above crit; the LED shows the worst of the three metrics."""

    poll_interval_seconds: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_POLL_INTERVAL_SECONDS", 10.0))
    disk_path: str = field(default_factory=lambda: _str("CARPEDIEM_SYSMETRICS_DISK_PATH", "/"))
    cpu_warn_percent: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_CPU_WARN_PERCENT", 60.0))
    cpu_crit_percent: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_CPU_CRIT_PERCENT", 85.0))
    mem_warn_percent: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_MEM_WARN_PERCENT", 70.0))
    mem_crit_percent: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_MEM_CRIT_PERCENT", 90.0))
    # These two are of disk *used* percent (100 - free%), even though the
    # rest of the app talks about "remaining disk space" - used% is what
    # actually trips a warning as it climbs, so it matches cpu/mem's
    # "higher is worse" sense directly.
    disk_warn_percent: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_DISK_WARN_PERCENT", 80.0))
    disk_crit_percent: float = field(default_factory=lambda: _float("CARPEDIEM_SYSMETRICS_DISK_CRIT_PERCENT", 95.0))


@dataclass
class MatrixConfig:
    """MAX7219 LED matrix settings - see matrix_display.py. Brightness is a
    0-100 percentage, translated to the 0-255 contrast level luma's
    device.contrast() expects."""

    brightness_percent: int = field(default_factory=lambda: _int("CARPEDIEM_MATRIX_BRIGHTNESS_PERCENT", 50))


@dataclass
class HmiConfig:
    """Magedok 7" IPS touchscreen (1024x600) settings - see hmi/app.py.

    theme selects the visual skin (only "startrek" exists so far, but the
    renderer is written against a Theme object precisely so more can be
    added later without touching page code - see hmi/theme.py).
    """

    width: int = field(default_factory=lambda: _int("CARPEDIEM_HMI_WIDTH", 1024))
    height: int = field(default_factory=lambda: _int("CARPEDIEM_HMI_HEIGHT", 600))
    fullscreen: bool = field(default_factory=lambda: _bool("CARPEDIEM_HMI_FULLSCREEN", True))
    fps: int = field(default_factory=lambda: _int("CARPEDIEM_HMI_FPS", 20))
    theme: str = field(default_factory=lambda: _str("CARPEDIEM_HMI_THEME", "startrek"))


@dataclass
class UpsConfig:
    """Geekworm X-UPS 'PLD' (Power Loss Detection) signal, wired to a GPIO
    pin (default GPIO23 / physical pin 16). The UPS drives this pin to its
    active level when external (mains) power is lost and it switches to
    battery - there's no way to read remaining battery capacity from the
    Pi side, so the only safe response is to shut down as soon as it fires.
    """

    gpio_pin: int = field(default_factory=lambda: _int("UPS_PLD_GPIO_PIN", 23))
    # Most Geekworm UPS HATs idle this pin low and drive it high on power
    # loss - but verify against your actual board/wiring and flip this if
    # it turns out to be the other way round.
    active_high: bool = field(default_factory=lambda: _bool("UPS_PLD_ACTIVE_HIGH", True))
    bounce_seconds: float = field(default_factory=lambda: _float("UPS_PLD_BOUNCE_SECONDS", 0.2))
    shutdown_script: str = field(
        default_factory=lambda: _str(
            "UPS_SHUTDOWN_SCRIPT",
            str(Path(__file__).resolve().parent.parent / "scripts" / "pld_shutdown.sh"),
        )
    )


@dataclass
class WindCalibrationConfig:
    """Corrects the Bresser 7-in-1 wind vane's raw direction reading for
    how it's actually mounted - see wind_calibration.py for the full
    explanation and formulas. course_deg is the boat's own compass course
    at the moment the vane was physically mounted/calibrated while moored
    (259 degrees, CDPI1's own mooring heading at Marina Nieuwe Meer) - this
    is a one-time physical-installation constant, not something that
    should normally change unless the sensor gets remounted.
    """

    course_deg: float = field(default_factory=lambda: _float("WIND_CALIBRATION_COURSE_DEG", 259.0))


@dataclass
class Bme280Config:
    """SparkFun SEN-15440 BME280 (temperature/humidity/barometric
    pressure), wired directly to the Pi's I2C bus 1 - see
    sensors/bme280_sensor.py and README.md for wiring. i2c_address is
    0x77 (119) with the board's SDO pin left floating/pulled high
    (default), or 0x76 (118) if SDO is tied to GND.

    i2c_bus is which /dev/i2c-N to open (default 1, the Pi GPIO header's
    bus) - only needs changing if `i2cdetect` finds the sensor on a
    different bus number, e.g. on a Pi with extra I2C buses enumerated for
    HDMI DDC/CEC alongside the GPIO one.
    """

    i2c_address: int = field(default_factory=lambda: _int("BME280_I2C_ADDRESS", 0x77))
    i2c_bus: int = field(default_factory=lambda: _int("BME280_I2C_BUS", 1))
    poll_interval_seconds: float = field(default_factory=lambda: _float("BME280_POLL_INTERVAL_SECONDS", 30.0))


@dataclass
class LogConfig:
    dir: Path = field(default_factory=lambda: Path(_str("CARPEDIEM_LOG_DIR", "./logs")))
    level: str = field(default_factory=lambda: _str("CARPEDIEM_LOG_LEVEL", "INFO"))
    max_bytes: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_MAX_BYTES", 4 * 1024 * 1024))
    backup_count: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_BACKUP_COUNT", 10))
    retention_days: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_RETENTION_DAYS", 14))
    # The sketch's `int ShowLogLevel` verbosity threshold, ported to
    # logging_setup.py's log(level, ...) helper - separate from `level`
    # above, which only controls the standard Python logging module's
    # own INFO/DEBUG/etc filtering on the handlers. Every log() call in
    # the codebase actually goes through logging.Logger.info() regardless
    # of its own level argument, so `level` alone can never surface a
    # log(10, ...) debug line - only raising this verbosity value (e.g. to
    # 10) does. Default 9 matches the sketch's original default.
    verbosity: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_VERBOSITY", 9))


@dataclass
class WebServerConfig:
    """Read-only JSON API exposing display_data - see web_server.py.
    host="0.0.0.0" (default) listens on every interface, reachable both
    from the boat's own LAN (e.g. an Arduino/ESP32 driving a Waveshare
    e-ink display) and via NordVPN Meshnet (e.g. an iPhone app) - see
    README.md "Web server (data API)". No authentication: Meshnet is a
    private overlay only this account's own devices join, not the public
    internet.
    """

    host: str = field(default_factory=lambda: _str("WEBSERVER_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("WEBSERVER_PORT", 8080))


@dataclass
class Config:
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    cerbo: CerboConfig = field(default_factory=CerboConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    emtrak: EmtrakConfig = field(default_factory=EmtrakConfig)
    aisstream: AisStreamConfig = field(default_factory=AisStreamConfig)
    ais: AisConfig = field(default_factory=AisConfig)
    ring: RingConfig = field(default_factory=RingConfig)
    wunderground: WundergroundConfig = field(default_factory=WundergroundConfig)
    bresser_rtl: BresserRtlConfig = field(default_factory=BresserRtlConfig)
    vaarweg: VaarwegConfig = field(default_factory=VaarwegConfig)
    gpx: GpxConfig = field(default_factory=GpxConfig)
    ble: BleConfig = field(default_factory=BleConfig)
    matrix: MatrixConfig = field(default_factory=MatrixConfig)
    hmi: HmiConfig = field(default_factory=HmiConfig)
    sysmetrics: SysMetricsConfig = field(default_factory=SysMetricsConfig)
    ups: UpsConfig = field(default_factory=UpsConfig)
    bme280: Bme280Config = field(default_factory=Bme280Config)
    wind_calibration: WindCalibrationConfig = field(default_factory=WindCalibrationConfig)
    webserver: WebServerConfig = field(default_factory=WebServerConfig)
    log: LogConfig = field(default_factory=LogConfig)


# Module-level singleton - import `config` from this module elsewhere.
config = Config()
