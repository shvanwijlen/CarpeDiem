"""P - Power. Layout ported from the "P" tab / "Claude prompts" rows
79-92 of Screen design v02.xlsx - note the spec (both the text and the
"P" tab's mockup, which has no body content below the top bar at all)
stops after describing section B's left third; the right two-thirds is a
power-flow diagram per direct request, not from the spreadsheet.

Below the top bar, section A and section B are equal height (43% of
total screen height each - conveniently sums to exactly the 86% actually
available, unlike some other pages' section percentages).

Section A - 3 even, centered subsections: Grid / DC / Solar, each a bold
label (bigger than any value) over one or more value lines, all values
sharing one common font size regardless of how many lines a subsection
has. Grid shows "-" (not "none") when Active input source != 1 GRID, per
explicit spec; every other None value falls back to the literal text
"none" per this page's own general rule (stated nowhere else in the
app - see the module-level NONE_TEXT).

Section B left third - AC Load + Starter battery stack: two label/value
pairs, then a combined Volts+Amps line, then a combined SOC%+TTG line
(TTG prefers "System" over "Batt", "-" if neither has a value - both per
explicit spec).

Section B right two-thirds - a schematic power-flow diagram: Grid/Solar/
DC feed a central bus, the bus feeds AC Load, and the battery sits on the
bus either as a source (discharging) or a sink (charging) depending on
the sign of "Battery Power (W)" (Victron convention: positive = charging).
Flow line thickness scales with wattage - this part has no spec to port,
it's the graphical centerpiece the spec's missing two-thirds asked for.
"""
from __future__ import annotations

import math
from typing import Optional

import pygame

from carpediem.display_data import display_data
from carpediem.hmi.theme import Theme
from carpediem.hmi.widgets import draw_text, draw_text_tracked, glow_circle, glow_rect, panel

Rect = pygame.Rect

LEFT_B_WIDTH_FRACTION = 1 / 3
NONE_TEXT = "none"

LABEL_SIZE_FRACTION = 0.070  # of screen height - shared by every "Grid"/"DC"/"Solar"/"AC Load"/"Starter" label
VALUE_SIZE_FRACTION = 0.052  # of screen height - shared by every watt/volt/amp/%/TTG value, anywhere on the page

# Flow-line thickness scaling: 0W is a thin trickle, this many watts (or
# more) maxes out the line at its thickest - purely a visual scale, not
# calibrated to any real system capacity.
FLOW_MAX_WATTS = 1200.0


def _fmt(value: Optional[float], suffix: str = "", decimals: int = 0) -> str:
    if value is None:
        return NONE_TEXT
    return f"{value:.{decimals}f}{suffix}"


