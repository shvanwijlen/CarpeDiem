"""Visual skins for the HMI. Only "startrek" exists today, but every page
draws purely through a Theme object (colors + font()) so a second theme is
just a second Theme instance registered in THEMES - no page code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

import pygame

Color = Tuple[int, int, int]

# Fonts are resolved by family name at draw time (SysFont, not bundled
# files) so the app has no font-asset dependency - a bold condensed-ish
# sans is closer to the LCARS look than a monospace/console font, and
# Raspberry Pi OS ships DejaVu Sans + Noto Sans out of the box. Windows dev
# machines fall back further down the list.
_FONT_FAMILIES = "bahnschrift,dejavusanscondensed,dejavusans,notosans,liberationsans,verdana,arial,sans-serif"


@dataclass
class Theme:
    name: str

    bg: Color  # page background
    bg_hi: Color  # lighter end of the page background gradient
    panel_bg: Color  # section/card background
    panel_bg_hi: Color  # lighter end of the panel background gradient
    panel_border: Color  # thin dividers between sections
    accent: Color  # primary accent (active tab, headline numbers)
    accent_dim: Color  # accent at rest / inactive
    secondary: Color  # secondary accent (e.g. speed, highlights)
    tertiary: Color  # third accent, used sparingly (e.g. wind markers)
    text: Color
    text_dim: Color
    ok: Color
    warn: Color
    danger: Color
    neutral: Color  # e.g. stationary-vessel dot

    _font_cache: Dict[Tuple[int, bool], "pygame.font.Font"] = field(
        default_factory=dict, repr=False, compare=False
    )

    def font(self, size: int, bold: bool = False) -> "pygame.font.Font":
        key = (size, bold)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        f = pygame.font.SysFont(_FONT_FAMILIES, size, bold=bold)
        self._font_cache[key] = f
        return f


STARTREK = Theme(
    name="startrek",
    bg=(3, 5, 9),
    bg_hi=(9, 14, 22),
    panel_bg=(9, 15, 24),
    panel_bg_hi=(15, 24, 36),
    panel_border=(45, 85, 105),
    accent=(255, 153, 0),      # LCARS orange
    accent_dim=(120, 80, 30),
    secondary=(102, 204, 255),  # LCARS blue
    tertiary=(204, 153, 255),   # LCARS purple
    text=(226, 246, 255),
    text_dim=(120, 150, 165),
    ok=(51, 255, 102),
    warn=(255, 170, 40),
    danger=(255, 60, 60),
    neutral=(130, 140, 150),
)

THEMES: Dict[str, Theme] = {
    STARTREK.name: STARTREK,
}


def get_theme(name: str) -> Theme:
    try:
        return THEMES[name]
    except KeyError:
        raise ValueError(f"Unknown HMI theme '{name}' - available: {sorted(THEMES)}") from None
