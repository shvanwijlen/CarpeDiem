"""Detects whether the Magedok display (HDMI-connected) is plugged into
the Pi, and writes the result into the "Display" field of display_data -
the one field the original Arduino sketch never had, since the display
itself didn't exist yet (see README.md).

Modern Raspberry Pi OS (Bullseye onward) uses the KMS DRM driver, which
exposes each video output's connection state as plain text at
/sys/class/drm/card*-HDMI-A-*/status ("connected" / "disconnected") - no
root, no vcgencmd/tvservice (both deprecated/removed under KMS) required.
A Pi can have more than one HDMI port (Pi 4/5); any one of them reporting
"connected" counts as the display being linked.
"""
from __future__ import annotations

import asyncio
import glob

from carpediem.display_data import display_data
from carpediem.logging_setup import log

POLL_INTERVAL_SECONDS = 10

_STATUS_GLOB = "/sys/class/drm/card*-HDMI-*/status"


def hdmi_connected() -> bool:
    """Is the Magedok display physically linked to the Pi? True only if a
    DRM HDMI connector reports "connected" - no status file at all (not a
    Pi / not Linux / KMS driver absent) counts as not connected, same as
    finding one that says "disconnected"."""
    paths = glob.glob(_STATUS_GLOB)
    if not paths:
        log(9, "HDMI: no DRM status file found, can't detect display link on this platform")
        return False
    for path in paths:
        try:
            with open(path, "r") as f:
                if f.read().strip() == "connected":
                    return True
        except OSError as exc:
            log(9, f"HDMI: couldn't read {path}: {exc}")
    return False


class HdmiDisplayMonitor:
    """Polls hdmi_connected() and mirrors it into display_data["Display"],
    same pattern as ModbusPoller/BleScanner for the other "is this
    subsystem alive" flags. Only run when config.flags.do_fake is False -
    fake mode sets "Display" itself (see fake_data.py)."""

    def check_once(self) -> None:
        display_data.update("Display", 1 if hdmi_connected() else 0, source="S")

    async def run_forever(self) -> None:
        while True:
            self.check_once()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
