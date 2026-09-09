"""A - AIS traffic list. Layout ported from the "A" tab of Screen design
v02.xlsx / "Claude prompts" rows 43-65:

Below the top bar, content splits into a left 85%-width traffic list and
a right 15%-width status rail, each divided into exactly 13 equal-height
cells (86% of screen height / 13, no header row - matches the spec's own
math, which explicitly has no room for one).

Left: the top 26 tracked vessels by distance (all_vessels_by_distance()),
13 in the left half's column, 13 in the right half's, each cell showing
name / distance / speed / own course, plus a colored arrow for "look"
(relative bearing) instead of a 5th number column - color and orientation
reuse the exact same rule as the Main page's radar (see main_page.py's
_draw_vessel): red = behind and faster than us, orange = faster than
FAST_VESSEL_THRESHOLD_KMH, green = everything else, grey dot = not
moving. That's the "creative/startrek" license the spec explicitly
invited for this page - tying every vessel's indicator to the same
traffic-light rule used everywhere else, rather than a plain text list.

Right: 13 status cells top to bottom - counts of vessels behind-and-
faster (red bg) / faster-than-threshold (orange bg) / the rest (green
bg) - these three are display_data's existing VesselsBehindMe/
VesselsFasterThan10/VesselsOther, already computed by ais/service.py's
_print_loop, not recomputed here - then own course/speed/lat/lon (lat/
lon as DMS, matching the spec's own example format), sent/received
message counts ("S:"/"R:"), an antenna health cell (red/green from
$AIALR alarms - see emtrak_reader.py's _handle_alr), and 3 blank cells
reserved for future use.
"""
from __future__ import annotations

from typing import List, Optional

import pygame

from carpediem.ais.service import AisService, DEFAULT_OWN_COG_DEG, FAST_VESSEL_THRESHOLD_KMH
from carpediem.ais.vessel_tracker import VesselProximity
from carpediem.display_data import display_data
from carpediem.hmi.theme import Theme
from carpediem.hmi.util import decimal_to_dms
from carpediem.hmi.widgets import arrow, dot, draw_text, fit_text, panel

Rect = pygame.Rect

LEFT_WIDTH_FRACTION = 0.85
ROWS = 13
VESSELS_PER_HALF = 13
TOTAL_VESSELS = 26


def _truncate(theme: Theme, s: str, size: int, bold: bool, max_width: int) -> str:
    font = theme.font(size, bold=bold)
    if font.size(s)[0] <= max_width:
        return s
    while s and font.size(s + "…")[0] > max_width:
        s = s[:-1]
    return (s + "…") if s else "…"


