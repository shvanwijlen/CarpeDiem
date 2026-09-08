"""Tab icons for the top bar - drawn as vector shapes (not text/glyphs) per
the spec: "use your imagination to come up with logic icons instead of the
words." Each draw_* function fits itself inside the given square-ish rect
and takes an explicit color, so the same icon can render dim (inactive) or
in the accent color (active tab).
"""
from __future__ import annotations

import math
from typing import Callable, Dict

import pygame

from carpediem.hmi.theme import Color

Rect = pygame.Rect


def draw_main(surface: pygame.Surface, rect: Rect, color: Color, width: int = 2) -> None:
    """Ship's wheel - the "helm" - for the main/overview page."""
    cx, cy = rect.center
    r = min(rect.width, rect.height) // 2 - 2
    pygame.draw.circle(surface, color, (cx, cy), r, width=width)
    pygame.draw.circle(surface, color, (cx, cy), max(2, r // 4), width=width)
    for i in range(8):
        theta = math.radians(i * 45)
        x1, y1 = cx + math.sin(theta) * r * 0.35, cy - math.cos(theta) * r * 0.35
        x2, y2 = cx + math.sin(theta) * r, cy - math.cos(theta) * r
        pygame.draw.line(surface, color, (x1, y1), (x2, y2), width)


def draw_ais(surface: pygame.Surface, rect: Rect, color: Color, width: int = 2) -> None:
    """Radar sweep with a couple of target blips."""
    cx, cy = rect.center
    r = min(rect.width, rect.height) // 2 - 2
    pygame.draw.circle(surface, color, (cx, cy), r, width=width)
    pygame.draw.circle(surface, color, (cx, cy), int(r * 0.6), width=1)
    theta = math.radians(-40)
    pygame.draw.line(surface, color, (cx, cy), (cx + math.sin(theta) * r, cy - math.cos(theta) * r), width)
    for dx, dy in ((0.35, -0.5), (-0.45, 0.15), (0.1, 0.55)):
        pygame.draw.circle(surface, color, (int(cx + dx * r), int(cy + dy * r)), 2)


def draw_weather(surface: pygame.Surface, rect: Rect, color: Color, width: int = 2) -> None:
    """A cloud with wind lines trailing off it."""
    cx, cy = rect.center
    w, h = rect.width, rect.height
    base_y = cy + h * 0.08
    pygame.draw.circle(surface, color, (int(cx - w * 0.15), int(base_y - h * 0.05)), int(h * 0.20), width)
    pygame.draw.circle(surface, color, (int(cx + w * 0.08), int(base_y - h * 0.14)), int(h * 0.26), width)
    pygame.draw.circle(surface, color, (int(cx + w * 0.28), int(base_y - h * 0.02)), int(h * 0.17), width)
    cloud_rect = pygame.Rect(0, 0, int(w * 0.62), int(h * 0.22))
    cloud_rect.center = (int(cx + 0.02 * w), int(base_y + h * 0.06))
    pygame.draw.rect(surface, color, cloud_rect, width=width, border_radius=cloud_rect.height // 2)
    for i, dy in enumerate((0.34, 0.44)):
        y = int(rect.top + h * (0.72 + dy * 0.3))
        x1 = int(rect.left + w * (0.2 + i * 0.1))
        x2 = int(rect.right - w * 0.12)
        pygame.draw.line(surface, color, (x1, y), (x2, y), width)


def draw_power(surface: pygame.Surface, rect: Rect, color: Color, width: int = 2) -> None:
    """A lightning bolt."""
    w, h = rect.width, rect.height
    x, y = rect.x, rect.y
    points = [
        (x + w * 0.55, y + h * 0.05),
        (x + w * 0.25, y + h * 0.58),
        (x + w * 0.46, y + h * 0.58),
        (x + w * 0.40, y + h * 0.95),
        (x + w * 0.75, y + h * 0.40),
        (x + w * 0.52, y + h * 0.40),
    ]
    pygame.draw.polygon(surface, color, points, width=width)


def draw_temps(surface: pygame.Surface, rect: Rect, color: Color, width: int = 2) -> None:
    """A thermometer."""
    cx = rect.centerx
    w, h = rect.width, rect.height
    stem = pygame.Rect(0, 0, max(4, int(w * 0.18)), int(h * 0.62))
    stem.midtop = (cx, rect.top + int(h * 0.06))
    bulb_r = int(w * 0.16)
    bulb_center = (cx, stem.bottom + bulb_r - 2)
    pygame.draw.rect(surface, color, stem, width=width, border_radius=stem.width // 2)
    pygame.draw.circle(surface, color, bulb_center, bulb_r, width=width)
    fill_top = stem.top + int(stem.height * 0.35)
    pygame.draw.line(surface, color, (cx, fill_top), (cx, bulb_center[1]), max(1, width - 1))
    pygame.draw.circle(surface, color, bulb_center, max(1, bulb_r - 4))


def draw_cam(surface: pygame.Surface, rect: Rect, color: Color, width: int = 2) -> None:
    """A camera glyph."""
    w, h = rect.width, rect.height
    body = pygame.Rect(0, 0, int(w * 0.8), int(h * 0.55))
    body.center = (rect.centerx, rect.centery + int(h * 0.08))
    bump = pygame.Rect(0, 0, int(w * 0.32), int(h * 0.16))
    bump.midbottom = (int(body.centerx - w * 0.05), body.top + 1)
    pygame.draw.rect(surface, color, body, width=width, border_radius=4)
    pygame.draw.rect(surface, color, bump, width=width, border_radius=2)
    pygame.draw.circle(surface, color, body.center, int(min(body.width, body.height) * 0.32), width=width)
    pygame.draw.circle(surface, color, body.center, 2)


ICONS: Dict[str, Callable[[pygame.Surface, Rect, Color, int], None]] = {
    "main": draw_main,
    "ais": draw_ais,
    "weather": draw_weather,
    "power": draw_power,
    "temps": draw_temps,
    "cam": draw_cam,
}