class PowerPage:
    def draw(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        a_h = rect.height // 2
        b_h = rect.height - a_h

        a_rect = pygame.Rect(rect.x, rect.y, rect.width, a_h)
        b_rect = pygame.Rect(rect.x, rect.y + a_h, rect.width, b_h)

        self._draw_section_a(surface, a_rect, theme)
        self._draw_section_b(surface, b_rect, theme)

    # -- section A: Grid / DC / Solar --------------------------------------

    def _draw_section_a(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        col_w = rect.width // 3
        cells = [pygame.Rect(rect.x + i * col_w, rect.y, col_w if i < 2 else rect.width - 2 * col_w, rect.height)
                 for i in range(3)]

        grid_status = display_data.get("Active input source")
        grid_w = display_data.get("Grid (W)")
        grid_value = "-" if grid_status != 1 else _fmt(grid_w, " W")
        self._draw_tile(surface, cells[0], theme, "GRID", [grid_value], theme.accent)

        dc_w = display_data.get("DC Power (W)")
        dc_a = display_data.get("DC Current (A)")
        self._draw_tile(surface, cells[1], theme, "DC", [_fmt(dc_w, " W"), _fmt(dc_a, " A", 1)], theme.secondary)

        pv_w = display_data.get("PV Power (W)")
        self._draw_tile(surface, cells[2], theme, "SOLAR", [_fmt(pv_w, " W")], theme.ok)

    def _draw_tile(self, surface: pygame.Surface, cell: Rect, theme: Theme, label: str,
                   value_lines: list[str], accent) -> None:
        label_size = max(14, int(cell.height * LABEL_SIZE_FRACTION))
        value_size = max(12, int(cell.height * VALUE_SIZE_FRACTION))
        line_gap = value_size * 1.25

        total_h = label_size * 1.3 + len(value_lines) * line_gap
        y = cell.centery - total_h / 2

        draw_text_tracked(surface, label, (cell.centerx, y), theme, size=label_size, spacing=2,
                           bold=True, color=accent, align="midtop")
        y += label_size * 1.5

        for line in value_lines:
            draw_text(surface, line, (cell.centerx, y), theme, size=value_size, bold=False,
                      color=theme.text, align="midtop")
            y += line_gap

    # -- section B: AC Load/Starter stack + power-flow diagram ------------

    def _draw_section_b(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        left_w = int(rect.width * LEFT_B_WIDTH_FRACTION)
        left_rect = pygame.Rect(rect.x, rect.y, left_w, rect.height)
        right_rect = pygame.Rect(rect.x + left_w, rect.y, rect.width - left_w, rect.height)

        self._draw_ac_starter_stack(surface, left_rect, theme)
        self._draw_power_flow(surface, right_rect, theme)

    def _draw_ac_starter_stack(self, surface: pygame.Surface, cell: Rect, theme: Theme) -> None:
        label_size = max(14, int(cell.height * LABEL_SIZE_FRACTION))
        value_size = max(12, int(cell.height * VALUE_SIZE_FRACTION))

        ac_w = display_data.get("AC Loads (W)")
        starter_w = display_data.get("Battery0 Power (W)")
        volts = display_data.get("Battery0 Voltage (V)")
        amps = display_data.get("Battery0 Current (A)")
        soc = display_data.get("Battery SOC (%)")
        ttg = display_data.get("Battery Time to Go (System)")
        if ttg is None:
            ttg = display_data.get("Battery Time to Go (Batt)")

        volts_amps = f"{_fmt(volts, ' V', 1)}  {_fmt(amps, ' A', 1)}"
        soc_str = "-" if soc is None else f"{soc:.0f}%"
        ttg_str = "-" if ttg is None else f"{ttg:.1f}h"
        soc_ttg = f"{soc_str}  {ttg_str}" if not (soc is None and ttg is None) else "-"

        rows = [
            ("AC LOAD", True), (_fmt(ac_w, " W"), False),
            ("STARTER", True), (_fmt(starter_w, " W"), False),
            (volts_amps, False),
            (soc_ttg, False),
        ]
        line_h = cell.height / len(rows)
        y = cell.y
        for text, is_label in rows:
            size = label_size if is_label else value_size
            draw_text_tracked(surface, text, (cell.centerx, y + line_h / 2), theme, size=size, spacing=2 if is_label else 0,
                               bold=is_label, color=theme.accent if is_label else theme.text, align="center")
            y += line_h

    def _draw_power_flow(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        panel(surface, rect.inflate(-8, -8), theme, border=False)

        bus_x = rect.centerx
        bus_top = rect.y + rect.height * 0.12
        bus_bottom = rect.y + rect.height * 0.82
        glow_rect(surface, pygame.Rect(int(bus_x - 3), int(bus_top), 6, int(bus_bottom - bus_top)),
                  theme.accent, spread=6, layers=2, max_alpha=50, border_radius=3)
        pygame.draw.line(surface, theme.accent, (bus_x, bus_top), (bus_x, bus_bottom), 3)

        grid_status = display_data.get("Active input source")
        grid_w = display_data.get("Grid (W)") if grid_status == 1 else 0.0
        dc_w = display_data.get("DC Power (W)") or 0.0
        pv_w = display_data.get("PV Power (W)") or 0.0
        ac_w = display_data.get("AC Loads (W)") or 0.0
        battery_w = display_data.get("Battery Power (W)")

        left_x = rect.x + rect.width * 0.09
        source_rows = [
            ("GRID", grid_w or 0.0, theme.accent, _icon_grid),
            ("SOLAR", pv_w, theme.ok, _icon_sun),
            ("DC", dc_w, theme.secondary, _icon_gear),
        ]
        for i, (label, watts, color, icon_fn) in enumerate(source_rows):
            y = rect.y + rect.height * (0.20 + i * 0.28)
            self._draw_flow_node(surface, theme, (left_x, y), label, watts, " W", color, icon_fn, on_left=True)
            self._draw_flow_line(surface, (left_x + 26, y), (bus_x, y), color, watts)

        right_x = rect.right - rect.width * 0.09
        load_y = rect.y + rect.height * 0.34
        self._draw_flow_node(surface, theme, (right_x, load_y), "AC LOAD", ac_w, " W", theme.warn, _icon_plug,
                              on_left=False)
        self._draw_flow_line(surface, (bus_x, load_y), (right_x - 26, load_y), theme.warn, ac_w)

        batt_y = rect.y + rect.height * 0.72
        batt_x = right_x
        charging = battery_w is not None and battery_w >= 0
        batt_color = theme.ok if charging else theme.warn
        self._draw_flow_node(surface, theme, (batt_x, batt_y), "BATTERY", battery_w, " W", batt_color,
                              _icon_battery_flow, on_left=False)
        if battery_w is not None:
            if charging:
                self._draw_flow_line(surface, (bus_x, batt_y), (batt_x - 26, batt_y), batt_color, battery_w)
            else:
                self._draw_flow_line(surface, (batt_x - 26, batt_y), (bus_x, batt_y), batt_color, -battery_w)

    def _draw_flow_node(self, surface: pygame.Surface, theme: Theme, pos, label: str, watts: Optional[float],
                        suffix: str, color, icon_fn, on_left: bool) -> None:
        x, y = pos
        icon_r = 16
        glow_circle(surface, (int(x), int(y)), icon_r, color, spread=6, layers=2, max_alpha=40)
        icon_rect = pygame.Rect(int(x - icon_r), int(y - icon_r), icon_r * 2, icon_r * 2)
        icon_fn(surface, icon_rect, theme, color)

        text_x = x + icon_r + 8 if on_left else x - icon_r - 8
        align = "midleft" if on_left else "midright"
        draw_text_tracked(surface, label, (text_x, y - 12), theme, size=12, spacing=1, bold=False,
                           color=theme.text_dim, align=align)
        draw_text(surface, _fmt(watts, suffix), (text_x, y + 8), theme, size=16, bold=True,
                  color=theme.text, align=align)

    def _draw_flow_line(self, surface: pygame.Surface, p1, p2, color, watts: Optional[float]) -> None:
        watts = abs(watts) if watts is not None else 0.0
        thickness = 2 + int(min(1.0, watts / FLOW_MAX_WATTS) * 8)
        pygame.draw.line(surface, color, p1, p2, thickness)

        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head_len, head_w = 10, 6
        tip = p2
        base_l = (p2[0] - ux * head_len + px * head_w, p2[1] - uy * head_len + py * head_w)
        base_r = (p2[0] - ux * head_len - px * head_w, p2[1] - uy * head_len - py * head_w)
        pygame.draw.polygon(surface, color, [tip, base_l, base_r])


# -- power-flow node icons -------------------------------------------------

def _icon_grid(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    cx, top, bottom = rect.centerx, rect.top + 2, rect.bottom - 2
    pygame.draw.line(surface, color, (cx, top), (cx, bottom), 2)
    for frac, w in ((0.25, 0.7), (0.55, 0.5)):
        y = top + (bottom - top) * frac
        half = rect.width * w / 2
        pygame.draw.line(surface, color, (cx - half, y), (cx + half, y), 2)
        pygame.draw.line(surface, color, (cx - half, y), (cx, top), 1)
        pygame.draw.line(surface, color, (cx + half, y), (cx, top), 1)


def _icon_sun(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    r = rect.width * 0.28
    pygame.draw.circle(surface, color, rect.center, int(r), width=2)
    for deg in range(0, 360, 45):
        theta = math.radians(deg)
        x1 = rect.centerx + math.cos(theta) * (r + 3)
        y1 = rect.centery + math.sin(theta) * (r + 3)
        x2 = rect.centerx + math.cos(theta) * (r + 8)
        y2 = rect.centery + math.sin(theta) * (r + 8)
        pygame.draw.line(surface, color, (x1, y1), (x2, y2), 2)


def _icon_gear(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    r = rect.width * 0.3
    pygame.draw.circle(surface, color, rect.center, int(r), width=2)
    for deg in range(0, 360, 45):
        theta = math.radians(deg)
        x1 = rect.centerx + math.cos(theta) * r
        y1 = rect.centery + math.sin(theta) * r
        x2 = rect.centerx + math.cos(theta) * (r + 4)
        y2 = rect.centery + math.sin(theta) * (r + 4)
        pygame.draw.line(surface, color, (x1, y1), (x2, y2), 2)
    pygame.draw.circle(surface, color, rect.center, max(1, int(r * 0.35)))


def _icon_plug(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    body = rect.inflate(-rect.width // 4, -rect.height // 4)
    pygame.draw.rect(surface, color, body, width=2, border_radius=4)
    for dx in (-0.2, 0.2):
        x = body.centerx + dx * body.width
        pygame.draw.line(surface, color, (x, body.top - 4), (x, body.top + 3), 2)


def _icon_battery_flow(surface: pygame.Surface, rect: Rect, theme: Theme, color) -> None:
    body = rect.inflate(-rect.width // 4, -rect.height // 5)
    nub = pygame.Rect(0, 0, max(3, int(body.width * 0.4)), max(2, rect.height // 8))
    nub.midbottom = (body.centerx, body.top + 1)
    pygame.draw.rect(surface, color, nub, border_radius=2)
    pygame.draw.rect(surface, color, body, width=2, border_radius=4)
