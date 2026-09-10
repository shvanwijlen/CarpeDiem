"""SparkFun SEN-15440 BME280 (temperature / humidity / barometric
pressure) over I2C. Feeds the BME280-Temperature/BME280-Humidity/
BME280-Barometer display_data fields and the status matrix's Weather280
dot - see README.md's "BME280 environment sensor" section for wiring.

Uses Adafruit's CircuitPython BME280 library, which handles the
datasheet's compensation-formula math for you. Opens the I2C bus via
adafruit-extended-bus's ExtendedI2C(config.bme280.i2c_bus) rather than
busio.I2C(board.SCL, board.SDA): Blinka's board.SCL/board.SDA
auto-detection picks *a* I2C bus, but on a Pi with more than one exposed
(e.g. i2c-1 plus HDMI DDC/CEC buses enumerated as i2c-20+) it can pick the
wrong one - symptom is i2cdetect/i2cget finding the sensor fine on bus 1
while this library reports "not found". ExtendedI2C opens /dev/i2c-<N>
directly, sidestepping that detection entirely.

Follows the same "optional hardware, import lazily, log and no-op if
unavailable" pattern as rtc.py/matrix_display.py/ups_monitor.py, so
importing this module is always safe even when the library isn't
installed or there's no Pi/sensor to run it on.

BME280 pin	Raspberry Pi pin
VCC	Pin 1 (3.3V)
GND	Pin 6 (GND)
SDA	Pin 3 (GPIO2 / SDA1)
SCL	Pin 5 (GPIO3 / SCL1)
CSB	leave unconnected (board pulls it high → I2C mode)
SDO	leave unconnected for address 0x77 (default), or tie to GND for 0x76
Enable and verify:


sudo raspi-config   # Interface Options -> I2C -> enable, reboot
sudo apt install -y i2c-tools
i2cdetect -y 1       # sensor should show up at 77 (or 76)


"""
from __future__ import annotations

import asyncio

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log


class Bme280Monitor:
    def __init__(self) -> None:
        self._sensor = None

    def init(self) -> bool:
        """Probe the sensor at config.bme280.i2c_address. Returns True once
        found; logs and returns False if the library isn't installed or
        nothing answers at that address - never raises, same as
        MatrixDisplay.init()/init_rtc()/UpsMonitor.init()."""
        try:
            from adafruit_extended_bus import ExtendedI2C  # type: ignore
            from adafruit_bme280 import basic as adafruit_bme280  # type: ignore
        except Exception as exc:  # noqa: BLE001 - not on a Pi, or a library isn't installed
            log(9, f"BME280 not available (import failed): {exc}")
            return False

        address = config.bme280.i2c_address
        bus = config.bme280.i2c_bus
        try:
            i2c = ExtendedI2C(bus)
            self._sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=address)
            # Force a read now so a wrong address / dead sensor fails here,
            # in init(), rather than silently in the first run_forever() tick.
            _ = self._sensor.temperature
            log(9, f"BME280 found on I2C bus {bus} at address 0x{address:02x}")
            return True
        except Exception as exc:  # noqa: BLE001 - wrong address/bus, not wired up, I2C not enabled, ...
            log(9, f"BME280 not found on I2C bus {bus} at address 0x{address:02x} "
                   f"(check wiring, raspi-config's I2C interface, the SDO-pin address jumper, "
                   f"and that BME280_I2C_BUS matches `i2cdetect -y {bus}`): {exc}")
            self._sensor = None
            return False

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._read_once)
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(9, f"BME280: read failed, will retry: {exc}")
                self._sensor = None
                display_data.update("Weather280", 0, source="S")
            await asyncio.sleep(config.bme280.poll_interval_seconds)

    def _read_once(self) -> None:
        if self._sensor is None:
            # Sensor wasn't found at startup, or a previous read failed -
            # retry the probe each cycle so plugging it in later (or fixing
            # the wiring) recovers without a restart.
            if not self.init():
                display_data.update("Weather280", 0, source="S")
                return
        temperature = self._sensor.temperature  # degrees C
        humidity = self._sensor.relative_humidity  # % RH
        pressure = self._sensor.pressure  # hPa, station pressure (not sea-level-adjusted)

        display_data.update("BME280-Temperature", temperature, source="I")
        display_data.update("BME280-Humidity", humidity, source="I")
        display_data.update("BME280-Barometer", pressure, source="I")
        display_data.update("Weather280", 1, source="S")

        if not config.flags.do_fake:
            log(9, f"BME280: received {temperature:.1f}C, {humidity:.0f}% RH, {pressure:.1f} hPa")

    def close(self) -> None:
        self._sensor = None
