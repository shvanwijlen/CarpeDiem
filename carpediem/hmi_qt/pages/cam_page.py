"""C - Cam, StartrekGraphical (Qt) version. A grid of cards, one per Ring
camera, built directly from config.ring.camera_field_map/
camera_connection_field_map rather than a hardcoded camera list, so a
renamed or newly added camera (see ring_client.py/config.py) needs no
change here.

Three levels: level 1 (always on) is name + connection status + battery,
all of it already polled by ring_client.py regardless of config. Level 2
is each card's snapshot image, written by the background poll loop when
config.ring.fetch_snapshots is on (off by default - see ring_client.py's
docstring). Level 3 is live video: every camera starts watching live as
soon as this page becomes visible (see showEvent, which calls
_start_live() for each camera) and stops when it's hidden - the only
thing that works at all on camera models the Snapshot API doesn't
support (the 3rd Gen Stick Up Cam Battery - see ring_client.py's
fetch_snapshot_now() docstring), and generally the more useful "is
something happening right now" view snapshots can't give you. All 4 run
simultaneously - a real, currently-unverified load on the Pi (aiortc
decodes in software) - see ring_live_view.py's docstring.

Tapping a tile in the small grid expands it to fill the page (see
_expanded/_draw_expanded); tapping again anywhere returns to the grid.
This only changes what's drawn - all 4 cameras keep streaming in the
background regardless of which one (if any) is expanded, so switching
between them is instant rather than re-negotiating a new session.
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
        self._watching: set = set()  # cam_names we've asked to go live
        self._connected: set = set()  # cam_names among those with a frame actually in hand
        self._live_frames: Dict[str, QImage] = {}
        self._watch_seq: Dict[str, int] = {}  # per-camera - guards against a stale callback
        self._expanded: Optional[str] = None  # cam_name shown full-screen, or None for the grid

    def refresh(self) -> None:
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - page opened: go live on every camera
        super().showEvent(event)
        for cam_name in config.ring.camera_field_map:
            if cam_name not in self._watching:
                self._start_live(cam_name)

    def hideEvent(self, event) -> None:  # noqa: N802 - leaving the page: stop decoding/streaming
        for cam_name in list(self._watching):
            self._stop_live(cam_name)
        self._expanded = None
        super().hideEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # While a tile is expanded, any tap closes it back to the grid -
        # all cameras keep streaming in the background either way (see
        # showEvent), this only changes what's drawn.
        if self._expanded is not None:
            self._expanded = None
            self.update()
            return
        pos = event.position()
        for cam_name, rect in self._card_rects.items():
            if rect.contains(pos):
                self._expanded = cam_name
                self.update()
                return

    def _start_live(self, cam_name: str) -> None:
        if self._ring_client is None:
            log(10, f"Ring: wanted to start live view for '{cam_name}' but no RingClient is wired up - ignoring")
            return
        log(10, f"Ring: starting live view for '{cam_name}'")
        seq = self._watch_seq.get(cam_name, 0) + 1
        self._watch_seq[cam_name] = seq
        self._watching.add(cam_name)
        self._connected.discard(cam_name)
        self._live_frames.pop(cam_name, None)
        self.update()
        task = asyncio.ensure_future(self._ring_client.watch_live(
            cam_name,
            lambda arr, name=cam_name, s=seq: self._on_frame(name, s, arr),
            on_ended=lambda name=cam_name, s=seq: self._on_live_ended(name, s),
        ))
        task.add_done_callback(lambda t, name=cam_name, s=seq: self._on_watch_started(name, s, t))

    def _stop_live(self, cam_name: str) -> None:
        log(10, f"Ring: stopping live view for '{cam_name}'")
        self._watch_seq[cam_name] = self._watch_seq.get(cam_name, 0) + 1
        self._watching.discard(cam_name)
        self._connected.discard(cam_name)
        self._live_frames.pop(cam_name, None)
        self.update()
        if self._ring_client is not None:
            asyncio.ensure_future(self._ring_client.stop_live_view(cam_name))

    def _on_watch_started(self, cam_name: str, seq: int, task: "asyncio.Task[bool]") -> None:
        if self._watch_seq.get(cam_name) != seq:
            return  # superseded by a later toggle before this one even finished connecting
        try:
            ok = task.result()
        except Exception as exc:  # noqa: BLE001 - report it, don't crash the callback
            log(10, f"Ring: live view request for '{cam_name}' raised: {exc!r}")
            ok = False
        if ok:
            log(10, f"Ring: live view request for '{cam_name}' succeeded - waiting for the first frame")
        else:
            log(10, f"Ring: live view for '{cam_name}' failed to start "
                   f"(see earlier Ring: log lines above for why)")
            self._watching.discard(cam_name)
            self.update()

    def _on_frame(self, cam_name: str, seq: int, array: "np.ndarray") -> None:
        if self._watch_seq.get(cam_name) != seq:
            return  # a frame from a session we've since stopped/restarted
        array = np.ascontiguousarray(array)
        h, w = array.shape[0], array.shape[1]
        image = QImage(array.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self._connected.add(cam_name)
        self._live_frames[cam_name] = image
        self.update()

    def _on_live_ended(self, cam_name: str, seq: int) -> None:
        if self._watch_seq.get(cam_name) != seq:
            return
        log(10, f"Ring: live view for '{cam_name}' ended")
        self._watching.discard(cam_name)
        self._connected.discard(cam_name)
        self._live_frames.pop(cam_name, None)
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

        if self._expanded is not None and self._expanded in config.ring.camera_field_map:
            self._draw_expanded(painter, theme, QRectF(0, 0, w, h).adjusted(14, 10, -14, -14), self._expanded)
            return

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

    def _draw_expanded(self, painter: QPainter, theme: QtTheme, rect: QRectF, cam_name: str) -> None:
        """Full-page view of one tapped tile - same title/video/battery
        layout as _draw_card, just at (nearly) full page size, since all
        the font/icon sizing in those helpers already scales off the
        rect's own height rather than being hardcoded for the small grid
        cell size."""
        battery_field = config.ring.camera_field_map[cam_name]
        connection_field = config.ring.camera_connection_field_map[cam_name]
        connection = display_data.get(connection_field)
        battery = display_data.get(battery_field)
        wired = battery_field in WIRED_BATTERY_FIELDS

        online = connection == "online" if connection is not None else None
        status_color = theme.ok if online else (theme.danger if online is not None else theme.neutral)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(rect, 14, 14)

        title_h = max(36, int(rect.height() * 0.09))
        footer_h = max(32, int(rect.height() * 0.08))
        self._draw_card_title(painter, theme, QRectF(rect.x(), rect.y(), rect.width(), title_h),
                               cam_name, status_color, connection)

        video_rect = QRectF(rect.x() + 14, rect.y() + title_h, rect.width() - 28,
                             rect.height() - title_h - footer_h - 8)
        self._draw_snapshot(painter, theme, video_rect, cam_name, snapshot_key(battery_field), show_live_badge=False)

        # Badge in the video area's top-right corner (mirrors the LIVE/
        # CONNECTING badge _draw_live already puts top-left) rather than
        # the title bar, which already has the name and connection status
        # both drawn there.
        close_font = tracked_font(self.font(), 0.8)
        close_font.setPixelSize(max(12, int(video_rect.height() * 0.045)))
        close_text = "tap anywhere to close"
        pad = 6.0
        text_w = QFontMetricsF(close_font).horizontalAdvance(close_text)
        close_rect = QRectF(video_rect.right() - text_w - pad * 2 - 8, video_rect.y() + 8,
                             text_w + pad * 2, close_font.pixelSize() + pad)
        painter.setBrush(QColor(3, 5, 9, 190))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(close_rect, 4, 4)
        painter.setFont(close_font)
        painter.setPen(QPen(theme.text_dim))
        painter.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, close_text)

        footer_rect = QRectF(rect.x(), rect.bottom() - footer_h, rect.width(), footer_h)
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

    def _draw_snapshot(self, painter: QPainter, theme: QtTheme, rect: QRectF, cam_name: str, key: str,
                       show_live_badge: bool = True) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.bg_hi)
        painter.drawRoundedRect(rect, 8, 8)

        if cam_name in self._watching:
            self._draw_live(painter, theme, rect, cam_name, show_live_badge=show_live_badge)
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

    def _draw_live(self, painter: QPainter, theme: QtTheme, rect: QRectF, cam_name: str,
                   show_live_badge: bool = True) -> None:
        frame = self._live_frames.get(cam_name)
        connected = cam_name in self._connected and frame is not None
        if connected:
            fitted = _fit_aspect(rect.adjusted(3, 3, -3, -3), frame.width() / frame.height())
            painter.drawImage(fitted, frame)
        else:
            icon_r = min(rect.width(), rect.height()) * 0.16
            icon_rect = QRectF(rect.center().x() - icon_r, rect.center().y() - icon_r * 1.4, icon_r * 2, icon_r * 2)
            _icon_camera(painter, icon_rect, theme.secondary)

        # The LIVE badge is redundant once a tile fills the whole page (see
        # _draw_expanded) - it's only meant to distinguish a live feed from
        # a static snapshot at a glance in the small grid. CONNECTING still
        # shows everywhere, expanded or not, since that's real information.
        if connected and not show_live_badge:
            return
        badge_text, badge_color = ("● LIVE", theme.danger) if connected else ("CONNECTING…", theme.secondary)
        badge_font = tracked_font(self.font(), 1.0)
        badge_font.setBold(True)
        badge_font.setPixelSize(max(13, int(rect.height() * 0.1)))
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
