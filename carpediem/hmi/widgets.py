"""Small reusable drawing primitives shared by the top bar and every page.
Nothing here knows about display_data - callers pass plain values/colors in
and get pixels out, which keeps this module themeable and unit-testable
without a real display.

Visual language: LCARS-ish - big rounded/pill shapes, soft additive glow
around focal elements, gradient panel fills instead of flat color, bold
sans caption text (see theme.py) instead of a monospace/console font.
Gradients and glow halos are cached by (shape, size, color, ...) since the
panel/LED/etc. geometry they're built from is static frame to frame - only
the first draw actually rasterizes anything, every later one is a cheap
blit, which matters at HMI_FPS on a Pi.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

import pygame

from carpediem.hmi.theme import Color, Theme

Rect = pygame.Rect

_gradient_cache: Dict[tuple, pygame.Surface] = {}
_glow_cache: Dict[tuple, pygame.Surface] = {}


# -- backgrounds / panels ---------------------------------------------------

def gradient_rect(
    surface: pygame.Surface,
    rect: Rect,
    top_color: Color,
    bottom_color: Color,
    border_radius: int = 0,
) -> None:
    """Vertical gradient fill, rounded-rect masked. Cached per (size,
    colors, radius) - only rasterized once, every repeat call is a blit."""
    key = (rect.size, top_color, bottom_color, border_radius)
    cached = _gradient_cache.get(key)
    if cached is None:
        w, h = max(1, rect.width), max(1, rect.height)
        cached = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(h):
            t = y / max(1, h - 1)
            color = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
            pygame.draw.line(cached, color, (0, y), (w, y))
        if border_radius:
            mask = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=border_radius)
            cached.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        _gradient_cache[key] = cached
    surface.blit(cached, rect.topleft)


def glow_rect(
    surface: pygame.Surface,
    rect: Rect,
    color: Color,
    spread: int = 10,
    layers: int = 4,
    max_alpha: int = 90,
    border_radius: int = 12,
) -> None:
    """Soft additive glow behind a rounded rect area (e.g. an active tab,
    a highlighted panel)."""
    key = ("rect", rect.size, color, spread, layers, max_alpha, border_radius)
    cached = _glow_cache.get(key)
    if cached is None:
        w, h = rect.width + spread * 2, rect.height + spread * 2
        cached = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in range(layers, 0, -1):
            pad = spread * i / layers
            layer_rect = pygame.Rect(pad, pad, w - 2 * pad, h - 2 * pad)
            alpha = int(max_alpha * (1 - i / (layers + 1)))
            pygame.draw.rect(cached, (*color, alpha), layer_rect, border_radius=border_radius + int(pad))
        _glow_cache[key] = cached
    surface.blit(cached, (rect.x - spread, rect.y - spread), special_flags=pygame.BLEND_RGBA_ADD)


def glow_circle(
    surface: pygame.Surface,
    center: Tuple[int, int],
    radius: int,
    color: Color,
    spread: int = 10,
    layers: int = 4,
    max_alpha: int = 100,
) -> None:
    key = ("circle", radius, color, spread, layers, max_alpha)
    cached = _glow_cache.get(key)
    if cached is None:
        size = int((radius + spread) * 2)
        cached = pygame.Surface((size, size), pygame.SRCALPHA)
        c = (size // 2, size // 2)
        for i in range(layers, 0, -1):
            r = radius + spread * i / layers
            alpha = int(max_alpha * (1 - i / (layers + 1)))
            pygame.draw.circle(cached, (*color, alpha), c, int(r))
        _glow_cache[key] = cached
    size = cached.get_width()
    surface.blit(cached, (center[0] - size // 2, center[1] - size // 2), special_flags=pygame.BLEND_RGBA_ADD)


def panel(
    surface: pygame.Surface,
    rect: Rect,
    theme: Theme,
    border: bool = True,
    radius: int = 14,
    glow: bool = False,
    glow_color: Optional[Color] = None,
) -> None:
    if glow:
        glow_rect(surface, rect, glow_color if glow_color is not None else theme.accent,
                  spread=10, layers=4, max_alpha=55, border_radius=radius)
    gradient_rect(surface, rect, theme.panel_bg_hi, theme.panel_bg, border_radius=radius)
    if border:
        pygame.draw.rect(surface, theme.panel_border, rect, width=1, border_radius=radius)


def _line_glow(surface: pygame.Surface, rect: Rect, theme: Theme) -> None:
    glow_rect(surface, rect, theme.panel_border, spread=5, layers=3, max_alpha=45, border_radius=1)


def divider_v(surface: pygame.Surface, x: int, y1: int, y2: int, theme: Theme, width: int = 2) -> None:
    _line_glow(surface, pygame.Rect(x - 1, min(y1, y2), width, abs(y2 - y1)), theme)
    pygame.draw.line(surface, theme.panel_border, (x, y1), (x, y2), width)


def divider_h(surface: pygame.Surface, y: int, x1: int, x2: int, theme: Theme, width: int = 2) -> None:
    _line_glow(surface, pygame.Rect(min(x1, x2), y - 1, abs(x2 - x1), width), theme)
    pygame.draw.line(surface, theme.panel_border, (x1, y), (x2, y), width)


# -- text ---------------------------------------------------------------

def draw_text(
    surface: pygame.Surface,
    s: str,
    pos: Tuple[int, int],
    theme: Theme,
    size: int,
    bold: bool = True,
    color: Optional[Color] = None,
    align: str = "topleft",
) -> pygame.Rect:
    """Renders `s` and blits it, positioning the given `align` corner/edge
    of the rendered text at `pos` (same anchor names as pygame.Rect, e.g.
    "center", "midtop", "topleft"). Returns the blitted rect."""
    font = theme.font(size, bold=bold)
    surf = font.render(s, True, color if color is not None else theme.text)
    rect = surf.get_rect(**{align: pos})
    surface.blit(surf, rect)
    return rect


def draw_text_tracked(
    surface: pygame.Surface,
    s: str,
    pos: Tuple[int, int],
    theme: Theme,
    size: int,
    spacing: int = 2,
    bold: bool = True,
    color: Optional[Color] = None,
    align: str = "topleft",
) -> pygame.Rect:
    """Same as draw_text but with extra letter-spacing (LCARS captions read
    as tracked-out uppercase, not tight-set text) - renders char by char."""
    font = theme.font(size, bold=bold)
    col = color if color is not None else theme.text
    widths = [font.size(ch)[0] for ch in s]
    total_w = sum(widths) + spacing * max(0, len(s) - 1)
    height = font.get_height()

    block = pygame.Surface((max(1, total_w), height), pygame.SRCALPHA)
    x = 0
    for ch, w in zip(s, widths):
        block.blit(font.render(ch, True, col), (x, 0))
        x += w + spacing

    rect = block.get_rect(**{align: pos})
    surface.blit(block, rect)
    return rect


def fit_text(
    surface: pygame.Surface,
    s: str,
    rect: Rect,
    theme: Theme,
    max_size: int,
    min_size: int = 10,
    bold: bool = True,
    color: Optional[Color] = None,
    padding: int = 4,
) -> pygame.Rect:
    """Picks the largest font size (<= max_size) that fits `s` inside
    `rect` (with `padding` on each side), then centers it. Used for fields
    like the bridge/lock banner where "as big as fits the height" was the
    explicit spec."""
    avail_w = max(1, rect.width - 2 * padding)
    avail_h = max(1, rect.height - 2 * padding)
    size = max_size
    while size > min_size:
        font = theme.font(size, bold=bold)
        w, h = font.size(s)
        if w <= avail_w and h <= avail_h:
            break
        size -= 1
    return draw_text(surface, s, rect.center, theme, size, bold=bold, color=color, align="center")


# -- indicators / markers ------------------------------------------------

def led(surface: pygame.Surface, center: Tuple[int, int], radius: int, on: bool, theme: Theme) -> None:
    color = theme.ok if on else theme.danger
    if on:
        glow_circle(surface, center, radius, color, spread=radius, layers=3, max_alpha=110)
    pygame.draw.circle(surface, color, center, radius)
    pygame.draw.circle(surface, theme.panel_border, center, radius, width=1)


def arrow(
    surface: pygame.Surface,
    center: Tuple[float, float],
    length: float,
    angle_deg: float,
    color: Color,
    width: int = 3,
    glow: bool = True,
) -> None:
    """Draws an arrow (a slim triangle) at `center`, `length` px tip-to-tail,
    pointing toward `angle_deg` measured clockwise from straight up (screen
    "north"), matching how every angle in this app - course, bearing,
    relative bearing - is already defined."""
    theta = math.radians(angle_deg)
    dx, dy = math.sin(theta), -math.cos(theta)
    px, py = -dy, dx  # perpendicular, for the tail width

    tip = (center[0] + dx * length * 0.6, center[1] + dy * length * 0.6)
    tail_l = (center[0] - dx * length * 0.4 + px * length * 0.28, center[1] - dy * length * 0.4 + py * length * 0.28)
    tail_r = (center[0] - dx * length * 0.4 - px * length * 0.28, center[1] - dy * length * 0.4 - py * length * 0.28)
    if glow:
        # A tight halo behind the shape, not a blob that swallows it - the
        # glow radius is deliberately smaller than the arrow itself.
        glow_circle(surface, (int(center[0]), int(center[1])), max(2, int(length * 0.22)), color,
                    spread=max(2, int(length * 0.18)), layers=2, max_alpha=45)
    pygame.draw.polygon(surface, color, [tip, tail_l, tail_r])
    _ = width  # kept for API symmetry with other draw_* helpers


def dot(surface: pygame.Surface, center: Tuple[int, int], radius: int, color: Color) -> None:
    pygame.draw.circle(surface, color, center, radius)


def compass_rose(
    surface: pygame.Surface,
    center: Tuple[int, int],
    radius: int,
    theme: Theme,
    markers: Sequence[Tuple[float, Color]] = (),
) -> None:
    """North-up compass ring with tick marks every 30deg and a glowing
    pill marker (angle clockwise from top, color) for each entry in
    `markers` - used for the own-course/wind-direction indicators."""
    glow_circle(surface, center, radius, theme.secondary, spread=7, layers=2, max_alpha=20)
    pygame.draw.circle(surface, theme.panel_bg, center, radius)
    pygame.draw.circle(surface, theme.secondary, center, radius, width=1)

    for deg in range(0, 360, 30):
        theta = math.radians(deg)
        outer = (center[0] + math.sin(theta) * radius, center[1] - math.cos(theta) * radius)
        inner = (center[0] + math.sin(theta) * (radius - 8), center[1] - math.cos(theta) * (radius - 8))
        pygame.draw.line(surface, theme.text_dim, inner, outer, 2)

    for deg, color in markers:
        theta = math.radians(deg)
        mx = center[0] + math.sin(theta) * (radius - 3)
        my = center[1] - math.cos(theta) * (radius - 3)
        glow_circle(surface, (int(mx), int(my)), 6, color, spread=8, layers=3, max_alpha=90)
        marker_rect = pygame.Rect(0, 0, 16, 8)
        marker_rect.center = (mx, my)
        rotated = pygame.transform.rotate(_pill_surface(marker_rect.size, color), -deg)
        surface.blit(rotated, rotated.get_rect(center=(mx, my)))


def _pill_surface(size: Tuple[int, int], color: Color) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(surf, (*color, 255), surf.get_rect(), border_radius=size[1] // 2)
    return surf


def battery_bar(
    surface: pygame.Surface,
    rect: Rect,
    percent: Optional[float],
    theme: Theme,
) -> None:
    """Vertical battery gauge (rounded outline + a small nub on top, like a
    real battery glyph) filled bottom-up by `percent`, with the percentage
    printed centered over the fill."""
    body = pygame.Rect(rect.x, rect.y + rect.height // 10, rect.width, int(rect.height * 0.88))
    nub_w = int(rect.width * 0.36)
    nub = pygame.Rect(0, 0, nub_w, rect.height // 10 + 2)
    nub.midbottom = (body.centerx, body.top + 2)

    pygame.draw.rect(surface, theme.panel_border, nub, border_radius=3)
    pygame.draw.rect(surface, theme.bg, body, border_radius=10)

    pct = 0.0 if percent is None else max(0.0, min(100.0, percent))
    fill_h = int((body.height - 6) * (pct / 100.0))
    if fill_h > 0:
        fill_color = theme.ok if pct > 25 else (theme.warn if pct > 10 else theme.danger)
        fill_rect = pygame.Rect(body.x + 3, body.bottom - 3 - fill_h, body.width - 6, fill_h)
        gradient_rect(surface, fill_rect, tuple(min(255, c + 60) for c in fill_color), fill_color, border_radius=8)
        glow_rect(surface, pygame.Rect(fill_rect.x, fill_rect.y, fill_rect.width, 3), fill_color,
                  spread=6, layers=3, max_alpha=100, border_radius=3)

    pygame.draw.rect(surface, theme.accent_dim, body, width=2, border_radius=10)

    label = "--" if percent is None else f"{pct:.0f}%"
    draw_text(surface, label, body.center, theme, size=max(12, rect.width // 4), color=theme.text, align="center")


def label_value(
    surface: pygame.Surface,
    rect: Rect,
    label: str,
    value: str,
    theme: Theme,
    value_color: Optional[Color] = None,
    icon_draw=None,
) -> None:
    """Common "small caption + big value, with an optional icon" layout
    used by the voltage/wattage cells: icon (if given) on the left third,
    caption above the value on the remaining width."""
    pad = 4
    if icon_draw is not None:
        icon_rect = pygame.Rect(rect.x + pad, rect.y + pad, rect.height - 2 * pad, rect.height - 2 * pad)
        icon_draw(surface, icon_rect, theme)
        text_x = icon_rect.right + pad
    else:
        text_x = rect.x + pad
    text_rect = pygame.Rect(text_x, rect.y, rect.right - text_x - pad, rect.height)

    draw_text_tracked(surface, label, (text_rect.x, text_rect.y + 2), theme, size=max(10, rect.height // 6),
                       spacing=1, bold=False, color=theme.text_dim, align="topleft")
    draw_text(
        surface, value, (text_rect.x, text_rect.bottom - 4), theme,
        size=max(14, rect.height // 3), color=value_color, align="bottomleft",
    )
