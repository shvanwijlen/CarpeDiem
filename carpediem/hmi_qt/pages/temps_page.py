"""T - Temps, StartrekGraphical (Qt) version. Two deck-plan diagrams (from
the owner's "vessel temperature layout v2.pptx") instead of a plain
textual list, since the ~14 temperature/humidity sensors are scattered
across the whole boat and a list loses that spatial context. Sensor
marker positions below are measured directly off that PowerPoint's circle
shapes (each circle's center, as a fraction of the picture placeholder
both its slides share). Each Sensor's code -> display_data field mapping
is cross-checked against "Screen design v02.xlsx", tab T, columns CM
(code)/CN (field).

The source images are a plain black-line-on-white CAD export - inverted
(white lines on near-black) and multiply-tinted toward theme.secondary at
paint time so they read as a schematic overlay instead of a stark white
rectangle sitting in an otherwise all-dark UI.

Markers are color-coded by sensor hardware, not by reading/alarm state:
BLE puck (Teltonika Blue Puck tag) = secondary, Ruuvi tag (read via the
Cerbo GX) = tertiary, fixed single-temp probe = warn. Tapping a marker
"focuses" it (dims everything else) - a few sensors in the technical view
(Console/Electronics Bay/Engine Room x2) sit close enough together that
their callouts crowd each other at rest.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from carpediem.display_data import display_data
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import draw_solid_text, tracked_font

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "temps"
NONE_TEXT = "none"

# Both slides' picture placeholder was 12192000 x 4267200 EMU in the
# source .pptx - both deck-plan jpgs share this aspect ratio.
IMAGE_ASPECT = 12192000 / 4267200

_KIND_COLOR_ATTR = {"ble": "secondary", "ruuvi": "tertiary", "probe": "warn"}


def _fmt(value: Optional[float], suffix: str = "", decimals: int = 1) -> str:
    if value is None:
        return NONE_TEXT
    return f"{value:.{decimals}f}{suffix}"


@dataclass(frozen=True)
class Sensor:
    code: str
    name: str
    kind: str  # "ble" | "ruuvi" | "probe"
    temp_field: str
    hum_field: Optional[str]  # None for single-temp fixed probes
    x: float  # marker position, fraction of image width (0-1)
    y: float  # fraction of image height
    cx: float  # callout anchor position, fraction of image width
    cy: float
    side: str  # "left" | "right" - which way the callout box grows from cx


LIVING_SENSORS: List[Sensor] = [
    Sensor("S", "Kajuit", "ble", "Kajuit Temp", "Kajuit Humidity",
           0.5126, 0.8295, 0.58, 0.70, "left"),
    Sensor("M", "Master Bedroom", "ble", "Master Bedroom Temp", "Master Bedroom Humidity",
           0.0447, 0.7366, 0.13, 0.60, "left"),
    Sensor("T", "Toilet", "ble", "Toilet Temp", "Toilet Humidity",
           0.2450, 0.7311, 0.24, 0.92, "left"),
    Sensor("V", "Voorin", "ble", "Voorin Temp", "Voorin Humidity",
           0.7455, 0.3172, 0.70, 0.14, "right"),
    # Displayed as "Washcabin" (matching display_data.py's human label for
    # this field) even though the internal_label is the sensor model no.
    Sensor("W", "Washcabin", "ble", "P RHT 900F0A Temp", "P RHT 900F0A Humidity",
           0.2701, 0.3080, 0.33, 0.12, "left"),
]

TECHNICAL_SENSORS: List[Sensor] = [
    Sensor("C", "Ruuvi Console", "ruuvi", "RuuviConsoleTemp", "RuuviConsoleHumidity",
           0.2401, 0.6207, 0.14, 0.44, "right"),
    Sensor("K", "Buitenkraan", "ble", "Buitenkraan Temp", "Buitenkraan Humidity",
           0.2150, 0.7334, 0.13, 0.88, "right"),
    Sensor("L", "Elecs Bay (BME280)", "ble", "BME280-Temperature", "BME280-Humidity",
           0.3016, 0.4591, 0.35, 0.22, "left"),
    # callout anchor (cx, cy) moved to top-left, above C's box - X's old
    # anchor (0.42, 0.52) sat in the middle of the C/1/Y cluster and its
    # leader line crossed several others.
    Sensor("X", "Electronics Bay", "probe", "Electronics bay (C)", None,
           0.2862, 0.5961, 0.03, 0.08, "left"),
    Sensor("1", "Engine Room", "ble", "Engine Room Temp", "Engine Room Humidity",
           0.3286, 0.5961, 0.47, 0.30, "left"),
    Sensor("Y", "Engine Room (probe)", "probe", "Engine room (C)", None,
           0.3286, 0.6715, 0.47, 0.86, "left"),
    Sensor("2", "Ruuvi Watertank PS", "ruuvi", "RuuviWatertankPSTemp", "RuuviWatertankPSHumidity",
           0.3905, 0.2841, 0.52, 0.12, "left"),
    # moved well above the drawing itself, into the panel's blank margin -
    # its old anchor (0.52, 0.64) crowded the C/X/1/Y cluster below.
    Sensor("3", "Watertank PS", "ble", "Watertank PS Temp", "Watertank PS Humidity",
           0.3905, 0.1977, 0.68, -0.20, "left"),
    # nudged further below the drawing (was 0.96, right at its edge).
    Sensor("4", "Watertank SB", "ble", "Watertank SB Temp", "Watertank SB Humidity",
           0.3905, 0.8372, 0.56, 1.04, "left"),
]

VIEWS = [
    ("living", "LIVING AREA", ASSET_DIR / "living_area.jpg", LIVING_SENSORS),
    ("technical", "TECHNICAL AREA", ASSET_DIR / "technical_area.jpg", TECHNICAL_SENSORS),
]

MARKER_R = 9.0
DIM_OPACITY = 0.3


class TempsPage(QWidget):
    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._view_index = 0
        self._focused: Optional[str] = None
        self._pixmap_cache: Dict[str, QPixmap] = {}
        self._toggle_rects: List[QRectF] = []
        self._marker_rects: Dict[str, QRectF] = {}

    def refresh(self) -> None:
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        for i, rect in enumerate(self._toggle_rects):
            if rect.contains(pos):
                if i != self._view_index:
                    self._view_index = i
                    self._focused = None
                    self.update()
                return
        for code, rect in self._marker_rects.items():
            if rect.contains(pos):
                self._focused = None if self._focused == code else code
                self.update()
                return

    # -- image loading -----------------------------------------------------

    def _tinted_pixmap(self, path: Path) -> Optional[QPixmap]:
        """Inverted-to-white-on-black QPixmap, cached per path. The cyan
        tint is applied at draw time (paintEvent) via a multiply blend, not
        baked in here, so it always follows the live theme."""
        key = str(path)
        cached = self._pixmap_cache.get(key)
        if cached is not None:
            return cached
        image = QImage(key)
        if image.isNull():
            return None
        image.invertPixels()
        pixmap = QPixmap.fromImage(image)
        self._pixmap_cache[key] = pixmap
        return pixmap

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()

        header_h = max(56, int(h * 0.11))
        self._draw_header(painter, QRectF(0, 0, w, header_h), theme)
        self._draw_diagram(painter, QRectF(0, header_h, w, h - header_h), theme)

    def _draw_header(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        self._toggle_rects = []
        pad = 14.0
        btn_h = rect.height() - pad * 2
        font = tracked_font(self.font(), 1.0)
        font.setBold(True)
        font.setPixelSize(max(13, int(btn_h * 0.36)))
        fm = QFontMetricsF(font)

        x = pad
        for i, (_view_id, label, _path, _sensors) in enumerate(VIEWS):
            btn_w = fm.horizontalAdvance(label) + btn_h * 1.1
            btn_rect = QRectF(x, rect.y() + pad, btn_w, btn_h)
            self._toggle_rects.append(btn_rect)
            active = i == self._view_index
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.secondary if active else theme.panel_bg)
            painter.drawRoundedRect(btn_rect, 8, 8)
            if not active:
                painter.setPen(QPen(theme.panel_border, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(btn_rect, 8, 8)
            painter.setFont(font)
            painter.setPen(QPen(theme.bg if active else theme.text_dim))
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, label)
            x += btn_w + 10

        self._draw_legend(painter, QRectF(x + 10, rect.y(), rect.right() - x - 10 - pad, rect.height()), theme)

    def _draw_legend(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        items = [("BLE puck", theme.secondary), ("Ruuvi", theme.tertiary), ("Fixed probe", theme.warn)]
        font = QFont(self.font())
        font.setPixelSize(max(11, int(rect.height() * 0.24)))
        fm = QFontMetricsF(font)
        dot_r = 5.0
        gap = 8.0
        group_gap = 20.0

        total_w = sum(dot_r * 2 + gap + fm.horizontalAdvance(label) for label, _ in items) \
            + group_gap * (len(items) - 1)
        x = rect.right() - total_w
        cy = rect.center().y()
        painter.setFont(font)
        for label, color in items:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x + dot_r, cy), dot_r, dot_r)
            x += dot_r * 2 + gap
            painter.setPen(QPen(theme.text_dim))
            text_w = fm.horizontalAdvance(label)
            painter.drawText(QRectF(x, rect.y(), text_w, rect.height()),
                              Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            x += text_w + group_gap

    def _draw_diagram(self, painter: QPainter, rect: QRectF, theme: QtTheme) -> None:
        panel = rect.adjusted(14, 8, -14, -14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(panel, 14, 14)

        _view_id, _label, path, sensors = VIEWS[self._view_index]
        self._marker_rects = {}

        inner = panel.adjusted(16, 16, -16, -16)
        img_rect = _fit_aspect(inner, IMAGE_ASPECT)

        pixmap = self._tinted_pixmap(path)
        if pixmap is not None:
            painter.drawPixmap(img_rect, pixmap, QRectF(pixmap.rect()))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            # Dim, desaturated blue-grey (theme.panel_border), not the
            # vivid theme.secondary cyan - that tinted the drawing the
            # same color as the BLE sensors' dots/lines, making them hard
            # to tell apart from the drawing itself.
            painter.fillRect(img_rect, theme.panel_border)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        for sensor in sensors:
            self._draw_sensor(painter, theme, img_rect, sensor)

    def _draw_sensor(self, painter: QPainter, theme: QtTheme, img_rect: QRectF, sensor: Sensor) -> None:
        color = getattr(theme, _KIND_COLOR_ATTR[sensor.kind])
        mx = img_rect.x() + sensor.x * img_rect.width()
        my = img_rect.y() + sensor.y * img_rect.height()
        cx = img_rect.x() + sensor.cx * img_rect.width()
        cy = img_rect.y() + sensor.cy * img_rect.height()

        focused = self._focused == sensor.code
        dimmed = self._focused is not None and not focused
        painter.setOpacity(DIM_OPACITY if dimmed else 1.0)

        painter.setPen(_pen(color, 1.6))
        painter.drawLine(QPointF(mx, my), QPointF(cx, cy))

        painter.setPen(_pen(theme.bg, 2))
        painter.setBrush(color)
        painter.drawEllipse(QPointF(mx, my), MARKER_R, MARKER_R)
        self._marker_rects[sensor.code] = QRectF(mx - MARKER_R - 6, my - MARKER_R - 6,
                                                  (MARKER_R + 6) * 2, (MARKER_R + 6) * 2)

        self._draw_callout(painter, QPointF(cx, cy), sensor, color)
        painter.setOpacity(1.0)

    def _draw_callout(self, painter: QPainter, anchor: QPointF, sensor: Sensor, accent: QColor) -> None:
        name_font = tracked_font(self.font(), 0.8)
        name_font.setBold(True)
        name_font.setPixelSize(14)
        vals_font = QFont(self.font())
        vals_font.setFamilies(["Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "Monospace"])
        vals_font.setBold(True)
        vals_font.setPixelSize(19)

        temp = display_data.get(sensor.temp_field)
        vals_text = _fmt(temp, "°C")
        if sensor.hum_field is not None:
            hum = display_data.get(sensor.hum_field)
            vals_text = f"{vals_text}  ·  {_fmt(hum, '%', decimals=0)}"

        fm_name = QFontMetricsF(name_font)
        fm_vals = QFontMetricsF(vals_font)
        name_text = f"{sensor.code} · {sensor.name}"
        box_w = max(fm_name.horizontalAdvance(name_text), fm_vals.horizontalAdvance(vals_text)) + 18
        box_h = 50.0

        box = QRectF(0, 0, box_w, box_h)
        if sensor.side == "right":
            box.moveTopRight(QPointF(anchor.x(), anchor.y() - box_h / 2))
        else:
            box.moveTopLeft(QPointF(anchor.x(), anchor.y() - box_h / 2))

        # Light grey card, not the dark panel color - against the
        # near-black diagram, a dark card made the callout text (also
        # light) unreadable since card and background both read as black.
        card_bg = QColor(224, 227, 231, 250)
        text_dark = QColor(30, 34, 38)
        text_dark_dim = QColor(90, 98, 106)

        painter.setPen(_pen(QColor(160, 166, 172), 1))
        painter.setBrush(card_bg)
        painter.drawRoundedRect(box, 5, 5)
        bar = QRectF(box.x() if sensor.side != "right" else box.right() - 3, box.y(), 3, box.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRect(bar)

        text_pad = 9.0
        text_rect = QRectF(box.x() + text_pad, box.y() + 3, box.width() - text_pad * 2, box.height() - 6)
        painter.setFont(name_font)
        painter.setPen(QPen(text_dark_dim))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name_text)
        draw_solid_text(painter, text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                         vals_text, vals_font, text_dark)


def _fit_aspect(rect: QRectF, aspect: float) -> QRectF:
    """Largest rect with the given width/height ratio that fits centered
    inside `rect` (letterboxed), same idea as CSS object-fit: contain."""
    if rect.width() / rect.height() > aspect:
        h = rect.height()
        w = h * aspect
    else:
        w = rect.width()
        h = w / aspect
    x = rect.x() + (rect.width() - w) / 2
    y = rect.y() + (rect.height() - h) / 2
    return QRectF(x, y, w, h)


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen
