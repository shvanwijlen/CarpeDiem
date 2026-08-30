"""Optional DS3231 RTC support - port of the rtc.begin()/rtc.now() /
rtc.adjust() calls and the settimeofday() sync-on-boot step from setup().

On the original ESP32-S3, an external RTC was needed because the board
has no battery-backed clock and boots with a wrong time until WiFi/NTP (or
this chip) sets it. A Raspberry Pi 4 doesn't need this at all under normal
use: it keeps time via NTP whenever it has network, and systemd's
fake-hwclock saves/restores the time across reboots so it starts with a
reasonable clock even offline. So this module is fully optional
(config.flags.use_rtc, default False) - wire up a DS3231 only if you want
accurate time during long stretches with no network at all.

Uses Adafruit's CircuitPython DS3231 library (I2C bus 1, the Pi's default),
which handles the BCD register decoding for you - no manual bit-twiddling
needed the way raw smbus register access would require.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from typing import Optional

from carpediem.logging_setup import log

_rtc = None  # lazily initialized adafruit_ds3231.DS3231 instance


def _get_rtc():
    global _rtc
    if _rtc is None:
        import board  # type: ignore
        import busio  # type: ignore
        import adafruit_ds3231  # type: ignore

        i2c = busio.I2C(board.SCL, board.SDA)
        _rtc = adafruit_ds3231.DS3231(i2c)
    return _rtc


def init_rtc() -> bool:
    """Equivalent of `if (!rtc.begin())`. Also syncs the Pi's system clock
    from the RTC if the RTC time looks sane, mirroring the settimeofday()
    call in the original setup(). Returns True on success."""
    try:
        rtc = _get_rtc()
        rtc_now = rtc.datetime  # time.struct_time
        rtc_dt = dt.datetime(*rtc_now[:6])
        log(9, f"DS3231 RTC found, reports {rtc_dt.isoformat()}")

        if rtc_dt.year >= 2026:  # sanity check, same spirit as the sketch's usage
            _set_system_clock(rtc_dt)
        else:
            log(9, "DS3231 time looks invalid (year < 2026) - not syncing system clock from it")
        return True
    except Exception as exc:  # noqa: BLE001 - no RTC wired up, or I2C error
        log(9, f"DS3231 RTC not found or unavailable: {exc}")
        return False


def _set_system_clock(new_time: dt.datetime) -> None:
    """Best-effort `sudo date -s ...`. Requires passwordless sudo for
    `date` (or run the whole app as root/with CAP_SYS_TIME) - set that up
    in your systemd unit / sudoers if you rely on this."""
    try:
        subprocess.run(
            ["sudo", "date", "-s", new_time.strftime("%Y-%m-%d %H:%M:%S")],
            check=True,
            capture_output=True,
        )
    except Exception as exc:  # noqa: BLE001
        log(9, f"Could not set system clock from RTC (non-fatal): {exc}")


def now() -> dt.datetime:
    """Port of `DateTime now = rtc.now();`. Falls back to system time if
    no RTC is configured/available - this is what most deployments should
    just use directly instead of enabling CARPEDIEM_USE_RTC."""
    if _rtc is not None:
        try:
            t = _rtc.datetime
            return dt.datetime(*t[:6])
        except Exception as exc:  # noqa: BLE001
            log(9, f"DS3231 read failed, falling back to system clock: {exc}")
    return dt.datetime.now()


def set_rtc_time(new_time: dt.datetime) -> bool:
    """Port of setRTCTime(): write a new time into the DS3231."""
    try:
        rtc = _get_rtc()
        rtc.datetime = new_time.timetuple()
        log(9, f"RTC time set to: {new_time.isoformat()}")
        return True
    except Exception as exc:  # noqa: BLE001
        log(9, f"Failed to set RTC time: {exc}")
        return False
