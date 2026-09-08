"""Magedok 7" IPS touchscreen (1024x600) HMI - see app.py for the entry
point and README.md (top of the repo) for how this fits into main.py.

Package layout:
- theme.py    - visual skin (colors/fonts), swappable via config.hmi.theme
- widgets.py  - small reusable drawing primitives (LEDs, arrows, gauges)
- topbar.py   - the page-selector + subsystem-status bar shared by every page
- pages/      - one module per display tab (Main/AIS/Weather/Power/Temps/Cam)
- app.py      - pygame setup, the redraw/event loop, page switching
"""
