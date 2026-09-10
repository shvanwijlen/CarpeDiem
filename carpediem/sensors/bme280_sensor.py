"""SparkFun SEN-15440 BME280 (temperature / humidity / barometric
pressure) over I2C. Feeds the BME280-Temperature/BME280-Humidity/
BME280-Barometer display_data fields and (via the combined status-matrix
slot) the Weather dot - see README.md's "BME280 environment sensor"
section for wiring.

Talks to the sensor directly over smbus2 - no Adafruit CircuitPython/
Blinka (its I2C backend raised `[Errno 5] Input/output error` reading this
exact sensor on the CDPI1 Pi 4B, even though smbus2 read it fine - see
PORTING_NOTES.md/commit history) and no third-party `bme280` PyPI package
either: the one that got pulled in during that debugging session turned
out to expose its functions under a different import path than published
examples suggest, and - worse - has real bugs in its calibration parsing
(dig_H6 is never read at all despite compensate_humidity() indexing it,
and the sign-correction pass silently skips dig_T3 and dig_P9), so it
would have produced wrong readings even with the import path fixed.

The register map and floating-point compensation formulas below are
ported directly from the Bosch BME280 datasheet (section 4.2, "Compensation
formulas") instead, with all nine calibration coefficients that need
two's-complement sign correction (dig_T2/T3, dig_P2-P9, dig_H2, dig_H4/H5
as 12-bit, dig_H6 as 8-bit) actually being sign-corrected.

All reads use read_byte_data() one register at a time (never
read_i2c_block_data() bursts, which briefly looked like the culprit but
weren't). The sensor runs in forced mode, not normal (continuous) mode:
normal mode reliably produced [Errno 5] Input/output error reading this
sensor back on the CDPI1 Pi 4B - on the data registers, and even on the
status register - regardless of read style or added settle delays, which
points at the sensor's background conversion (and whatever clock-
stretching it does while normal mode keeps it continuously converting)
colliding with the Pi's bcm2835 I2C controller, a known-flaky combination.
A plain write-then-read to an idle (sleep-mode) register, by contrast,
worked fine on the very first try. Forced mode fixed the I/O errors -
each _read_once() explicitly triggers exactly one conversion and the
sensor drops back to sleep on its own once it's done, so there's no
window where it's converting unless we're actively waiting for it.

That uncovered a second, quieter bug: the first version of the forced-mode
code polled the status register for the "measuring" bit to clear before
reading, which raced the trigger write - there's a brief window right
after writing ctrl_meas where the sensor hasn't internally started
converting yet, so an immediate status check can see "not measuring" (true
- because the conversion hasn't *started*, not because it's *finished*)
and return instantly, reading back 0x80000/0x8000, the BME280's documented
"measurement skipped"/not-yet-converted sentinel, instead of a real
reading - which produced a temperature and humidity that happened to look
plausible but a wildly wrong pressure (664 hPa, i.e. ~3500m-altitude
pressure, from a boat at sea level). See _read_data_registers()'s
docstring for the fixed-delay replacement, and why a delay sidesteps this
race in a way polling couldn't.

That fixed-delay version still hit [Errno 5] on some runs, but a
register-by-register live diagnostic pinned it down precisely: it's
specifically the *first* register access after the write+delay that can
glitch - every access after that one, including a different register read
immediately afterwards with no extra delay, succeeded cleanly every time.
So it's a one-off "waking the bus back up after being idle" glitch, not a
per-register or per-conversion problem - see _read_byte()'s docstring for
the in-place retry that fixed it (retrying the *whole* trigger+read cycle,
an earlier attempt, didn't help, because every retry recreated the exact
same "first access after idle" situation that glitches in the first
place). _read_data_registers() also separately re-polls the data itself
(not the status register - see above) if it's still the skip sentinel,
without re-triggering, for the same reason.

Follows the same "optional hardware, import lazily, log and no-op if
unavailable" pattern as rtc.py/matrix_display.py/ups_monitor.py, so
importing this module is always safe even when smbus2 isn't installed or
there's no Pi/sensor to run it on.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

_CHIP_ID_REG = 0xD0
_EXPECTED_CHIP_ID = 0x60

_CTRL_HUM_REG = 0xF2
_CTRL_MEAS_REG = 0xF4
_CONFIG_REG = 0xF5
_DATA_REG = 0xF7  # pressure(3 bytes) + temperature(3 bytes) + humidity(2 bytes)

# Oversampling x1 on all three. Humidity oversampling (ctrl_hum) is written
# once in init() and persists; ctrl_meas has to be rewritten with mode=
# forced before every single reading, since the sensor auto-returns to
# sleep mode after each forced conversion completes.
_CTRL_HUM_VALUE = 0x01
_CTRL_MEAS_FORCED_VALUE = (0x01 << 5) | (0x01 << 2) | 0x01  # osrs_t=1, osrs_p=1, mode=forced
_CONFIG_VALUE = 0x00  # standby/filter don't matter in forced mode; 3-wire SPI disabled


def _s16(v: int) -> int:
    return v - 65536 if v & 0x8000 else v


def _s12(v: int) -> int:
    return v - 4096 if v & 0x800 else v


def _s8(v: int) -> int:
    return v - 256 if v & 0x80 else v


@dataclass
class _Calibration:
    dig_T1: int
    dig_T2: int
    dig_T3: int
    dig_P1: int
    dig_P2: int
    dig_P3: int
    dig_P4: int
    dig_P5: int
    dig_P6: int
    dig_P7: int
    dig_P8: int
    dig_P9: int
    dig_H1: int
    dig_H2: int
    dig_H3: int
    dig_H4: int
    dig_H5: int
    dig_H6: int


def _read_calibration(bus, address: int) -> _Calibration:
    def r(reg: int) -> int:
        return bus.read_byte_data(address, reg)

    def u16(reg_lo: int) -> int:
        return r(reg_lo) | (r(reg_lo + 1) << 8)

    e1, e2, e3, e4, e5, e6, e7 = (r(reg) for reg in range(0xE1, 0xE8))

    return _Calibration(
        dig_T1=u16(0x88),
        dig_T2=_s16(u16(0x8A)),
        dig_T3=_s16(u16(0x8C)),
        dig_P1=u16(0x8E),
        dig_P2=_s16(u16(0x90)),
        dig_P3=_s16(u16(0x92)),
        dig_P4=_s16(u16(0x94)),
        dig_P5=_s16(u16(0x96)),
        dig_P6=_s16(u16(0x98)),
        dig_P7=_s16(u16(0x9A)),
        dig_P8=_s16(u16(0x9C)),
        dig_P9=_s16(u16(0x9E)),
        dig_H1=r(0xA1),
        dig_H2=_s16(e1 | (e2 << 8)),
        dig_H3=e3,
        dig_H4=_s12((e4 << 4) | (e5 & 0x0F)),
        dig_H5=_s12((e6 << 4) | (e5 >> 4)),
        dig_H6=_s8(e7),
    )


_BYTE_READ_ATTEMPTS = 3  # retries for a single register read - see _read_byte()
_SENTINEL_POLL_ATTEMPTS = 10  # re-polls of the *data*, no re-trigger - see _read_data_registers()
_SENTINEL_POLL_DELAY_SECONDS = 0.02


def _read_byte(bus, address: int, reg: int) -> int:
    """read_byte_data() with a few immediate retries. A live diagnostic
    (writing ctrl_meas, sleeping 50ms, then reading 0xF7-0xFE one at a
    time) showed [Errno 5] on exactly the *first* register access after
    that idle gap, every time - and every access after that first one,
    including a different register read immediately afterwards with no
    extra delay, succeeding cleanly. That's a one-off "waking the bus back
    up" glitch, not a per-register or per-transaction problem, so the fix
    is to retry the exact same read in place rather than backing off or
    restarting anything."""
    last_exc: Exception | None = None
    for _ in range(_BYTE_READ_ATTEMPTS):
        try:
            return bus.read_byte_data(address, reg)
        except OSError as exc:
            last_exc = exc
    raise last_exc  # type: ignore[misc] - loop always runs at least once


def _read_data_once(bus, address: int) -> tuple[int, int, int]:
    raw = [_read_byte(bus, address, reg) for reg in range(_DATA_REG, _DATA_REG + 8)]
    adc_p = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
    adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
    adc_h = (raw[6] << 8) | raw[7]
    return adc_t, adc_p, adc_h


def _read_data_registers(bus, address: int) -> tuple[int, int, int]:
    """Triggers one forced-mode conversion and returns (adc_t, adc_p,
    adc_h). Two independent problems showed up debugging this against the
    real sensor, and each needed a different fix:

    1. The very first register read after triggering (see _read_byte()'s
       docstring) can raise [Errno 5] as a one-off "waking the bus back up"
       glitch, unrelated to whether the sensor is actually ready -
       retried in place by _read_byte()/_read_data_once().

    2. Even once reads are succeeding cleanly, the sensor can still report
       0x80000 (pressure/temperature) / 0x8000 (humidity) - its documented
       "measurement skipped"/not-yet-converted sentinel - if the fixed 50ms
       post-trigger delay wasn't quite enough. Polling the status register
       for the "measuring" bit instead of a fixed delay was tried first and
       made this worse (it raced the trigger write itself - see git
       history), so instead this re-reads the *data* registers again
       (without re-triggering, which would just reintroduce problem #1 on
       every retry) until they're no longer the skip sentinel."""
    bus.write_byte_data(address, _CTRL_MEAS_REG, _CTRL_MEAS_FORCED_VALUE)
    time.sleep(0.05)  # ~9.3ms max conversion time at x1 oversampling per the datasheet; generous margin

    for _ in range(_SENTINEL_POLL_ATTEMPTS):
        adc_t, adc_p, adc_h = _read_data_once(bus, address)
        if adc_t != 0x80000 and adc_p != 0x80000 and adc_h != 0x8000:
            return adc_t, adc_p, adc_h
        time.sleep(_SENTINEL_POLL_DELAY_SECONDS)

    raise IOError("still reading the sensor's 'measurement skipped' sentinel after repeated polling - "
                  "conversion never completed")


