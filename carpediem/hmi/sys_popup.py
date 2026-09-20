"""SYS lamp detail popup, pygame version of hmi_qt/sys_popup.py - see that
module for the reasoning (full-window overlay, tap anywhere to close). Same
rows (sysmetrics_monitor.summary_rows()), same colors, so both HMI engines
and the iPhone app show identical numbers.
"""
from __future__ import annotations

from typing import Optional

import pygame

from carpediem.hmi.theme import Theme
from carpediem.hmi.widgets import draw_text, draw_text_tracked, gradient_rect
from carpediem.sysmetrics_monitor import summary_rows, sysmetrics_monitor

_STATUS_TEXT = {"ok": "ALL SYSTEMS OK", "warn": "WARNING", "crit": "CRITICAL"}


def _level_color(theme: Theme, level: Optional[str]):
    return {"ok": theme.ok, "warn": theme.warn, "crit": theme.danger}.get(level or "", theme.neutral)


def draw(surface: pygame.Surface, theme: Theme) -> None:
    w, h = surface.get_size()

    dim = pygame.Surface((w, h), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 175))
    surface.blit(dim, (0, 0))

    metrics = sysmetrics_monitor.latest
    panel_w = int(min(w * 0.72, 720))
    panel_h = int(min(h * 0.86, 460))
    panel = pygame.Rect(0, 0, panel_w, panel_h)
    panel.center = (w // 2, h // 2)

    status_color = _level_color(theme, metrics.status if metrics else None)
    for spread, alpha in ((14, 28), (8, 48), (3, 90)):
        glow = pygame.Surface(panel.inflate(spread * 2, spread * 2).size, pygame.SRCALPHA)
        pygame.draw.rect(glow, (*status_color, alpha), glow.get_rect(), width=spread, border_radius=20 + spread)
        surface.blit(glow, panel.inflate(spread * 2, spread * 2).topleft)
    gradient_rect(surface, panel, theme.panel_bg_hi, theme.panel_bg, border_radius=20)
    pygame.draw.rect(surface, status_color, panel, width=2, border_radius=20)

    pad = int(panel_h * 0.06)
    inner = panel.inflate(-int(pad * 2.8), -pad * 2)
    title_h = int(panel_h * 0.13)

    draw_text_tracked(surface, "SYSTEM", (inner.left, inner.top + title_h // 2), theme,
                       size=max(14, int(title_h * 0.62)), spacing=3, color=theme.accent, align="midleft")
    status_text = _STATUS_TEXT.get(metrics.status, "--") if metrics else "NO DATA"
    dot_d = max(8, int(title_h * 0.3))
    pygame.draw.circle(surface, status_color, (inner.right - dot_d // 2, inner.top + title_h // 2), dot_d // 2)
    draw_text_tracked(surface, status_text, (inner.right - dot_d - int(title_h * 0.3), inner.top + title_h // 2),
                       theme, size=max(12, int(title_h * 0.42)), spacing=2, color=status_color, align="midright")

    if metrics is None:
        draw_text(surface, "No system reading yet", panel.center, theme, size=max(12, int(panel_h * 0.06)),
                   bold=False, color=theme.text_dim, align="center")
        return

    rows = summary_rows(metrics)
    rows_top = inner.top + title_h + int(pad * 0.6)
    footer_h = int(panel_h * 0.08)
    row_h = (inner.bottom - footer_h - rows_top) / len(rows)

    for i, row in enumerate(rows):
        top = rows_top + i * row_h
        color = _level_color(theme, row.level)
        line_y = int(top + row_h * 0.3)
        draw_text_tracked(surface, row.label, (inner.left, line_y), theme, size=max(11, int(row_h * 0.26)),
                           spacing=2, bold=False, color=theme.text_dim, align="midleft")
        draw_text(surface, row.value, (inner.right, line_y), theme, size=max(14, int(row_h * 0.36)),
                   bold=True, color=color, align="midright")

        if row.fraction is not None:
            bar_h = max(6, int(row_h * 0.11))
            bar = pygame.Rect(inner.left, int(top + row_h * 0.64), inner.width, bar_h)
            pygame.draw.rect(surface, (20, 34, 44), bar, border_radius=bar_h // 2)
            fill = pygame.Rect(bar.left, bar.top, max(bar_h, int(bar.width * row.fraction)), bar_h)
            pygame.draw.rect(surface, color, fill, border_radius=bar_h // 2)

    draw_text_tracked(surface, "TAP ANYWHERE TO CLOSE", (inner.centerx, inner.bottom - footer_h // 2), theme,
                       size=max(10, int(footer_h * 0.5)), spacing=2, bold=False, color=theme.text_dim,
                       align="center")
