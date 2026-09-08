"""Vector icons - QPainter ports of hmi/icons.py (top-bar tab icons) and
of main_page.py's subsystem icons (starter battery, alternator, solar).
Same shapes/designs as the pygame version for visual continuity between
the two engines, just drawn with anti-aliasing and real gradients/glow.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from carpediem.hmi_qt.theme import QtTheme

# -- top-bar tab icons (pure paint functions: painter, rect, color, width) --


def draw_main(painter: QPainter, rect: QRectF, color: QColor, width: float = 2.0) -> None:
    c = rect.center()
    r = min(rect.width(), rect.height()) / 2 - 2
    painter.setPen(QPen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(c, r, r)
    painter.drawEllipse(c, max(2.0, r / 4), max(2.0, r / 4))
    for i in range(8):
        theta = math.radians(i * 45)
        p1 = c + QPointF(math.sin(theta) * r * 0.35, -math.cos(theta) * r * 0.35)
        p2 = c + QPointF(math.sin(theta) * r, -math.cos(theta) * r)
        painter.drawLine(p1, p2)


def draw_ais(painter: QPainter, rect: QRectF, color: QColor, width: float = 2.0) -> None:
    c = rect.center()
    r = min(rect.width(), rect.height()) / 2 - 2
    painter.setPen(QPen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(c, r, r)
    painter.drawEllipse(c, r * 0.6, r * 0.6)
    theta = math.radians(-40)
    painter.drawLine(c, c + QPointF(math.sin(theta) * r, -math.cos(theta) * r))
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    for dx, dy in ((0.35, -0.5), (-0.45, 0.15), (0.1, 0.55)):
        painter.drawEllipse(c + QPointF(dx * r, dy * r), 2, 2)


def draw_weather(painter: QPainter, rect: QRectF, color: QColor, width: float = 2.0) -> None:
    w, h = rect.width(), rect.height()
    cx, cy = rect.center().x(), rect.center().y()
    base_y = cy + h * 0.08
    painter.setPen(QPen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx - w * 0.15, base_y - h * 0.05), h * 0.20, h * 0.20)
    painter.drawEllipse(QPointF(cx + w * 0.08, base_y - h * 0.14), h * 0.26, h * 0.26)
    painter.drawEllipse(QPointF(cx + w * 0.28, base_y - h * 0.02), h * 0.17, h * 0.17)
    cloud = QRectF(0, 0, w * 0.62, h * 0.22)
    cloud.moveCenter(QPointF(cx + 0.02 * w, base_y + h * 0.06))
    painter.drawRoundedRect(cloud, cloud.height() / 2, cloud.height() / 2)
    for i, dy in enumerate((0.34, 0.44)):
        y = rect.top() + h * (0.72 + dy * 0.3)
        x1 = rect.left() + w * (0.2 + i * 0.1)
        x2 = rect.right() - w * 0.12
        painter.drawLine(QPointF(x1, y), QPointF(x2, y))


def draw_power(painter: QPainter, rect: QRectF, color: QColor, width: float = 2.0) -> None:
    w, h = rect.width(), rect.height()
    x, y = rect.x(), rect.y()
    pts = [
        QPointF(x + w * 0.55, y + h * 0.05),
        QPointF(x + w * 0.25, y + h * 0.58),
        QPointF(x + w * 0.46, y + h * 0.58),
        QPointF(x + w * 0.40, y + h * 0.95),
        QPointF(x + w * 0.75, y + h * 0.40),
        QPointF(x + w * 0.52, y + h * 0.40),
    ]
    painter.setPen(QPen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(QPolygonF(pts))


def draw_temps(painter: QPainter, rect: QRectF, color: QColor, width: float = 2.0) -> None:
    w, h = rect.width(), rect.height()
    cx = rect.center().x()
    stem_w = max(4.0, w * 0.18)
    stem = QRectF(cx - stem_w / 2, rect.top() + h * 0.06, stem_w, h * 0.62)
    bulb_r = w * 0.16
    bulb_center = QPointF(cx, stem.bottom() + bulb_r - 2)
    painter.setPen(QPen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(stem, stem_w / 2, stem_w / 2)
    painter.drawEllipse(bulb_center, bulb_r, bulb_r)
    fill_top = stem.top() + stem.height() * 0.35
    painter.drawLine(QPointF(cx, fill_top), QPointF(cx, bulb_center.y()))
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(bulb_center, max(1.0, bulb_r - 4), max(1.0, bulb_r - 4))


def draw_cam(painter: QPainter, rect: QRectF, color: QColor, width: float = 2.0) -> None:
    w, h = rect.width(), rect.height()
    body = QRectF(0, 0, w * 0.8, h * 0.55)
    body.moveCenter(QPointF(rect.center().x(), rect.center().y() + h * 0.08))
    bump = QRectF(0, 0, w * 0.32, h * 0.16)
    bump.moveBottomLeft(QPointF(body.center().x() - w * 0.05 - w * 0.16, body.top() + 1))
    painter.setPen(QPen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 4, 4)
    painter.drawRoundedRect(bump, 2, 2)
    r = min(body.width(), body.height()) * 0.32
    painter.drawEllipse(body.center(), r, r)
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(body.center(), 2, 2)


ICONS: Dict[str, Callable[[QPainter, QRectF, QColor, float], None]] = {
    "main": draw_main,
    "ais": draw_ais,
    "weather": draw_weather,
    "power": draw_power,
    "temps": draw_temps,
    "cam": draw_cam,
}


# -- Main-page subsystem icon widgets ---------------------------------

HOUSE_BATTERY_EMPTY_V = 12.2
HOUSE_BATTERY_FULL_V = 14.2


class StarterBatteryIcon(QWidget):
    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()
        body = QRectF(w * 0.14, h * 0.14, w * 0.72, h * 0.72)

        grad = QLinearGradient(body.topLeft(), body.bottomLeft())
        grad.setColorAt(0.0, theme.panel_bg_hi)
        grad.setColorAt(1.0, theme.bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(body, 5, 5)
        painter.setPen(QPen(theme.tertiary, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body, 5, 5)

        painter.setPen(QPen(theme.tertiary, 1))
        for i in (1, 2, 3):
            x = body.left() + body.width() * i / 4
            painter.drawLine(QPointF(x, body.top() + 3), QPointF(x, body.top() + body.height() * 0.3))

        plus_x = body.left() + body.width() * 0.26
        minus_x = body.left() + body.width() * 0.74
        post_w, post_h = max(3.0, body.width() / 6), max(3.0, body.height() / 6)
        painter.setBrush(QBrush(theme.tertiary))
        painter.setPen(Qt.PenStyle.NoPen)
        for x in (plus_x, minus_x):
            post = QRectF(x - post_w / 2, body.top() - post_h + 1, post_w, post_h)
            painter.drawRoundedRect(post, 1, 1)

        tick = max(2.0, post_w / 2)
        py = body.center().y()
        painter.setPen(QPen(theme.tertiary, 2))
        painter.drawLine(QPointF(plus_x - tick, py), QPointF(plus_x + tick, py))
        painter.drawLine(QPointF(plus_x, py - tick), QPointF(plus_x, py + tick))
        painter.drawLine(QPointF(minus_x - tick, py), QPointF(minus_x + tick, py))


class AlternatorIcon(QWidget):
    """A pulley/fan wheel with a belt hint - the alternator's drive
    pulley, which reads as "alternator" at a glance far more literally
    than a sine-wave-in-a-circle schematic symbol would."""

    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        center = QPointF(self.width() / 2, self.height() / 2)
        half = min(self.width(), self.height()) / 2
        # The pulley itself is sized to leave room inside the widget for
        # both the glow and the belt arc drawn around it - anything drawn
        # past the widget's own bounds gets hard-clipped by Qt rather than
        # fading out, which for the glow gradient specifically left a
        # visible dim square (fixed) and for the belt just clipped it away
        # entirely (this sizing avoids both).
        r = half * 0.78

        glow_r = min(r * 1.6, half)
        glow = QRadialGradient(center, glow_r)
        c1 = QColor(theme.accent)
        c1.setAlpha(90)
        glow.setColorAt(0.0, c1)
        c2 = QColor(theme.accent)
        c2.setAlpha(0)
        glow.setColorAt(1.0, c2)
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, glow_r, glow_r)

        belt_r = min(r * 1.35, half - 1)
        belt_rect = QRectF(center.x() - belt_r, center.y() - belt_r, belt_r * 2, belt_r * 2)
        painter.setPen(QPen(theme.accent_dim, 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(belt_rect, 200 * 16, 140 * 16)

        painter.setBrush(QBrush(theme.bg))
        painter.setPen(QPen(theme.accent, 2))
        painter.drawEllipse(center, r, r)

        hub_r = r * 0.24
        blade_len = r * 0.82
        blade_half_w = r * 0.12
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(theme.accent))
        for i in range(6):
            theta = math.radians(i * 60)
            dx, dy = math.sin(theta), -math.cos(theta)
            px, py = -dy, dx
            base_l = center + QPointF(dx * hub_r + px * blade_half_w, dy * hub_r + py * blade_half_w)
            base_r = center + QPointF(dx * hub_r - px * blade_half_w, dy * hub_r - py * blade_half_w)
            tip = center + QPointF(dx * blade_len, dy * blade_len)
            painter.drawPolygon(QPolygonF([base_l, base_r, tip]))

        painter.setBrush(QBrush(theme.bg))
        painter.setPen(QPen(theme.accent, 2))
        painter.drawEllipse(center, hub_r, hub_r)


class SolarIcon(QWidget):
    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()
        body = QRectF(w * 0.10, h * 0.06, w * 0.80, h * 0.58)

        grad = QLinearGradient(body.topLeft(), body.bottomLeft())
        grad.setColorAt(0.0, theme.panel_bg_hi)
        grad.setColorAt(1.0, theme.bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(body, 3, 3)
        painter.setPen(QPen(theme.ok, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body, 3, 3)

        painter.setPen(QPen(theme.ok, 1))
        for i in (1, 2):
            x = body.left() + body.width() * i / 3
            painter.drawLine(QPointF(x, body.top()), QPointF(x, body.bottom()))
        y = body.top() + body.height() / 2
        painter.drawLine(QPointF(body.left(), y), QPointF(body.right(), y))

        post_w = max(2.0, body.width() * 0.1)
        post = QRectF(body.center().x() - post_w / 2, body.bottom() - 1, post_w, max(3.0, h - body.bottom()))
        painter.setBrush(QBrush(theme.panel_border))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(post)
        base_w = body.width() * 0.5
        painter.setPen(QPen(theme.panel_border, 2))
        painter.drawLine(QPointF(w / 2 - base_w / 2, h - 1), QPointF(w / 2 + base_w / 2, h - 1))
