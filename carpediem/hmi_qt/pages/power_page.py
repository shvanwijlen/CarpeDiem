"""P - Power, StartrekGraphical (Qt) version of hmi/pages/power_page.py -
see that module's docstring for the full layout spec, the None/"none"
convention, and the power-flow diagram's reasoning. Drawn as one custom-
painted QWidget (like RadarView/AisPage/WeatherPage) rather than composed
of many child widgets.

Sizing/style note: text across this page was noticeably smaller than the
other pages and the power-flow diagram (section B's right two-thirds) was
flagged as the part worth investing in - bigger, and with a real graphical
touch instead of plain circles. Each flow node now gets a soft additive
glow (same QRadialGradient pattern as widgets.py's Led/CompassRose), and
the battery node specifically gets a charge-percentage ring plus an SOC%/
TTG line - that data used to live only in the cramped AC LOAD/STARTER
stack on the left, which is what the ring/line replace it with here.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from carpediem.display_data import display_data
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import draw_solid_text, tracked_font

LEFT_B_WIDTH_FRACTION = 1 / 3
NONE_TEXT = "none"

LABEL_SIZE_FRACTION = 0.17
VALUE_SIZE_FRACTION = 0.13

FLOW_MAX_WATTS = 1200.0


def _fmt(value: Optional[float], suffix: str = "", decimals: int = 0) -> str:
    if value is None:
        return NONE_TEXT
    return f"{value:.{decimals}f}{suffix}"


def _pen(color: QColor, width: float, round_cap: bool = False) -> QPen:
    pen = QPen(color, width)
    if round_cap:
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _draw_node_glow(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
    """Soft additive glow halo - same QRadialGradient pattern as
    widgets.py's Led/CompassRose. Split out from _draw_icon_badge() so
    _draw_flow_node() can still sandwich its charge ring between the glow
    and the solid icon circle (glow behind everything, ring around the
    icon, icon on top)."""
    glow_r = radius * 2.1
    grad = QRadialGradient(center, glow_r)
    c1 = QColor(color)
    c1.setAlpha(110)
    grad.setColorAt(0.0, c1)
    c2 = QColor(color)
    c2.setAlpha(0)
    grad.setColorAt(1.0, c2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawEllipse(center, glow_r, glow_r)


def _draw_node_icon_circle(painter: QPainter, theme: QtTheme, center: QPointF, radius: float,
                            color: QColor, icon_fn) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(center, radius, radius)
    icon_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    icon_fn(painter, icon_rect, theme, theme.bg)


def _draw_icon_badge(painter: QPainter, theme: QtTheme, center: QPointF, radius: float,
                      color: QColor, icon_fn, glow: bool = True) -> None:
    """Filled circle + icon_fn glyph, with an optional glow behind it.
    Shared by the power-flow nodes and the section-A/AC-LOAD/STARTER
    icons so the whole page reads as one visual language instead of the
    flow diagram being the only part with icons."""
    if glow:
        _draw_node_glow(painter, center, radius, color)
    _draw_node_icon_circle(painter, theme, center, radius, color, icon_fn)


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
        self._draw_tile(painter, cells[0], theme, "GRID", [grid_value], theme.accent, _icon_grid)

        dc_w = display_data.get("DC Power (W)")
        dc_a = display_data.get("DC Current (A)")
        self._draw_tile(painter, cells[1], theme, "DC", [_fmt(dc_w, " W"), _fmt(dc_a, " A", 1)], theme.secondary,
                         _icon_gear)

        pv_w = display_data.get("PV Power (W)")
        self._draw_tile(painter, cells[2], theme, "SOLAR", [_fmt(pv_w, " W")], theme.ok, _icon_sun)

    def _draw_tile(self, painter: QPainter, cell: QRectF, theme: QtTheme, label: str,
                   value_lines: List[str], accent: QColor, icon_fn) -> None:
        label_size = max(16, int(cell.height() * LABEL_SIZE_FRACTION))
        value_size = max(14, int(cell.height() * VALUE_SIZE_FRACTION))
        line_gap = value_size * 1.25
        icon_r = max(20, int(cell.height() * 0.11))

        total_h = icon_r * 2 + 10 + label_size * 1.3 + len(value_lines) * line_gap
        y = cell.center().y() - total_h / 2

        # Same icon glyph/color the flow diagram below uses for this same
        # source (GRID/DC/SOLAR), so the two sections visually echo each
        # other rather than the flow diagram being the only illustrated
        # part of the page.
        _draw_icon_badge(painter, theme, QPointF(cell.center().x(), y + icon_r), icon_r, accent, icon_fn)
        y += icon_r * 2 + 10

        font = tracked_font(self.font(), 2.2)
        font.setBold(True)
        font.setPixelSize(label_size)
        painter.setFont(font)
        painter.setPen(QPen(accent))
        painter.drawText(QRectF(cell.x(), y, cell.width(), label_size * 1.3),
                          Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)
        y += label_size * 1.5

        vfont = QFont(self.font())
        vfont.setPixelSize(value_size)
        for line in value_lines:
            draw_solid_text(painter, QRectF(cell.x(), y, cell.width(), line_gap),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line, vfont, theme.text)
            y += line_gap

    # -- section B: AC Load/Starter stack + power-flow diagram ------------

    def _draw_section_b(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        left_w = rect.width() * LEFT_B_WIDTH_FRACTION
        left_rect = QRectF(rect.x(), rect.y(), left_w, rect.height())
        right_rect = QRectF(rect.x() + left_w, rect.y(), rect.width() - left_w, rect.height())

        self._draw_ac_starter_stack(painter, left_rect, theme)
        self._draw_power_flow(painter, right_rect, theme)

    def _draw_ac_starter_stack(self, painter: QPainter, cell: QRectF, theme: QtTheme) -> None:
        label_size = max(16, int(cell.height() * LABEL_SIZE_FRACTION))
        value_size = max(14, int(cell.height() * VALUE_SIZE_FRACTION))

        ac_w = display_data.get("AC Loads (W)")
        starter_w = display_data.get("Battery0 Power (W)")
        volts = display_data.get("Battery0 Voltage (V)")
        amps = display_data.get("Battery0 Current (A)")

        volts_amps = f"{_fmt(volts, ' V', 1)}  {_fmt(amps, ' A', 1)}"

        # SOC%/TTG used to have a 4th row here too - now shown on the
        # power-flow diagram's BATTERY node instead (a ring + text line),
        # which is the section this page's real estate is better spent on.
        # Label rows carry an icon (same idea as section A's tiles) so this
        # stack isn't the one plain-text part of an otherwise illustrated
        # page.
        rows = [
            ("AC LOAD", True, _icon_plug), (_fmt(ac_w, " W"), False, None),
            ("STARTER", True, _icon_starter), (_fmt(starter_w, " W"), False, None),
            (volts_amps, False, None),
        ]
        line_h = cell.height() / len(rows)
        y = cell.y()
        icon_r = max(16, int(label_size * 0.6))
        for text, is_label, icon_fn in rows:
            size = label_size if is_label else value_size
            font = tracked_font(self.font(), 2.0 if is_label else 0.0)
            font.setPixelSize(size)
            row_rect = QRectF(cell.x(), y, cell.width(), line_h)
            if is_label:
                font.setBold(True)
                fm = QFontMetricsF(font)
                gap = 8.0
                group_w = icon_r * 2 + gap + fm.horizontalAdvance(text)
                group_x = cell.center().x() - group_w / 2
                icon_center = QPointF(group_x + icon_r, row_rect.center().y())
                _draw_icon_badge(painter, theme, icon_center, icon_r, theme.accent, icon_fn, glow=False)
                text_rect = QRectF(group_x + icon_r * 2 + gap, y, cell.right() - (group_x + icon_r * 2 + gap), line_h)
                painter.setFont(font)
                painter.setPen(QPen(theme.accent))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            else:
                draw_solid_text(painter, row_rect, Qt.AlignmentFlag.AlignCenter, text, font, theme.text)
            y += line_h

    def _draw_power_flow(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        c = rect.adjusted(10, 10, -10, -10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(c, 16, 16)

        bus_x = rect.center().x()
        bus_top = rect.y() + rect.height() * 0.12
        bus_bottom = rect.y() + rect.height() * 0.84
        painter.setPen(_pen(theme.accent, 5, round_cap=True))
        painter.drawLine(QPointF(bus_x, bus_top), QPointF(bus_x, bus_bottom))

        grid_status = display_data.get("Active input source")
        grid_w = (display_data.get("Grid (W)") if grid_status == 1 else 0.0) or 0.0
        dc_w = display_data.get("DC Power (W)") or 0.0
        pv_w = display_data.get("PV Power (W)") or 0.0
        ac_w = display_data.get("AC Loads (W)") or 0.0
        battery_w = display_data.get("Battery Power (W)")
        soc = display_data.get("Battery SOC (%)")
        ttg = display_data.get("Battery Time to Go (System)")
        if ttg is None:
            ttg = display_data.get("Battery Time to Go (Batt)")

        left_x = rect.x() + rect.width() * 0.13
        source_rows = [
            ("GRID", grid_w, theme.accent, _icon_grid),
            ("SOLAR", pv_w, theme.ok, _icon_sun),
            ("DC", dc_w, theme.secondary, _icon_gear),
        ]
        for i, (label, watts, color, icon_fn) in enumerate(source_rows):
            y = rect.y() + rect.height() * (0.20 + i * 0.28)
            self._draw_flow_node(painter, theme, (left_x, y), label, watts, " W", color, icon_fn, on_left=True)
            self._draw_flow_line(painter, (left_x + 40, y), (bus_x, y), color, watts)

        right_x = rect.right() - rect.width() * 0.15
        # AC LOAD sits higher (0.20, mirroring GRID's row on the left) and
        # BATTERY lower (0.78) than before - freeing enough vertical room
        # for the SOC/TTG title now drawn above the battery icon at
        # section-A title size, so it doesn't collide with AC LOAD's node.
        load_y = rect.y() + rect.height() * 0.20
        self._draw_flow_node(painter, theme, (right_x, load_y), "AC LOAD", ac_w, " W", theme.warn, _icon_plug,
                              on_left=False)
        self._draw_flow_line(painter, (bus_x, load_y), (right_x - 40, load_y), theme.warn, ac_w)

        batt_y = rect.y() + rect.height() * 0.78
        charging = battery_w is not None and battery_w >= 0
        batt_color = theme.ok if charging else theme.warn
        soc_str = None if soc is None else f"{soc:.0f}%"
        ttg_str = None if ttg is None else f"{ttg:.1f}h"
        soc_ttg_line = "  ·  ".join(s for s in (soc_str, ttg_str) if s) or None
        # SOC/TTG "belong" to the battery, so they're shown as a title
        # above its icon, sized the same as section A's GRID/DC/SOLAR
        # headings, rather than a small line beside the icon.
        title_size = max(16, int((self.height() // 2) * LABEL_SIZE_FRACTION))
        self._draw_flow_node(painter, theme, (right_x, batt_y), "BATTERY", battery_w, " W", batt_color,
                              _icon_battery_flow, on_left=False, ring_percent=soc,
                              top_label=soc_ttg_line, top_label_size=title_size)
        if battery_w is not None:
            if charging:
                self._draw_flow_line(painter, (bus_x, batt_y), (right_x - 40, batt_y), batt_color, battery_w)
            else:
                self._draw_flow_line(painter, (right_x - 40, batt_y), (bus_x, batt_y), batt_color, -battery_w)

    def _draw_flow_node(self, painter: QPainter, theme: QtTheme, pos: Tuple[float, float], label: str,
                        watts: Optional[float], suffix: str, color: QColor, icon_fn, on_left: bool,
                        ring_percent: Optional[float] = None,
                        top_label: Optional[str] = None, top_label_size: int = 20) -> None:
        x, y = pos
        icon_r = 34.0
        center = QPointF(x, y)

        _draw_node_glow(painter, center, icon_r, color)

        if ring_percent is not None:
            ring_r = icon_r + 9
            ring_rect = QRectF(x - ring_r, y - ring_r, ring_r * 2, ring_r * 2)
            painter.setPen(_pen(theme.panel_border, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ring_rect)
            pct = max(0.0, min(100.0, ring_percent))
            ring_color = theme.ok if pct > 25 else (theme.warn if pct > 10 else theme.danger)
            painter.setPen(_pen(ring_color, 3, round_cap=True))
            span_sixteenths = -int(pct / 100.0 * 360 * 16)
            painter.drawArc(ring_rect, 90 * 16, span_sixteenths)

        _draw_node_icon_circle(painter, theme, center, icon_r, color, icon_fn)

        # Top label (SOC%/TTG for BATTERY) sits centered above the icon,
        # title-sized to match section A's GRID/DC/SOLAR headings, since
        # it "belongs" to the battery graphic rather than being another
        # beside-icon text line.
        if top_label:
            tfont = tracked_font(self.font(), 1.5)
            tfont.setBold(True)
            tfont.setPixelSize(top_label_size)
            top_rect = QRectF(x - 100, y - icon_r - top_label_size * 1.3 - 8, 200, top_label_size * 1.3)
            painter.setPen(QPen(color))
            painter.setFont(tfont)
            painter.drawText(top_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, top_label)

        # Text sits beside the icon (like the original layout) rather than
        # above/below it - stacking label+icon+value vertically needs far
        # more height per node than 3 densely-packed source rows have to
        # give (tried that first). Label/value are staggered just enough
        # to clear the flow line's own thickness (up to 14px, see
        # _draw_flow_line) at this y, not the much taller icon.
        text_w = 190
        tx = (x + icon_r + 14) if on_left else (x - icon_r - 14 - text_w)
        align = Qt.AlignmentFlag.AlignLeft if on_left else Qt.AlignmentFlag.AlignRight

        font = tracked_font(self.font(), 1.2)
        font.setPixelSize(18)
        label_rect = QRectF(tx, y - 38, text_w, 22)
        draw_solid_text(painter, label_rect, align | Qt.AlignmentFlag.AlignBottom, label, font, theme.text_dim)

        vfont = QFont(self.font())
        vfont.setBold(True)
        vfont.setPixelSize(28)
        painter.setFont(vfont)
        painter.setPen(QPen(theme.text))
        value_rect = QRectF(tx, y + 14, text_w, 34)
        painter.drawText(value_rect, align | Qt.AlignmentFlag.AlignTop, _fmt(watts, suffix))

    def _draw_flow_line(self, painter: QPainter, p1: Tuple[float, float], p2: Tuple[float, float],
                        color: QColor, watts: Optional[float]) -> None:
        watts = abs(watts) if watts is not None else 0.0
        thickness = 3 + min(1.0, watts / FLOW_MAX_WATTS) * 11
        painter.setPen(_pen(color, thickness, round_cap=True))
        painter.drawLine(QPointF(*p1), QPointF(*p2))

        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head_len, head_w = 15, 10
        tip = QPointF(*p2)
        base_l = QPointF(p2[0] - ux * head_len + px * head_w, p2[1] - uy * head_len + py * head_w)
        base_r = QPointF(p2[0] - ux * head_len - px * head_w, p2[1] - uy * head_len - py * head_w)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, base_l, base_r]))


# -- node icons - shared by section A's tiles, the AC LOAD/STARTER stack, --
# -- and the power-flow diagram, via _draw_icon_badge() -------------------

def _icon_grid(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    cx, top, bottom = rect.center().x(), rect.top() + 3, rect.bottom() - 3
    painter.setPen(_pen(color, 2.5, round_cap=True))
    painter.drawLine(QPointF(cx, top), QPointF(cx, bottom))
    for frac, wfrac in ((0.25, 0.7), (0.55, 0.5)):
        y = top + (bottom - top) * frac
        half = rect.width() * wfrac / 2
        painter.drawLine(QPointF(cx - half, y), QPointF(cx + half, y))
        painter.drawLine(QPointF(cx - half, y), QPointF(cx, top))
        painter.drawLine(QPointF(cx + half, y), QPointF(cx, top))


def _icon_sun(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    r = rect.width() * 0.26
    painter.setPen(_pen(color, 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect.center(), r, r)
    ray_pen = _pen(color, 2.5, round_cap=True)
    painter.setPen(ray_pen)
    for deg in range(0, 360, 45):
        theta = math.radians(deg)
        p1 = rect.center() + QPointF(math.cos(theta) * (r + 4), math.sin(theta) * (r + 4))
        p2 = rect.center() + QPointF(math.cos(theta) * (r + 10), math.sin(theta) * (r + 10))
        painter.drawLine(p1, p2)


def _icon_gear(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    r = rect.width() * 0.28
    painter.setPen(_pen(color, 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect.center(), r, r)
    tooth_pen = _pen(color, 2.5, round_cap=True)
    painter.setPen(tooth_pen)
    for deg in range(0, 360, 45):
        theta = math.radians(deg)
        p1 = rect.center() + QPointF(math.cos(theta) * r, math.sin(theta) * r)
        p2 = rect.center() + QPointF(math.cos(theta) * (r + 5), math.sin(theta) * (r + 5))
        painter.drawLine(p1, p2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(rect.center(), max(1.0, r * 0.35), max(1.0, r * 0.35))


def _icon_plug(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    body = rect.adjusted(rect.width() * 0.25, rect.height() * 0.25, -rect.width() * 0.25, -rect.height() * 0.25)
    painter.setPen(_pen(color, 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 5, 5)
    prong_pen = _pen(color, 2.5, round_cap=True)
    painter.setPen(prong_pen)
    for dxfrac in (-0.2, 0.2):
        x = body.center().x() + dxfrac * body.width()
        painter.drawLine(QPointF(x, body.top() - 5), QPointF(x, body.top() + 3))


def _icon_battery_flow(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    body = rect.adjusted(rect.width() * 0.25, rect.height() * 0.2, -rect.width() * 0.25, -rect.height() * 0.2)
    nub_w = body.width() * 0.4
    nub = QRectF(body.center().x() - nub_w / 2, body.top() - body.height() * 0.14, nub_w, body.height() * 0.14 + 1)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(nub, 2, 2)
    painter.setPen(_pen(color, 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 5, 5)


def _icon_starter(painter: QPainter, rect: QRectF, theme: QtTheme, color: QColor) -> None:
    """Cranking/ignition bolt in a ring - distinct from the plain battery
    glyph (_icon_battery_flow) used for the house bank, since STARTER here
    is the separate starter battery."""
    r = rect.width() * 0.34
    painter.setPen(_pen(color, 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect.center(), r, r)

    cx, cy = rect.center().x(), rect.center().y()
    bw, bh = r * 0.95, r * 1.25
    bolt = QPolygonF([
        QPointF(cx + bw * 0.12, cy - bh * 0.55),
        QPointF(cx - bw * 0.32, cy + bh * 0.05),
        QPointF(cx - bw * 0.04, cy + bh * 0.05),
        QPointF(cx - bw * 0.16, cy + bh * 0.55),
        QPointF(cx + bw * 0.32, cy - bh * 0.08),
        QPointF(cx + bw * 0.04, cy - bh * 0.08),
    ])
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(bolt)
