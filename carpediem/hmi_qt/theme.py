"""Color palette for the StartrekGraphical engine - same values as
hmi/theme.py's STARTREK Theme, just as QColor instead of (r,g,b) tuples,
so both engines read as the same "brand" even though one is pygame and the
other is Qt."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor


def _c(r: int, g: int, b: int) -> QColor:
    return QColor(r, g, b)


@dataclass(frozen=True)
class QtTheme:
    bg: QColor
    bg_hi: QColor
    panel_bg: QColor
    panel_bg_hi: QColor
    panel_border: QColor
    accent: QColor
    accent_dim: QColor
    secondary: QColor
    tertiary: QColor
    text: QColor
    text_dim: QColor
    ok: QColor
    warn: QColor
    danger: QColor
    neutral: QColor


STARTREK_GRAPHICAL = QtTheme(
    bg=_c(3, 5, 9),
    bg_hi=_c(9, 14, 22),
    panel_bg=_c(9, 15, 24),
    panel_bg_hi=_c(15, 24, 36),
    panel_border=_c(45, 85, 105),
    accent=_c(255, 153, 0),
    accent_dim=_c(120, 80, 30),
    secondary=_c(102, 204, 255),
    tertiary=_c(204, 153, 255),
    text=_c(226, 246, 255),
    text_dim=_c(120, 150, 165),
    ok=_c(51, 255, 102),
    warn=_c(255, 170, 40),
    danger=_c(255, 60, 60),
    neutral=_c(130, 140, 150),
)
