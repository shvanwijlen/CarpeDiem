"""Aggregates every subsystem's health into the heart-vs-dots decision for
the MAX7219 status matrix (see matrix_display.py). Slot order matches the
requested physical layout: row 1 = slots 0-7 (columns 1-8), row 2 = slots
8-9 (columns 9-10) -

    1 Fake mode   5 BLE          9  Weather (BME280 + RTL-SDR/rtl_433, combined)
    2 WiFi        6 AIS          10 WebServer  (not wired up yet)
    3 MODBUS      7 AISstream
    4 MQTT        8 Ring

The "Weather" dot is one matrix slot covering two separate peripherals -
the BME280 (config.flags.use_bme280, display_data's Weather280 field) and
the RTL-SDR/rtl_433 receiver (not wired into the app yet - only the
throwaway scripts/rtl433_sniff.py diagnostic exists so far, Weather433
field). Each peripheral still gets its own display_data field/reading; only
the matrix representation is merged - see _weather_enabled()/_weather_ok()
below. It's "ok" only while every *enabled* one of the two is reporting ok,
so either one failing lights the dot, but a peripheral that isn't wired up
yet never drags it down.

A slot whose `enabled()` is False (not turned on, or not implemented yet)
never lights its dot and never blocks the heart - that's how new slots
(WebServer) can sit in the layout months before they're actually wired up,
and how a deliberately-disabled subsystem (e.g. CARPEDIEM_DO_RING=false)
doesn't get stuck reporting "broken" forever.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Tuple

from carpediem.config import config
from carpediem.display_data import display_data

TOTAL_SLOTS = 10


@dataclass
class StatusSlot:
    name: str
    enabled: Callable[[], bool]
    ok: Callable[[], bool]


def _display_ok(label: str) -> Callable[[], bool]:
    return lambda: display_data.get(label) == 1


def _weather_enabled() -> bool:
    """True once at least one of the two weather peripherals is turned on.
    Extend this with an `or` once the RTL-SDR/rtl_433 receiver gets its own
    feature flag - there isn't one yet, it's not wired into the app."""
    return config.flags.use_bme280


def _weather_ok() -> bool:
    """AND of whichever weather peripherals are actually enabled - see the
    module docstring. Nothing enabled means this is never consulted
    (_weather_enabled() is False), so `all([])` == True here is harmless."""
    checks = []
    if config.flags.use_bme280:
        checks.append(display_data.get("Weather280") == 1)
    # RTL-SDR/rtl_433: append display_data.get("Weather433") == 1 here once
    # it has a real feature flag to gate on.
    return all(checks)


_SLOTS: List[StatusSlot] = [
    # "ok" is never consulted for this slot - compute_status() decides the
    # fake-mode dot directly (lit whenever DoFake is on, regardless of
    # anything else) - kept here only so every column has an entry.
    StatusSlot("Fake", lambda: True, lambda: True),
    StatusSlot("WiFi", lambda: config.flags.check_wifi, _display_ok("WiFi")),
    StatusSlot("MODBUS", lambda: config.flags.do_modbus, _display_ok("MODBUS")),
    StatusSlot("MQTT", lambda: config.flags.do_mqtt, _display_ok("MQTT")),
    StatusSlot("BLE", lambda: config.flags.do_ble, _display_ok("BLE")),
    StatusSlot("AIS", lambda: config.flags.do_ais, _display_ok("AIS")),
    StatusSlot("AISstream", lambda: config.flags.do_ais and config.aisstream.configured, _display_ok("AISstream")),
    StatusSlot("Ring", lambda: config.flags.do_ring, _display_ok("Cam")),
    StatusSlot("Weather", _weather_enabled, _weather_ok),
    StatusSlot("WebServer", lambda: False, _display_ok("WebServer")),
]
assert len(_SLOTS) == TOTAL_SLOTS


def compute_status() -> Tuple[bool, List[bool]]:
    """Returns (all_ok, dots). `dots[i]` True means light that matrix
    position - see the module docstring for the slot-to-column layout.

    In fake mode, everything except WiFi is assumed to work (matches the
    boat-dependent subsystems being switched off entirely by DoFake) - only
    WiFi gets a real check, same as on the real boat.
    """
    if config.flags.do_fake:
        wifi_ok = _SLOTS[1].ok() if config.flags.check_wifi else True
        dots = [True] + [False] * (TOTAL_SLOTS - 1)
        dots[1] = not wifi_ok
        return wifi_ok, dots

    dots = [False] * TOTAL_SLOTS
    all_ok = True
    for i, slot in enumerate(_SLOTS):
        if slot.name == "Fake":
            continue
        if not slot.enabled():
            continue
        if not slot.ok():
            dots[i] = True
            all_ok = False
    return all_ok, dots