class AisPage:
    def __init__(self, ais_service: Optional[AisService]) -> None:
        self._ais_service = ais_service

    def draw(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        left_w = int(rect.width * LEFT_WIDTH_FRACTION)
        left_rect = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right_rect = pygame.Rect(rect.x + left_w, rect.y, rect.width - left_w, rect.height)

        vessels: List[VesselProximity] = []
        own_speed_knots = 0.0
        own_cog = DEFAULT_OWN_COG_DEG
        if self._ais_service is not None:
            vessels = self._ais_service.all_vessels_by_distance()[:TOTAL_VESSELS]
            own_fix = self._ais_service.reader.own_fix
            own_speed_knots = own_fix.sog_knots or 0.0
            own_cog = own_fix.cog if own_fix.cog is not None else DEFAULT_OWN_COG_DEG

        half_w = left_w // 2
        row_h = rect.height / ROWS
        for col in range(2):
            col_x = left_rect.x + col * half_w
            col_w = half_w if col == 0 else left_w - half_w
            for i in range(VESSELS_PER_HALF):
                idx = col * VESSELS_PER_HALF + i
                cell = pygame.Rect(col_x, int(rect.y + i * row_h), col_w, int(row_h) + 1)
                v = vessels[idx] if idx < len(vessels) else None
                self._draw_vessel_cell(surface, cell, theme, v, own_speed_knots, own_cog)

        self._draw_status_rail(surface, right_rect, theme, row_h)

    def _draw_vessel_cell(self, surface: pygame.Surface, cell: Rect, theme: Theme,
                           r: Optional[VesselProximity], own_speed_knots: float, own_cog: float) -> None:
        if r is None:
            return
        pad = 6
        name_w = int(cell.width * 0.44)
        dist_w = int(cell.width * 0.17)
        speed_w = int(cell.width * 0.17)
        course_w = int(cell.width * 0.12)
        look_w = cell.width - name_w - dist_w - speed_w - course_w

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

        # Thin colored accent bar at the cell's left edge - the row's
        # "traffic light" without tinting the whole row's background.
        pygame.draw.rect(surface, color, (cell.x, cell.y, 3, cell.height))

        name = r.vessel.name or f"MMSI {r.vessel.mmsi}"
        name = _truncate(theme, name, 15, False, name_w - pad * 2)
        x = cell.x + pad + 3
        draw_text(surface, name, (x, cell.centery), theme, size=15, bold=False,
                  color=theme.text, align="midleft")
        x += name_w

        draw_text(surface, f"{r.distance_km:.1f}km", (x + dist_w - pad, cell.centery), theme,
                  size=14, bold=False, color=theme.text_dim, align="midright")
        x += dist_w

        draw_text(surface, f"{sog_kmh:.1f}", (x + speed_w - pad, cell.centery), theme,
                  size=14, bold=False, color=theme.text_dim, align="midright")
        x += speed_w

        course_str = f"{r.vessel.cog_deg:.0f}°" if r.vessel.cog_deg is not None else "--"
        draw_text(surface, course_str, (x + course_w - pad, cell.centery), theme,
                  size=14, bold=False, color=theme.text_dim, align="midright")
        x += course_w

        look_center = (x + look_w // 2, cell.centery)
        if stationary:
            dot(surface, look_center, 4, color)
        elif r.relative_bearing_deg is not None:
            heading = ((r.vessel.cog_deg - own_cog) % 360) if r.vessel.cog_deg is not None else r.relative_bearing_deg
            arrow(surface, look_center, cell.height * 0.6, heading, color, glow=False)

    # -- right-hand status rail -------------------------------------------

    def _draw_status_rail(self, surface: pygame.Surface, rect: Rect, theme: Theme, row_h: float) -> None:
        reader = self._ais_service.reader if self._ais_service is not None else None
        own_fix = reader.own_fix if reader is not None else None

        def cell_rect(i: int) -> Rect:
            return pygame.Rect(rect.x, int(rect.y + i * row_h), rect.width, int(row_h) + 1)

        self._status_count_cell(surface, cell_rect(0), theme, display_data.get("VesselsBehindMe"), theme.danger)
        self._status_count_cell(surface, cell_rect(1), theme, display_data.get("VesselsFasterThan10"), theme.warn)
        self._status_count_cell(surface, cell_rect(2), theme, display_data.get("VesselsOther"), theme.ok)

        course_str = f"{own_fix.cog:.0f}°" if own_fix and own_fix.cog is not None else "--"
        self._status_text_cell(surface, cell_rect(3), theme, course_str, max_size=int(row_h * 1.6))

        speed_str = f"{(own_fix.sog_knots or 0) * 1.852:.1f} km/h" if own_fix else "--"
        self._status_text_cell(surface, cell_rect(4), theme, speed_str, max_size=int(row_h * 1.6))

        lat_str = decimal_to_dms(own_fix.lat, "N", "S") if own_fix and own_fix.lat is not None else "--"
        self._status_text_cell(surface, cell_rect(5), theme, lat_str)

        lon_str = decimal_to_dms(own_fix.lon, "E", "W") if own_fix and own_fix.lon is not None else "--"
        self._status_text_cell(surface, cell_rect(6), theme, lon_str)

        sent = (reader.own_reports_type18 + reader.own_reports_type19 + reader.own_reports_other) if reader else None
        self._status_text_cell(surface, cell_rect(7), theme, f"S:{sent}" if sent is not None else "S:--",
                                align="midleft")

        received = reader.received_reports if reader else None
        self._status_text_cell(surface, cell_rect(8), theme, f"R:{received}" if received is not None else "R:--",
                                align="midleft")

        self._status_antenna_cell(surface, cell_rect(9), theme, display_data.get("AISAntenna"))

        for i in (10, 11, 12):
            panel(surface, cell_rect(i).inflate(-4, -4), theme, border=False)

    def _status_count_cell(self, surface: pygame.Surface, cell: Rect, theme: Theme,
                            value, bg_color) -> None:
        pygame.draw.rect(surface, bg_color, cell)
        text = "--" if value is None else str(int(value))
        draw_text(surface, text, cell.center, theme, size=int(cell.height * 0.5), bold=True,
                  color=theme.bg, align="center")

    def _status_text_cell(self, surface: pygame.Surface, cell: Rect, theme: Theme, text: str,
                           align: str = "center", size_frac: float = 0.32, max_size: Optional[int] = None) -> None:
        panel(surface, cell.inflate(-4, -4), theme, border=False)
        if align == "center":
            # Auto-sized to fill the cell (both width and height) instead
            # of a fixed fraction of height - "180°"/"12.0 km/h"/the DMS
            # lat/lon strings all previously rendered much smaller than
            # the box actually had room for. Passing the *full* cell into
            # fit_text (which applies its own padding) rather than an
            # already-inset one - the previous double-inset wasted height
            # budget the text could have used.
            fit_text(surface, text, cell, theme, max_size=max_size or cell.height, min_size=11,
                     bold=False, color=theme.text, padding=6)
        else:
            pos = (cell.x + 10, cell.centery)
            draw_text(surface, text, pos, theme, size=max(11, int(cell.height * size_frac)), bold=False,
                      color=theme.text, align=align)

    def _status_antenna_cell(self, surface: pygame.Surface, cell: Rect, theme: Theme, antenna) -> None:
        if antenna is None:
            bg, text_color = theme.panel_bg, theme.text_dim
        else:
            bg = theme.ok if antenna == 1 else theme.danger
            text_color = theme.bg
        pygame.draw.rect(surface, bg, cell)
        fit_text(surface, "ANTENNA", cell.inflate(-16, -8), theme, max_size=cell.height, min_size=10,
                 bold=True, color=text_color)
