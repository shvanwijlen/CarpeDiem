"""Stand-in for the 5 tabs not built out yet, same as hmi/pages/placeholder.py."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from carpediem.hmi_qt import icons
from carpediem.hmi_qt.theme import QtTheme


class PlaceholderPage(QWidget):
    def __init__(self, theme: QtTheme, title: str, icon_key: str, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._title = title
        self._icon_key = icon_key

    def refresh(self) -> None:
        pass

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()
        size = min(w, h) // 4
        icon_rect = QRectF(0, 0, size, size)
        icon_rect.moveCenter(self.rect().center())
        icon_rect.moveBottom(self.rect().center().y())
        icons.ICONS[self._icon_key](painter, icon_rect, theme.accent_dim, 3.0)

        font = painter.font()
        font.setPixelSize(32)
        painter.setFont(font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(0, icon_rect.bottom() + 20, w, 50), Qt.AlignmentFlag.AlignHCenter, self._title.upper())

        font2 = painter.font()
        font2.setPixelSize(16)
        painter.setFont(font2)
        painter.drawText(QRectF(0, icon_rect.bottom() + 64, w, 30), Qt.AlignmentFlag.AlignHCenter, "under construction")
