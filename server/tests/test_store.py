"""Run from server/:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import tempfile
import unittest
from dataclasses import replace

from aiohttp.test_utils import TestClient, TestServer

from carpediem_store.app import create_app, run_cleanup
from carpediem_store.config import ConfigError, StoreConfig
from carpediem_store.storage import SqliteStorage, create_storage

READ = {"X-API-Key": "read-key"}
WRITE = {"X-API-Key": "write-key"}
DAY = 86400
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_cfg(**overrides) -> StoreConfig:
    base = StoreConfig(read_api_key="read-key", write_api_key="write-key", sqlite_path=":memory:",
                       retention_days=30, history_interval_seconds=60)
    return replace(base, **overrides)


class ConfigTests(unittest.TestCase):
    def test_keys_are_required(self):
        with self.assertRaises(ConfigError):
            StoreConfig.from_env({})

    def test_keys_must_differ(self):
        with self.assertRaises(ConfigError):
            StoreConfig.from_env({"READ_API_KEY": "same", "WRITE_API_KEY": "same"})

    def test_retention_values(self):
        env = {"READ_API_KEY": "r", "WRITE_API_KEY": "w"}
        self.assertFalse(StoreConfig.from_env({**env, "RETENTION_DAYS": "-1"}).cleanup_enabled)
        self.assertEqual(StoreConfig.from_env({**env, "RETENTION_DAYS": "7"}).retention_days, 7)
        self.assertEqual(StoreConfig.from_env(env).retention_days, 30)  # default
        for bad in ("0", "-2", "abc"):
            with self.assertRaises(ConfigError, msg=bad):
                StoreConfig.from_env({**env, "RETENTION_DAYS": bad})

    def test_unknown_backend(self):
        with self.assertRaises(ConfigError):
            create_storage(make_cfg(storage_backend="mongo"))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.storage = SqliteStorage(":memory:")
        self.cfg = make_cfg()
        self.client = TestClient(TestServer(create_app(self.cfg, self.storage, self.clock)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def push(self, data=None, **kw):
        return await self.client.put("/v1/state", json={"sent_at": 5, "data": data or {"Speed": 4.2}, **kw}, headers=WRITE)

    async def test_health_is_open(self):
        resp = await self.client.get("/health")
        self.assertEqual(resp.status, 200)

    async def test_auth_read_vs_write(self):
        self.assertEqual((await self.client.get("/v1/state")).status, 401)
        self.assertEqual((await self.client.get("/v1/state", headers={"X-API-Key": "nope"})).status, 401)
        self.assertEqual((await self.client.get("/v1/state", headers=WRITE)).status, 401)  # write key can't read
        self.assertEqual((await self.client.put("/v1/state", json={"data": {}}, headers=READ)).status, 401)  # read key can't write
        self.assertEqual((await self.client.put("/v1/state", json={"data": {}})).status, 401)
        self.assertEqual((await self.client.get("/v1/state", headers=READ)).status, 200)

    async def test_empty_store(self):
        body = await (await self.client.get("/v1/state", headers=READ)).json()
        self.assertIsNone(body["age_seconds"])
        self.assertEqual(body["data"], {})

    async def test_round_trip_and_age(self):
        resp = await self.push({"Speed": 4.2, "Lat": 52.3}, vessels={"vessels": []}, system={"status": "ok"})
        self.assertEqual(resp.status, 200)
        self.clock.now += 7
        body = await (await self.client.get("/v1/state", headers=READ)).json()
        self.assertEqual(body["data"], {"Speed": 4.2, "Lat": 52.3})
        self.assertEqual(body["vessels"], {"vessels": []})
        self.assertEqual(body["system"], {"status": "ok"})
        self.assertAlmostEqual(body["age_seconds"], 7)
        self.assertEqual(body["sent_at"], 5)

    async def test_latest_wins(self):
        await self.push({"Speed": 1})
        self.clock.now += 1
        await self.push({"Speed": 2})
        body = await (await self.client.get("/v1/state", headers=READ)).json()
        self.assertEqual(body["data"]["Speed"], 2)

    async def test_gzip_request_body(self):
        raw = gzip.compress(json.dumps({"data": {"Speed": 9}}).encode())
        resp = await self.client.put("/v1/state", data=raw, headers={**WRITE, "Content-Type": "application/json",
                                                                      "Content-Encoding": "gzip"})
        self.assertEqual(resp.status, 200)
        body = await (await self.client.get("/v1/state", headers=READ)).json()
        self.assertEqual(body["data"]["Speed"], 9)

    async def test_rejects_bad_payloads(self):
        for bad in ([1, 2], {"nodata": 1}, {"data": [1]}, {"data": {}, "vessels": 3}):
            resp = await self.client.put("/v1/state", json=bad, headers=WRITE)
            self.assertEqual(resp.status, 400, bad)
        resp = await self.client.put("/v1/state", data=b"not json", headers=WRITE)
        self.assertEqual(resp.status, 400)

    async def test_history_is_throttled(self):
        await self.push()                      # t0: kept
        self.clock.now += 10
        await self.push()                      # 10s later: latest only
        self.clock.now += 55
        await self.push()                      # 65s after the first: kept
        self.assertEqual(await self.storage.history_count(), 2)

    async def test_history_disabled(self):
        self.cfg = make_cfg(history_interval_seconds=0)
        client = TestClient(TestServer(create_app(self.cfg, SqliteStorage(":memory:"), self.clock)))
        await client.start_server()
        try:
            await client.put("/v1/state", json={"data": {}}, headers=WRITE)
            body = await (await client.get("/v1/history", headers=READ)).json()
            self.assertEqual(body["states"], [])
            self.assertIsNotNone((await (await client.get("/v1/state", headers=READ)).json())["received_at"])
        finally:
            await client.close()

    async def test_history_endpoint(self):
        for speed in (1, 2, 3):
            await self.push({"Speed": speed})
            self.clock.now += 100
        states = (await (await self.client.get("/v1/history?limit=2", headers=READ)).json())["states"]
        self.assertEqual([s["data"]["Speed"] for s in states], [3, 2])  # newest first
        self.assertEqual((await self.client.get("/v1/history?since=abc", headers=READ)).status, 400)

    async def test_snapshot_round_trip(self):
        self.assertEqual((await self.client.get("/v1/cam/salon/snapshot.jpg", headers=READ)).status, 404)
        resp = await self.client.put("/v1/cam/salon/snapshot", data=JPEG, headers=WRITE)
        self.assertEqual(resp.status, 200)
        got = await self.client.get("/v1/cam/salon/snapshot.jpg", headers=READ)
        self.assertEqual(got.status, 200)
        self.assertEqual(got.content_type, "image/jpeg")
        self.assertEqual(await got.read(), JPEG)

    async def test_snapshot_validation(self):
        self.assertEqual((await self.client.put("/v1/cam/salon/snapshot", data=b"GIF89a", headers=WRITE)).status, 400)
        self.assertEqual((await self.client.put("/v1/cam/BAD NAME/snapshot", data=JPEG, headers=WRITE)).status, 400)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock(100 * DAY)
        self.storage = SqliteStorage(":memory:")
        await self.storage.open()
        # history at 60, 45, 20 and 1 days old, plus a "latest" state and snapshot that are also old
        for age_days in (60, 45, 20, 1):
            await self.storage.put_state(self.clock.now - age_days * DAY, {"data": {"age": age_days}}, keep_history=True)
        await self.storage.put_state(self.clock.now - 90 * DAY, {"data": {"latest": True}}, keep_history=False)
        await self.storage.put_snapshot("salon", self.clock.now - 90 * DAY, JPEG)

    async def asyncTearDown(self):
        await self.storage.close()

    async def test_retention_30_days(self):
        deleted = await run_cleanup(make_cfg(retention_days=30), self.storage, self.clock)
        self.assertEqual(deleted, 2)
        remaining = await self.storage.history(0, self.clock.now, 100)
        self.assertEqual([r.payload["data"]["age"] for r in remaining], [1, 20])

    async def test_never_cleanup(self):
        self.assertEqual(await run_cleanup(make_cfg(retention_days=-1), self.storage, self.clock), 0)
        self.assertEqual(await self.storage.history_count(), 4)

    async def test_cleanup_keeps_latest_state_and_snapshot(self):
        await run_cleanup(make_cfg(retention_days=1), self.storage, self.clock)
        self.assertEqual((await self.storage.get_state()).payload["data"], {"latest": True})
        self.assertIsNotNone(await self.storage.get_snapshot("salon"))

    async def test_cleanup_runs_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.db")
            first = SqliteStorage(path)
            await first.open()
            await first.put_state(self.clock.now - 60 * DAY, {"data": {}}, keep_history=True)
            await first.put_state(self.clock.now - 1 * DAY, {"data": {}}, keep_history=True)
            await first.close()

            storage = SqliteStorage(path)
            client = TestClient(TestServer(create_app(make_cfg(sqlite_path=path, retention_days=30), storage, self.clock)))
            await client.start_server()
            try:
                for _ in range(50):  # the cleanup task starts with the app; give it a moment
                    if await storage.history_count() == 1:
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(await storage.history_count(), 1)
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
