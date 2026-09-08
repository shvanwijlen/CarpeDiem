"""Small reusable drawing primitives shared by the top bar and every page.
Nothing here knows about display_data - callers pass plain values/colors in
and get pixels out, which keeps this module themeable and unit-testable
without a real display.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

import pygame

from carpediem.hmi.theme import Color, Theme

Rect = pygame.Rect


def panel(surface: pygame.Surface, rect: Rect, theme: Theme, border: bool = True) -> None:
    pygame.draw.rect(surface, theme.panel_bg, rect, border_radius=6)
    if border:
        pygame.draw.rect(surface, theme.panel_border, rect, width=1, border_radius=6)


def divider_v(surface: pygame.Surface, x: int, y1: int, y2: int, theme: Theme, width: int = 1) -> None:
    pygame.draw.line(surface, theme.panel_border, (x, y1), (x, y2), width)


def divider_h(surface: pygame.Surface, y: int, x1: int, x2: int, theme: Theme, width: int = 1) -> None:
    pygame.draw.line(surface, theme.panel_border, (x1, y), (x2, y), width)


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


def led(surface: pygame.Surface, center: Tuple[int, int], radius: int, on: bool, theme: Theme) -> None:
    color = theme.ok if on else theme.danger
    pygame.draw.circle(surface, color, center, radius)
    pygame.draw.circle(surface, theme.panel_border, center, radius, width=1)


def arrow(
    surface: pygame.Surface,
    center: Tuple[float, float],
    length: float,
    angle_deg: float,
    color: Color,
    width: int = 3,
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
    """North-up compass ring with tick marks every 30deg and a colored
    rectangle marker (angle clockwise from top, color) for each entry in
    `markers` - used for the own-course/wind-direction indicators."""
    pygame.draw.circle(surface, theme.panel_bg, center, radius)
    pygame.draw.circle(surface, theme.panel_border, center, radius, width=2)

    for deg in range(0, 360, 30):
        theta = math.radians(deg)
        outer = (center[0] + math.sin(theta) * radius, center[1] - math.cos(theta) * radius)
        inner = (center[0] + math.sin(theta) * (radius - 8), center[1] - math.cos(theta) * (radius - 8))
        pygame.draw.line(surface, theme.text_dim, inner, outer, 2)

    for deg, color in markers:
        theta = math.radians(deg)
        mx = center[0] + math.sin(theta) * (radius - 3)
        my = center[1] - math.cos(theta) * (radius - 3)
        marker_rect = pygame.Rect(0, 0, 14, 8)
        marker_rect.center = (mx, my)
        rotated = pygame.transform.rotate(_solid_surface(marker_rect.size, color), -deg)
        surface.blit(rotated, rotated.get_rect(center=(mx, my)))


def _solid_surface(size: Tuple[int, int], color: Color) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill((*color, 255))
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

    pygame.draw.rect(surface, theme.panel_border, nub, border_radius=2)
    pygame.draw.rect(surface, theme.bg, body, border_radius=4)

    pct = 0.0 if percent is None else max(0.0, min(100.0, percent))
    fill_h = int((body.height - 6) * (pct / 100.0))
    if fill_h > 0:
        fill_color = theme.ok if pct > 25 else (theme.warn if pct > 10 else theme.danger)
        fill_rect = pygame.Rect(body.x + 3, body.bottom - 3 - fill_h, body.width - 6, fill_h)
        pygame.draw.rect(surface, fill_color, fill_rect, border_radius=3)

    pygame.draw.rect(surface, theme.accent_dim, body, width=2, border_radius=4)

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

    draw_text(surface, label, (text_rect.x, text_rect.y + 2), theme, size=max(10, rect.height // 5),
              bold=False, color=theme.text_dim, align="topleft")
    draw_text(
        surface, value, (text_rect.x, text_rect.bottom - 4), theme,
        size=max(14, rect.height // 3), color=value_color, align="bottomleft",
    )
