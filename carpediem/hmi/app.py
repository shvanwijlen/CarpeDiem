"""Entry point for the Magedok 7" IPS touchscreen (1024x600) HMI.

Fully optional (config.flags.use_hmi, default False). Runs as one asyncio
task (see _tick()/run_forever(), driven from main.py the same way
matrix_display.py's MAX7219 loop is) that redraws at config.hmi.fps and
polls input every tick - pygame's own event loop is blocking, so it's never
called directly; everything goes through short non-blocking calls plus
asyncio.sleep() between frames so the rest of the app's subsystem tasks
keep running.

On the Pi, running without a desktop session needs an SDL video driver set
before this process starts, e.g. `SDL_VIDEODRIVER=kmsdrm` (DRM/KMS,
preferred on recent Raspberry Pi OS) or `SDL_VIDEODRIVER=fbcon` (plain
framebuffer) - that's a deployment/systemd-unit concern, not something this
module sets itself, since it depends on how the Pi is configured.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional

import pygame

from carpediem.ais.service import AisService
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log
from carpediem.hmi import topbar
from carpediem.hmi.pages.ais_page import AisPage
from carpediem.hmi.pages.base import Page
from carpediem.hmi.pages.main_page import MainPage
from carpediem.hmi.pages.placeholder import PlaceholderPage
from carpediem.hmi.theme import get_theme

Rect = pygame.Rect


class HmiApp:
    def __init__(self, ais_service: Optional[AisService] = None) -> None:
        self._ais_service = ais_service
        self._surface: Optional[pygame.Surface] = None
        self._theme = get_theme(config.hmi.theme)
        self._active_page = "main"
        self._topbar_rect: Rect = Rect(0, 0, 0, 0)
        self._content_rect: Rect = Rect(0, 0, 0, 0)
        self._pages: Dict[str, Page] = {}

    def init(self) -> bool:
        try:
            pygame.init()
            size = (config.hmi.width, config.hmi.height)
            flags = pygame.FULLSCREEN if config.hmi.fullscreen else 0
            self._surface = pygame.display.set_mode(size, flags)
            pygame.display.set_caption("CarpeDiem")
            pygame.mouse.set_visible(not config.hmi.fullscreen)

            # Fullscreen mode can hand back a different resolution than
            # requested (e.g. matching the desktop/current video mode) - lay
            # out against what we actually got, not the configured size, so
            # there's no stray unrendered band if the two ever differ.
            w, h = self._surface.get_size()
            top_h = int(h * 0.14)
            self._topbar_rect = Rect(0, 0, w, top_h)
            self._content_rect = Rect(0, top_h, w, h - top_h)

            self._pages = {
                "main": MainPage(self._ais_service),
                "ais": AisPage(self._ais_service),
                "weather": PlaceholderPage("Weather", "weather"),
                "power": PlaceholderPage("Power", "power"),
                "temps": PlaceholderPage("Temps", "temps"),
                "cam": PlaceholderPage("Cam", "cam"),
            }
            log(9, f"HMI initialized: {w}x{h} theme={self._theme.name} fullscreen={config.hmi.fullscreen}")
            return True
        except Exception as exc:  # noqa: BLE001 - no display attached, or pygame/SDL unavailable
            log(9, f"HMI not available: {exc}")
            self._surface = None
            return False

    def _handle_events(self) -> None:
        assert self._surface is not None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                log(9, "HMI: window closed, disabling display (other subsystems keep running)")
                self.close()
                return
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._handle_tap(event.pos)
            elif event.type == pygame.FINGERDOWN:
                w, h = self._surface.get_size()
                self._handle_tap((int(event.x * w), int(event.y * h)))

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        lay = topbar.layout(self._topbar_rect)
        for page_id, rect in lay.tab_rects.items():
            if rect.collidepoint(pos):
                self._active_page = page_id
                return

    def _tick(self) -> None:
        assert self._surface is not None
        self._handle_events()
        if self._surface is None:  # closed during event handling
            return

        self._surface.fill(self._theme.bg)
        topbar.draw(self._surface, self._topbar_rect, self._theme, self._active_page)
        page = self._pages.get(self._active_page)
        if page is not None:
            page.draw(self._surface, self._content_rect, self._theme)
        pygame.display.flip()

    async def run_forever(self) -> None:
        interval = 1.0 / max(1, config.hmi.fps)
        while True:
            if self._surface is not None:
                try:
                    self._tick()
                    display_data.update("Display", 1, source="S")
                except Exception as exc:  # noqa: BLE001 - a bad frame must not kill the redraw loop
                    log(9, f"HMI: frame render failed, will retry: {exc}")
                    display_data.update("Display", 0, source="S")
            await asyncio.sleep(interval)

    def close(self) -> None:
        if self._surface is not None:
            pygame.quit()
            self._surface = None
