"""Run from the repo root:  python -m unittest discover -s tests -v

Covers the /screen view (web_server.py) and the Qt window grab behind it
(QtHmiApp.screenshot_jpeg).
"""
from __future__ import annotations

import os
import unittest
from typing import List, Optional

from aiohttp.test_utils import AioHTTPTestCase

from carpediem.config import config
from carpediem import web_server
from carpediem.web_server import SCREEN_MAX_WIDTH, SCREEN_MIN_WIDTH, WebServer

FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class ScreenRouteTests(AioHTTPTestCase):
    async def get_application(self):
        self.calls: List[Optional[int]] = []
        self.next_result: Optional[bytes] = FAKE_JPEG
        self.web = WebServer(screen_provider=self._provider)
        self.saved_key = config.webserver.api_key
        config.webserver.api_key = ""
        self.addCleanup(setattr, config.webserver, "api_key", self.saved_key)
        # A slow test machine mustn't turn "within the cache window" into a race.
        saved_interval = web_server.SCREEN_MIN_INTERVAL_SECONDS
        web_server.SCREEN_MIN_INTERVAL_SECONDS = 60.0
        self.addCleanup(setattr, web_server, "SCREEN_MIN_INTERVAL_SECONDS", saved_interval)
        return self.web._build_app()

    def _provider(self, width):
        self.calls.append(width)
        return self.next_result

    async def test_page_is_served(self):
        resp = await self.client.get("/screen")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.headers["Content-Type"])
        self.assertIn("/api/screen.jpg", await resp.text())

    async def test_jpeg(self):
        resp = await self.client.get("/api/screen.jpg")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["Content-Type"], "image/jpeg")
        self.assertEqual(await resp.read(), FAKE_JPEG)
        self.assertEqual(self.calls, [None])

    async def test_requests_in_quick_succession_share_one_capture(self):
        for _ in range(5):
            await self.client.get("/api/screen.jpg")
        self.assertEqual(len(self.calls), 1)  # cached, not repainted per request

    async def test_width_is_passed_and_clamped(self):
        await self.client.get("/api/screen.jpg?w=800")
        await self.client.get("/api/screen.jpg?w=5")
        await self.client.get("/api/screen.jpg?w=99999")
        self.assertEqual(self.calls, [800, SCREEN_MIN_WIDTH, SCREEN_MAX_WIDTH])

    async def test_bad_width_is_a_400(self):
        resp = await self.client.get("/api/screen.jpg?w=wide")
        self.assertEqual(resp.status, 400)
        self.assertEqual(self.calls, [])

    async def test_no_window_is_a_503(self):
        self.next_result = None
        resp = await self.client.get("/api/screen.jpg")
        self.assertEqual(resp.status, 503)

    async def test_provider_crash_is_a_503_not_a_500(self):
        def boom(width):
            raise RuntimeError("grab failed")
        self.web._screen_provider = boom
        resp = await self.client.get("/api/screen.jpg")
        self.assertEqual(resp.status, 503)

    async def test_pygame_engine_has_no_provider(self):
        self.web._screen_provider = None
        resp = await self.client.get("/api/screen.jpg")
        self.assertEqual(resp.status, 501)

    async def test_api_key_protects_the_image_but_not_the_page(self):
        config.webserver.api_key = "s3cret"
        self.assertEqual((await self.client.get("/screen")).status, 200)  # the page holds no data
        self.assertEqual((await self.client.get("/api/screen.jpg")).status, 401)
        self.assertEqual((await self.client.get("/api/screen.jpg", headers={"X-API-Key": "wrong"})).status, 401)
        ok = await self.client.get("/api/screen.jpg", headers={"X-API-Key": "s3cret"})
        self.assertEqual(ok.status, 200)
        self.assertEqual(self.calls, [None])  # the refused requests never reached the capture


try:
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:  # PySide6 is optional (Qt HMI only)
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QtGrabTests(unittest.TestCase):
    def setUp(self):
        # Forced, not setdefault: importing carpediem.config loads the repo's .env,
        # which on the Pi (and a copied .env) sets QT_QPA_PLATFORM=xcb.
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        self.app = QApplication.instance() or QApplication([])

    def make_hmi(self):
        from carpediem.hmi_qt.app import QtHmiApp
        hmi = QtHmiApp()
        hmi._window = QLabel("hello")
        hmi._window.resize(640, 360)
        return hmi

    def test_returns_a_jpeg_of_the_window(self):
        data = self.make_hmi().screenshot_jpeg()
        self.assertIsNotNone(data)
        self.assertTrue(data.startswith(b"\xff\xd8"))  # JPEG magic

    def test_scales_down_to_max_width(self):
        from PySide6.QtGui import QImage
        data = self.make_hmi().screenshot_jpeg(max_width=320)
        image = QImage.fromData(data)
        self.assertEqual(image.width(), 320)
        self.assertEqual(image.height(), 180)

    def test_no_window_means_none(self):
        from carpediem.hmi_qt.app import QtHmiApp
        self.assertIsNone(QtHmiApp().screenshot_jpeg())


if __name__ == "__main__":
    unittest.main()
