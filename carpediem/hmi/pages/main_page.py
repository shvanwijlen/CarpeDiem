"""M - Main page. Layout ported 1:1 from the "M" tab of the Screen design
v02.xlsx spreadsheet (percentages below are quoted from the "Claude
prompts" tab, cross-checked against the M tab's cell layout):

Below the 14%-tall top bar, the remaining 86% of the height splits into a
64%-wide left column and 36%-wide right column (thin divider between).

Right column (full 86% height): a course-up vessel radar - own ship as a
fixed blue arrow pointing up at the center, AIS targets plotted at their
distance/relative-bearing, colored by the same rule as the AIS-page
counters (see ais/service.py's _print_loop: red = behind and faster than
us, orange = faster than FAST_VESSEL_THRESHOLD_KMH, green = everything
else, grey dot = not moving).

Left column, top to bottom (three horizontal sections, thin dividers):
  A (39% of total height) - left half: 24h clock (big) over Pi uptime
                              (smaller); right half: a north-up compass
                              rose showing course/speed as text, plus 3
                              rectangle markers (own course, wind direction
                              recalibrated for course drift since Bresser
                              calibration, and wind as experienced on deck)
  B (11%) - next bridge/lock + VHF/phone, font sized to fill the field
            (blank for now - "NextObject" has no producer yet)
  C (36%) - SOC battery gauge, then house/starter battery voltage, then
            DC/solar wattage - each with a small icon

Note: the spec's intro sentence for section A also mentions "calculated
wind speed", but the detailed rows that follow (and the two field names
actually given - WindspeedCalculatedRecalibrated/AsExperienced) only
define *direction* values, not a wind-speed number with nowhere specified
to put it - so no separate wind-speed readout is drawn here.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

import pygame

from carpediem.ais.service import AisService, DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.hmi.theme import Theme
from carpediem.hmi.util import format_duration, system_uptime_seconds
from carpediem.hmi.widgets import (
    arrow,
    battery_bar,
    compass_rose,
    divider_h,
    divider_v,
    dot,
    draw_text,
    fit_text,
    label_value,
    panel,
)

Rect = pygame.Rect

LEFT_WIDTH_FRACTION = 0.64
SECTION_A_FRACTION = 39 / 86
SECTION_B_FRACTION = 11 / 86
# Section C takes the remainder of the left column's height.

COL1_WIDTH_FRACTION = 0.17  # of full screen width - SOC gauge
COL2_WIDTH_FRACTION = 0.23  # of full screen width - battery voltages
# Col 3 (DC/solar wattage) absorbs whatever's left of the left column.


def _icon_battery(surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
    body = rect.inflate(-rect.width // 4, -rect.height // 5)
    nub = pygame.Rect(0, 0, max(3, body.width // 4), max(2, rect.height // 8))
    nub.midleft = (body.right, body.centery)
    pygame.draw.rect(surface, theme.secondary, body, width=2, border_radius=2)
    pygame.draw.rect(surface, theme.secondary, nub, border_radius=1)
    pygame.draw.line(surface, theme.secondary, (body.centerx, body.top + 2), (body.centerx, body.bottom - 2), 2)


def _icon_starter_battery(surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
    body = rect.inflate(-rect.width // 5, -rect.height // 4)
    pygame.draw.rect(surface, theme.tertiary, body, width=2, border_radius=2)
    for dx in (0.3, 0.7):
        x = body.x + int(body.width * dx)
        pygame.draw.line(surface, theme.tertiary, (x, body.top - 4), (x, body.top), 2)


def _icon_alternator(surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
    r = min(rect.width, rect.height) // 2 - 2
    pygame.draw.circle(surface, theme.accent, rect.center, r, width=2)
    prev = None
    for i in range(9):
        t = i / 8
        x = rect.centerx - r * 0.7 + t * r * 1.4
        y = rect.centery + math.sin(t * math.pi * 2) * r * 0.35
        if prev is not None:
            pygame.draw.line(surface, theme.accent, prev, (x, y), 2)
        prev = (x, y)


def _icon_solar(surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
    body = rect.inflate(-rect.width // 6, -rect.height // 6)
    pygame.draw.rect(surface, theme.ok, body, width=2, border_radius=2)
    for i in range(1, 3):
        x = body.x + body.width * i // 3
        pygame.draw.line(surface, theme.ok, (x, body.top), (x, body.bottom), 1)
    y = body.y + body.height // 2
    pygame.draw.line(surface, theme.ok, (body.left, y), (body.right, y), 1)


class MainPage:
    def __init__(self, ais_service: Optional[AisService]) -> None:
        self._ais_service = ais_service

    # -- top-level layout -------------------------------------------------

    def draw(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        left_w = int(rect.width * LEFT_WIDTH_FRACTION)
        left_rect = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right_rect = pygame.Rect(rect.x + left_w, rect.y, rect.width - left_w, rect.height)
        divider_v(surface, right_rect.x, rect.top, rect.bottom, theme, width=2)

        self._draw_left_column(surface, left_rect, rect.width, theme)
        self._draw_radar(surface, right_rect, theme)

    # -- left column --------------------------------------------------

    def _draw_left_column(self, surface: pygame.Surface, rect: Rect, screen_width: int, theme: Theme) -> None:
        a_h = int(rect.height * SECTION_A_FRACTION)
        b_h = int(rect.height * SECTION_B_FRACTION)
        c_h = rect.height - a_h - b_h

        a_rect = pygame.Rect(rect.x, rect.y, rect.width, a_h)
        b_rect = pygame.Rect(rect.x, a_rect.bottom, rect.width, b_h)
        c_rect = pygame.Rect(rect.x, b_rect.bottom, rect.width, c_h)

        divider_h(surface, b_rect.top, rect.left, rect.right, theme)
        divider_h(surface, c_rect.top, rect.left, rect.right, theme)

        self._draw_section_a(surface, a_rect, theme)
        self._draw_section_b(surface, b_rect, theme)
        self._draw_section_c(surface, c_rect, screen_width, theme)

    def _draw_section_a(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        half_w = rect.width // 2
        clock_rect = pygame.Rect(rect.x, rect.y, half_w, rect.height)
        compass_rect = pygame.Rect(rect.x + half_w, rect.y, rect.width - half_w, rect.height)
        divider_v(surface, compass_rect.x, rect.top, rect.bottom, theme)

        time_rect = pygame.Rect(clock_rect.x, clock_rect.y, clock_rect.width, clock_rect.height // 2)
        uptime_rect = pygame.Rect(clock_rect.x, time_rect.bottom, clock_rect.width, clock_rect.height - time_rect.height)
        now_str = datetime.now().strftime("%H:%M")
        draw_text(surface, now_str, time_rect.center, theme, size=int(time_rect.height * 0.6),
                  bold=True, color=theme.accent, align="center")
        uptime_str = format_duration(system_uptime_seconds())
        draw_text(surface, uptime_str, uptime_rect.center, theme, size=int(uptime_rect.height * 0.4),
                  bold=True, color=theme.text_dim, align="center")

        self._draw_compass(surface, compass_rect, theme)

    def _draw_compass(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        radius = int(min(rect.width, rect.height) * 0.42)
        center = rect.center

        course = display_data.get("Course")
        recal = display_data.get("WindspeedCalculatedRecalibrated")
        experienced = display_data.get("WindspeedCalculatedAsExperienced")

        markers = []
        if course is not None:
            markers.append((float(course), theme.secondary))
        if recal is not None:
            markers.append((float(recal), theme.tertiary))
        if experienced is not None:
            markers.append((float(experienced), theme.ok))
        compass_rose(surface, center, radius, theme, markers=markers)

        course_str = f"{course:.0f}°" if course is not None else "--"
        speed = display_data.get("Speed")
        speed_str = f"{speed:.1f}" if speed is not None else "--"

        draw_text(surface, course_str, (center[0], center[1] - radius * 0.32), theme,
                  size=int(radius * 0.32), bold=True, color=theme.secondary, align="center")
        draw_text(surface, speed_str, (center[0], center[1] + radius * 0.14), theme,
                  size=int(radius * 0.5), bold=True, color=theme.accent, align="center")
        draw_text(surface, "km/h", (center[0], center[1] + radius * 0.62), theme,
                  size=int(radius * 0.16), bold=False, color=theme.text_dim, align="center")

    def _draw_section_b(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        panel(surface, rect.inflate(-6, -6), theme)
        value = display_data.get("NextObject")
        text = str(value) if value else "-- no upcoming bridge/lock --"
        fit_text(surface, text, rect, theme, max_size=rect.height, color=theme.text)

    def _draw_section_c(self, surface: pygame.Surface, rect: Rect, screen_width: int, theme: Theme) -> None:
        col1_w = int(screen_width * COL1_WIDTH_FRACTION)
        col2_w = int(screen_width * COL2_WIDTH_FRACTION)
        col3_w = rect.width - col1_w - col2_w

        col1 = pygame.Rect(rect.x, rect.y, col1_w, rect.height)
        col2 = pygame.Rect(col1.right, rect.y, col2_w, rect.height)
        col3 = pygame.Rect(col2.right, rect.y, col3_w, rect.height)
        divider_v(surface, col2.x, rect.top, rect.bottom, theme)
        divider_v(surface, col3.x, rect.top, rect.bottom, theme)

        soc = display_data.get("Battery SOC (%)")
        battery_bar(surface, col1.inflate(-int(col1.width * 0.4), -12), soc, theme)

        house_v = display_data.get("Battery0 Voltage (V)")
        starter_v = display_data.get("Starter battery (V)")
        top2 = pygame.Rect(col2.x, col2.y, col2.width, col2.height // 2)
        bot2 = pygame.Rect(col2.x, top2.bottom, col2.width, col2.height - top2.height)
        divider_h(surface, bot2.top, col2.left, col2.right, theme)
        label_value(surface, top2, "HOUSE 12V", f"{house_v:.2f} V" if house_v is not None else "--",
                    theme, value_color=theme.secondary, icon_draw=_icon_battery)
        label_value(surface, bot2, "STARTER", f"{starter_v:.2f} V" if starter_v is not None else "--",
                    theme, value_color=theme.tertiary, icon_draw=_icon_starter_battery)

        dc_w = display_data.get("DC Power (W)")
        pv_w = display_data.get("PV Power (W)")
        top3 = pygame.Rect(col3.x, col3.y, col3.width, col3.height // 2)
        bot3 = pygame.Rect(col3.x, top3.bottom, col3.width, col3.height - top3.height)
        divider_h(surface, bot3.top, col3.left, col3.right, theme)
        label_value(surface, top3, "DC ALT", f"{dc_w:.0f} W" if dc_w is not None else "--",
                    theme, value_color=theme.accent, icon_draw=_icon_alternator)
        label_value(surface, bot3, "SOLAR", f"{pv_w:.0f} W" if pv_w is not None else "--",
                    theme, value_color=theme.ok, icon_draw=_icon_solar)

    # -- right column: vessel radar ---------------------------------------

    def _draw_radar(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        panel(surface, rect, theme, border=False)
        center = rect.center
        radius = min(rect.width, rect.height) // 2 - 12

        max_range_km = config.ais.max_range_km

        for frac in (1 / 3, 2 / 3, 1.0):
            pygame.draw.circle(surface, theme.panel_border, center, int(radius * frac), width=1)
        draw_text(surface, f"{max_range_km:.0f} km", (center[0] + 4, center[1] - radius), theme,
                  size=12, bold=False, color=theme.text_dim, align="topleft")

        if self._ais_service is not None:
            own_speed_knots = self._ais_service.reader.own_fix.sog_knots or 0.0
            for r in self._ais_service.nearby_vessels():
                self._draw_vessel(surface, center, radius, max_range_km, theme, r, own_speed_knots)

        arrow(surface, center, radius * 0.28, 0, theme.secondary, width=4)

    def _draw_vessel(self, surface, center, radius, max_range_km, theme, r, own_speed_knots) -> None:
        if r.relative_bearing_deg is None:
            return
        frac = min(1.0, r.distance_km / max_range_km) if max_range_km else 0.0
        rad = math.radians(r.relative_bearing_deg)
        px = center[0] + math.sin(rad) * radius * frac
        py = center[1] - math.cos(rad) * radius * frac

        sog_knots = r.vessel.sog_knots or 0.0
        sog_kmh = sog_knots * 1.852
        if sog_knots < 0.2:
            dot(surface, (px, py), 4, theme.neutral)
            return

        behind_and_faster = abs(r.relative_bearing_deg) > 90 and sog_knots > own_speed_knots
        if behind_and_faster:
            color = theme.danger
        elif sog_kmh > FAST_VESSEL_THRESHOLD_KMH:
            color = theme.warn
        else:
            color = theme.ok

        if r.vessel.cog_deg is not None:
            own_cog = (self._ais_service.reader.own_fix.cog if self._ais_service is not None
                       and self._ais_service.reader.own_fix.cog is not None else DEFAULT_OWN_COG_DEG)
            heading = (r.vessel.cog_deg - own_cog) % 360
        else:
            heading = r.relative_bearing_deg
        arrow(surface, (px, py), radius * 0.12, heading, color, width=2)
