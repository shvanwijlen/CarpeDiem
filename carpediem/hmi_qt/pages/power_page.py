"""P - Power, StartrekGraphical (Qt) version of hmi/pages/power_page.py -
see that module's docstring for the full layout spec, the None/"none"
convention, and the power-flow diagram's reasoning. Drawn as one custom-
painted QWidget (like RadarView/AisPage/WeatherPage) rather than composed
of many child widgets.

Layout: a narrow left column stacks GRID/DC/SOLAR/AC LOAD/STARTER as
compact icon+label+value rows, full page height. The rest of the width is
one tall right-hand panel: a standalone SOC/TTG readout on top, and the
power-flow diagram (bus + flow nodes, each with a soft additive glow -
same QRadialGradient pattern as widgets.py's Led/CompassRose) below it.
Battery's charge ring stays on its flow node, but the SOC%/TTG numbers
themselves live in the standalone readout, not on the node, so they can
be shown at prominent size instead of squeezed beside/above an icon.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from carpediem.display_data import display_data
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import draw_solid_text, tracked_font

LEFT_COL_WIDTH_FRACTION = 0.27
SOC_BOX_HEIGHT_FRACTION = 0.22
NONE_TEXT = "none"

# Fractions of the *full page height* (unlike the old section-based
# layout, the left column and its rows now span the whole page).
LEFT_LABEL_SIZE_FRACTION = 0.055
LEFT_VALUE_SIZE_FRACTION = 0.062

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
    Shared by the power-flow nodes and the left column's icon+label rows
    so the whole page reads as one visual language instead of the flow
    diagram being the only part with icons."""
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

        left_w = w * LEFT_COL_WIDTH_FRACTION
        left_rect = QRectF(0, 0, left_w, h)

        soc_box_h = h * SOC_BOX_HEIGHT_FRACTION
        soc_rect = QRectF(left_w, 0, w - left_w, soc_box_h)
        graph_rect = QRectF(left_w, soc_box_h, w - left_w, h - soc_box_h)

        self._draw_left_column(painter, left_rect, theme)
        self._draw_soc_ttg_box(painter, soc_rect, theme)
        self._draw_power_flow(painter, graph_rect, theme)

    # -- left column: Grid / DC / Solar / AC Load / Starter, stacked ------

    def _draw_left_column(self, painter: QPainter, cell: QRectF, theme: QtTheme) -> None:
        label_size = max(16, int(cell.height() * LEFT_LABEL_SIZE_FRACTION))
        value_size = max(14, int(cell.height() * LEFT_VALUE_SIZE_FRACTION))
        label_h = label_size * 1.15
        value_h = value_size * 1.15
        group_gap = 10.0

        grid_status = display_data.get("Active input source")
        grid_w = display_data.get("Grid (W)")
        grid_value = "-" if grid_status != 1 else _fmt(grid_w, " W")
        dc_w = display_data.get("DC Power (W)")
        dc_a = display_data.get("DC Current (A)")
        pv_w = display_data.get("PV Power (W)")
        ac_w = display_data.get("AC Loads (W)")
        starter_w = display_data.get("Battery0 Power (W)")
        volts = display_data.get("Battery0 Voltage (V)")
        amps = display_data.get("Battery0 Current (A)")
        volts_amps = f"{_fmt(volts, ' V', 1)}  {_fmt(amps, ' A', 1)}"

        # Each group is a label row (icon + name) followed by its value
        # line(s) - same icon+label+value language the old section-A tiles
        # and AC LOAD/STARTER stack each used separately, now unified into
        # one vertical stack spanning the full page height.
        groups: List[Tuple[str, object, QColor, List[str]]] = [
            ("GRID", _icon_grid, theme.accent, [grid_value]),
            ("DC", _icon_gear, theme.secondary, [_fmt(dc_w, " W"), _fmt(dc_a, " A", 1)]),
            ("SOLAR", _icon_sun, theme.ok, [_fmt(pv_w, " W")]),
            ("AC LOAD", _icon_plug, theme.accent, [_fmt(ac_w, " W")]),
            ("STARTER", _icon_starter, theme.accent, [_fmt(starter_w, " W"), volts_amps]),
        ]

        total_h = sum(label_h + len(values) * value_h for _, _, _, values in groups) \
            + group_gap * (len(groups) - 1)
        y = cell.y() + max(6.0, (cell.height() - total_h) / 2)
        icon_r = max(14, int(label_size * 0.6))

        label_font = tracked_font(self.font(), 2.0)
        label_font.setBold(True)
        label_font.setPixelSize(label_size)
        value_font = QFont(self.font())
        value_font.setPixelSize(value_size)

        # Left-aligned instead of centered: icons sit in a fixed left
        # column, with labels and values both starting at the same text
        # x just to the right of it.
        left_margin = 16.0
        gap = 8.0
        icon_x = cell.x() + left_margin + icon_r
        text_x = cell.x() + left_margin + icon_r * 2 + gap

        for label, icon_fn, accent, values in groups:
            label_rect = QRectF(cell.x(), y, cell.width(), label_h)
            icon_center = QPointF(icon_x, label_rect.center().y())
            _draw_icon_badge(painter, theme, icon_center, icon_r, accent, icon_fn, glow=False)
            text_rect = QRectF(text_x, y, cell.right() - text_x, label_h)
            painter.setFont(label_font)
            painter.setPen(QPen(accent))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            y += label_h

            for value in values:
                value_rect = QRectF(text_x, y, cell.right() - text_x, value_h)
                draw_solid_text(painter, value_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 value, value_font, theme.text)
                y += value_h
            y += group_gap

    # -- standalone SOC/TTG readout, top of the right-hand panel ----------

    def _draw_soc_ttg_box(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        soc = display_data.get("Battery SOC (%)")
        ttg = display_data.get("Battery Time to Go (System)")
        if ttg is None:
            ttg = display_data.get("Battery Time to Go (Batt)")
        battery_w = display_data.get("Battery Power (W)")
        charging = battery_w is not None and battery_w >= 0
        color = theme.ok if charging else theme.warn

        stats = [("SOC", _fmt(soc, "%")), ("TTG", _fmt(ttg, "h", 1))]
        title_size = max(18, int(rect.height() * 0.26))
        value_size = max(28, int(rect.height() * 0.48))

        title_font = tracked_font(self.font(), 2.2)
        title_font.setBold(True)
        title_font.setPixelSize(title_size)
        value_font = QFont(self.font())
        value_font.setBold(True)
        value_font.setPixelSize(value_size)

        col_w = rect.width() / 2
        for i, (title, value) in enumerate(stats):
            col = QRectF(rect.x() + i * col_w, rect.y(), col_w, rect.height())
            painter.setFont(title_font)
            painter.setPen(QPen(theme.text_dim))
            title_rect = QRectF(col.x(), col.y(), col.width(), title_size * 1.4)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, title)
            value_rect = QRectF(col.x(), title_rect.bottom(), col.width(), col.bottom() - title_rect.bottom())
            draw_solid_text(painter, value_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                             value, value_font, color)

    def _draw_power_flow(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        c = rect.adjusted(10, 10, -10, -10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(c, 16, 16)

        bus_width = 5
        bus_half = bus_width / 2
        bus_x = rect.center().x()
        bus_top = rect.y() + rect.height() * 0.12
        bus_bottom = rect.y() + rect.height() * 0.84
        painter.setPen(_pen(theme.accent, bus_width, round_cap=True))
        painter.drawLine(QPointF(bus_x, bus_top), QPointF(bus_x, bus_bottom))

        grid_status = display_data.get("Active input source")
        grid_w = (display_data.get("Grid (W)") if grid_status == 1 else 0.0) or 0.0
        dc_w = display_data.get("DC Power (W)") or 0.0
        pv_w = display_data.get("PV Power (W)") or 0.0
        ac_w = display_data.get("AC Loads (W)") or 0.0
        battery_w = display_data.get("Battery Power (W)")
        soc = display_data.get("Battery SOC (%)")  # still drives the charge ring on BATTERY's node

        left_x = rect.x() + rect.width() * 0.13
        source_rows = [
            ("GRID", grid_w, theme.accent, _icon_grid),
            ("SOLAR", pv_w, theme.ok, _icon_sun),
            ("DC", dc_w, theme.secondary, _icon_gear),
        ]
        for i, (label, watts, color, icon_fn) in enumerate(source_rows):
            # Wider spacing (was 0.20 + i*0.28) - the bigger icons/fonts
            # added last round outgrew that spacing, causing GRID/SOLAR/DC
            # to overlap each other.
            y = rect.y() + rect.height() * (0.17 + i * 0.31)
            self._draw_flow_node(painter, theme, (left_x, y), label, watts, " W", color, icon_fn, on_left=True)
            # DC can go negative (DC loads pulling from the bus rather
            # than feeding it) - reverse the arrow toward the source in
            # that case, same as BATTERY's arrow does when discharging.
            # Endpoints stop at the bus's edge (bus_x - bus_half), not its
            # centerline, so the arrow touches the bus instead of cutting
            # into its stroke.
            if watts < 0:
                self._draw_flow_line(painter, (bus_x - bus_half, y), (left_x + 40, y), color, watts)
            else:
                self._draw_flow_line(painter, (left_x + 40, y), (bus_x - bus_half, y), color, watts)

        right_x = rect.right() - rect.width() * 0.15
        # AC LOAD sits higher (0.20, mirroring GRID's row on the left) and
        # BATTERY lower (0.78) so the two nodes' text/glow don't collide.
        load_y = rect.y() + rect.height() * 0.20
        self._draw_flow_node(painter, theme, (right_x, load_y), "AC LOAD", ac_w, " W", theme.warn, _icon_plug,
                              on_left=False)
        self._draw_flow_line(painter, (bus_x + bus_half, load_y), (right_x - 40, load_y), theme.warn, ac_w)

        batt_y = rect.y() + rect.height() * 0.78
        charging = battery_w is not None and battery_w >= 0
        batt_color = theme.ok if charging else theme.warn
        # SOC%/TTG themselves are shown in the standalone readout above
        # this graph now, not on the node - the ring here is just the
        # at-a-glance charge indicator.
        self._draw_flow_node(painter, theme, (right_x, batt_y), "BATTERY", battery_w, " W", batt_color,
                              _icon_battery_flow, on_left=False, ring_percent=soc)
        # BATTERY has a charge ring around its icon (radius icon_r + 9,
        # see _draw_flow_node) that AC LOAD doesn't - stopping at the same
        # "- 40" offset used for AC LOAD left the arrow tip landing inside
        # that ring instead of outside it, so BATTERY gets a wider "- 51"
        # clearance instead.
        if battery_w is not None:
            if charging:
                self._draw_flow_line(painter, (bus_x + bus_half, batt_y), (right_x - 51, batt_y),
                                      batt_color, battery_w)
            else:
                self._draw_flow_line(painter, (right_x - 51, batt_y), (bus_x + bus_half, batt_y),
                                      batt_color, -battery_w)

    def _draw_flow_node(self, painter: QPainter, theme: QtTheme, pos: Tuple[float, float], label: str,
                        watts: Optional[float], suffix: str, color: QColor, icon_fn, on_left: bool,
                        ring_percent: Optional[float] = None) -> None:
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
        label_rect = QRectF(tx, y - 32, text_w, 20)
        draw_solid_text(painter, label_rect, align | Qt.AlignmentFlag.AlignBottom, label, font, theme.text_dim)

        vfont = QFont(self.font())
        vfont.setBold(True)
        vfont.setPixelSize(28)
        painter.setFont(vfont)
        painter.setPen(QPen(theme.text))
        value_rect = QRectF(tx, y + 8, text_w, 34)
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


# -- node icons - shared by the left column's rows and the power-flow -----
# -- diagram's nodes, via _draw_icon_badge() -------------------------------

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
