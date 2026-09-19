"""SparkFun SEN-15440 BME280 (temperature / humidity / barometric
pressure) over I2C. Feeds the sparkfun_elec_bay_temperature/
sparkfun_elec_bay_humidity/BME280-Barometer display_data fields and (via
the combined status-matrix slot) the Weather dot - see README.md's
"BME280 environment sensor" section for wiring.

Uses SparkFun's own `qwiic_bme280` library rather than the hand-rolled
smbus2 driver this module used previously. That hand-rolled driver existed
because Adafruit's CircuitPython/Blinka stack raised `[Errno 5]
Input/output error` reading this exact sensor on the CDPI1 Pi 4B - but
`sf_ex_bme280.py` (SparkFun's own example script, run to confirm the
sensor itself wasn't at fault before reporting it to SparkFun as
defective) read the same sensor on the same bus cleanly using
`qwiic_bme280`, continuous ("normal") mode included. `qwiic_i2c`'s Linux
backend also talks smbus2 underneath, but retries every single read/write
on IOError (see `qwiic_i2c/linux_i2c.py`), which is apparently enough to
absorb whatever bus glitch the old driver's narrower single-register retry
was working around - so there's no need to carry our own register-level
workarounds (forced-mode triggering, sentinel polling, first-access-after-
idle retries) any more.

Follows the same "optional hardware, import lazily, log and no-op if
unavailable" pattern as rtc.py/matrix_display.py/ups_monitor.py, so
importing this module is always safe even when qwiic_bme280 isn't
installed or there's no Pi/sensor to run it on.
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
        """Probe the sensor at config.bme280.i2c_address on
        config.bme280.i2c_bus. Returns True once found; logs and returns
        False if qwiic_bme280 isn't installed or nothing answers - never
        raises, same as MatrixDisplay.init()/init_rtc()/UpsMonitor.init()."""
        try:
            import qwiic_bme280  # type: ignore
            import qwiic_i2c  # type: ignore
        except Exception as exc:  # noqa: BLE001 - not on a Pi, or the package isn't installed
            log(9, f"BME280 not available (import failed): {exc}")
            return False

        address = config.bme280.i2c_address
        bus_number = config.bme280.i2c_bus
        try:
            # Passing iBus explicitly (rather than leaving it to qwiic_i2c's
            # default of bus 1) opens its own driver instance instead of
            # reusing/caching qwiic_i2c's process-wide default one, so this
            # respects BME280_I2C_BUS even if it's not 1.
            i2c_driver = qwiic_i2c.getI2CDriver(iBus=bus_number)
            if i2c_driver is None:
                raise RuntimeError("no qwiic I2C driver available for this platform")

            sensor = qwiic_bme280.QwiicBme280(address=address, i2c_driver=i2c_driver)
            if not sensor.connected:
                raise RuntimeError("device not responding")
            if not sensor.begin():
                raise RuntimeError("begin() failed (unexpected chip ID)")

            self._sensor = sensor
            log(9, f"BME280 found on I2C bus {bus_number} at address 0x{address:02x}")
            return True
        except Exception as exc:  # noqa: BLE001 - wrong address/bus, not wired up, I2C not enabled, ...
            log(9, f"BME280 not found on I2C bus {bus_number} at address 0x{address:02x} "
                   f"(check wiring, raspi-config's I2C interface, the SDO-pin address jumper, "
                   f"and that BME280_I2C_BUS matches `i2cdetect -y {bus_number}`): {exc}")
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

        temperature = self._sensor.temperature_celsius
        humidity = self._sensor.humidity
        pressure = self._sensor.pressure / 100.0  # Pa -> hPa

        display_data.update("sparkfun_elec_bay_temperature", temperature, source="I")
        display_data.update("sparkfun_elec_bay_humidity", humidity, source="I")
        display_data.update("BME280-Barometer", pressure, source="I")
        display_data.update("Weather280", 1, source="S")

        if not config.flags.do_fake:
            log(9, f"BME280: received {temperature:.1f}C, {humidity:.0f}% RH, {pressure:.1f} hPa")

    def close(self) -> None:
        self._sensor = None
