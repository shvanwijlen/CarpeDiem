"""Custom-painted Qt widgets - the StartrekGraphical equivalents of
hmi/widgets.py's pygame drawing primitives. Real anti-aliasing
(QPainter.Antialiasing), real gradients (QLinearGradient/QRadialGradient)
and real glow (QGraphicsDropShadowEffect) instead of the pygame version's
manual multi-layer-alpha-circle approximation.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget

from carpediem.hmi_qt.theme import QtTheme


def apply_glow(widget: QWidget, color: QColor, radius: int = 24, alpha: int = 200) -> None:
    """Soft blurred halo behind a whole widget - Qt's built-in drop-shadow
    effect used with zero offset, which is exactly a glow."""
    effect = QGraphicsDropShadowEffect(widget)
    glow_color = QColor(color)
    glow_color.setAlpha(alpha)
    effect.setColor(glow_color)
    effect.setBlurRadius(radius)
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)


def tracked_font(base: QFont, spacing_px: float = 1.5) -> QFont:
    f = QFont(base)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing_px)
    return f


class BatteryGauge(QWidget):
    """Vertical battery glyph, filled bottom-up by percent - used both as
    the big SOC gauge and (smaller, no label) as the house-battery icon."""

    def __init__(self, theme: QtTheme, show_label: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._percent: Optional[float] = None
        self._show_label = show_label

    def set_percent(self, percent: Optional[float]) -> None:
        self._percent = percent
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        theme = self._theme

        body = QRectF(w * 0.12, h * 0.10, w * 0.76, h * 0.84)
        nub = QRectF(0, 0, body.width() * 0.36, h * 0.08)
        nub.moveCenter(QPointF(body.center().x(), body.top() + 1))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(theme.panel_border))
        painter.drawRoundedRect(nub, 3, 3)
        painter.setBrush(QBrush(theme.bg))
        radius = min(body.width(), body.height()) * 0.12
        painter.drawRoundedRect(body, radius, radius)

        pct = 0.0 if self._percent is None else max(0.0, min(100.0, self._percent))
        if pct > 0:
            fill_color = theme.ok if pct > 25 else (theme.warn if pct > 10 else theme.danger)
            fill_h = (body.height() - 6) * (pct / 100.0)
            fill_rect = QRectF(body.x() + 3, body.bottom() - 3 - fill_h, body.width() - 6, fill_h)
            grad = QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
            grad.setColorAt(0.0, fill_color.lighter(140))
            grad.setColorAt(1.0, fill_color)
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(fill_rect, radius * 0.8, radius * 0.8)

        painter.setPen(QPen(theme.accent_dim, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body, radius, radius)

        if self._show_label:
            label = "--" if self._percent is None else f"{pct:.0f}%"
            painter.setPen(QPen(theme.text))
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(max(12, int(w * 0.22)))
            painter.setFont(font)
            painter.drawText(body, Qt.AlignmentFlag.AlignCenter, label)


class CompassRose(QWidget):
    """North-up compass ring with course/speed text and up to 3 colored
    rim markers (own course, wind-recalibrated, wind-as-experienced)."""

    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._course: Optional[float] = None
        self._speed: Optional[float] = None
        self._markers: List[Tuple[float, QColor]] = []

    def set_values(self, course: Optional[float], speed: Optional[float], markers: Sequence[Tuple[float, QColor]]) -> None:
        self._course = course
        self._speed = speed
        self._markers = list(markers)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        side = min(self.width(), self.height())
        radius = side * 0.42
        center = QPointF(self.width() / 2, self.height() / 2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(theme.panel_bg))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QPen(theme.secondary, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)

        for deg in range(0, 360, 30):
            theta = math.radians(deg)
            outer = center + QPointF(math.sin(theta) * radius, -math.cos(theta) * radius)
            inner = center + QPointF(math.sin(theta) * (radius - 8), -math.cos(theta) * (radius - 8))
            painter.setPen(QPen(theme.text_dim, 1.4))
            painter.drawLine(inner, outer)

        for deg, color in self._markers:
            theta = math.radians(deg)
            mx = center.x() + math.sin(theta) * (radius - 3)
            my = center.y() - math.cos(theta) * (radius - 3)
            painter.save()
            painter.translate(mx, my)
            painter.rotate(deg)
            glow = QRadialGradient(0, 0, 12)
            glow_color = QColor(color)
            glow_color.setAlpha(140)
            glow.setColorAt(0.0, glow_color)
            glow_color.setAlpha(0)
            glow.setColorAt(1.0, glow_color)
            painter.setBrush(QBrush(glow))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(0, 0), 12, 12)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(-8, -4, 16, 8), 4, 4)
            painter.restore()

        course_str = f"{self._course:.0f}°" if self._course is not None else "--"
        speed_str = f"{self._speed:.1f}" if self._speed is not None else "--"

        big = QFont(self.font())
        big.setBold(True)
        big.setPixelSize(max(10, int(radius * 0.48)))
        painter.setFont(big)
        painter.setPen(QPen(theme.secondary))
        painter.drawText(QRectF(center.x() - radius, center.y() - radius * 0.7, radius * 2, radius * 0.5),
                          Qt.AlignmentFlag.AlignCenter, course_str)

        painter.setPen(QPen(theme.accent))
        painter.drawText(QRectF(center.x() - radius, center.y() - radius * 0.05, radius * 2, radius * 0.6),
                          Qt.AlignmentFlag.AlignCenter, speed_str)

        small = QFont(self.font())
        small.setPixelSize(max(8, int(radius * 0.15)))
        painter.setFont(small)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(center.x() - radius, center.y() + radius * 0.55, radius * 2, radius * 0.3),
                          Qt.AlignmentFlag.AlignCenter, "km/h")


class Led(QWidget):
    """Small round status indicator. Two ways to drive it:
    - set_state(True/False/None): binary on(green)/off(red)/unknown(hollow
      grey) - the 7 subsystem indicators.
    - set_state("ok"/"warn"/"crit"): 3-state green/orange/red - the SYS
      (CPU/memory/disk) indicator, see sysmetrics_monitor.py. None still
      means "no reading yet" (hollow grey) in this mode too.
    Glows in whichever color it's showing, except the hollow/unknown state.
    """

    _STATUS_COLORS = {"ok": "ok", "warn": "warn", "crit": "danger"}

    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._state: Optional[bool | str] = None  # None = unknown

    def set_state(self, state: Optional[bool | str]) -> None:
        if state == self._state:
            return
        self._state = state
        self.update()

    def _resolve_color(self) -> Optional[QColor]:
        theme = self._theme
        if self._state is None:
            return None
        if isinstance(self._state, str):
            attr = self._STATUS_COLORS.get(self._state)
            return getattr(theme, attr) if attr else None
        return theme.ok if self._state else theme.danger

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        r = min(self.width(), self.height()) / 2 - 1
        center = QPointF(self.width() / 2, self.height() / 2)

        color = self._resolve_color()
        if color is None:
            painter.setPen(QPen(theme.neutral, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, r, r)
            return

        # Clamped to the widget's own half-size: a gradient radius bigger
        # than that gets hard-clipped at the widget edge before its alpha
        # reaches 0, leaving a visible dim square - same bug fixed in
        # icons.py's AlternatorIcon.
        glow_r = min(r * 2.2, self.width() / 2, self.height() / 2)
        glow = QRadialGradient(center, glow_r)
        c1 = QColor(color)
        c1.setAlpha(160)
        glow.setColorAt(0.0, c1)
        c2 = QColor(color)
        c2.setAlpha(0)
        glow.setColorAt(1.0, c2)
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, r * 2.2, r * 2.2)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(theme.panel_border, 1))
        painter.drawEllipse(center, r, r)


class Arrow(QWidget):
    """A single arrow/dot marker, used standalone only for reference -
    RadarView draws its vessel markers inline for performance (one widget
    per vessel would be wasteful for ~40 targets redrawn every refresh)."""


def draw_arrow(painter: QPainter, center: QPointF, length: float, angle_deg: float, color: QColor) -> None:
    theta = math.radians(angle_deg)
    dx, dy = math.sin(theta), -math.cos(theta)
    px, py = -dy, dx
    tip = center + QPointF(dx * length * 0.6, dy * length * 0.6)
    tail_l = center + QPointF(-dx * length * 0.4 + px * length * 0.28, -dy * length * 0.4 + py * length * 0.28)
    tail_r = center + QPointF(-dx * length * 0.4 - px * length * 0.28, -dy * length * 0.4 - py * length * 0.28)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPolygon(QPolygonF([tip, tail_l, tail_r]))


class RadarView(QWidget):
    """Course-up vessel plot - own position is the center point (no
    marker there, by request), targets plotted at distance/relative-
    bearing and colored by the same rule as the AIS-page counters."""

    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._max_range_km = 5.0
        # each: (relative_bearing_deg, distance_km, is_dot, color, heading_deg)
        self._vessels: List[Tuple[float, float, bool, QColor, float]] = []

    def set_data(self, max_range_km: float, vessels: Sequence[Tuple[float, float, bool, QColor, float]]) -> None:
        self._max_range_km = max_range_km
        self._vessels = list(vessels)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()
        center = QPointF(w / 2, h / 2)
        radius = min(w, h) / 2 - 14

        painter.setPen(QPen(theme.panel_border, 1))
        for frac in (1 / 3, 2 / 3, 1.0):
            painter.drawEllipse(center, radius * frac, radius * frac)

        small = QFont(self.font())
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(center.x() + 4, center.y() - radius - 16, 100, 16),
                          Qt.AlignmentFlag.AlignLeft, f"{self._max_range_km:.0f} KM")

        for rel_bearing, distance_km, is_dot, color, heading in self._vessels:
            frac = min(1.0, distance_km / self._max_range_km) if self._max_range_km else 0.0
            theta = math.radians(rel_bearing)
            px = center.x() + math.sin(theta) * radius * frac
            py = center.y() - math.cos(theta) * radius * frac
            if is_dot:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QPointF(px, py), 4, 4)
            else:
                draw_arrow(painter, QPointF(px, py), radius * 0.12, heading, color)


class IconBase(QWidget):
    """Common base for the small subsystem icons (house battery, starter,
    alternator, solar) - just fixes a square-ish sizing hint."""

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(48, 48)
