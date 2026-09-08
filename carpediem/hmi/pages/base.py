"""Common interface every display tab implements. app.py only ever calls
`draw(surface, rect, theme)` on whichever page is currently active - it
doesn't know or care what's inside."""
from __future__ import annotations

from typing import Protocol

import pygame

from carpediem.hmi.theme import Theme

Rect = pygame.Rect


class Page(Protocol):
    def draw(self, surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
        """Render this page's content into `rect` (the area below the top
        bar - the page must not draw outside it)."""
        ...
