"""Stand-in for the 5 tabs not built out yet (AIS/Weather/Power/Temps/Cam) -
just enough so page switching/navigation can be exercised end-to-end while
each page gets its real layout built one at a time."""
from __future__ import annotations

import pygame

from carpediem.hmi.icons import ICONS
from carpediem.hmi.theme import Theme
from carpediem.hmi.widgets import draw_text

Rect = pygame.Rect


class PlaceholderPage:
    def __init__(self, title: str, icon_key: str) -> None:
        self.title = title
        self.icon_key = icon_key

    def draw(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        icon_size = min(rect.width, rect.height) // 4
        icon_rect = pygame.Rect(0, 0, icon_size, icon_size)
        icon_rect.center = (rect.centerx, rect.centery - icon_size // 2)
        ICONS[self.icon_key](surface, icon_rect, theme.accent_dim, 3)
        draw_text(surface, self.title.upper(), (rect.centerx, icon_rect.bottom + 20), theme,
                  size=32, color=theme.text_dim, align="midtop")
        draw_text(surface, "under construction", (rect.centerx, icon_rect.bottom + 64), theme,
                  size=16, bold=False, color=theme.text_dim, align="midtop")
