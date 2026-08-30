"""Optional MAX7219 8x8 LED matrix status display - port of the
displayIcon/displayStartupAnimation/updateMatrixDisplay/displayTimeOnMatrix
functions.

Fully optional (config.flags.use_matrix, default False) - this was a
stand-in status indicator before the e-ink screen existed. Kept working
here in case you still want a tiny always-on heartbeat/status light even
after the e-ink display is wired up, but nothing else depends on it.

Uses luma.led_matrix (SPI) instead of MD_MAX72XX - same chip, a
maintained Python library for it. One behaviour change: the original's
first status frame showed an SD-card-present/missing icon; there's no SD
card subsystem to report on any more (see logging_setup.py), so that
frame now shows whether the log file is currently writable instead.
"""
from __future__ import annotations

import time
from typing import List, Optional

from carpediem.logging_setup import log

# 8x8 bit patterns, ported 1:1 from ICON_* in the sketch (row-major, MSB = leftmost pixel)
ICON_LOG_OK: List[int] = [0b00111100, 0b01000010, 0b10111101, 0b10100101,
                          0b10111101, 0b10000001, 0b01111110, 0b00000000]
ICON_LOG_ERROR: List[int] = [0b00111100, 0b01000010, 0b10000001, 0b10000001,
                              0b10000001, 0b10000001, 0b01111110, 0b00000000]
ICON_HEART: List[int] = [0b00000000, 0b01100110, 0b11111111, 0b11111111,
                          0b01111110, 0b00111100, 0b00011000, 0b00000000]
ICON_CHECKMARK: List[int] = [0b00000000, 0b00000001, 0b00000011, 0b10000110,
                              0b11001100, 0b01111000, 0b00110000, 0b00000000]
ICON_ERROR: List[int] = [0b10000001, 0b01000010, 0b00100100, 0b00011000,
                          0b00011000, 0b00100100, 0b01000010, 0b10000001]


class MatrixDisplay:
    def __init__(self) -> None:
        self._device = None
        self._mode = 0
        self.log_writable = True  # updated externally by whatever checks the log file

    def init(self) -> bool:
        try:
            from luma.core.interface.serial import spi, noop
            from luma.led_matrix.device import max7219

            serial = spi(port=0, device=0, gpio=noop())
            self._device = max7219(serial, cascaded=1, block_orientation=0, rotate=0)
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

    def show_time(self, hour: int, minute: int) -> None:
        """Port of displayTimeOnMatrix(): a rough bar-graph clock, not a
        legible digit display - same behaviour as the original."""
        if self._device is None:
            return
        from luma.core.render import canvas

        with canvas(self._device) as draw:
            for i in range(min(hour, 8)):
                draw.line([(i, 0), (i, 3)], fill="white")
            min_bars = (minute * 8) // 60
            for i in range(min(min_bars, 8)):
                draw.line([(i, 4), (i, 7)], fill="white")

    def tick(self, now_hour: int, now_minute: int) -> None:
        """Equivalent of updateMatrixDisplay(): cycles through 3 status
        frames, call this on the same MATRIX_UPDATE_INTERVAL (5s) as the
        original."""
        if self._device is None:
            return
        if self._mode == 0:
            self.show_icon(ICON_LOG_OK if self.log_writable else ICON_LOG_ERROR)
        elif self._mode == 1:
            self.show_icon(ICON_HEART)
        else:
            self.show_time(now_hour, now_minute)
        self._mode = (self._mode + 1) % 3
