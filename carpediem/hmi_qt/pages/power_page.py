"""P - Power, StartrekGraphical (Qt) version of hmi/pages/power_page.py -
see that module's docstring for the full layout spec, the None/"none"
convention, and the power-flow diagram's reasoning. Drawn as one custom-
painted QWidget (like RadarView/AisPage/WeatherPage) rather than composed
of many child widgets.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from carpediem.display_data import display_data
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import tracked_font

LEFT_B_WIDTH_FRACTION = 1 / 3
NONE_TEXT = "none"

LABEL_SIZE_FRACTION = 0.070
VALUE_SIZE_FRACTION = 0.052

FLOW_MAX_WATTS = 1200.0


def _fmt(value: Optional[float], suffix: str = "", decimals: int = 0) -> str:
    if value is None:
        return NONE_TEXT
    return f"{value:.{decimals}f}{suffix}"


class PowerPage(QWidget):
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

        a_h = h // 2
        b_h = h - a_h

        self._draw_section_a(painter, QRectF(0, 0, w, a_h), theme)
        self._draw_section_b(painter, QRectF(0, a_h, w, b_h), theme)

    # -- section A: Grid / DC / Solar --------------------------------------

    def _draw_section_a(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        col_w = rect.width() / 3
        cells = [QRectF(rect.x() + i * col_w, rect.y(), col_w, rect.height()) for i in range(3)]

        grid_status = display_data.get("Active input source")
        grid_w = display_data.get("Grid (W)")
        grid_value = "-" if grid_status != 1 else _fmt(grid_w, " W")
        self._draw_tile(painter, cells[0], theme, "GRID", [grid_value], theme.accent)

        dc_w = display_data.get("DC Power (W)")
        dc_a = display_data.get("DC Current (A)")
        self._draw_tile(painter, cells[1], theme, "DC", [_fmt(dc_w, " W"), _fmt(dc_a, " A", 1)], theme.secondary)

        pv_w = display_data.get("PV Power (W)")
        self._draw_tile(painter, cells[2], theme, "SOLAR", [_fmt(pv_w, " W")], theme.ok)

    def _draw_tile(self, painter: QPainter, cell: QRectF, theme: QtTheme, label: str,
                   value_lines: List[str], accent: QColor) -> None:
        label_size = max(14, int(cell.height() * LABEL_SIZE_FRACTION))
        value_size = max(12, int(cell.height() * VALUE_SIZE_FRACTION))
        line_gap = value_size * 1.25

        total_h = label_size * 1.3 + len(value_lines) * line_gap
        y = cell.center().y() - total_h / 2

        font = tracked_font(self.font(), 2.0)
        font.setBold(True)
        font.setPixelSize(label_size)
        painter.setFont(font)
        painter.setPen(QPen(accent))
        painter.drawText(QRectF(cell.x(), y, cell.width(), label_size * 1.3),
                          Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)
        y += label_size * 1.5

        vfont = QFont(self.font())
        vfont.setPixelSize(value_size)
        painter.setFont(vfont)
        painter.setPen(QPen(theme.text))
        for line in value_lines:
            painter.drawText(QRectF(cell.x(), y, cell.width(), line_gap),
                              Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line)
            y += line_gap

    # -- section B: AC Load/Starter stack + power-flow diagram ------------

    def _draw_section_b(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        left_w = rect.width() * LEFT_B_WIDTH_FRACTION
        left_rect = QRectF(rect.x(), rect.y(), left_w, rect.height())
        right_rect = QRectF(rect.x() + left_w, rect.y(), rect.width() - left_w, rect.height())

        self._draw_ac_starter_stack(painter, left_rect, theme)
        self._draw_power_flow(painter, right_rect, theme)

    def _draw_ac_starter_stack(self, painter: QPainter, cell: QRectF, theme: QtTheme) -> None:
        label_size = max(14, int(cell.height() * LABEL_SIZE_FRACTION))
        value_size = max(12, int(cell.height() * VALUE_SIZE_FRACTION))

        ac_w = display_data.get("AC Loads (W)")
        starter_w = display_data.get("Battery0 Power (W)")
        volts = display_data.get("Battery0 Voltage (V)")
        amps = display_data.get("Battery0 Current (A)")
        soc = display_data.get("Battery SOC (%)")
        ttg = display_data.get("Battery Time to Go (System)")
        if ttg is None:
            ttg = display_data.get("Battery Time to Go (Batt)")

        volts_amps = f"{_fmt(volts, ' V', 1)}  {_fmt(amps, ' A', 1)}"
        soc_str = "-" if soc is None else f"{soc:.0f}%"
        ttg_str = "-" if ttg is None else f"{ttg:.1f}h"
        soc_ttg = f"{soc_str}  {ttg_str}" if not (soc is None and ttg is None) else "-"

        rows = [
            ("AC LOAD", True), (_fmt(ac_w, " W"), False),
            ("STARTER", True), (_fmt(starter_w, " W"), False),
            (volts_amps, False),
            (soc_ttg, False),
        ]
        line_h = cell.height() / len(rows)
        y = cell.y()
        for text, is_label in rows:
            size = label_size if is_label else value_size
            font = tracked_font(self.font(), 2.0 if is_label else 0.0)
            font.setBold(is_label)
            font.setPixelSize(size)
            painter.setFont(font)
            painter.setPen(QPen(theme.accent if is_label else theme.text))
            painter.drawText(QRectF(cell.x(), y, cell.width(), line_h), Qt.AlignmentFlag.AlignCenter, text)
            y += line_h

    def _draw_power_flow(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        c = rect.adjusted(8, 8, -8, -8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(c, 14, 14)

        bus_x = rect.center().x()
        bus_top = rect.y() + rect.height() * 0.12
        bus_bottom = rect.y() + rect.height() * 0.82
        painter.setPen(QPen(theme.accent, 3))
        painter.drawLine(QPointF(bus_x, bus_top), QPointF(bus_x, bus_bottom))

        grid_status = display_data.get("Active input source")
        grid_w = (display_data.get("Grid (W)") if grid_status == 1 else 0.0) or 0.0
        dc_w = display_data.get("DC Power (W)") or 0.0
        pv_w = display_data.get("PV Power (W)") or 0.0
        ac_w = display_data.get("AC Loads (W)") or 0.0
        battery_w = display_data.get("Battery Power (W)")

        left_x = rect.x() + rect.width() * 0.09
        source_rows = [
            ("GRID", grid_w, theme.accent, _icon_grid),
            ("SOLAR", pv_w, theme.ok, _icon_sun),
            ("DC", dc_w, theme.secondary, _icon_gear),
        ]
        for i, (label, watts, color, icon_fn) in enumerate(source_rows):
            y = rect.y() + rect.height() * (0.20 + i * 0.28)
            self._draw_flow_node(painter, theme, (left_x, y), label, watts, " W", color, icon_fn, on_left=True)
            self._draw_flow_line(painter, (left_x + 26, y), (bus_x, y), color, watts)

        right_x = rect.right() - rect.width() * 0.09
        load_y = rect.y() + rect.height() * 0.34
        self._draw_flow_node(painter, theme, (right_x, load_y), "AC LOAD", ac_w, " W", theme.warn, _icon_plug,
                              on_left=False)
        self._draw_flow_line(painter, (bus_x, load_y), (right_x - 26, load_y), theme.warn, ac_w)

        batt_y = rect.y() + rect.height() * 0.72
        charging = battery_w is not None and battery_w >= 0
        batt_color = theme.ok if charging else theme.warn
        self._draw_flow_node(painter, theme, (right_x, batt_y), "BATTERY", battery_w, " W", batt_color,
                              _icon_battery_flow, on_left=False)
        if battery_w is not None:
            if charging:
                self._draw_flow_line(painter, (bus_x, batt_y), (right_x - 26, batt_y), batt_color, battery_w)
            else:
                self._draw_flow_line(painter, (right_x - 26, batt_y), (bus_x, batt_y), batt_color, -battery_w)

    def _draw_flow_node(self, painter: QPainter, theme: QtTheme, pos: Tuple[float, float], label: str,
                        watts: Optional[float], suffix: str, color: QColor, icon_fn, on_left: bool) -> None:
        x, y = pos
        icon_r = 16.0
        center = QPointF(x, y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, icon_r, icon_r)
        icon_rect = QRectF(x - icon_r, y - icon_r, icon_r * 2, icon_r * 2)
        icon_fn(painter, icon_rect, theme, theme.bg)

        text_x = x + icon_r + 8 if on_left else x - icon_r - 8
        align = Qt.AlignmentFlag.AlignLeft if on_left else Qt.AlignmentFlag.AlignRight
        text_w = 140

        font = tracked_font(self.font(), 1.0)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QPen(theme.text_dim))
        label_rect = QRectF(text_x if on_left else text_x - text_w, y - 22, text_w, 16)
        painter.drawText(label_rect, align | Qt.AlignmentFlag.AlignVCenter, label)

        vfont = QFont(self.font())
        vfont.setBold(True)
        vfont.setPixelSize(16)
        painter.setFont(vfont)
        painter.setPen(QPen(theme.text))
        value_rect = QRectF(text_x if on_left else text_x - text_w, y, text_w, 20)
        painter.drawText(value_rect, align | Qt.AlignmentFlag.AlignVCenter, _fmt(watts, suffix))

    def _draw_flow_line(self, painter: QPainter, p1: Tuple[float, float], p2: Tuple[float, float],
                        color: QColor, watts: Optional[float]) -> None:
        watts = abs(watts) if watts is not None else 0.0
        thickness = 2 + min(1.0, watts / FLOW_MAX_WATTS) * 8
        painter.setPen(QPen(color, thickness))
        painter.drawLine(QPointF(*p1), QPointF(*p2))

        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head_len, head_w = 10, 6
        tip = QPointF(*p2)
        base_l = QPointF(p2[0] - ux * head_len + px * head_w, p2[1] - uy * head_len + py * head_w)
        base_r = QPointF(p2[0] - ux * head_len - px * head_w, p2[1] - uy * head_len - py * head_w)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, base_l, base_r]))


# -- power-flow node icons -------------------------------------------------

def _icon_grid(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    cx, top, bottom = rect.center().x(), rect.top() + 2, rect.bottom() - 2
    painter.setPen(QPen(color, 2))
    painter.drawLine(QPointF(cx, top), QPointF(cx, bottom))
    for frac, wfrac in ((0.25, 0.7), (0.55, 0.5)):
        y = top + (bottom - top) * frac
        half = rect.width() * wfrac / 2
        painter.drawLine(QPointF(cx - half, y), QPointF(cx + half, y))
        painter.drawLine(QPointF(cx - half, y), QPointF(cx, top))
        painter.drawLine(QPointF(cx + half, y), QPointF(cx, top))


def _icon_sun(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    r = rect.width() * 0.28
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect.center(), r, r)
    for deg in range(0, 360, 45):
        theta = math.radians(deg)
        p1 = rect.center() + QPointF(math.cos(theta) * (r + 3), math.sin(theta) * (r + 3))
        p2 = rect.center() + QPointF(math.cos(theta) * (r + 8), math.sin(theta) * (r + 8))
        painter.drawLine(p1, p2)


def _icon_gear(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    r = rect.width() * 0.3
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect.center(), r, r)
    for deg in range(0, 360, 45):
        theta = math.radians(deg)
        p1 = rect.center() + QPointF(math.cos(theta) * r, math.sin(theta) * r)
        p2 = rect.center() + QPointF(math.cos(theta) * (r + 4), math.sin(theta) * (r + 4))
        painter.drawLine(p1, p2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(rect.center(), max(1.0, r * 0.35), max(1.0, r * 0.35))


def _icon_plug(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    body = rect.adjusted(rect.width() * 0.25, rect.height() * 0.25, -rect.width() * 0.25, -rect.height() * 0.25)
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 4, 4)
    for dxfrac in (-0.2, 0.2):
        x = body.center().x() + dxfrac * body.width()
        painter.drawLine(QPointF(x, body.top() - 4), QPointF(x, body.top() + 3))


def _icon_battery_flow(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    body = rect.adjusted(rect.width() * 0.25, rect.height() * 0.2, -rect.width() * 0.25, -rect.height() * 0.2)
    nub_w = body.width() * 0.4
    nub = QRectF(body.center().x() - nub_w / 2, body.top() - body.height() * 0.12, nub_w, body.height() * 0.12 + 1)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(nub, 2, 2)
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 4, 4)
