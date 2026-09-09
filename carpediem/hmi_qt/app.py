"""Entry point for the StartrekGraphical (Qt) HMI engine - selected via
CARPEDIEM_HMI_THEME=StartrekGraphical instead of the default pygame
"startrek" engine (see main.py's engine-selection logic). Same public
interface as hmi/app.py's HmiApp (init()/run_forever()/close()) so main.py
doesn't need to know which engine it's driving.

Qt has its own event loop (QApplication.exec()), which would block the
whole asyncio process if called normally. Instead of pulling in qasync,
this pumps Qt's event queue manually via processEvents() inside the same
asyncio-task-with-a-sleep pattern hmi/app.py uses for pygame - one fewer
dependency, and it keeps both engines integrating with main.py's asyncio
loop the same way. A QTimer (started in init()) drives the actual data
refresh independently of that pump rate, since widgets only need to be
told to redraw when something changed, not every tick.

This process needs a Qt platform plugin selected via QT_QPA_PLATFORM - see
.env.example for the two cases (desktop session running vs. none at all).
Note this isn't a straight analogy to pygame/SDL's SDL_VIDEODRIVER: on a
Pi already running the labwc/Wayland desktop, Qt's *native* "wayland" QPA
plugin left the window invisible (fullscreen requests silently not
honored - a labwc/Qt-wayland interop gap), where SDL_VIDEODRIVER=wayland
worked fine for pygame in that same setup. QT_QPA_PLATFORM=xcb (Qt running
as an XWayland client instead) is what actually worked there.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional

from carpediem.ais.service import AisService
from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log


class QtHmiApp:
    def __init__(self, ais_service: Optional[AisService] = None) -> None:
        self._ais_service = ais_service
        self._app = None
        self._window = None
        self._topbar = None
        self._stack = None
        self._pages: Dict[str, object] = {}
        self._refresh_timer = None

    def init(self) -> bool:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QFont
            from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

            from carpediem.hmi_qt.theme import STARTREK_GRAPHICAL
            from carpediem.hmi_qt.topbar import TopBar
            from carpediem.hmi_qt.pages.main_page import MainPage
            from carpediem.hmi_qt.pages.placeholder import PlaceholderPage

            self._app = QApplication.instance() or QApplication([])
            theme = STARTREK_GRAPHICAL

            # A generic family alias ("Sans Serif") can silently fail to
            # resolve to any real glyphs on some Qt platform plugins - seen
            # first as blank/tofu text under the "offscreen" plugin used
            # for local dev screenshots, but cheap enough insurance to set
            # explicitly everywhere. Same fallback order as hmi/theme.py's
            # pygame font list, using Qt's native multi-family fallback.
            default_font = QFont()
            default_font.setFamilies([
                "Bahnschrift", "DejaVu Sans Condensed", "DejaVu Sans",
                "Noto Sans", "Liberation Sans", "Verdana", "Arial", "Sans Serif",
            ])
            self._app.setFont(default_font)

            self._window = QWidget()
            self._window.setWindowTitle("CarpeDiem")
            self._window.setStyleSheet(
                f"background-color: rgb({theme.bg.red()},{theme.bg.green()},{theme.bg.blue()});"
            )
            self._window.resize(config.hmi.width, config.hmi.height)

            layout = QVBoxLayout(self._window)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self._topbar = TopBar(theme)
            layout.addWidget(self._topbar)

            self._stack = QStackedWidget()
            layout.addWidget(self._stack, 1)

            self._pages = {
                "main": MainPage(theme, self._ais_service),
                "ais": PlaceholderPage(theme, "AIS", "ais"),
                "weather": PlaceholderPage(theme, "Weather", "weather"),
                "power": PlaceholderPage(theme, "Power", "power"),
                "temps": PlaceholderPage(theme, "Temps", "temps"),
                "cam": PlaceholderPage(theme, "Cam", "cam"),
            }
            for page_id, _caption, _icon in self._page_order():
                self._stack.addWidget(self._pages[page_id])
            self._topbar.page_selected.connect(self._on_page_selected)

            if config.hmi.fullscreen:
                self._window.setCursor(Qt.CursorShape.BlankCursor)
                self._window.showFullScreen()
            else:
                self._window.show()

            from PySide6.QtCore import QTimer
            self._refresh_timer = QTimer()
            self._refresh_timer.timeout.connect(self._refresh)
            self._refresh_timer.start(max(50, int(1000 / max(1, config.hmi.fps))))
            self._refresh()

            log(7, f"Qt HMI (StartrekGraphical) initialized: {config.hmi.width}x{config.hmi.height} "
                    f"fullscreen={config.hmi.fullscreen}")
            return True
        except Exception as exc:  # noqa: BLE001 - no display attached, or Qt/plugin unavailable
            log(1, f"Qt HMI not available: {exc}")
            self._app = None
            return False

    @staticmethod
    def _page_order():
        from carpediem.hmi_qt.topbar import PAGES
        return [(pid, cap, icon) for pid, cap, icon in PAGES]

    def _on_page_selected(self, page_id: str) -> None:
        widget = self._pages.get(page_id)
        if widget is not None:
            self._stack.setCurrentWidget(widget)

    def _refresh(self) -> None:
        try:
            self._topbar.refresh()
            current = self._stack.currentWidget()
            if current is not None and hasattr(current, "refresh"):
                current.refresh()
            display_data.update("Display", 1, source="S")
        except Exception as exc:  # noqa: BLE001 - a bad refresh must not kill the QTimer callback
            log(1, f"Qt HMI: refresh failed, will retry: {exc}")
            display_data.update("Display", 0, source="S")

    async def run_forever(self) -> None:
        while True:
            if self._app is not None:
                try:
                    self._app.processEvents()
                except Exception as exc:  # noqa: BLE001 - keep the pump alive
                    log(1, f"Qt HMI: event pump failed, will retry: {exc}")
            await asyncio.sleep(0.03)

    def close(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None
        self._app = None
