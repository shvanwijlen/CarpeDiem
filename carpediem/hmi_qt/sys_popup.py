"""SYS lamp detail popup - what you get when you tap the top bar's SYS
indicator: CPU / memory / disk usage and the Pi's own temperature, from
sysmetrics_monitor.summary_rows() (the same rows the iPhone app and the
pygame HMI show, so the numbers and warn/crit colors match everywhere).

A full-window overlay rather than a small popup box: dimmed backdrop plus a
centered panel, and a tap *anywhere* closes it. On a touchscreen (the
Magedok, no keyboard/mouse) that is much easier to dismiss than hitting a
tiny close button, and it means "tap SYS again" isn't needed either.
Values refresh live while it's open (HMI refresh tick -> refresh()).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import tracked_font
from carpediem.sysmetrics_monitor import summary_rows, sysmetrics_monitor

_STATUS_TEXT = {"ok": "ALL SYSTEMS OK", "warn": "WARNING", "crit": "CRITICAL"}


class SysPopup(QWidget):
    def __init__(self, theme: QtTheme, parent: QWidget) -> None:
        super().__init__(parent)
        self._theme = theme
        self.hide()

    def _level_color(self, level: Optional[str]) -> QColor:
        theme = self._theme
        return {"ok": theme.ok, "warn": theme.warn, "crit": theme.danger}.get(level or "", theme.neutral)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None and self.geometry() != parent.rect():
            self.setGeometry(parent.rect())

    def open(self) -> None:
        self._sync_geometry()
        self.show()
        self.raise_()
        self.update()

    def refresh(self) -> None:
        if self.isVisible():
            self._sync_geometry()
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()

        painter.fillRect(self.rect(), QColor(0, 0, 0, 175))

        metrics = sysmetrics_monitor.latest
        panel_w = min(w * 0.72, 720.0)
        panel_h = min(h * 0.86, 460.0)
        panel = QRectF((w - panel_w) / 2, (h - panel_h) / 2, panel_w, panel_h)

        grad = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        grad.setColorAt(0.0, theme.panel_bg_hi)
        grad.setColorAt(1.0, theme.panel_bg)
        status_color = self._level_color(metrics.status if metrics else None)
        # Soft glow in the overall status color, then the panel itself.
        for spread, alpha in ((14, 28), (8, 48), (3, 90)):
            glow = QColor(status_color)
            glow.setAlpha(alpha)
            painter.setPen(QPen(glow, spread))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(panel, 20, 20)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(status_color, 2))
        painter.drawRoundedRect(panel, 20, 20)

        pad = panel_h * 0.06
        inner = panel.adjusted(pad * 1.4, pad, -pad * 1.4, -pad)

        # Title row: "SYSTEM" + overall status.
        title_h = panel_h * 0.13
        title_font = tracked_font(self.font(), 3.0)
        title_font.setBold(True)
        title_font.setPixelSize(max(14, int(title_h * 0.6)))
        painter.setFont(title_font)
        painter.setPen(QPen(theme.accent))
        painter.drawText(QRectF(inner.left(), inner.top(), inner.width() / 2, title_h),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "SYSTEM")

        status_text = _STATUS_TEXT.get(metrics.status, "--") if metrics else "NO DATA"
        status_font = tracked_font(self.font(), 2.0)
        status_font.setBold(True)
        status_font.setPixelSize(max(12, int(title_h * 0.42)))
        painter.setFont(status_font)
        painter.setPen(QPen(status_color))
        text_rect = QRectF(inner.center().x(), inner.top(), inner.width() / 2 - title_h * 0.5, title_h)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, status_text)
        dot = title_h * 0.3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(status_color))
        painter.drawEllipse(QRectF(inner.right() - dot, inner.top() + (title_h - dot) / 2, dot, dot))

        if metrics is None:
            msg_font = QFont(self.font())
            msg_font.setPixelSize(max(12, int(panel_h * 0.06)))
            painter.setFont(msg_font)
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(inner.adjusted(0, title_h, 0, 0), Qt.AlignmentFlag.AlignCenter,
                             "No system reading yet\n(CARPEDIEM_CHECK_SYSMETRICS off?)")
            return

        # Metric rows: label + value on one line, a level-colored bar under it.
        rows = summary_rows(metrics)
        rows_top = inner.top() + title_h + pad * 0.6
        footer_h = panel_h * 0.08
        row_h = (inner.bottom() - footer_h - rows_top) / len(rows)

        label_font = tracked_font(self.font(), 2.0)
        label_font.setPixelSize(max(11, int(row_h * 0.26)))
        value_font = QFont(self.font())
        value_font.setBold(True)
        value_font.setPixelSize(max(14, int(row_h * 0.36)))

        for i, row in enumerate(rows):
            top = rows_top + i * row_h
            color = self._level_color(row.level)
            line = QRectF(inner.left(), top, inner.width(), row_h * 0.6)
            painter.setFont(label_font)
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(line, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, row.label)
            painter.setFont(value_font)
            painter.setPen(QPen(color))
            painter.drawText(line, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, row.value)

            if row.fraction is not None:
                bar_h = max(6.0, row_h * 0.11)
                bar = QRectF(inner.left(), top + row_h * 0.64, inner.width(), bar_h)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(theme.panel_border.darker(180)))
                painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)
                fill = QRectF(bar.left(), bar.top(), max(bar_h, bar.width() * row.fraction), bar_h)
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(fill, bar_h / 2, bar_h / 2)

        hint_font = tracked_font(self.font(), 1.5)
        hint_font.setPixelSize(max(10, int(footer_h * 0.5)))
        painter.setFont(hint_font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(QRectF(inner.left(), inner.bottom() - footer_h, inner.width(), footer_h),
                         Qt.AlignmentFlag.AlignCenter, "TAP ANYWHERE TO CLOSE")
