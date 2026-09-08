"""Checks whether the Pi currently has a working network connection -
purely to feed the "WiFi" status dot on the MAX7219 matrix (see
matrix_display.py, status_monitor.py).

The Pi's WiFi itself is managed by the OS (NetworkManager/wpa_supplicant),
same as the rest of the network stack - see config.py's note on why there
is no DoWiFi flag here. This module only observes the result, it never
configures or reconnects anything.

Connectivity is checked with a real outbound TCP connection attempt rather
than reading interface/link state: associated-to-an-AP-but-no-upstream-route
is a real "not working" case that a link-state check would miss, and this
also happens to be the same check that matters most on a boat (marina wifi
often stays link-up long after it stops routing anywhere).
"""
from __future__ import annotations

import asyncio
import socket

from carpediem.display_data import display_data
from carpediem.logging_setup import log

POLL_INTERVAL_SECONDS = 15
CHECK_TIMEOUT_SECONDS = 3.0
# Cloudflare's public DNS - fast, reliable, no auth, and reachable from
# marina wifi or a cellular uplink alike.
_PROBE_HOST = "1.1.1.1"
_PROBE_PORT = 53


def wifi_connected() -> bool:
    try:
        with socket.create_connection((_PROBE_HOST, _PROBE_PORT), timeout=CHECK_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


class WifiMonitor:
    """Polls wifi_connected() and mirrors it into display_data["WiFi"],
    same pattern as HdmiDisplayMonitor for the other "is this subsystem
    alive" flags."""

    def check_once(self) -> bool:
        ok = wifi_connected()
        display_data.update("WiFi", 1 if ok else 0, source="S")
        return ok

    async def run_forever(self) -> None:
        while True:
            try:
                ok = await asyncio.to_thread(self.check_once)
                log(10, f"WiFi: {'connected' if ok else 'not connected'}")
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(9, f"WiFi: check failed, will retry: {exc}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
