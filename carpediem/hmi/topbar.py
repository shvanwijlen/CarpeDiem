"""The page-selector + subsystem-status bar shared by every page (spec:
"The top bar is the same on all pages except obviously for marking a page
as being the currently active one."). 14% of screen height; 6 page tabs on
the left (~11% width each), then a bank of subsystem OK/NOK LEDs filling
the rest, evenly spread - the exact percentages in the spec don't sum
cleanly (6*11% + 8*5% = 106%, not the stated 101%), so indicator width is
derived (remaining space / indicator count) rather than hardcoded, per the
spec's own "you'll figure it out to evenly spread".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pygame

from carpediem.display_data import display_data
from carpediem.hmi import icons
from carpediem.hmi.theme import Theme
from carpediem.hmi.widgets import draw_text_tracked, gradient_rect, glow_rect, led, led3
from carpediem.sysmetrics_monitor import sysmetrics_monitor

Rect = pygame.Rect

# (page_id, caption, icon_key)
PAGES: List[Tuple[str, str, str]] = [
    ("main", "MAIN", "main"),
    ("ais", "AIS", "ais"),
    ("weather", "WEATHER", "weather"),
    ("power", "POWER", "power"),
    ("temps", "TEMPS", "temps"),
    ("cam", "CAM", "cam"),
]
TAB_WIDTH_FRACTION = 0.11  # of screen width, per spec

# (caption, display_data label) - label None means "always neutral / unused".
# The last slot is special-cased below: it's a 3-state (green/orange/red)
# CPU+memory+disk health LED instead of the usual binary display_data one -
# see sysmetrics_monitor.py.
SYSMETRICS_SENTINEL = "__sysmetrics__"
INDICATORS: List[Tuple[str, Optional[str]]] = [
    ("WIFI", "WiFi"),
    ("AIS", "AIS"),
    ("MQTT", "MQTT"),
    ("MDB", "MODBUS"),
    ("BLE", "BLE"),
    ("WX", "Weather"),
    ("RING", "Cam"),
    ("SYS", SYSMETRICS_SENTINEL),
]


@dataclass
class TopBarLayout:
    tab_rects: Dict[str, Rect]
    indicator_rects: List[Rect]


def layout(rect: Rect) -> TopBarLayout:
    tab_w = int(rect.width * TAB_WIDTH_FRACTION)
    tab_rects: Dict[str, Rect] = {}
    x = rect.x
    for page_id, _caption, _icon in PAGES:
        tab_rects[page_id] = pygame.Rect(x, rect.y, tab_w, rect.height)
        x += tab_w

    remaining = rect.right - x
    n = len(INDICATORS)
    ind_w = remaining // n if n else 0
    indicator_rects: List[Rect] = []
    for i in range(n):
        indicator_rects.append(pygame.Rect(x + i * ind_w, rect.y, ind_w, rect.height))
    return TopBarLayout(tab_rects=tab_rects, indicator_rects=indicator_rects)


def draw(surface: pygame.Surface, rect: Rect, theme: Theme, active_page_id: str) -> TopBarLayout:
    lay = layout(rect)
    gradient_rect(surface, rect, theme.panel_bg_hi, theme.bg, border_radius=0)
    pygame.draw.line(surface, theme.accent_dim, (rect.left, rect.bottom - 1), (rect.right, rect.bottom - 1), 2)

    margin = max(3, rect.height // 14)
    for page_id, caption, icon_key in PAGES:
        tab_rect = lay.tab_rects[page_id]
        active = page_id == active_page_id
        color = theme.accent if active else theme.text_dim
        button_rect = tab_rect.inflate(-margin * 2, -margin * 2)

        if active:
            glow_rect(surface, button_rect, theme.accent, spread=8, layers=4, max_alpha=70, border_radius=button_rect.height // 2)
            gradient_rect(surface, button_rect, theme.panel_bg_hi, theme.panel_bg, border_radius=button_rect.height // 2)
            pygame.draw.rect(surface, theme.accent, button_rect, width=2, border_radius=button_rect.height // 2)
        else:
            pygame.draw.rect(surface, theme.panel_border, button_rect, width=1, border_radius=button_rect.height // 2)

        icon_size = int(button_rect.height * 0.46)
        icon_rect = pygame.Rect(0, 0, icon_size, icon_size)
        icon_rect.centerx = button_rect.centerx
        icon_rect.top = button_rect.top + max(2, int(button_rect.height * 0.10))
        icons.ICONS[icon_key](surface, icon_rect, color, 3 if active else 2)

        draw_text_tracked(surface, caption, (button_rect.centerx, button_rect.bottom - 6), theme,
                           size=max(9, button_rect.height // 8), spacing=2, bold=active, color=color,
                           align="midbottom")

    for (caption, label), ind_rect in zip(INDICATORS, lay.indicator_rects):
        chip = ind_rect.inflate(-max(2, ind_rect.width // 6), -margin * 2)
        pygame.draw.rect(surface, theme.panel_bg, chip, border_radius=chip.height // 2)
        pygame.draw.rect(surface, theme.panel_border, chip, width=1, border_radius=chip.height // 2)

        radius = max(4, min(chip.width, chip.height) // 6)
        center = (chip.centerx, chip.top + int(chip.height * 0.34))
        if label == SYSMETRICS_SENTINEL:
            metrics = sysmetrics_monitor.latest
            led3(surface, center, radius, metrics.status if metrics is not None else None, theme=theme)
        else:
            value = display_data.get(label) if label is not None else None
            if value is None:
                pygame.draw.circle(surface, theme.neutral, center, radius, width=2)
            else:
                led(surface, center, radius, on=bool(value == 1 or value is True), theme=theme)
        draw_text_tracked(surface, caption, (chip.centerx, chip.bottom - 4), theme,
                           size=max(8, chip.height // 8), spacing=1, bold=False, color=theme.text_dim,
                           align="midbottom")

    return lay
