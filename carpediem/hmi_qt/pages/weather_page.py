"""W - Weather, StartrekGraphical (Qt) version of hmi/pages/weather_page.py
- see that module's docstring for the full layout spec and reasoning.
Drawn as one custom-painted QWidget (like RadarView/AisPage) rather than
composed of many child widgets.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from carpediem.display_data import display_data
from carpediem.hmi.util import compass_abbr
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import tracked_font

SECTION_A_FRACTION = 48 / 87
LEFT_WIDTH_FRACTION = 0.59
SECTION_B_COLUMNS = 5

BAROMETER_MIN_HPA = 970.0
BAROMETER_MAX_HPA = 1040.0
WINDSOCK_FULL_EXTENSION_KMH = 35.0


class WeatherPage(QWidget):
    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def refresh(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()

        a_h = h * SECTION_A_FRACTION
        b_h = h - a_h

        self._draw_section_a(painter, QRectF(0, 0, w, a_h), theme)
        self._draw_section_b(painter, QRectF(0, a_h, w, b_h), theme)

    # -- section A: the two wind gauges ------------------------------------

    def _draw_section_a(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        left_w = rect.width() * LEFT_WIDTH_FRACTION
        left_rect = QRectF(rect.x(), rect.y(), left_w, rect.height())
        right_rect = QRectF(rect.x() + left_w, rect.y(), rect.width() - left_w, rect.height())

        speed = display_data.get("BresserWindAverageSpeed")
        speed_str = f"{speed:.1f}" if speed is not None else "--"

        course_relative_dir = display_data.get("WindspeedCalculatedAsExperienced")
        self._draw_wind_circle(painter, left_rect, theme, course_relative_dir, speed_str,
                                "RELATIVE TO COURSE", theme.secondary)

        raw_dir = display_data.get("BresserWindDirection")
        self._draw_wind_circle(painter, right_rect, theme, raw_dir, speed_str,
                                "AS DEVICE REPORTS", theme.tertiary)

    def _draw_wind_circle(self, painter: QPainter, cell: QRectF, theme: QtTheme,
                           direction_deg: Optional[float], speed_str: str, caption: str, accent: QColor) -> None:
        radius = min(cell.width(), cell.height()) * 0.36
        center = QPointF(cell.center().x(), cell.center().y() + cell.height() * 0.04)

        font = tracked_font(self.font(), 2.0)
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(cell.x(), cell.y() + cell.height() * 0.02, cell.width(), 24),
                          Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, caption)

        glow = QRadialGradient(center, radius * 1.25)
        c1 = QColor(accent)
        c1.setAlpha(90)
        glow.setColorAt(0.0, c1)
        c2 = QColor(accent)
        c2.setAlpha(0)
        glow.setColorAt(1.0, c2)
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius * 1.25, radius * 1.25)

        face = QRadialGradient(center, radius)
        face.setColorAt(0.0, theme.panel_bg_hi)
        face.setColorAt(1.0, accent.darker(160))
        painter.setBrush(face)
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QPen(theme.text_dim, 2))
        for deg in range(0, 360, 30):
            theta = math.radians(deg)
            outer = center + QPointF(math.sin(theta) * radius, -math.cos(theta) * radius)
            inner = center + QPointF(math.sin(theta) * (radius - 8), -math.cos(theta) * (radius - 8))
            painter.drawLine(inner, outer)

        painter.setPen(QPen(accent, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)

        if direction_deg is not None:
            theta = math.radians(direction_deg)
            marker = center + QPointF(math.sin(theta) * (radius - 5), -math.cos(theta) * (radius - 5))
            mglow = QRadialGradient(marker, 12)
            mc1 = QColor(theme.accent)
            mc1.setAlpha(180)
            mglow.setColorAt(0.0, mc1)
            mc2 = QColor(theme.accent)
            mc2.setAlpha(0)
            mglow.setColorAt(1.0, mc2)
            painter.setBrush(mglow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(marker, 12, 12)
            painter.setBrush(theme.accent)
            painter.drawEllipse(marker, 6, 6)

        dir_str = compass_abbr(direction_deg) if direction_deg is not None else "--"
        f1 = QFont(self.font())
        f1.setBold(True)
        f1.setPixelSize(max(10, int(radius * 0.24)))
        painter.setFont(f1)
        painter.setPen(QPen(theme.text))
        painter.drawText(QRectF(center.x() - radius, center.y() - radius * 0.55, radius * 2, radius * 0.3),
                          Qt.AlignmentFlag.AlignCenter, dir_str)

        f2 = QFont(self.font())
        f2.setBold(True)
        f2.setPixelSize(max(14, int(radius * 0.44)))
        painter.setFont(f2)
        painter.drawText(QRectF(center.x() - radius, center.y() - radius * 0.1, radius * 2, radius * 0.5),
                          Qt.AlignmentFlag.AlignCenter, speed_str)

        f3 = QFont(self.font())
        f3.setPixelSize(max(9, int(radius * 0.15)))
        painter.setFont(f3)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(center.x() - radius, center.y() + radius * 0.4, radius * 2, radius * 0.25),
                          Qt.AlignmentFlag.AlignCenter, "km/h")

    # -- section B: the 5 tiles -------------------------------------------

    def _draw_section_b(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        col_w = rect.width() / SECTION_B_COLUMNS
        cells = [QRectF(rect.x() + i * col_w, rect.y(), col_w, rect.height()) for i in range(SECTION_B_COLUMNS)]

        temp = display_data.get("BresserTemperature")
        self._draw_tile(painter, cells[0], theme, "OUTSIDE TEMP", _icon_thermometer, theme.warn,
                         f"{temp:.1f}°C" if temp is not None else "--")

        humidity = display_data.get("BresserHumidity")
        self._draw_tile(painter, cells[1], theme, "OUTSIDE HUMIDITY", _icon_droplet, theme.secondary,
                         f"{humidity:.0f}%" if humidity is not None else "--")

        rainfall = display_data.get("BresserRainfall")
        self._draw_tile(painter, cells[2], theme, "RAIN",
                         lambda p, r, t, c: _icon_rain_gauge(p, r, t, c, rainfall), theme.secondary,
                         f"{rainfall:.1f} mm" if rainfall is not None else "--")

        pressure = display_data.get("BME280-Barometer")
        self._draw_tile(painter, cells[3], theme, "BAROMETER",
                         lambda p, r, t, c: _icon_barometer(p, r, t, c, pressure), theme.accent,
                         f"{pressure:.1f} hPa" if pressure is not None else "--")

        wind_speed = display_data.get("BresserWindAverageSpeed")
        wind_color = _wind_level_color(theme, wind_speed)
        self._draw_tile(painter, cells[4], theme, "WIND LEVEL",
                         lambda p, r, t, c: _icon_windsock(p, r, t, c, wind_speed), wind_color,
                         f"{wind_speed:.1f} km/h" if wind_speed is not None else "--")

    def _draw_tile(self, painter: QPainter, cell: QRectF, theme: QtTheme, caption: str,
                   icon_draw, accent: QColor, value_str: str) -> None:
        c = cell.adjusted(8, 8, -8, -8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(c, 14, 14)

        font = tracked_font(self.font(), 1.5)
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(cell.x(), cell.y() + cell.height() * 0.10, cell.width(), 20),
                          Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, caption)

        icon_size = min(cell.width(), cell.height()) * 0.42
        icon_rect = QRectF(0, 0, icon_size, icon_size)
        icon_rect.moveCenter(QPointF(cell.center().x(), 0))
        icon_rect.moveTop(cell.y() + cell.height() * 0.22)
        icon_draw(painter, icon_rect, theme, accent)

        font2 = QFont(self.font())
        font2.setBold(True)
        font2.setPixelSize(max(12, int(cell.height() * 0.13)))
        painter.setFont(font2)
        painter.setPen(QPen(theme.text))
        painter.drawText(QRectF(cell.x(), cell.bottom() - cell.height() * 0.20, cell.width(), cell.height() * 0.16),
                          Qt.AlignmentFlag.AlignCenter, value_str)


# -- Section B icons --------------------------------------------------------

def _icon_thermometer(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    w, h = rect.width(), rect.height()
    cx = rect.center().x()
    stem_w = max(4.0, w * 0.22)
    stem = QRectF(cx - stem_w / 2, rect.top() + h * 0.05, stem_w, h * 0.6)
    bulb_r = w * 0.2
    bulb_center = QPointF(cx, stem.bottom() + bulb_r - 2)

    glow = QRadialGradient(bulb_center, bulb_r * 1.8)
    c1 = QColor(color)
    c1.setAlpha(90)
    glow.setColorAt(0.0, c1)
    c2 = QColor(color)
    c2.setAlpha(0)
    glow.setColorAt(1.0, c2)
    painter.setBrush(glow)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(bulb_center, bulb_r * 1.8, bulb_r * 1.8)

    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(stem, stem_w / 2, stem_w / 2)
    painter.drawEllipse(bulb_center, bulb_r, bulb_r)
    painter.drawLine(QPointF(cx, stem.top() + stem.height() * 0.3), QPointF(cx, bulb_center.y()))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(bulb_center, max(1.0, bulb_r - 5), max(1.0, bulb_r - 5))


def _icon_droplet(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    w, h = rect.width(), rect.height()
    cx = rect.center().x()
    tip = QPointF(cx, rect.top() + h * 0.05)
    r = w * 0.38
    body_y = rect.top() + h * 0.62

    glow = QRadialGradient(QPointF(cx, body_y), r * 1.8)
    c1 = QColor(color)
    c1.setAlpha(90)
    glow.setColorAt(0.0, c1)
    c2 = QColor(color)
    c2.setAlpha(0)
    glow.setColorAt(1.0, c2)
    painter.setBrush(glow)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(cx, body_y), r * 1.8, r * 1.8)

    points = [
        tip, QPointF(cx + r, body_y - r * 0.15), QPointF(cx + r * 0.7, body_y + r * 0.7),
        QPointF(cx, rect.bottom() - 2), QPointF(cx - r * 0.7, body_y + r * 0.7), QPointF(cx - r, body_y - r * 0.15),
    ]
    painter.setPen(QPen(color, 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(QPolygonF(points))


def _icon_rain_gauge(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor, amount: Optional[float]) -> None:
    w, h = rect.width(), rect.height()
    tube = QRectF(0, 0, w * 0.4, h * 0.85)
    tube.moveCenter(QPointF(rect.center().x(), 0))
    tube.moveTop(rect.top())

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.bg)
    painter.drawRoundedRect(tube, 4, 4)

    max_mm = 10.0
    pct = 0.0 if amount is None else max(0.0, min(1.0, amount / max_mm))
    fill_h = (tube.height() - 4) * pct
    if fill_h > 0:
        fill_rect = QRectF(tube.x() + 2, tube.bottom() - 2 - fill_h, tube.width() - 4, fill_h)
        grad = QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
        grad.setColorAt(0.0, color.lighter(140))
        grad.setColorAt(1.0, color)
        painter.setBrush(grad)
        painter.drawRoundedRect(fill_rect, 3, 3)

    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(tube, 4, 4)

    painter.setPen(QPen(theme.text_dim, 1))
    for frac in (0.33, 0.66):
        y = tube.bottom() - tube.height() * frac
        painter.drawLine(QPointF(tube.left() + 2, y), QPointF(tube.left() + 6, y))


def _icon_barometer(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor, pressure: Optional[float]) -> None:
    w, h = rect.width(), rect.height()
    center = QPointF(rect.center().x(), rect.bottom() - h * 0.08)
    radius = min(w, h * 1.7) * 0.46

    painter.setPen(QPen(theme.text_dim, 2))
    for deg in (180, 90, 0):
        theta = math.radians(deg)
        outer = center + QPointF(-math.cos(theta) * radius, -math.sin(theta) * radius)
        inner_r = radius - 7
        inner = center + QPointF(-math.cos(theta) * inner_r, -math.sin(theta) * inner_r)
        painter.drawLine(inner, outer)

    arc_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    painter.setPen(QPen(color, 3))
    painter.drawArc(arc_rect, 0, 180 * 16)

    pct = 0.5
    if pressure is not None:
        span = BAROMETER_MAX_HPA - BAROMETER_MIN_HPA
        pct = max(0.0, min(1.0, (pressure - BAROMETER_MIN_HPA) / span))
    needle_deg = 180 - pct * 180
    theta = math.radians(needle_deg)
    tip = center + QPointF(-math.cos(theta) * (radius - 6), -math.sin(theta) * (radius - 6))
    painter.setPen(QPen(theme.accent, 3))
    painter.drawLine(center, tip)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.accent)
    painter.drawEllipse(center, 4, 4)


def _icon_windsock(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor, speed: Optional[float]) -> None:
    """Droop scales with speed only (not direction) - direction is already
    fully covered by section A's two wind circles above."""
    w, h = rect.width(), rect.height()
    pole_x = rect.x() + w * 0.18
    pole_top = QPointF(pole_x, rect.top() + h * 0.05)
    pole_bottom = QPointF(pole_x, rect.bottom() - 2)
    painter.setPen(QPen(theme.panel_border, 3))
    painter.drawLine(pole_top, pole_bottom)

    speed_frac = 0.0 if speed is None else max(0.0, min(1.0, speed / WINDSOCK_FULL_EXTENSION_KMH))
    droop = (1.0 - speed_frac) * (h * 0.35)
    sock_len = w * 0.68
    tip = QPointF(pole_x + sock_len, pole_top.y() + droop)
    mid = QPointF(pole_x + sock_len * 0.55, pole_top.y() + droop * 0.35)

    base_half_w = h * 0.16
    tip_half_w = h * 0.03
    points = [
        QPointF(pole_x, pole_top.y() - base_half_w * 0.5), QPointF(pole_x, pole_top.y() + base_half_w),
        QPointF(mid.x(), mid.y() + base_half_w * 0.55), QPointF(tip.x(), tip.y() + tip_half_w),
        QPointF(tip.x(), tip.y() - tip_half_w), QPointF(mid.x(), mid.y() - base_half_w * 0.55),
    ]
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF(points))

    painter.setBrush(theme.bg)
    for frac in (0.35, 0.65):
        band_pt = QPointF(pole_x + (tip.x() - pole_x) * frac, pole_top.y() + droop * (frac ** 1.5))
        painter.drawEllipse(band_pt, 2, 2)


def _wind_level_color(theme: QtTheme, speed: Optional[float]) -> QColor:
    if speed is None:
        return theme.neutral
    if speed > 25:
        return theme.danger
    if speed > 12:
        return theme.warn
    return theme.ok
