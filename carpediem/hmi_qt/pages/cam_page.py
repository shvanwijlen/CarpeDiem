"""C - Cam, StartrekGraphical (Qt) version. A grid of cards, one per Ring
camera, built directly from config.ring.camera_field_map/
camera_connection_field_map rather than a hardcoded camera list, so a
renamed or newly added camera (see ring_client.py/config.py) needs no
change here.

Three levels: level 1 (always on) is name + connection status + battery,
all of it already polled by ring_client.py regardless of config. Level 2
is each card's snapshot image, written by the background poll loop when
config.ring.fetch_snapshots is on (off by default - see ring_client.py's
docstring). Level 3 is tap-to-watch-live (see _toggle_live): a real-time
WebRTC video session for whichever one tile is tapped - the only thing
that works at all on camera models the Snapshot API doesn't support (the
3rd Gen Stick Up Cam Battery - see ring_client.py's fetch_snapshot_now()
docstring), and generally the more useful "is something happening right
now" view snapshots can't give you. Only one camera can be live at once
(tapping a second tile stops the first) - decoding several video streams
at once is a very different, much heavier problem on a Pi than watching
one on demand.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Dict, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QMouseEvent, QPainter, QPen, QPixmap
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
        self._watching: Optional[str] = None  # cam_name of the tile we've asked to go live on
        self._connected: Optional[str] = None  # cam_name once a frame has actually arrived
        self._live_frame: Optional[QImage] = None
        self._watch_seq = 0  # bumped on every toggle, so a stale callback can't clobber a newer one

    def refresh(self) -> None:
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802 - leaving the page: stop decoding/streaming
        if self._watching is not None:
            self._stop_live()
        super().hideEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        for cam_name, rect in self._card_rects.items():
            if rect.contains(pos):
                self._toggle_live(cam_name)
                return

    def _toggle_live(self, cam_name: str) -> None:
        if self._ring_client is None:
            log(9, f"Ring: tile tapped for '{cam_name}' but no RingClient is wired up - ignoring")
            return
        if self._watching == cam_name:
            self._stop_live()
            return
        # Switching cameras (or starting from idle) - watch_live() itself
        # stops whatever was previously live before starting the new one,
        # so no separate stop-then-start dance is needed here.
        log(9, f"Ring: tile tapped - starting live view for '{cam_name}'")
        self._watch_seq += 1
        seq = self._watch_seq
        self._watching = cam_name
        self._connected = None
        self._live_frame = None
        self.update()
        task = asyncio.ensure_future(self._ring_client.watch_live(
            cam_name,
            lambda arr, name=cam_name, s=seq: self._on_frame(name, s, arr),
            on_ended=lambda name=cam_name, s=seq: self._on_live_ended(name, s),
        ))
        task.add_done_callback(lambda t, name=cam_name, s=seq: self._on_watch_started(name, s, t))

    def _stop_live(self) -> None:
        log(9, f"Ring: stopping live view for '{self._watching}'")
        self._watch_seq += 1
        self._watching = None
        self._connected = None
        self._live_frame = None
        self.update()
        if self._ring_client is not None:
            asyncio.ensure_future(self._ring_client.stop_live_view())

    def _on_watch_started(self, cam_name: str, seq: int, task: "asyncio.Task[bool]") -> None:
        if seq != self._watch_seq:
            return  # superseded by a later tap before this one even finished connecting
        try:
            ok = task.result()
        except Exception as exc:  # noqa: BLE001 - report it, don't crash the callback
            log(9, f"Ring: live view request for '{cam_name}' raised: {exc!r}")
            ok = False
        if ok:
            log(9, f"Ring: live view request for '{cam_name}' succeeded - waiting for the first frame")
        else:
            log(9, f"Ring: live view for '{cam_name}' failed to start "
                   f"(see earlier Ring: log lines above for why)")
            self._watching = None
            self.update()

    def _on_frame(self, cam_name: str, seq: int, array: "np.ndarray") -> None:
        if seq != self._watch_seq:
            return  # a frame from a session we've since stopped/switched away from
        array = np.ascontiguousarray(array)
        h, w = array.shape[0], array.shape[1]
        image = QImage(array.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self._connected = cam_name
        self._live_frame = image
        self.update()

    def _on_live_ended(self, cam_name: str, seq: int) -> None:
        if seq != self._watch_seq:
            return
        log(9, f"Ring: live view for '{cam_name}' ended")
        self._watching = None
        self._connected = None
        self._live_frame = None
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

        if self._watching == cam_name:
            self._draw_live(painter, theme, rect, cam_name)
            return

        # Whatever's on disk gets shown - fetch_snapshots only gates the
        # background poll loop that writes it periodically (see module
        # docstring).
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

            label = "Tap to watch live"
            label_font = QFont(self.font())
            label_font.setPixelSize(max(13, int(rect.height() * 0.11)))
            label_rect = QRectF(rect.x(), icon_rect.bottom() + 6, rect.width(), 26)
            painter.setFont(label_font)
            painter.setPen(QPen(theme.text_dim))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

    def _draw_live(self, painter: QPainter, theme: QtTheme, rect: QRectF, cam_name: str) -> None:
        badge_font = tracked_font(self.font(), 1.0)
        badge_font.setBold(True)
        badge_font.setPixelSize(max(13, int(rect.height() * 0.1)))

        if self._connected == cam_name and self._live_frame is not None:
            fitted = _fit_aspect(rect.adjusted(3, 3, -3, -3),
                                  self._live_frame.width() / self._live_frame.height())
            painter.drawImage(fitted, self._live_frame)
            badge_text, badge_color = "● LIVE", theme.danger
        else:
            icon_r = min(rect.width(), rect.height()) * 0.16
            icon_rect = QRectF(rect.center().x() - icon_r, rect.center().y() - icon_r * 1.4, icon_r * 2, icon_r * 2)
            _icon_camera(painter, icon_rect, theme.secondary)
            badge_text, badge_color = "CONNECTING…", theme.secondary

        badge_pad = 6.0
        text_w = QFontMetricsF(badge_font).horizontalAdvance(badge_text)
        badge_rect = QRectF(rect.x() + 8, rect.y() + 8, text_w + badge_pad * 2, badge_font.pixelSize() + badge_pad)
        painter.setBrush(QColor(3, 5, 9, 190))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 4, 4)
        painter.setFont(badge_font)
        painter.setPen(QPen(badge_color))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

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
