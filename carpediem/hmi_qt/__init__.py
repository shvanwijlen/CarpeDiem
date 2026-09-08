""""StartrekGraphical" - a second HMI engine, built on PySide6/Qt instead
of pygame (see ../hmi/ for the original). Selected by setting
CARPEDIEM_HMI_THEME=StartrekGraphical instead of the default "startrek" -
see main.py's engine-selection logic.

Same visual language and layout as the pygame version (same color palette,
same Main-page composition, ported from the same Screen design v02.xlsx
spec), but drawn with real anti-aliased QPainter graphics, native
QGraphicsDropShadowEffect glow, QFont letter-spacing, and Qt layouts
instead of hand-rolled pixel math - a "true graphical" rendering path per
the request that started this, rather than pygame's immediate-mode
software rasterizing.

Package layout mirrors carpediem/hmi/:
- theme.py    - QColor palette
- widgets.py  - custom-painted QWidgets (gauges, compass, radar, LEDs)
- icons.py    - vector tab icons, QPainter versions of hmi/icons.py's
- topbar.py   - the page-selector + subsystem-status bar
- pages/      - one module per display tab
- app.py      - QApplication setup, the asyncio-driven event pump, page switching
"""
