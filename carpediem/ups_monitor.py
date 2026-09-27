"""Geekworm X-UPS power-loss-detection (PLD) monitor.

The X-UPS drives its PLD pin to its active level when it loses external
(mains) power and switches the Pi over to battery. There's no way to read
remaining battery capacity from the Pi side, so the only safe response is:
as soon as PLD fires, shut down cleanly before the battery runs out.

Wiring: UPS PLD -> GPIO23 / physical pin 16 (config.ups.gpio_pin).
                   GPIO26 / physical pin 37 (config.ups.gpio_pin_alt) used to tell the UPS to shutdown
                   

Uses gpiozero (interrupt-driven - no polling loop needed) and follows the
same "optional hardware, import lazily, log and no-op if unavailable"
pattern as matrix_display.py / rtc.py, so importing this module is always
safe even when gpiozero isn't installed or there's no Pi to run it on.
"""

# force update of the file


from __future__ import annotations

import subprocess
import time
from typing import Optional

from carpediem.config import config
from carpediem.logging_setup import log


class UpsStatus:
    """What the SYS popup's "UPS" row shows (sysmetrics_monitor.popup_rows())
    - same "tiny status singleton read every frame" pattern as
    publish_status.PublishStatus. Updated by UpsMonitor below as it arms and
    (hopefully never, but on a boat, eventually) trips."""

    def __init__(self) -> None:
        self.enabled = False  # only True once UpsMonitor.init() actually runs
        self.armed = False
        self.error: Optional[str] = None
        self.power_lost = False

    def popup_row(self) -> Optional[tuple[str, str]]:
        """(level, text) for the SYS popup's "UPS" row, or None when the
        monitor isn't enabled (CARPEDIEM_USE_UPS_MONITOR off)."""
        if not self.enabled:
            return None
        if self.power_lost:
            return "crit", "POWER LOST - shutting down"
        if not self.armed:
            return "crit", f"NOT ARMED - {self.error or 'unknown error'}"
        return "ok", f"armed on GPIO{config.ups.gpio_pin}"


ups_status = UpsStatus()


class UpsMonitor:
    def __init__(self) -> None:
        self._device = None
        self._triggered = False

    def init(self) -> bool:
        """Arm the GPIO interrupt. Returns True once armed; logs and
        returns False if gpiozero isn't available or the pin can't be
        claimed - never raises, same as MatrixDisplay.init()/init_rtc()."""
        ups = config.ups
        ups_status.enabled = True
        log(1, f"UPS monitor: initiating PLD signal monitor on GPIO{ups.gpio_pin} "
               f"(active {'high' if ups.active_high else 'low'})")

        try:
            from gpiozero import DigitalInputDevice
        except Exception as exc:  # noqa: BLE001 - not on a Pi, or gpiozero missing
            log(1, f"UPS monitor not available (gpiozero import failed): {exc}")
            ups_status.armed = False
            ups_status.error = str(exc)
            return False

        try:
            self._device = DigitalInputDevice(
                ups.gpio_pin,
                pull_up=not ups.active_high,
                bounce_time=ups.bounce_seconds,
            )
            if ups.active_high:
                self._device.when_activated = self._on_power_lost
            else:
                self._device.when_deactivated = self._on_power_lost
            log(1, f"UPS monitor armed on GPIO{ups.gpio_pin}")
            ups_status.armed = True
            ups_status.error = None
            return True
        except Exception as exc:  # noqa: BLE001 - pin already claimed, no permissions, etc.
            log(1, f"UPS monitor: failed to arm GPIO{ups.gpio_pin}: {exc}")
            self._device = None
            ups_status.armed = False
            ups_status.error = str(exc)
            return False

    def _on_power_lost(self) -> None:
        """Fired on gpiozero's own callback thread when the UPS's PLD
        signal goes active. Latched so it only ever fires once - the pin
        can chatter on the way down, but we only want one shutdown."""
        if self._triggered:
            return
        self._triggered = True
        ups_status.power_lost = True

        log(1, "UPS PLD signal received: external power lost, shutting down")
        time.sleep(5)  # temporary - gives time to watch the behaviour before it fires

        script = config.ups.shutdown_script
        try:
            subprocess.Popen(["/bin/bash", script])
            log(1, f"Shutdown script launched: {script}")
        except Exception as exc:  # noqa: BLE001 - must not raise on a GPIO callback thread
            log(1, f"Failed to launch shutdown script {script}: {exc}")

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None
