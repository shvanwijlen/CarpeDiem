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
from carpediem.hmi.widgets import draw_text, led, panel

Rect = pygame.Rect

# (page_id, caption, icon_key)
PAGES: List[Tuple[str, str, str]] = [
    ("main", "Main", "main"),
    ("ais", "AIS", "ais"),
    ("weather", "Weather", "weather"),
    ("power", "Power", "power"),
    ("temps", "Temps", "temps"),
    ("cam", "Cam", "cam"),
]
TAB_WIDTH_FRACTION = 0.11  # of screen width, per spec

# (caption, display_data label) - label None means "always neutral / unused"
INDICATORS: List[Tuple[str, Optional[str]]] = [
    ("WiFi", "WiFi"),
    ("AIS", "AIS"),
    ("MQTT", "MQTT"),
    ("MDB", "MODBUS"),
    ("BLE", "BLE"),
    ("WX", "Weather"),
    ("RING", "Cam"),
    ("--", None),
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
    panel(surface, rect, theme, border=False)
    pygame.draw.line(surface, theme.panel_border, (rect.left, rect.bottom), (rect.right, rect.bottom), 2)

    for page_id, caption, icon_key in PAGES:
        tab_rect = lay.tab_rects[page_id]
        active = page_id == active_page_id
        color = theme.accent if active else theme.text_dim
        if active:
            highlight = tab_rect.inflate(-4, -4)
            pygame.draw.rect(surface, theme.panel_bg, highlight, border_radius=6)
            pygame.draw.rect(surface, theme.accent, highlight, width=2, border_radius=6)
            pygame.draw.line(surface, theme.accent, (tab_rect.left + 4, tab_rect.bottom - 2),
                              (tab_rect.right - 4, tab_rect.bottom - 2), 3)

        icon_size = int(tab_rect.height * 0.52)
        icon_rect = pygame.Rect(0, 0, icon_size, icon_size)
        icon_rect.centerx = tab_rect.centerx
        icon_rect.top = tab_rect.top + max(2, int(tab_rect.height * 0.08))
        icons.ICONS[icon_key](surface, icon_rect, color, 2 if not active else 3)

        draw_text(surface, caption, (tab_rect.centerx, tab_rect.bottom - 4), theme,
                  size=max(10, tab_rect.height // 7), bold=active, color=color, align="midbottom")

        if page_id != PAGES[-1][0]:
            divider_x = tab_rect.right
            pygame.draw.line(surface, theme.panel_border, (divider_x, rect.top + 6), (divider_x, rect.bottom - 6), 1)

    for (caption, label), ind_rect in zip(INDICATORS, lay.indicator_rects):
        value = display_data.get(label) if label is not None else None
        radius = max(5, min(ind_rect.width, ind_rect.height) // 5)
        center = (ind_rect.centerx, ind_rect.top + int(ind_rect.height * 0.36))
        if value is None:
            pygame.draw.circle(surface, theme.neutral, center, radius, width=2)
        else:
            led(surface, center, radius, on=bool(value == 1 or value is True), theme=theme)
        draw_text(surface, caption, (ind_rect.centerx, ind_rect.bottom - 4), theme,
                  size=max(9, ind_rect.height // 8), bold=False, color=theme.text_dim, align="midbottom")

    return lay
