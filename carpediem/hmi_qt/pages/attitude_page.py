"""A - Attitude, StartrekGraphical (Qt) page: how the boat rolls and pitches,
from the BNO055 (sensors/bno055_sensor.py) via the Roll / Pitch display_data
fields (degrees; roll positive = starboard side down, pitch positive = bow up).

Two gauges side by side, each a hull silhouette that tilts against a fixed
angle scale and waterline: ROLL seen from astern (starboard on the right, so
heeling to starboard turns the hull clockwise) and PITCH seen from the
starboard side with the bow to the right (bow up turns it counter-clockwise).
A pointer on the scale takes the severity colour (green/amber/red - the
thresholds below are rough "comfortable / uncomfortable / alarming" values for
a displacement motor yacht, not a safety limit), and the big readout beside
each gauge names the side ("4.2 STBD", "BOW UP"). Underneath, a 60 s trace of
both angles with the extremes of that window, which is what tells a steady
heel (wind, one-sided load) from a rolling swell.

Roll/Pitch are None when there's no sensor or no valid reading (never a stale
value - see bno055_sensor.py): the hulls then sit level and dim, the readouts
say "--" and the header says NO SENSOR. The 60 s history is collected by this
widget's own timer, so it keeps filling while another page is showing.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Deque, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from carpediem.display_data import display_data
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import draw_solid_text, tracked_font

HISTORY_SECONDS = 60.0
SAMPLE_INTERVAL_MS = 200

ROLL_WARN_DEG, ROLL_DANGER_DEG = 12.0, 22.0
PITCH_WARN_DEG, PITCH_DANGER_DEG = 6.0, 12.0

ROLL_SCALE_DEG, PITCH_SCALE_DEG = 30, 20   # half-span of each gauge's scale
CHART_SPANS = (10, 20, 30, 40, 60, 90)      # the trace autoscales to the smallest of these that fits the last 60 s
NONE_TEXT = "--"

Sample = Tuple[float, Optional[float], Optional[float]]  # (monotonic time, roll, pitch)


def _pen(color: QColor, width: float, round_cap: bool = True) -> QPen:
    pen = QPen(color, width)
    if round_cap:
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def severity_color(theme: QtTheme, value: Optional[float], warn: float, danger: float) -> QColor:
    if value is None:
        return theme.neutral
    a = abs(value)
    return theme.danger if a >= danger else theme.warn if a >= warn else theme.ok


# -- hull silhouettes, in unit coordinates (x right, y down, waterline y=0) ---

def _rear_hull() -> Tuple[QPainterPath, QPainterPath, QPainterPath]:
    hull = QPainterPath()
    hull.moveTo(-0.95, -0.25)
    hull.lineTo(0.95, -0.25)
    hull.lineTo(0.62, 0.30)
    hull.quadTo(0.0, 0.62, -0.62, 0.30)
    hull.closeSubpath()
    cabin = QPainterPath()
    cabin.moveTo(-0.62, -0.25)
    cabin.lineTo(-0.46, -0.72)
    cabin.lineTo(0.46, -0.72)
    cabin.lineTo(0.62, -0.25)
    cabin.closeSubpath()
    mast = QPainterPath()
    mast.moveTo(0.0, -0.72)
    mast.lineTo(0.0, -1.0)
    return hull, cabin, mast


def _side_hull() -> Tuple[QPainterPath, QPainterPath, QPainterPath]:
    hull = QPainterPath()
    hull.moveTo(-1.0, -0.22)
    hull.lineTo(1.05, -0.38)
    hull.lineTo(0.80, 0.30)
    hull.lineTo(-0.85, 0.30)
    hull.closeSubpath()
    cabin = QPainterPath()
    cabin.moveTo(-0.55, -0.27)
    cabin.lineTo(-0.55, -0.62)
    cabin.lineTo(0.10, -0.62)
    cabin.lineTo(0.40, -0.32)
    cabin.closeSubpath()
    mast = QPainterPath()
    mast.moveTo(-0.15, -0.62)
    mast.lineTo(-0.15, -0.98)
    return hull, cabin, mast


class AttitudePage(QWidget):
    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._history: Deque[Sample] = deque(maxlen=int(HISTORY_SECONDS * 1000 / SAMPLE_INTERVAL_MS) + 20)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sample)
        self._timer.start(SAMPLE_INTERVAL_MS)

    def _sample(self, now: Optional[float] = None) -> None:
        self._history.append((time.monotonic() if now is None else now,
                              display_data.get("Roll"), display_data.get("Pitch")))

    def refresh(self) -> None:
        self.update()

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = float(self.width()), float(self.height())
        margin, gap, header_h = 12.0, 10.0, 30.0

        roll, pitch = display_data.get("Roll"), display_data.get("Pitch")

        self._draw_header(painter, QRectF(margin, margin * 0.5, w - margin * 2, header_h), theme, roll)

        body_top = margin * 0.5 + header_h + 4
        body_h = h - body_top - margin
        gauges_h = (body_h - gap) * 0.62
        gauge_w = (w - margin * 2 - gap) / 2
        roll_rect = QRectF(margin, body_top, gauge_w, gauges_h)
        pitch_rect = QRectF(margin + gauge_w + gap, body_top, gauge_w, gauges_h)
        chart_rect = QRectF(margin, body_top + gauges_h + gap, w - margin * 2, body_h - gauges_h - gap)

        self._draw_gauge(painter, theme, roll_rect, "ROLL", "VIEW FROM ASTERN", roll, kind="roll")
        self._draw_gauge(painter, theme, pitch_rect, "PITCH", "VIEW FROM STARBOARD", pitch, kind="pitch")
        self._draw_chart(painter, theme, chart_rect)

    def _draw_header(self, painter: QPainter, rect: QRectF, theme: QtTheme, roll: Optional[float]) -> None:
        font = tracked_font(self.font(), 2.0)
        font.setBold(True)
        font.setPixelSize(15)
        painter.setFont(font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "BOAT ATTITUDE")

        if roll is None:
            text, color = "NO SENSOR", theme.warn
        else:
            cal = display_data.get("ImuCalibration")
            if cal is None:
                text, color = "IMU", theme.text_dim
            else:
                text = f"IMU CAL {int(cal)}/3" + ("" if cal >= 3 else "  CALIBRATING")
                color = theme.ok if cal >= 3 else theme.warn
        painter.setPen(QPen(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_panel(self, painter: QPainter, theme: QtTheme, rect: QRectF) -> None:
        painter.setPen(_pen(theme.panel_border, 1, round_cap=False))
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(rect, 12, 12)

    def _draw_caption(self, painter: QPainter, theme: QtTheme, rect: QRectF, title: str, sub: str) -> None:
        font = tracked_font(self.font(), 2.0)
        font.setBold(True)
        font.setPixelSize(16)
        painter.setFont(font)
        painter.setPen(QPen(theme.secondary))
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        title_w = QFontMetricsF(font).horizontalAdvance(title)
        sub_font = tracked_font(self.font(), 1.2)
        sub_font.setPixelSize(11)
        painter.setFont(sub_font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(rect.left() + title_w + 14, rect.top(), rect.width() - title_w - 14, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)

    # -- one gauge (roll or pitch) --------------------------------------------

    def _draw_gauge(self, painter: QPainter, theme: QtTheme, rect: QRectF, title: str, sub: str,
                    value: Optional[float], kind: str) -> None:
        self._draw_panel(painter, theme, rect)
        inner = rect.adjusted(16, 10, -16, -10)
        self._draw_caption(painter, theme, QRectF(inner.left(), inner.top(), inner.width(), 22), title, sub)

        content = QRectF(inner.left(), inner.top() + 26, inner.width(), inner.height() - 26)
        gauge_area = QRectF(content.left(), content.top(), content.width() * 0.62, content.height())
        readout = QRectF(gauge_area.right(), content.top(), content.right() - gauge_area.right(), content.height())

        is_roll = kind == "roll"
        warn, danger = (ROLL_WARN_DEG, ROLL_DANGER_DEG) if is_roll else (PITCH_WARN_DEG, PITCH_DANGER_DEG)
        scale_span = ROLL_SCALE_DEG if is_roll else PITCH_SCALE_DEG
        color = severity_color(theme, value, warn, danger)

        radius = max(40.0, min(gauge_area.width() * 0.45, gauge_area.height() / 1.5))
        cx = gauge_area.center().x() - (0 if is_roll else radius * 0.12)
        cy = gauge_area.top() + radius * 1.12 if is_roll else gauge_area.center().y()
        center = QPointF(cx, cy)

        self._draw_scale(painter, theme, center, radius, scale_span, value, color, is_roll)

        # World waterline (fixed) - the hull tilts against it.
        half = radius * 0.92
        waterline_y = cy
        painter.setPen(QPen(_alpha(theme.secondary, 170), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(cx - half, waterline_y), QPointF(cx + half, waterline_y))

        angle = 0.0 if value is None else max(-scale_span * 1.2, min(scale_span * 1.2, value))
        hull, cabin, mast = _rear_hull() if is_roll else _side_hull()
        t = QTransform()
        t.translate(cx, cy)
        t.rotate(angle if is_roll else -angle)  # +roll = clockwise; +pitch (bow up, bow on the right) = counter-clockwise
        t.scale(radius * 0.62, radius * 0.62)
        outline = theme.accent if value is not None else theme.neutral
        fill = QLinearGradient(QPointF(cx, cy - radius * 0.6), QPointF(cx, cy + radius * 0.4))
        fill.setColorAt(0.0, theme.panel_bg_hi.lighter(125))
        fill.setColorAt(1.0, theme.panel_bg_hi)
        painter.setPen(_pen(outline, 2.4))
        painter.setBrush(fill)
        painter.drawPath(t.map(cabin))
        painter.drawPath(t.map(hull))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(t.map(mast))
        if is_roll:  # navigation lights: red port (left), green starboard (right) seen from astern
            for x, c in ((-0.88, theme.danger), (0.88, theme.ok)):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(c if value is not None else theme.neutral)
                painter.drawEllipse(t.map(QPointF(x, -0.25)), 4.5, 4.5)

        # Water: a translucent band below the fixed waterline tints the submerged part of the hull.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_alpha(theme.secondary, 42))
        painter.drawRect(QRectF(cx - half, waterline_y, half * 2, radius * 0.5))

        self._draw_readout(painter, theme, readout, value, color, is_roll)

    def _draw_scale(self, painter: QPainter, theme: QtTheme, center: QPointF, radius: float, span: int,
                    value: Optional[float], color: QColor, is_roll: bool) -> None:
        """Fixed arc with ticks every 5 degrees and a pointer at `value`. Angles
        are measured clockwise from straight up on screen; roll's scale is
        centred on "up", pitch's on "right" (the bow) with positive values
        counter-clockwise (bow up)."""
        centre_deg, sign = (0.0, 1.0) if is_roll else (90.0, -1.0)

        def point(value_deg: float, r: float) -> QPointF:
            a = math.radians(centre_deg + sign * value_deg)
            return QPointF(center.x() + r * math.sin(a), center.y() - r * math.cos(a))

        arc = QPainterPath(point(-span, radius))
        for i in range(-span + 1, span + 1):
            arc.lineTo(point(i, radius))
        painter.setPen(_pen(theme.panel_border, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(arc)

        label_font = tracked_font(self.font(), 0.5)
        label_font.setPixelSize(12)
        painter.setFont(label_font)
        for v in range(-span, span + 1, 5):
            major = v % 10 == 0
            tick_in = radius * (0.88 if major else 0.94)
            painter.setPen(_pen(theme.accent if v == 0 else theme.text_dim, 2.0 if major else 1.0))
            painter.drawLine(point(v, radius), point(v, tick_in))
            if major and v != 0:
                lp = point(v, radius * 0.80)
                painter.setPen(QPen(theme.text_dim))
                painter.drawText(QRectF(lp.x() - 14, lp.y() - 8, 28, 16), Qt.AlignmentFlag.AlignCenter, str(abs(v)))

        if value is not None:
            v = max(-span * 1.1, min(span * 1.1, value))
            spread_deg = 2.6
            path = QPainterPath(point(v, radius * 0.90))
            path.lineTo(point(v + spread_deg, radius * 1.09))
            path.lineTo(point(v - spread_deg, radius * 1.09))
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path)

    def _draw_readout(self, painter: QPainter, theme: QtTheme, rect: QRectF, value: Optional[float],
                      color: QColor, is_roll: bool) -> None:
        if value is None:
            number, word = NONE_TEXT, ""
        else:
            number = f"{abs(value):.1f}°"
            if abs(value) < 0.05:
                word = "LEVEL"
            elif is_roll:
                word = "STARBOARD" if value > 0 else "PORT"
            else:
                word = "BOW UP" if value > 0 else "BOW DOWN"

        big = tracked_font(self.font(), 1.0)
        big.setBold(True)
        size = max(28, min(64, int(rect.width() * 0.34)))
        big.setPixelSize(size)
        while size > 20 and QFontMetricsF(big).horizontalAdvance(number) > rect.width() * 0.92:  # "13.5°" must still fit
            size -= 2
            big.setPixelSize(size)
        draw_solid_text(painter, QRectF(rect.left(), rect.center().y() - big.pixelSize() * 0.9, rect.width(),
                                        big.pixelSize() * 1.2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                        number, big, theme.text if value is None or color == theme.ok else color)
        small = tracked_font(self.font(), 2.0)
        small.setBold(True)
        small.setPixelSize(max(12, min(20, int(rect.width() * 0.105))))
        painter.setFont(small)
        painter.setPen(QPen(color if value is not None else theme.text_dim))
        painter.drawText(QRectF(rect.left(), rect.center().y() + big.pixelSize() * 0.35, rect.width(), small.pixelSize() * 1.6),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, word)

    # -- 60 s trace --------------------------------------------------------------

    def _draw_chart(self, painter: QPainter, theme: QtTheme, rect: QRectF) -> None:
        self._draw_panel(painter, theme, rect)
        inner = rect.adjusted(14, 8, -14, -8)

        now = time.monotonic()
        t0 = now - HISTORY_SECONDS
        window = [s for s in self._history if s[0] >= t0]
        rolls = [s[1] for s in window if s[1] is not None]
        pitches = [s[2] for s in window if s[2] is not None]
        peak = max([abs(v) for v in rolls + pitches] + [0.0])
        span = next((s for s in CHART_SPANS if s >= peak), CHART_SPANS[-1])  # round numbers, so half-span labels are too

        # Header: window length, then one legend entry per trace with that window's extremes.
        font = tracked_font(self.font(), 1.5)
        font.setBold(True)
        font.setPixelSize(13)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        head = QRectF(inner.left(), inner.top(), inner.width(), 18)
        painter.setPen(QPen(theme.text_dim))
        title = f"LAST {int(HISTORY_SECONDS)} S"
        painter.drawText(head, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        x = head.left() + fm.horizontalAdvance(title) + 28
        for name, values, color in (("ROLL", rolls, theme.secondary), ("PITCH", pitches, theme.tertiary)):
            rng = f"{min(values):+.1f} … {max(values):+.1f}°" if values else NONE_TEXT
            text = f"{name}  {rng}"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x + 5, head.center().y()), 5, 5)
            painter.setPen(QPen(color))
            painter.drawText(QRectF(x + 16, head.top(), fm.horizontalAdvance(text) + 4, head.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            x += 16 + fm.horizontalAdvance(text) + 30

        plot = QRectF(inner.left() + 44, inner.top() + 24, inner.width() - 44, inner.height() - 24)
        if plot.height() < 20:
            return

        def y_of(v: float) -> float:
            return plot.center().y() - v / span * plot.height() / 2

        label_font = tracked_font(self.font(), 0.3)
        label_font.setPixelSize(11)
        painter.setFont(label_font)
        for v in (-span, -span // 2, 0, span // 2, span):
            y = y_of(v)
            painter.setPen(QPen(theme.accent_dim if v == 0 else _alpha(theme.panel_border, 140), 1.2 if v == 0 else 1.0))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(QRectF(inner.left(), y - 8, 40, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             "0" if v == 0 else f"{v:+d}")

        for index, color in ((1, theme.secondary), (2, theme.tertiary)):
            path = QPainterPath()
            pen_down = False
            for sample in window:
                v = sample[index]
                if v is None:
                    pen_down = False
                    continue
                p = QPointF(plot.left() + (sample[0] - t0) / HISTORY_SECONDS * plot.width(),
                            y_of(max(-span, min(span, v))))
                if pen_down:
                    path.lineTo(p)
                else:
                    path.moveTo(p)
                    pen_down = True
            painter.setPen(_pen(color, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
