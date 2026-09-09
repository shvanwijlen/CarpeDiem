"""W - Weather. Layout ported from the "W" tab of Screen design v02.xlsx /
"Claude prompts" rows 67-73:

Below the top bar, content splits into section A (48% of total screen
height) over section B (39%) - normalized to the 86%-tall content area the
same way Main page's three sections are (the spec's 48+39=87% doesn't
quite match the 86% actually available below the top bar).

Section A - two wind "gauges" (a VEVOR/Bresser-console-style filled dial
with a direction pointer and a big centered speed readout, per the
reference screenshot pasted into the "W" tab), side by side:
  left (59% width)  - wind speed/direction *relative to the boat's course*
                       (WindspeedCalculatedAsExperienced - see
                       main_page.py's docstring for what that field means)
  right (41% width) - wind speed/direction exactly as the Bresser device
                       reports it (BresserWindDirection), unrotated
Both read the same BresserWindAverageSpeed number (there's only one
anemometer) - what differs is which direction reference frame is shown,
which is the whole point of putting them side by side.

Section B - 5 equal-width (20%) tiles, each a caption + a graphical icon
+ a value, instead of plain numeric readouts per the spec's explicit
invitation to be graphical here:
  outside temp (thermometer) / outside humidity (droplet) / rain amount
  (a graduated cylinder, filled by amount) / barometric pressure (a
  half-circle needle gauge) / wind level (an airport-windsock icon whose
  droop angle scales with wind speed, colored by the same speed-severity
  rule used elsewhere - a nicer alternative to Bresser's own bar-style
  wind level indicator, per the spec's own suggestion).
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import pygame

from carpediem.display_data import display_data
from carpediem.hmi.theme import Theme
from carpediem.hmi.util import compass_abbr
from carpediem.hmi.widgets import draw_text, draw_text_tracked, glow_circle, glow_rect, gradient_rect, panel

Rect = pygame.Rect

SECTION_A_FRACTION = 48 / 87
LEFT_WIDTH_FRACTION = 0.59
SECTION_B_COLUMNS = 5

# Typical marine barometric range, hPa - maps linearly onto the gauge's
# 180deg sweep. Not calibrated to any real station, just a plausible band.
BAROMETER_MIN_HPA = 970.0
BAROMETER_MAX_HPA = 1040.0

# Wind-level windsock droop: fully limp at 0, fully horizontal at/above
# this speed (km/h) - matches FAST_VESSEL_THRESHOLD_KMH's rough order of
# magnitude for "this counts as properly windy" elsewhere in the app.
WINDSOCK_FULL_EXTENSION_KMH = 35.0


class WeatherPage:
    def draw(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        a_h = int(rect.height * SECTION_A_FRACTION)
        b_h = rect.height - a_h

        a_rect = pygame.Rect(rect.x, rect.y, rect.width, a_h)
        b_rect = pygame.Rect(rect.x, rect.y + a_h, rect.width, b_h)

        self._draw_section_a(surface, a_rect, theme)
        self._draw_section_b(surface, b_rect, theme)

    # -- section A: the two wind gauges -----------------------------------

    def _draw_section_a(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        left_w = int(rect.width * LEFT_WIDTH_FRACTION)
        left_rect = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right_rect = pygame.Rect(rect.x + left_w, rect.y, rect.width - left_w, rect.height)

        speed = display_data.get("BresserWindAverageSpeed")
        speed_str = f"{speed:.1f}" if speed is not None else "--"

        course_relative_dir = display_data.get("WindspeedCalculatedAsExperienced")
        self._draw_wind_circle(surface, left_rect, theme, course_relative_dir, speed_str,
                                "RELATIVE TO COURSE", theme.secondary)

        raw_dir = display_data.get("BresserWindDirection")
        self._draw_wind_circle(surface, right_rect, theme, raw_dir, speed_str,
                                "AS DEVICE REPORTS", theme.tertiary)

    def _draw_wind_circle(self, surface: pygame.Surface, cell: Rect, theme: Theme,
                           direction_deg: Optional[float], speed_str: str, caption: str,
                           accent: Tuple[int, int, int]) -> None:
        radius = int(min(cell.width, cell.height) * 0.36)
        center = (cell.centerx, cell.centery + int(cell.height * 0.04))

        draw_text_tracked(surface, caption, (center[0], cell.y + int(cell.height * 0.06)), theme,
                           size=13, spacing=2, bold=False, color=theme.text_dim, align="midtop")

        glow_circle(surface, center, radius, accent, spread=10, layers=3, max_alpha=45)

        # Concentric-circle radial gradient (rim -> core) - pygame has no
        # native radial gradient primitive, so this fakes one cheaply.
        rim = tuple(max(0, c - 50) for c in accent)
        core = theme.panel_bg_hi
        steps = 20
        for i in range(steps, 0, -1):
            t = i / steps
            r = radius * t
            color = tuple(int(core[j] + (rim[j] - core[j]) * t) for j in range(3))
            pygame.draw.circle(surface, color, center, int(r))

        for deg in range(0, 360, 30):
            theta = math.radians(deg)
            outer = (center[0] + math.sin(theta) * radius, center[1] - math.cos(theta) * radius)
            inner = (center[0] + math.sin(theta) * (radius - 8), center[1] - math.cos(theta) * (radius - 8))
            pygame.draw.line(surface, theme.text_dim, inner, outer, 2)

        pygame.draw.circle(surface, accent, center, radius, width=2)

        if direction_deg is not None:
            theta = math.radians(direction_deg)
            mx = center[0] + math.sin(theta) * (radius - 5)
            my = center[1] - math.cos(theta) * (radius - 5)
            glow_circle(surface, (int(mx), int(my)), 7, theme.accent, spread=8, layers=2, max_alpha=100)
            pygame.draw.circle(surface, theme.accent, (int(mx), int(my)), 6)

        dir_str = compass_abbr(direction_deg) if direction_deg is not None else "--"
        draw_text(surface, dir_str, (center[0], center[1] - radius * 0.32), theme,
                  size=int(radius * 0.24), bold=True, color=theme.text, align="center")
        draw_text(surface, speed_str, (center[0], center[1] + radius * 0.06), theme,
                  size=int(radius * 0.44), bold=True, color=theme.text, align="center")
        draw_text(surface, "km/h", (center[0], center[1] + radius * 0.52), theme,
                  size=int(radius * 0.15), bold=False, color=theme.text_dim, align="center")

    # -- section B: the 5 tiles -------------------------------------------

    def _draw_section_b(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        col_w = rect.width // SECTION_B_COLUMNS
        cells = [pygame.Rect(rect.x + i * col_w, rect.y,
                              col_w if i < SECTION_B_COLUMNS - 1 else rect.width - i * col_w, rect.height)
                 for i in range(SECTION_B_COLUMNS)]

        temp = display_data.get("BresserTemperature")
        self._draw_tile(surface, cells[0], theme, "OUTSIDE TEMP", _icon_thermometer, theme.warn,
                         f"{temp:.1f}°C" if temp is not None else "--")

        humidity = display_data.get("BresserHumidity")
        self._draw_tile(surface, cells[1], theme, "OUTSIDE HUMIDITY", _icon_droplet, theme.secondary,
                         f"{humidity:.0f}%" if humidity is not None else "--")

        rainfall = display_data.get("BresserRainfall")
        self._draw_tile(surface, cells[2], theme, "RAIN",
                         lambda s, r, t, c: _icon_rain_gauge(s, r, t, c, rainfall), theme.secondary,
                         f"{rainfall:.1f} mm" if rainfall is not None else "--")

        pressure = display_data.get("BME280-Barometer")
        self._draw_tile(surface, cells[3], theme, "BAROMETER",
                         lambda s, r, t, c: _icon_barometer(s, r, t, c, pressure), theme.accent,
                         f"{pressure:.1f} hPa" if pressure is not None else "--")

        wind_speed = display_data.get("BresserWindAverageSpeed")
        wind_color = _wind_level_color(theme, wind_speed)
        self._draw_tile(surface, cells[4], theme, "WIND LEVEL",
                         lambda s, r, t, c: _icon_windsock(s, r, t, c, wind_speed), wind_color,
                         f"{wind_speed:.1f} km/h" if wind_speed is not None else "--")

    def _draw_tile(self, surface: pygame.Surface, cell: Rect, theme: Theme, caption: str,
                   icon_draw, accent, value_str: str) -> None:
        panel(surface, cell.inflate(-8, -8), theme, border=False)
        draw_text_tracked(surface, caption, (cell.centerx, cell.y + int(cell.height * 0.10)), theme,
                           size=13, spacing=1, bold=False, color=theme.text_dim, align="midtop")

        icon_size = int(min(cell.width, cell.height) * 0.42)
        icon_rect = pygame.Rect(0, 0, icon_size, icon_size)
        icon_rect.centerx = cell.centerx
        icon_rect.top = cell.y + int(cell.height * 0.22)
        icon_draw(surface, icon_rect, theme, accent)

        draw_text(surface, value_str, (cell.centerx, cell.bottom - int(cell.height * 0.14)), theme,
                  size=int(cell.height * 0.13), bold=True, color=theme.text, align="center")


# -- Section B icons -------------------------------------------------------

def _icon_thermometer(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    w, h = rect.width, rect.height
    cx = rect.centerx
    stem_w = max(4, int(w * 0.22))
    stem = pygame.Rect(0, 0, stem_w, int(h * 0.6))
    stem.midtop = (cx, rect.top + int(h * 0.05))
    bulb_r = int(w * 0.2)
    bulb_center = (cx, stem.bottom + bulb_r - 2)
    glow_circle(surface, bulb_center, bulb_r, color, spread=6, layers=2, max_alpha=40)
    pygame.draw.rect(surface, color, stem, width=2, border_radius=stem_w // 2)
    pygame.draw.circle(surface, color, bulb_center, bulb_r, width=2)
    pygame.draw.line(surface, color, (cx, stem.top + int(stem.height * 0.3)), (cx, bulb_center[1]), 3)
    pygame.draw.circle(surface, color, bulb_center, max(1, bulb_r - 5))


def _icon_droplet(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    w, h = rect.width, rect.height
    cx = rect.centerx
    tip = (cx, rect.top + int(h * 0.05))
    r = int(w * 0.38)
    body_center = (cx, rect.top + int(h * 0.62))
    glow_circle(surface, body_center, r, color, spread=6, layers=2, max_alpha=40)
    points = [tip, (cx + r, body_center[1] - r * 0.15), (cx + r * 0.7, body_center[1] + r * 0.7),
              (cx, rect.bottom - 2), (cx - r * 0.7, body_center[1] + r * 0.7), (cx - r, body_center[1] - r * 0.15)]
    pygame.draw.polygon(surface, color, points, width=3)


def _icon_rain_gauge(surface: pygame.Surface, rect: Rect, theme: Theme, color, amount: Optional[float]) -> None:
    w, h = rect.width, rect.height
    tube = pygame.Rect(0, 0, int(w * 0.4), int(h * 0.85))
    tube.midtop = (rect.centerx, rect.top)
    pygame.draw.rect(surface, theme.bg, tube, border_radius=4)
    max_mm = 10.0
    pct = 0.0 if amount is None else max(0.0, min(1.0, amount / max_mm))
    fill_h = int((tube.height - 4) * pct)
    if fill_h > 0:
        fill_rect = pygame.Rect(tube.x + 2, tube.bottom - 2 - fill_h, tube.width - 4, fill_h)
        gradient_rect(surface, fill_rect, tuple(min(255, c + 60) for c in color), color, border_radius=3)
    pygame.draw.rect(surface, color, tube, width=2, border_radius=4)
    for frac in (0.33, 0.66):
        y = tube.bottom - int(tube.height * frac)
        pygame.draw.line(surface, theme.text_dim, (tube.left + 2, y), (tube.left + 6, y), 1)


def _icon_barometer(surface: pygame.Surface, rect: Rect, theme: Theme, color, pressure: Optional[float]) -> None:
    w, h = rect.width, rect.height
    center = (rect.centerx, rect.bottom - int(h * 0.08))
    radius = int(min(w, h * 1.7) * 0.46)
    for deg in (180, 90, 0):
        theta = math.radians(deg)
        outer = (center[0] - math.cos(math.radians(deg)) * radius, center[1] - math.sin(math.radians(deg)) * radius)
        inner_r = radius - 7
        inner = (center[0] - math.cos(math.radians(deg)) * inner_r, center[1] - math.sin(math.radians(deg)) * inner_r)
        pygame.draw.line(surface, theme.text_dim, inner, outer, 2)
    rect_arc = pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2)
    pygame.draw.arc(surface, color, rect_arc, math.radians(0), math.radians(180), 3)

    pct = 0.5
    if pressure is not None:
        span = BAROMETER_MAX_HPA - BAROMETER_MIN_HPA
        pct = max(0.0, min(1.0, (pressure - BAROMETER_MIN_HPA) / span))
    needle_deg = 180 - pct * 180  # 180deg (low, left) -> 0deg (high, right)
    theta = math.radians(needle_deg)
    tip = (center[0] - math.cos(theta) * (radius - 6), center[1] - math.sin(theta) * (radius - 6))
    pygame.draw.line(surface, theme.accent, center, tip, 3)
    pygame.draw.circle(surface, theme.accent, center, 4)


def _icon_windsock(surface: pygame.Surface, rect: Rect, theme: Theme, color, speed: Optional[float]) -> None:
    """Droop scales with speed only (not direction) - direction is already
    fully covered by section A's two wind circles above, so rotating this
    too would just be a redundant, blowing-in-place-already flag."""
    w, h = rect.width, rect.height
    pole_x = rect.x + int(w * 0.18)
    pole_top = (pole_x, rect.top + int(h * 0.05))
    pole_bottom = (pole_x, rect.bottom - 2)
    pygame.draw.line(surface, theme.panel_border, pole_top, pole_bottom, 3)

    speed_frac = 0.0 if speed is None else max(0.0, min(1.0, speed / WINDSOCK_FULL_EXTENSION_KMH))
    droop = (1.0 - speed_frac) * (h * 0.35)  # how far the tail sags below horizontal
    sock_len = w * 0.68
    tip = (pole_x + sock_len, pole_top[1] + droop)
    mid = (pole_x + sock_len * 0.55, pole_top[1] + droop * 0.35)

    base_half_w = h * 0.16
    tip_half_w = h * 0.03
    points = [
        (pole_x, pole_top[1] - base_half_w * 0.5), (pole_x, pole_top[1] + base_half_w),
        (mid[0], mid[1] + base_half_w * 0.55), (tip[0], tip[1] + tip_half_w),
        (tip[0], tip[1] - tip_half_w), (mid[0], mid[1] - base_half_w * 0.55),
    ]
    pygame.draw.polygon(surface, color, points)
    for frac in (0.35, 0.65):
        band_pt = (pole_x + (tip[0] - pole_x) * frac, pole_top[1] + droop * (frac ** 1.5))
        pygame.draw.circle(surface, theme.bg, (int(band_pt[0]), int(band_pt[1])), 2)


def _wind_level_color(theme: Theme, speed: Optional[float]):
    if speed is None:
        return theme.neutral
    if speed > 25:
        return theme.danger
    if speed > 12:
        return theme.warn
    return theme.ok
