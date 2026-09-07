"""Optional MAX7219 8x8 LED matrix status display - port of the
displayIcon/displayStartupAnimation functions, but updateMatrixDisplay's
3-frame cycle (log-status / heart / clock) has been replaced entirely by
a live subsystem health indicator - see status_monitor.py for the logic
and the module-level docstring there for the row1/row2 slot layout.

Fully optional (config.flags.use_matrix, default False) - this was a
stand-in status indicator before the e-ink screen existed. Kept working
here in case you still want a tiny always-on heartbeat/status light even
after the e-ink display is wired up, but nothing else depends on it.

Uses luma.led_matrix (SPI) instead of MD_MAX72XX - same chip, a
maintained Python library for it.

The matrix uses hardware SPI (spi(port=0, device=0, gpio=noop()) in matrix_display.py:47), not bit-banged GPIO, so it needs the standard Raspberry Pi SPI0 pins:
MAX7219 pin	Raspberry Pi pin	GPIO
VCC	5V  pin  2 	                    red
GND	GND pin 14	                    brown
DIN	    pin 19	GPIO10 (SPI0 MOSI)  orange
CS/CE	pin 24	GPIO8 (SPI0 CE0)    purple
CLK	    pin 23	GPIO11 (SPI0 SCLK)  green
port=0, device=0 maps to /dev/spidev0.0, i.e. CE0. gpio=noop() means no extra GPIO pin is used for chip-select toggling — it's purely the hardware SPI bus. 
Just make sure SPI is enabled (raspi-config → Interface Options → SPI) and nothing else is claiming SPI0/CE0.


"""
from __future__ import annotations

import time
from typing import List, Optional

from carpediem.config import config
from carpediem.logging_setup import log
from carpediem import status_monitor

# 8x8 bit patterns, ported 1:1 from ICON_* in the sketch (row-major, MSB = leftmost pixel)
ICON_HEART: List[int] = [0b00000000, 0b01100110, 0b11111111, 0b11111111,
                          0b01111110, 0b00111100, 0b00011000, 0b00000000]
ICON_CHECKMARK: List[int] = [0b00000000, 0b00000001, 0b00000011, 0b10000110,
                              0b11001100, 0b01111000, 0b00110000, 0b00000000]
ICON_ERROR: List[int] = [0b10000001, 0b01000010, 0b00100100, 0b00011000,
                          0b00011000, 0b00100100, 0b01000010, 0b10000001]


class MatrixDisplay:
    def __init__(self) -> None:
        self._device = None

    def init(self) -> bool:
        try:
            from luma.core.interface.serial import spi, noop
            from luma.led_matrix.device import max7219

            serial = spi(port=0, device=0, gpio=noop())
            self._device = max7219(serial, cascaded=1, block_orientation=0, rotate=0)
            self.set_brightness(config.matrix.brightness_percent)
            log(9, "MAX7219 matrix initialized")
            self._startup_animation()
            self.show_icon(ICON_CHECKMARK)
            return True
        except Exception as exc:  # noqa: BLE001 - matrix not wired up, or SPI unavailable
            log(9, f"MAX7219 matrix not available: {exc}")
            self._device = None
            return False

    def _startup_animation(self) -> None:
        if self._device is None:
            return
        from luma.core.render import canvas

        for row in range(8):
            with canvas(self._device) as draw:
                draw.line([(0, row), (7, row)], fill="white")
            time.sleep(0.05)
        for _ in range(3):
            with canvas(self._device) as draw:
                draw.rectangle((0, 0, 7, 7), fill="white")
            time.sleep(0.1)
            with canvas(self._device):
                pass  # clear
            time.sleep(0.1)

    def set_brightness(self, percent: int) -> None:
        """0-100 percentage, translated to luma's 0-255 contrast level
        (which in turn maps to the MAX7219's 0-15 intensity register)."""
        if self._device is None:
            return
        level = round(max(0, min(100, percent)) / 100 * 255)
        self._device.contrast(level)
        log(9, f"MAX7219 matrix brightness set to {percent}% (contrast={level})")

    def show_icon(self, icon: List[int]) -> None:
        if self._device is None:
            return
        from luma.core.render import canvas

        with canvas(self._device) as draw:
            for row, bits in enumerate(icon):
                for col in range(8):
                    if bits & (1 << (7 - col)):
                        draw.point((col, row), fill="white")

    def show_error(self) -> None:
        self.show_icon(ICON_ERROR)

    def show_status_dots(self, dots: List[bool]) -> None:
        """Renders status_monitor.compute_status()'s dots list: one lit
        pixel per flagged slot, row 1 = slots 0-7 (columns 1-8), row 2 =
        slots 8-10 (columns 9-11) - see status_monitor.py for what each
        slot means and when it lights up."""
        if self._device is None:
            return
        from luma.core.render import canvas

        with canvas(self._device) as draw:
            for i, flagged in enumerate(dots):
                if flagged:
                    row, col = divmod(i, 8)
                    draw.point((col, row), fill="white")

    def tick(self) -> None:
        """Call this on a regular interval (main.py uses
        MATRIX_TICK_INTERVAL_SECONDS). Shows a heart once every tracked
        subsystem reports OK, otherwise the row1/row2 status-dot grid for
        whichever ones aren't - see status_monitor.py for the logic."""
        if self._device is None:
            return
        all_ok, dots = status_monitor.compute_status()
        if all_ok:
            self.show_icon(ICON_HEART)
        else:
            self.show_status_dots(dots)
