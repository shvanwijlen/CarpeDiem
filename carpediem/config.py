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
    do_show: bool = field(default_factory=lambda: _bool("CARPEDIEM_DO_SHOW", True))

    use_rtc: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_RTC", False))
    use_matrix: bool = field(default_factory=lambda: _bool("CARPEDIEM_USE_MATRIX", False))
    check_hdmi: bool = field(default_factory=lambda: _bool("CARPEDIEM_CHECK_HDMI", True))
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
            self.do_show = True
            self.use_rtc = False
            self.use_matrix = False
            self.check_hdmi = False
            # use_ups_monitor is deliberately NOT forced off here: it's local
            # GPIO safety hardware, unrelated to "on the boat's network or
            # not" - you should be able to test the PLD wiring on the bench
            # with CARPEDIEM_DO_FAKE still on.


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
    ups: UpsConfig = field(default_factory=UpsConfig)
    log: LogConfig = field(default_factory=LogConfig)


# Module-level singleton - import `config` from this module elsewhere.
config = Config()
