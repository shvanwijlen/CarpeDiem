"""A - AIS traffic list, StartrekGraphical (Qt) version of
hmi/pages/ais_page.py - see that module's docstring for the full layout
spec and reasoning. Drawn as one custom-painted QWidget (like RadarView/
CompassRose) rather than composed of many child widgets - this is a
26+13-cell data grid redrawn from live data every refresh, which fits
immediate-mode painting better than maintaining that many QLabels.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from carpediem.ais.service import AisService, DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.ais.vessel_tracker import VesselProximity
from carpediem.display_data import display_data
from carpediem.hmi.util import decimal_to_dms
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import draw_arrow, draw_solid_text

LEFT_WIDTH_FRACTION = 0.85
ROWS = 13
VESSELS_PER_HALF = 13
TOTAL_VESSELS = 26


def _fit_pixel_size(text: str, max_w: float, max_h: float, max_size: int, bold: bool, min_size: int = 11) -> int:
    """Largest pixel size (<= max_size) whose rendered text still fits
    within max_w x max_h - same idea as hmi/widgets.py's fit_text(), Qt
    port using QFontMetrics instead of pygame.font.Font.size()."""
    size = max_size
    while size > min_size:
        font = QFont()
        font.setBold(bold)
        font.setPixelSize(size)
        fm = QFontMetrics(font)
        if fm.horizontalAdvance(text) <= max_w and fm.height() <= max_h:
            break
        size -= 1
    return size


def _truncate(painter: QPainter, font: QFont, s: str, max_width: float) -> str:
    fm = QFontMetrics(font)
    if fm.horizontalAdvance(s) <= max_width:
        return s
    while s and fm.horizontalAdvance(s + "…") > max_width:
        s = s[:-1]
    return (s + "…") if s else "…"


class AisPage(QWidget):
    def __init__(self, theme: QtTheme, ais_service: Optional[AisService], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._ais_service = ais_service

    def refresh(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        w, h = self.width(), self.height()

        left_w = w * LEFT_WIDTH_FRACTION
        right_x = left_w

        vessels: List[VesselProximity] = []
        own_speed_knots = 0.0
        own_cog = DEFAULT_OWN_COG_DEG
        if self._ais_service is not None:
            vessels = self._ais_service.all_vessels_by_distance()[:TOTAL_VESSELS]
            own_fix = self._ais_service.reader.own_fix
            own_speed_knots = own_fix.sog_knots or 0.0
            own_cog = own_fix.cog if own_fix.cog is not None else DEFAULT_OWN_COG_DEG

        half_w = left_w / 2
        row_h = h / ROWS
        for col in range(2):
            col_x = col * half_w
            col_w = half_w if col == 0 else left_w - half_w
            for i in range(VESSELS_PER_HALF):
                idx = col * VESSELS_PER_HALF + i
                cell = QRectF(col_x, i * row_h, col_w, row_h)
                v = vessels[idx] if idx < len(vessels) else None
                if v is not None:
                    self._draw_vessel_cell(painter, cell, theme, v, own_speed_knots, own_cog)

        self._draw_status_rail(painter, QRectF(right_x, 0, w - right_x, h), theme, row_h)

    def _draw_vessel_cell(self, painter: QPainter, cell: QRectF, theme: QtTheme,
                           r: VesselProximity, own_speed_knots: float, own_cog: float) -> None:
        pad = 6.0
        name_w = cell.width() * 0.44
        dist_w = cell.width() * 0.17
        speed_w = cell.width() * 0.17
        course_w = cell.width() * 0.12
        look_w = cell.width() - name_w - dist_w - speed_w - course_w

        sog_knots = r.vessel.sog_knots or 0.0
        sog_kmh = sog_knots * 1.852
        stationary = sog_knots < 0.2
        if stationary:
            color = theme.neutral
        else:
            behind_and_faster = (r.relative_bearing_deg is not None and abs(r.relative_bearing_deg) > 90
                                  and sog_knots > own_speed_knots)
            if behind_and_faster:
                color = theme.danger
            elif sog_kmh > FAST_VESSEL_THRESHOLD_KMH:
                color = theme.warn
            else:
                color = theme.ok

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(QRectF(cell.x(), cell.y(), 3, cell.height()))

        x = cell.x() + pad + 3

        # See draw_solid_text()'s docstring: neither QFont.setWeight(Medium)
        # nor redrawing the same fill twice (both tried first) made this
        # list read as solid rather than thin on the actual hardware -
        # a geometric stroke is what actually works.
        name_font = QFont(self.font())
        name_font.setPixelSize(15)
        name = r.vessel.name or f"MMSI {r.vessel.mmsi}"
        name = _truncate(painter, name_font, name, name_w - pad * 2)
        draw_solid_text(painter, QRectF(x, cell.y(), name_w - pad, cell.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name, name_font, theme.text)
        x += name_w

        small_font = QFont(self.font())
        small_font.setPixelSize(14)
        draw_solid_text(painter, QRectF(x, cell.y(), dist_w - pad, cell.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         f"{r.distance_km:.1f}km", small_font, theme.text_dim)
        x += dist_w

        draw_solid_text(painter, QRectF(x, cell.y(), speed_w - pad, cell.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         f"{sog_kmh:.1f}", small_font, theme.text_dim)
        x += speed_w

        course_str = f"{r.vessel.cog_deg:.0f}°" if r.vessel.cog_deg is not None else "--"
        draw_solid_text(painter, QRectF(x, cell.y(), course_w - pad, cell.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         course_str, small_font, theme.text_dim)
        x += course_w

        look_center = QPointF(x + look_w / 2, cell.center().y())
        if stationary:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(look_center, 4, 4)
        elif r.relative_bearing_deg is not None:
            heading = ((r.vessel.cog_deg - own_cog) % 360) if r.vessel.cog_deg is not None else r.relative_bearing_deg
            draw_arrow(painter, look_center, cell.height() * 0.6, heading, color)

    # -- right-hand status rail -------------------------------------------

    def _draw_status_rail(self, painter: QPainter, rect: QRectF, theme: QtTheme, row_h: float) -> None:
        reader = self._ais_service.reader if self._ais_service is not None else None
        own_fix = reader.own_fix if reader is not None else None

        def cell_rect(i: int) -> QRectF:
            return QRectF(rect.x(), rect.y() + i * row_h, rect.width(), row_h)

        # The count cells only ever hold a 1-3 digit number, so their fit
        # size is height-bound, not width-bound - compute that size once
        # (from the cell's own geometry, via a representative 2-digit
        # string) and reuse it for all three counts *and* force course/
        # speed to the same exact size, per explicit request. Course/speed
        # are much longer strings ("12.0 km/h") that would auto-fit to a
        # visibly smaller size if left to fit their own width within this
        # narrow column - forcing the shared size intentionally accepts
        # that "12.0 km/h" may then run close to/past the pill's edges.
        count_cell = cell_rect(0)
        count_size = _fit_pixel_size("88", count_cell.width() - 8, count_cell.height() - 8,
                                      max_size=int(count_cell.height() * 1.8), bold=True, min_size=14)

        self._status_count_cell(painter, cell_rect(0), theme, display_data.get("VesselsBehindMe"),
                                 theme.danger, count_size)
        self._status_count_cell(painter, cell_rect(1), theme, display_data.get("VesselsFasterThan10"),
                                 theme.warn, count_size)
        self._status_count_cell(painter, cell_rect(2), theme, display_data.get("VesselsOther"),
                                 theme.ok, count_size)

        course_str = f"{own_fix.cog:.0f}°" if own_fix and own_fix.cog is not None else "--"
        self._status_text_cell(painter, cell_rect(3), theme, course_str, max_size=count_size, min_size=count_size)

        speed_str = f"{(own_fix.sog_knots or 0) * 1.852:.1f} km/h" if own_fix else "--"
        self._status_text_cell(painter, cell_rect(4), theme, speed_str, max_size=count_size, min_size=count_size)

        lat_str = decimal_to_dms(own_fix.lat, "N", "S") if own_fix and own_fix.lat is not None else "--"
        self._status_text_cell(painter, cell_rect(5), theme, lat_str, size=13)

        lon_str = decimal_to_dms(own_fix.lon, "E", "W") if own_fix and own_fix.lon is not None else "--"
        self._status_text_cell(painter, cell_rect(6), theme, lon_str, size=13)

        sent = (reader.own_reports_type18 + reader.own_reports_type19 + reader.own_reports_other) if reader else None
        self._status_text_cell(painter, cell_rect(7), theme, f"S:{sent}" if sent is not None else "S:--",
                                align=Qt.AlignmentFlag.AlignLeft)

        received = reader.received_reports if reader else None
        self._status_text_cell(painter, cell_rect(8), theme, f"R:{received}" if received is not None else "R:--",
                                align=Qt.AlignmentFlag.AlignLeft)

        self._status_antenna_cell(painter, cell_rect(9), theme, display_data.get("AISAntenna"))

        for i in (10, 11, 12):
            c = cell_rect(i).adjusted(4, 4, -4, -4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.panel_bg)
            painter.drawRoundedRect(c, 10, 10)

    def _status_count_cell(self, painter: QPainter, cell: QRectF, theme: QtTheme, value, bg_color: QColor,
                            size: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRect(cell)
        text = "--" if value is None else str(int(value))
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(size)
        painter.setFont(font)
        painter.setPen(QPen(theme.bg))
        painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, text)

    def _status_text_cell(self, painter: QPainter, cell: QRectF, theme: QtTheme, text: str,
                           align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter, size: int = 16,
                           max_size: Optional[int] = None, min_size: int = 11) -> None:
        c = cell.adjusted(4, 4, -4, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.panel_bg)
        painter.drawRoundedRect(c, 14, 14)
        if align == Qt.AlignmentFlag.AlignCenter:
            # Auto-sized to fill the cell (both width and height) instead
            # of a fixed pixel size - "180°"/"12.0 km/h"/the DMS lat/lon
            # strings all previously rendered much smaller than the box
            # actually had room for. When max_size == min_size (course/
            # speed, forced to match the count cells above) this skips
            # the shrink-to-fit loop entirely and just uses that exact
            # size, even if it runs close to the pill's edges - see
            # _draw_status_rail's count_size.
            fit_size = _fit_pixel_size(text, c.width() - 16, c.height() - 8,
                                        max_size=max_size or int(c.height()), bold=False, min_size=min_size)
            font = QFont(self.font())
            font.setPixelSize(fit_size)
            painter.setFont(font)
            painter.setPen(QPen(theme.text))
            painter.drawText(c, Qt.AlignmentFlag.AlignCenter, text)
        else:
            font = QFont(self.font())
            font.setPixelSize(max(11, size))
            painter.setFont(font)
            painter.setPen(QPen(theme.text))
            text_rect = c.adjusted(10, 0, -10, 0)
            painter.drawText(text_rect, int(align) | int(Qt.AlignmentFlag.AlignVCenter), text)

    def _status_antenna_cell(self, painter: QPainter, cell: QRectF, theme: QtTheme, antenna) -> None:
        if antenna is None:
            bg, text_color = theme.panel_bg, theme.text_dim
        else:
            bg = theme.ok if antenna == 1 else theme.danger
            text_color = theme.bg
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRect(cell)
        fit_size = _fit_pixel_size("ANTENNA", cell.width() - 16, cell.height() - 8,
                                    max_size=int(cell.height()), bold=True, min_size=10)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(fit_size)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, "ANTENNA")
