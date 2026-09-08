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
    do_show: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_SHOW", True))

    use_rtc: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_RTC", False))
    use_matrix: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_MATRIX", False))
    use_hmi: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_HMI", False))
    check_hdmi: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_HDMI", True))
    check_wifi: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_WIFI", True))
    check_sysmetrics: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_SYSMETRICS", True))
    use_ups_monitor: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_UPS_MONITOR", False))

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
            self.do_show = True
            self.use_rtc = False
            self.check_hdmi = False
            # use_ups_monitor, use_matrix, use_hmi and check_sysmetrics are
            # deliberately NOT forced off here: they're local hardware/OS
            # state on the Pi itself (or, for the HMI, useful to run on a
            # dev machine with no boat network at all), unrelated to "on
            # the boat's network or not" - you should be able to test the
            # PLD/matrix/touchscreen/CPU-load on the bench with
            # CARPEDIEM_DO_FAKE still on.
            #
            # check_wifi is also deliberately left alone: in fake mode the
            # status matrix still shows a real WiFi check (heart only once
            # WiFi is actually up), everything else is assumed fine - see
            # status_monitor.py.


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

    # Ring device name (as shown in the Ring app) -> display_data internal_label.
    camera_field_map: dict[str, str] = field(default_factory=lambda: {
        _str("RING_CAM_SALON_NAME", "Salon"): "RingBatterySalon",
        _str("RING_CAM_BAKBOORD_NAME", "Bakboord"): "RingBatteryBakboord",
        _str("RING_CAM_STUURBOORD_NAME", "Stuurboord"): "RingBatteryStuurboord",
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
class BleConfig:
    """Teltonika Blue Puck BLE scan cadence (see ble_client.py). Temp/
    humidity readings change slowly, so there's no need to keep the
    Bluetooth radio scanning continuously - poll_interval_seconds is the
    gap between scans, scan_window_seconds is how long each scan listens
    before stopping again (long enough to hear from every known puck at
    least once - they advertise every few seconds)."""
    poll_interval_seconds: float = field(default_factory=lambda: _float("BLE_POLL_INTERVAL_SECONDS", 900.0))  # 15 min
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
class LogConfig:
    dir: Path = field(default_factory=lambda: Path(_str("CARPEDIEM_LOG_DIR", "./logs")))
    level: str = field(default_factory=lambda: _str("CARPEDIEM_LOG_LEVEL", "INFO"))
    max_bytes: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_MAX_BYTES", 4 * 1024 * 1024))
    backup_count: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_BACKUP_COUNT", 10))
    retention_days: int = field(default_factory=lambda: _int("CARPEDIEM_LOG_RETENTION_DAYS", 14))


@dataclass
class Config:
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    cerbo: CerboConfig = field(default_factory=CerboConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    emtrak: EmtrakConfig = field(default_factory=EmtrakConfig)
    aisstream: AisStreamConfig = field(default_factory=AisStreamConfig)
    ais: AisConfig = field(default_factory=AisConfig)
    ring: RingConfig = field(default_factory=RingConfig)
    ble: BleConfig = field(default_factory=BleConfig)
    matrix: MatrixConfig = field(default_factory=MatrixConfig)
    hmi: HmiConfig = field(default_factory=HmiConfig)
    sysmetrics: SysMetricsConfig = field(default_factory=SysMetricsConfig)
    ups: UpsConfig = field(default_factory=UpsConfig)
    log: LogConfig = field(default_factory=LogConfig)


# Module-level singleton - import `config` from this module elsewhere.
config = Config()