def _compensate(adc_t: int, adc_p: int, adc_h: int, c: _Calibration) -> tuple[float, float, float]:
    """Bosch datasheet's official floating-point compensation formulas.
    Returns (temperature_c, pressure_hpa, humidity_percent)."""
    var1 = (adc_t / 16384.0 - c.dig_T1 / 1024.0) * c.dig_T2
    var2 = (adc_t / 131072.0 - c.dig_T1 / 8192.0) ** 2 * c.dig_T3
    t_fine = var1 + var2
    temperature = t_fine / 5120.0

    var1 = (t_fine / 2.0) - 64000.0
    var2 = var1 * var1 * c.dig_P6 / 32768.0
    var2 += var1 * c.dig_P5 * 2.0
    var2 = (var2 / 4.0) + (c.dig_P4 * 65536.0)
    var1 = (c.dig_P3 * var1 * var1 / 524288.0 + c.dig_P2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * c.dig_P1
    if var1 == 0:
        pressure = 0.0
    else:
        pressure = 1048576.0 - adc_p
        pressure = (pressure - (var2 / 4096.0)) * 6250.0 / var1
        var1 = c.dig_P9 * pressure * pressure / 2147483648.0
        var2 = pressure * c.dig_P8 / 32768.0
        pressure = pressure + (var1 + var2 + c.dig_P7) / 16.0
    pressure /= 100.0  # Pa -> hPa

    var_h = t_fine - 76800.0
    var_h = (adc_h - (c.dig_H4 * 64.0 + c.dig_H5 / 16384.0 * var_h)) * (
        c.dig_H2 / 65536.0 * (1.0 + c.dig_H6 / 67108864.0 * var_h *
        (1.0 + c.dig_H3 / 67108864.0 * var_h)))
    var_h *= 1.0 - c.dig_H1 * var_h / 524288.0
    humidity = max(0.0, min(100.0, var_h))

    return temperature, pressure, humidity


class Bme280Monitor:
    def __init__(self) -> None:
        self._bus = None
        self._address = None
        self._calib: _Calibration | None = None

    def init(self) -> bool:
        """Probe the sensor at config.bme280.i2c_address on
        config.bme280.i2c_bus. Returns True once found; logs and returns
        False if smbus2 isn't installed or nothing answers - never raises,
        same as MatrixDisplay.init()/init_rtc()/UpsMonitor.init()."""
        try:
            import smbus2  # type: ignore
        except Exception as exc:  # noqa: BLE001 - not on a Pi, or smbus2 isn't installed
            log(9, f"BME280 not available (import failed): {exc}")
            return False

        address = config.bme280.i2c_address
        bus_number = config.bme280.i2c_bus
        try:
            bus = smbus2.SMBus(bus_number)
            chip_id = bus.read_byte_data(address, _CHIP_ID_REG)
            if chip_id != _EXPECTED_CHIP_ID:
                raise ValueError(f"unexpected chip ID 0x{chip_id:02x} (expected 0x{_EXPECTED_CHIP_ID:02x})")

            calib = _read_calibration(bus, address)
            # Humidity oversampling only takes effect once ctrl_meas is
            # next written (datasheet 5.4.3) - the first forced-mode
            # trigger in _read_once() covers that. The sensor stays asleep
            # (mode=00) until then, so these two writes never race a
            # conversion - see the module docstring for why that matters.
            bus.write_byte_data(address, _CTRL_HUM_REG, _CTRL_HUM_VALUE)
            bus.write_byte_data(address, _CONFIG_REG, _CONFIG_VALUE)

            self._bus = bus
            self._address = address
            self._calib = calib
            log(9, f"BME280 found on I2C bus {bus_number} at address 0x{address:02x}")
            return True
        except Exception as exc:  # noqa: BLE001 - wrong address/bus, not wired up, I2C not enabled, ...
            log(9, f"BME280 not found on I2C bus {bus_number} at address 0x{address:02x} "
                   f"(check wiring, raspi-config's I2C interface, the SDO-pin address jumper, "
                   f"and that BME280_I2C_BUS matches `i2cdetect -y {bus_number}`): {exc}")
            self._bus = None
            self._calib = None
            return False

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._read_once)
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(9, f"BME280: read failed, will retry: {exc}")
                self._bus = None
                display_data.update("Weather280", 0, source="S")
            await asyncio.sleep(config.bme280.poll_interval_seconds)

    def _read_once(self) -> None:
        if self._bus is None:
            # Sensor wasn't found at startup, or a previous read failed -
            # retry the probe each cycle so plugging it in later (or fixing
            # the wiring) recovers without a restart.
            if not self.init():
                display_data.update("Weather280", 0, source="S")
                return

        # Forced mode: trigger exactly one conversion, then read - see the
        # module docstring for why this replaced normal (continuous) mode,
        # and _read_data_registers()'s docstring for why it's a fixed
        # delay rather than status-register polling.
        adc_t, adc_p, adc_h = _read_data_registers(self._bus, self._address)
        temperature, pressure, humidity = _compensate(adc_t, adc_p, adc_h, self._calib)

        display_data.update("BME280-Temperature", temperature, source="I")
        display_data.update("BME280-Humidity", humidity, source="I")
        display_data.update("BME280-Barometer", pressure, source="I")
        display_data.update("Weather280", 1, source="S")

        if not config.flags.do_fake:
            log(9, f"BME280: received {temperature:.1f}C, {humidity:.0f}% RH, {pressure:.1f} hPa")

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup on shutdown
                pass
        self._bus = None
        self._calib = None
