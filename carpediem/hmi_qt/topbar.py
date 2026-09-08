"""The page-selector + subsystem-status bar - Qt port of hmi/topbar.py.
Same 6 tabs / 8 indicator layout and logic (indicator width auto-derived
from remaining space, matching the pygame version's handling of the
spec's percentages not quite summing to 100%), built with QHBoxLayout
instead of manual rect math.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from carpediem.display_data import display_data
from carpediem.hmi_qt import icons
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import Led, apply_glow, tracked_font
from carpediem.sysmetrics_monitor import sysmetrics_monitor

# (page_id, caption, icon_key)
PAGES: List[Tuple[str, str, str]] = [
    ("main", "MAIN", "main"),
    ("ais", "AIS", "ais"),
    ("weather", "WEATHER", "weather"),
    ("power", "POWER", "power"),
    ("temps", "TEMPS", "temps"),
    ("cam", "CAM", "cam"),
]

# (caption, display_data label) - label None means "always neutral/unused".
# The last slot is special-cased below: it's a 3-state (green/orange/red)
# CPU+memory+disk health LED instead of the usual binary display_data one -
# see sysmetrics_monitor.py.
SYSMETRICS_SENTINEL = "__sysmetrics__"
INDICATORS: List[Tuple[str, Optional[str]]] = [
    ("WIFI", "WiFi"),
    ("AIS", "AIS"),
    ("MQTT", "MQTT"),
    ("MDB", "MODBUS"),
    ("BLE", "BLE"),
    ("WX", "Weather"),
    ("RING", "Cam"),
    ("SYS", SYSMETRICS_SENTINEL),
]


class TabButton(QPushButton):
    def __init__(self, theme: QtTheme, icon_key: str, caption: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._icon_key = icon_key
        self._caption = caption
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(60)
        self.toggled.connect(self._on_toggled)
        self._on_toggled(False)

    def _on_toggled(self, checked: bool) -> None:
        if checked:
            apply_glow(self, self._theme.accent, radius=22, alpha=190)
        else:
            self.setGraphicsEffect(None)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        active = self.isChecked()
        color = theme.accent if active else theme.text_dim

        if active:
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, theme.panel_bg_hi)
            grad.setColorAt(1.0, theme.panel_bg)
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(theme.accent, 2))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.panel_border, 1))
        radius = rect.height() / 2
        painter.drawRoundedRect(rect, radius, radius)

        icon_size = rect.height() * 0.46
        icon_rect = QRectF(0, 0, icon_size, icon_size)
        icon_rect.moveCenter(rect.center())
        icon_rect.moveTop(rect.top() + rect.height() * 0.10)
        icons.ICONS[self._icon_key](painter, icon_rect, color, 3.0 if active else 2.0)

        font = tracked_font(self.font(), 1.5)
        font.setBold(active)
        font.setPixelSize(max(9, int(rect.height() * 0.16)))
        painter.setFont(font)
        painter.setPen(QPen(color))
        text_rect = QRectF(rect.left(), rect.bottom() - rect.height() * 0.28, rect.width(), rect.height() * 0.24)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._caption)


class IndicatorChip(QWidget):
    def __init__(self, theme: QtTheme, caption: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 4)
        layout.setSpacing(2)
        self._led = Led(theme)
        self._led.setFixedSize(14, 14)
        led_row = QHBoxLayout()
        led_row.addStretch(1)
        led_row.addWidget(self._led)
        led_row.addStretch(1)
        layout.addLayout(led_row)
        label = QLabel(caption)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = tracked_font(label.font(), 1.0)
        f.setPixelSize(10)
        label.setFont(f)
        label.setStyleSheet(f"color: rgb({theme.text_dim.red()},{theme.text_dim.green()},{theme.text_dim.blue()});")
        layout.addWidget(label)

    def set_state(self, state: Optional[bool | str]) -> None:
        self._led.set_state(state)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        rect = QRectF(self.rect()).adjusted(3, 6, -3, -4)
        painter.setBrush(QBrush(theme.panel_bg))
        painter.setPen(QPen(theme.panel_border, 1))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        super().paintEvent(event)


class TopBar(QWidget):
    page_selected = Signal(str)

    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setFixedHeight(84)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._tab_buttons: Dict[str, TabButton] = {}
        for page_id, caption, icon_key in PAGES:
            btn = TabButton(theme, icon_key, caption)
            btn.clicked.connect(lambda checked=False, pid=page_id: self._on_tab_clicked(pid))
            layout.addWidget(btn, 11)
            self._tab_buttons[page_id] = btn
        self._tab_buttons["main"].setChecked(True)

        self._indicators: Dict[str, IndicatorChip] = {}
        for caption, label in INDICATORS:
            chip = IndicatorChip(theme, caption)
            layout.addWidget(chip, 5)
            self._indicators[caption] = chip

    def _on_tab_clicked(self, page_id: str) -> None:
        for pid, btn in self._tab_buttons.items():
            btn.setChecked(pid == page_id)
        self.page_selected.emit(page_id)

    def refresh(self) -> None:
        for caption, label in INDICATORS:
            if label == SYSMETRICS_SENTINEL:
                metrics = sysmetrics_monitor.latest
                self._indicators[caption].set_state(metrics.status if metrics is not None else None)
                continue
            value = display_data.get(label) if label is not None else None
            state = None if value is None else bool(value == 1 or value is True)
            self._indicators[caption].set_state(state)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        theme = self._theme
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, theme.panel_bg_hi)
        grad.setColorAt(1.0, theme.bg)
        painter.fillRect(self.rect(), QBrush(grad))
        painter.setPen(QPen(theme.accent_dim, 2))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
