"""Geekworm X-UPS power-loss-detection (PLD) monitor.

The X-UPS drives its PLD pin to its active level when it loses external
(mains) power and switches the Pi over to battery. There's no way to read
remaining battery capacity from the Pi side, so the only safe response is:
as soon as PLD fires, shut down cleanly before the battery runs out.

Wiring: UPS PLD -> GPIO23 / physical pin 16 (config.ups.gpio_pin).

Uses gpiozero (interrupt-driven - no polling loop needed) and follows the
same "optional hardware, import lazily, log and no-op if unavailable"
pattern as matrix_display.py / rtc.py, so importing this module is always
safe even when gpiozero isn't installed or there's no Pi to run it on.
"""
from __future__ import annotations

import subprocess
import time

from carpediem.config import config
from carpediem.logging_setup import log


class UpsMonitor:
    def __init__(self) -> None:
        self._device = None
        self._triggered = False

    def init(self) -> bool:
        """Arm the GPIO interrupt. Returns True once armed; logs and
        returns False if gpiozero isn't available or the pin can't be
        claimed - never raises, same as MatrixDisplay.init()/init_rtc()."""
        try:
            from gpiozero import DigitalInputDevice
        except Exception as exc:  # noqa: BLE001 - not on a Pi, or gpiozero missing
            log(9, f"UPS monitor not available (gpiozero import failed): {exc}")
            return False

        ups = config.ups
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
            log(9, f"UPS monitor armed on GPIO{ups.gpio_pin} "
                   f"(active {'high' if ups.active_high else 'low'})")
            return True
        except Exception as exc:  # noqa: BLE001 - pin already claimed, no permissions, etc.
            log(9, f"UPS monitor: failed to arm GPIO{ups.gpio_pin}: {exc}")
            self._device = None
            return False

    def _on_power_lost(self) -> None:
        """Fired on gpiozero's own callback thread when the UPS's PLD
        signal goes active. Latched so it only ever fires once - the pin
        can chatter on the way down, but we only want one shutdown."""
        if self._triggered:
            return
        self._triggered = True

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
