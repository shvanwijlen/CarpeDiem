"""M - Main page, StartrekGraphical (Qt) version of hmi/pages/main_page.py.
Same layout/content/percentages (see that module's docstring for the full
spec breakdown and the reasoning behind each section), same accumulated
refinements (no divider lines except the top bar's, no radar sweep/no
own-ship marker, right-aligned col2/col3 captions, 1-decimal voltages,
house battery as a voltage-mapped fill icon, SOC+house/starter nudged
left) - just rendered with real QWidgets/QPainter instead of pygame.

Layout is done with explicit setGeometry() in resizeEvent rather than Qt
layouts: the percentages in the spec don't map cleanly onto nested
QLayout stretch factors once you get to 3-level splits (section C's 3
columns are percentages *of the screen*, not of their immediate parent),
and pixel-exact placement here mirrors the pygame version's own rect math
directly, which made it easy to port faithfully.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from carpediem.ais.service import AisService, DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.hmi_qt.icons import HOUSE_BATTERY_EMPTY_V, HOUSE_BATTERY_FULL_V, AlternatorIcon, SolarIcon, StarterBatteryIcon
from carpediem.hmi.util import format_duration, system_uptime_seconds
from carpediem.hmi_qt.theme import QtTheme
from carpediem.hmi_qt.widgets import BatteryGauge, CompassRose, RadarView, tracked_font

LEFT_WIDTH_FRACTION = 0.64
SECTION_A_FRACTION = 39 / 86
SECTION_B_FRACTION = 11 / 86
COL1_WIDTH_FRACTION = 0.17  # of full screen width - SOC gauge
COL2_WIDTH_FRACTION = 0.23  # of full screen width - battery voltages
COL2_SHIFT_PX = 14  # nudges house/starter cells left, into col1's slack


def _rgb(c: QColor) -> str:
    return f"rgb({c.red()},{c.green()},{c.blue()})"


class LabelValue(QWidget):
    """Icon (if any) + right-aligned tracked caption + bottom-left value -
    Qt port of hmi/widgets.py's label_value()."""

    def __init__(self, theme: QtTheme, caption: str, value_color: QColor,
                 icon_widget: Optional[QWidget] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.icon_widget = icon_widget
        if icon_widget is not None:
            icon_widget.setParent(self)

        self.caption_label = QLabel(caption, self)
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.caption_label.setStyleSheet(f"color: {_rgb(theme.text_dim)};")

        self.value_label = QLabel("--", self)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        vf = QFont(self.value_label.font())
        vf.setBold(True)
        self.value_label.setFont(vf)
        self.value_label.setStyleSheet(f"color: {_rgb(value_color)};")

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        pad = 4
        if self.icon_widget is not None:
            icon_size = h - 2 * pad
            self.icon_widget.setGeometry(pad, pad, icon_size, icon_size)
            text_x = pad + icon_size + pad
        else:
            text_x = pad
        text_w = max(1, w - text_x - pad)

        cap_font = tracked_font(self.caption_label.font(), 1.0)
        cap_font.setPixelSize(max(10, h // 6))
        self.caption_label.setFont(cap_font)
        self.caption_label.setGeometry(text_x, pad, text_w, h // 3)

        val_font = QFont(self.value_label.font())
        val_font.setPixelSize(max(14, h // 3))
        self.value_label.setFont(val_font)
        val_h = h // 3 + 6
        self.value_label.setGeometry(text_x, h - val_h - 2, text_w, val_h)


class FitTextBanner(QWidget):
    """Bridge/lock banner - font auto-sized to fill the available height,
    same as hmi/widgets.py's fit_text()."""

    def __init__(self, theme: QtTheme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._text = "-- NO UPCOMING BRIDGE / LOCK --"
        self._has_value = False

    def set_text(self, text: str, has_value: bool) -> None:
        self._text = text
        self._has_value = has_value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        rect = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        painter.setBrush(theme.panel_bg)
        painter.setPen(QPen(theme.panel_border, 1))
        painter.drawRoundedRect(rect, 14, 14)

        color = theme.text if self._has_value else theme.text_dim
        painter.setPen(QPen(color))
        size = int(rect.height())
        font = QFont(self.font())
        font.setBold(True)
        padding = 16
        while size > 10:
            font.setPixelSize(size)
            fm = QFontMetrics(font)
            if fm.horizontalAdvance(self._text) <= rect.width() - padding and fm.height() <= rect.height() - padding:
                break
            size -= 1
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class MainPage(QWidget):
    def __init__(self, theme: QtTheme, ais_service: Optional[AisService], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._ais_service = ais_service

        self.time_label = QLabel("--:--", self)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(f"color: {_rgb(theme.text_dim)};")
        tf = QFont(self.time_label.font())
        tf.setBold(True)
        self.time_label.setFont(tf)

        self.uptime_label = QLabel("00:00:00", self)
        self.uptime_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.uptime_label.setStyleSheet(f"color: {_rgb(theme.text_dim)};")
        uf = QFont(self.uptime_label.font())
        uf.setBold(True)
        self.uptime_label.setFont(uf)

        self.compass = CompassRose(theme, self)
        self.banner = FitTextBanner(theme, self)

        self.soc_gauge = BatteryGauge(theme, show_label=True, parent=self)

        self.house_icon = BatteryGauge(theme, show_label=False, parent=self)
        self.house_cell = LabelValue(theme, "HOUSE 12V", theme.secondary, self.house_icon, self)
        self.starter_icon = StarterBatteryIcon(theme, self)
        self.starter_cell = LabelValue(theme, "STARTER", theme.tertiary, self.starter_icon, self)

        self.alt_icon = AlternatorIcon(theme, self)
        self.alt_cell = LabelValue(theme, "DC ALT", theme.accent, self.alt_icon, self)
        self.solar_icon = SolarIcon(theme, self)
        self.solar_cell = LabelValue(theme, "SOLAR", theme.ok, self.solar_icon, self)

        self.radar = RadarView(theme, self)

    # -- layout -------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        left_w = int(w * LEFT_WIDTH_FRACTION)

        a_h = int(h * SECTION_A_FRACTION)
        b_h = int(h * SECTION_B_FRACTION)
        c_h = h - a_h - b_h

        half_w = left_w // 2
        self.time_label.setGeometry(0, 0, half_w, a_h // 2)
        self.uptime_label.setGeometry(0, a_h // 2, half_w, a_h - a_h // 2)
        self.compass.setGeometry(half_w, 0, left_w - half_w, a_h)

        self.banner.setGeometry(0, a_h, left_w, b_h)

        col1_w = int(w * COL1_WIDTH_FRACTION)
        col2_w = int(w * COL2_WIDTH_FRACTION)
        col3_w = left_w - col1_w - col2_w
        c_y = a_h + b_h

        soc_rect = QRectF(10, c_y + 12, col1_w * 0.58, c_h - 24)
        self.soc_gauge.setGeometry(int(soc_rect.x()), int(soc_rect.y()), int(soc_rect.width()), int(soc_rect.height()))

        col2_x = col1_w - COL2_SHIFT_PX
        self.house_cell.setGeometry(col2_x, c_y, col2_w, c_h // 2)
        self.starter_cell.setGeometry(col2_x, c_y + c_h // 2, col2_w, c_h - c_h // 2)

        col3_x = col1_w + col2_w
        self.alt_cell.setGeometry(col3_x, c_y, col3_w, c_h // 2)
        self.solar_cell.setGeometry(col3_x, c_y + c_h // 2, col3_w, c_h - c_h // 2)

        self.radar.setGeometry(left_w, 0, w - left_w, h)

        tf = QFont(self.time_label.font())
        tf.setPixelSize(max(16, int(self.time_label.height() * 0.55)))
        self.time_label.setFont(tf)
        uf = QFont(self.uptime_label.font())
        uf.setPixelSize(max(12, int(self.uptime_label.height() * 0.4)))
        self.uptime_label.setFont(uf)

        super().resizeEvent(event)

    # -- data refresh --------------------------------------------------

    def refresh(self) -> None:
        self.time_label.setText(datetime.now().strftime("%H:%M"))
        self.uptime_label.setText(format_duration(system_uptime_seconds()))

        theme = self._theme
        course = display_data.get("Course")
        recal = display_data.get("WindspeedCalculatedRecalibrated")
        experienced = display_data.get("WindspeedCalculatedAsExperienced")
        speed = display_data.get("Speed")

        markers = []
        if course is not None:
            markers.append((float(course), theme.secondary))
        if recal is not None:
            markers.append((float(recal), theme.tertiary))
        if experienced is not None:
            markers.append((float(experienced), theme.ok))
        self.compass.set_values(course, speed, markers)

        next_object = display_data.get("NextObject")
        if next_object:
            self.banner.set_text(str(next_object).upper(), True)
        else:
            self.banner.set_text("-- NO UPCOMING BRIDGE / LOCK --", False)

        soc = display_data.get("Battery SOC (%)")
        self.soc_gauge.set_percent(soc)

        house_v = display_data.get("Battery0 Voltage (V)")
        starter_v = display_data.get("Starter battery (V)")
        if house_v is None:
            self.house_icon.set_percent(None)
        else:
            span = HOUSE_BATTERY_FULL_V - HOUSE_BATTERY_EMPTY_V
            self.house_icon.set_percent(max(0.0, min(100.0, (house_v - HOUSE_BATTERY_EMPTY_V) / span * 100)))
        self.house_cell.set_value(f"{house_v:.1f} V" if house_v is not None else "--")
        self.starter_cell.set_value(f"{starter_v:.1f} V" if starter_v is not None else "--")

        dc_w = display_data.get("DC Power (W)")
        pv_w = display_data.get("PV Power (W)")
        self.alt_cell.set_value(f"{dc_w:.0f} W" if dc_w is not None else "--")
        self.solar_cell.set_value(f"{pv_w:.0f} W" if pv_w is not None else "--")

        self._refresh_radar()

    def _refresh_radar(self) -> None:
        theme = self._theme
        max_range_km = config.ais.max_range_km
        vessels: List[Tuple[float, float, bool, QColor, float]] = []
        if self._ais_service is not None:
            own_speed_knots = self._ais_service.reader.own_fix.sog_knots or 0.0
            own_cog = (self._ais_service.reader.own_fix.cog
                       if self._ais_service.reader.own_fix.cog is not None else DEFAULT_OWN_COG_DEG)
            for r in self._ais_service.nearby_vessels():
                if r.relative_bearing_deg is None:
                    continue
                sog_knots = r.vessel.sog_knots or 0.0
                sog_kmh = sog_knots * 1.852
                if sog_knots < 0.2:
                    vessels.append((r.relative_bearing_deg, r.distance_km, True, theme.neutral, 0.0))
                    continue
                behind_and_faster = abs(r.relative_bearing_deg) > 90 and sog_knots > own_speed_knots
                if behind_and_faster:
                    color = theme.danger
                elif sog_kmh > FAST_VESSEL_THRESHOLD_KMH:
                    color = theme.warn
                else:
                    color = theme.ok
                heading = (r.vessel.cog_deg - own_cog) % 360 if r.vessel.cog_deg is not None else r.relative_bearing_deg
                vessels.append((r.relative_bearing_deg, r.distance_km, False, color, heading))
        self.radar.set_data(max_range_km, vessels)
