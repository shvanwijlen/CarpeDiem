"""C - Cam, StartrekGraphical (Qt) version. A grid of cards, one per Ring
camera, built directly from config.ring.camera_field_map/
camera_connection_field_map rather than a hardcoded camera list, so a
renamed or newly added camera (see ring_client.py/config.py) needs no
change here.

Two levels, same idea as the Temps page's "known fields first, drawing
second": level 1 (always on) is name + connection status + battery, all
of it already polled by ring_client.py regardless of config. Level 2 is
each card's snapshot image - config.ring.fetch_snapshots (off by default;
see ring_client.py's docstring for why) only gates the *background* poll
loop writing a fresh file periodically. Whatever's on disk in
snapshot_dir gets shown regardless of that setting, since tapping a tile
(see _request_snapshot) fetches and writes one on demand irrespective of
it - a card falls back to a plain placeholder glyph only when there's no
snapshot file yet at all.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Dict, Optional, Set, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import draw_solid_text, tracked_font
from carpediem.logging_setup import log
from carpediem.ring_client import RingClient, snapshot_key

NONE_TEXT = "none"
GRID_COLUMNS = 2

# Cameras whose battery_life is a meaningless Ring API placeholder (a
# wired camera pinned at 100%, no real cell behind it) - see config.py's
# camera_field_map comment. Shown as "WIRED" instead of a percentage.
WIRED_BATTERY_FIELDS = {"RingBatteryConsole"}

# A snapshot older than this many poll intervals is treated as stale
# (probably fetch_snapshots was just turned on, or polling has stalled)
# and the placeholder is shown instead of a misleadingly-old image.
STALE_SNAPSHOT_POLLS = 3.0


def _icon_camera(painter: QPainter, rect: QRectF, color: QColor) -> None:
    body = rect.adjusted(rect.width() * 0.12, rect.height() * 0.28, -rect.width() * 0.12, -rect.height() * 0.12)
    pen = QPen(color, 2.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 4, 4)
    bump_w = body.width() * 0.32
    bump = QRectF(body.center().x() - bump_w / 2, body.top() - body.height() * 0.16, bump_w, body.height() * 0.2)
    painter.drawRoundedRect(bump, 3, 3)
    lens_r = body.height() * 0.26
    painter.drawEllipse(body.center(), lens_r, lens_r)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(body.center(), lens_r * 0.35, lens_r * 0.35)


class CamPage(QWidget):
    def __init__(self, theme: QtTheme, ring_client: Optional[RingClient] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._ring_client = ring_client
        self._pixmap_cache: Dict[str, Tuple[float, QPixmap]] = {}  # key -> (mtime, pixmap)
        self._card_rects: Dict[str, QRectF] = {}  # cam_name -> tile rect, for tap hit-testing
        self._fetching: Set[str] = set()  # cam_names with an on-demand fetch in flight

    def refresh(self) -> None:
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        for cam_name, rect in self._card_rects.items():
            if rect.contains(pos):
                self._request_snapshot(cam_name)
                return

    def _request_snapshot(self, cam_name: str) -> None:
        # Tap-to-fetch works even without config.ring.fetch_snapshots and
        # even in fake-data mode - it's an explicit, one-off user action,
        # not the background poll loop those gate. Still needs a real
        # RingClient with a valid cached token to actually succeed.
        if self._ring_client is None:
            log(9, f"Ring: tile tapped for '{cam_name}' but no RingClient is wired up - ignoring")
            return
        if cam_name in self._fetching:
            log(9, f"Ring: tile tapped for '{cam_name}' but a fetch is already in flight - ignoring")
            return
        log(9, f"Ring: tile tapped - fetching one snapshot for '{cam_name}'")
        self._fetching.add(cam_name)
        self.update()
        task = asyncio.ensure_future(self._ring_client.fetch_snapshot_now(cam_name))
        task.add_done_callback(lambda t, name=cam_name: self._on_fetch_done(name, t))

    def _on_fetch_done(self, cam_name: str, task: "asyncio.Task[bool]") -> None:
        self._fetching.discard(cam_name)
        try:
            ok = task.result()
        except Exception as exc:  # noqa: BLE001 - report it, don't crash the callback
            log(9, f"Ring: on-demand fetch for '{cam_name}' raised: {exc!r}")
        else:
            log(9, f"Ring: on-demand fetch for '{cam_name}' {'succeeded' if ok else 'failed'} "
                   f"(see earlier Ring: log lines above for why, if it failed)")
        self.update()

    def _snapshot_pixmap(self, key: str) -> Optional[Tuple[QPixmap, float]]:
        """Returns (pixmap, age_seconds), reloading from disk only when the
        file's mtime has changed since the last paint."""
        path = config.ring.snapshot_dir / f"{key}.jpg"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        cached = self._pixmap_cache.get(key)
        if cached is not None and cached[0] == mtime:
            pixmap = cached[1]
        else:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                return None
            self._pixmap_cache[key] = (mtime, pixmap)
        return pixmap, max(0.0, time.time() - mtime)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()

        names = list(config.ring.camera_field_map.keys())
        self._card_rects = {}
        grid_rect = QRectF(0, 0, w, h).adjusted(14, 10, -14, -14)
        cols = min(GRID_COLUMNS, max(1, len(names)))
        rows = math.ceil(len(names) / cols) if names else 1
        gap = 14.0
        cell_w = (grid_rect.width() - gap * (cols - 1)) / cols
        cell_h = (grid_rect.height() - gap * (rows - 1)) / rows

        for i, cam_name in enumerate(names):
            r, c = divmod(i, cols)
            cell = QRectF(grid_rect.x() + c * (cell_w + gap), grid_rect.y() + r * (cell_h + gap), cell_w, cell_h)
            self._draw_card(painter, theme, cell, cam_name)

    def _draw_card(self, painter: QPainter, theme: QtTheme, cell: QRectF, cam_name: str) -> None:
        self._card_rects[cam_name] = cell
        battery_field = config.ring.camera_field_map[cam_name]
        connection_field = config.ring.camera_connection_field_map[cam_name]
        connection = display_data.get(connection_field)
        battery = display_data.get(battery_field)
        wired = battery_field in WIRED_BATTERY_FIELDS

        online = connection == "online" if connection is not None else None
        status_color = theme.ok if online else (theme.danger if online is not None else theme.neutral)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(cell, 12, 12)

        title_h = max(28, int(cell.height() * 0.14))
        footer_h = max(26, int(cell.height() * 0.13))
        self._draw_card_title(painter, theme, QRectF(cell.x(), cell.y(), cell.width(), title_h),
                               cam_name, status_color, connection)

        snap_rect = QRectF(cell.x() + 10, cell.y() + title_h, cell.width() - 20,
                            cell.height() - title_h - footer_h - 6)
        self._draw_snapshot(painter, theme, snap_rect, cam_name, snapshot_key(battery_field))

        footer_rect = QRectF(cell.x(), cell.bottom() - footer_h, cell.width(), footer_h)
        self._draw_battery(painter, theme, footer_rect, battery, wired)

    def _draw_card_title(self, painter: QPainter, theme: QtTheme, rect: QRectF, name: str,
                          status_color: QColor, connection: Optional[str]) -> None:
        font = tracked_font(self.font(), 1.0)
        font.setBold(True)
        font.setPixelSize(max(16, int(rect.height() * 0.5)))
        pad = 12.0
        dot_r = 6.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(status_color)
        painter.drawEllipse(QPointF(rect.x() + pad, rect.center().y()), dot_r, dot_r)

        painter.setFont(font)
        painter.setPen(QPen(theme.text))
        name_rect = QRectF(rect.x() + pad + dot_r * 2 + 8, rect.y(), rect.width() * 0.6, rect.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name.upper())

        conn_font = QFont(self.font())
        conn_font.setPixelSize(max(13, int(rect.height() * 0.38)))
        conn_text = (connection or NONE_TEXT).upper()
        painter.setFont(conn_font)
        painter.setPen(QPen(theme.text_dim))
        conn_rect = QRectF(rect.x(), rect.y(), rect.width() - pad, rect.height())
        painter.drawText(conn_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, conn_text)

    def _draw_snapshot(self, painter: QPainter, theme: QtTheme, rect: QRectF, cam_name: str, key: str) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.bg_hi)
        painter.drawRoundedRect(rect, 8, 8)

        # Whatever's on disk gets shown - fetch_snapshots only gates the
        # background poll loop that writes it periodically (see module
        # docstring); a tap-to-fetch write must still display here even
        # when that setting is off.
        snap = self._snapshot_pixmap(key)
        stale_after = config.ring.poll_interval_seconds * STALE_SNAPSHOT_POLLS
        if snap is not None and snap[1] <= stale_after:
            pixmap, age = snap
            fitted = _fit_aspect(rect.adjusted(3, 3, -3, -3), pixmap.width() / pixmap.height())
            painter.drawPixmap(fitted, pixmap, QRectF(pixmap.rect()))
            age_font = QFont(self.font())
            age_font.setPixelSize(max(12, int(rect.height() * 0.09)))
            age_text = f"updated {_format_age(age)} ago"
            age_rect = QRectF(rect.x() + 8, rect.bottom() - 24, rect.width() - 16, 20)
            painter.setBrush(QColor(10, 15, 20, 170))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(age_rect.adjusted(-4, -2, 4, 2), 4, 4)
            painter.setFont(age_font)
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(age_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, age_text)
        else:
            icon_r = min(rect.width(), rect.height()) * 0.16
            icon_rect = QRectF(rect.center().x() - icon_r, rect.center().y() - icon_r * 1.4, icon_r * 2, icon_r * 2)
            _icon_camera(painter, icon_rect, theme.neutral)

            label = "No snapshot yet - tap to fetch"
            label_font = QFont(self.font())
            label_font.setPixelSize(max(13, int(rect.height() * 0.11)))
            label_rect = QRectF(rect.x(), icon_rect.bottom() + 6, rect.width(), 26)
            painter.setFont(label_font)
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

        if cam_name in self._fetching:
            painter.setBrush(QColor(3, 5, 9, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            fetch_font = tracked_font(self.font(), 1.0)
            fetch_font.setBold(True)
            fetch_font.setPixelSize(max(14, int(rect.height() * 0.1)))
            painter.setFont(fetch_font)
            painter.setPen(QPen(theme.secondary))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "FETCHING…")

    def _draw_battery(self, painter: QPainter, theme: QtTheme, rect: QRectF, battery: Optional[float],
                       wired: bool) -> None:
        pad = 12.0
        bar_w, bar_h = rect.width() * 0.32, rect.height() * 0.38
        bar_rect = QRectF(rect.x() + pad, rect.center().y() - bar_h / 2, bar_w, bar_h)

        if wired:
            font = tracked_font(self.font(), 1.0)
            font.setBold(True)
            font.setPixelSize(max(13, int(rect.height() * 0.46)))
            painter.setFont(font)
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(rect.adjusted(pad, 0, -pad, 0),
                              Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "WIRED")
            return

        pct = max(0.0, min(100.0, battery)) if battery is not None else None
        fill_color = theme.neutral if pct is None else (theme.ok if pct > 25 else (theme.warn if pct > 10 else theme.danger))

        painter.setPen(_pen(theme.panel_border, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bar_rect, 3, 3)
        if pct is not None:
            fill_rect = QRectF(bar_rect.x(), bar_rect.y(), bar_rect.width() * pct / 100.0, bar_rect.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(fill_rect, 2, 2)

        text_font = QFont(self.font())
        text_font.setBold(True)
        text_font.setPixelSize(max(14, int(rect.height() * 0.48)))
        text = f"{pct:.0f}%" if pct is not None else NONE_TEXT
        text_rect = QRectF(bar_rect.right() + 8, rect.y(), rect.width() - bar_rect.width() - pad * 2 - 8, rect.height())
        draw_solid_text(painter, text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         text, text_font, theme.text)


def _format_age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{int(minutes)}m"
    return f"{minutes / 60.0:.1f}h"


def _fit_aspect(rect: QRectF, aspect: float) -> QRectF:
    if aspect <= 0:
        return rect
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
