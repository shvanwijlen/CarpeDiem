"""SparkFun SEN-15440 BME280 (temperature / humidity / barometric
pressure) over I2C. Feeds the BME280-Temperature/BME280-Humidity/
BME280-Barometer display_data fields and (via the combined status-matrix
slot) the Weather dot - see README.md's "BME280 environment sensor"
section for wiring.

Uses smbus2 + the `bme280` package directly, NOT Adafruit's CircuitPython/
Blinka stack (an earlier version of this module did). On the CDPI1 Pi 4B,
Blinka's generic-Linux I2C backend raised `[Errno 5] Input/output error`
reading this exact sensor at this exact address/bus, even after ruling out
wiring (`i2cget -y 1 0x77 0xD0` returned the correct chip ID 0x60) and
ruling out the Pi's classic "combined transactions disabled" gotcha
(`smbus2`'s `i2c_rdwr()` - the same write-then-read/repeated-start
transaction CircuitPython uses - succeeded directly). So the problem was
specific to Blinka's own I2C wrapper, not the hardware/kernel; smbus2 +
`bme280` sidesteps it entirely by talking to /dev/i2c-<N> directly.

Follows the same "optional hardware, import lazily, log and no-op if
unavailable" pattern as rtc.py/matrix_display.py/ups_monitor.py, so
importing this module is always safe even when the library isn't
installed or there's no Pi/sensor to run it on.
"""
from __future__ import annotations

import asyncio

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log


class Bme280Monitor:
    def __init__(self) -> None:
        self._bus = None
        self._bme280 = None  # the imported `bme280` module, stashed so _read_once doesn't re-import
        self._calibration_params = None

    def init(self) -> bool:
        """Probe the sensor at config.bme280.i2c_address on
        config.bme280.i2c_bus. Returns True once found; logs and returns
        False if the library isn't installed or nothing answers - never
        raises, same as MatrixDisplay.init()/init_rtc()/UpsMonitor.init()."""
        try:
            import smbus2  # type: ignore
            import bme280  # type: ignore
        except Exception as exc:  # noqa: BLE001 - not on a Pi, or a library isn't installed
            log(9, f"BME280 not available (import failed): {exc}")
            return False

        address = config.bme280.i2c_address
        bus_number = config.bme280.i2c_bus
        try:
            bus = smbus2.SMBus(bus_number)
            calibration_params = bme280.load_calibration_params(bus, address)
            # Force a read now so a wrong address / dead sensor fails here,
            # in init(), rather than silently in the first run_forever() tick.
            bme280.sample(bus, address, calibration_params)
            self._bus = bus
            self._bme280 = bme280
            self._calibration_params = calibration_params
            log(9, f"BME280 found on I2C bus {bus_number} at address 0x{address:02x}")
            return True
        except Exception as exc:  # noqa: BLE001 - wrong address/bus, not wired up, I2C not enabled, ...
            log(9, f"BME280 not found on I2C bus {bus_number} at address 0x{address:02x} "
                   f"(check wiring, raspi-config's I2C interface, the SDO-pin address jumper, "
                   f"and that BME280_I2C_BUS matches `i2cdetect -y {bus_number}`): {exc}")
            self._bus = None
            self._bme280 = None
            self._calibration_params = None
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

        data = self._bme280.sample(self._bus, config.bme280.i2c_address, self._calibration_params)
        temperature = data.temperature  # degrees C
        humidity = data.humidity  # % RH
        pressure = data.pressure  # hPa, station pressure (not sea-level-adjusted)

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
        self._bme280 = None
        self._calibration_params = None
