"""Run from the repo root:  python -m unittest discover -s tests -v

Covers when the SYS lamp turns purple (publish_status.py + sys_lamp_state()).
"""
from __future__ import annotations

import unittest

from carpediem.publish_status import FAILURES_BEFORE_ALERT, PublishStatus, publish_status
from carpediem.sysmetrics_monitor import SysMetrics, popup_rows, summary_rows, sys_lamp_state, sysmetrics_monitor


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class PublishStatusTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.status = PublishStatus(self.clock)
        self.status.enabled = True

    def test_not_failing_until_enough_pushes_in_a_row_fail(self):
        for _ in range(FAILURES_BEFORE_ALERT - 1):
            self.status.mark_failed("timeout")
            self.assertFalse(self.status.failing)  # one dropped packet must not flash the lamp
        self.status.mark_failed("timeout")
        self.assertTrue(self.status.failing)

    def test_one_success_clears_it(self):
        for _ in range(5):
            self.status.mark_failed("timeout")
        self.status.mark_ok()
        self.assertFalse(self.status.failing)
        self.assertIsNone(self.status.last_error)

    def test_failures_must_be_consecutive(self):
        self.status.mark_failed("x")
        self.status.mark_ok()
        self.status.mark_failed("x")
        self.assertFalse(self.status.failing)

    def test_alert_now_for_misconfiguration(self):
        self.status.mark_failed("PUBLISH_URL not set", alert_now=True)
        self.assertTrue(self.status.failing)

    def test_disabled_publisher_never_fails(self):
        self.status.enabled = False
        for _ in range(10):
            self.status.mark_failed("x")
        self.assertFalse(self.status.failing)
        self.assertIsNone(self.status.popup_row())

    def test_popup_row_texts(self):
        self.assertEqual(self.status.popup_row(), ("ok", "connecting..."))
        self.status.mark_ok()
        self.clock.now += 45
        self.assertEqual(self.status.popup_row(), ("ok", "OK - pushed 45s ago"))
        self.status.mark_failed("x", alert_now=True)
        self.clock.now += 300  # 345 s since the last success
        self.assertEqual(self.status.popup_row(), ("publish", "NOT PUSHING - last OK 5m ago"))

    def test_popup_row_when_it_never_worked(self):
        self.status.mark_failed("wrong key", alert_now=True)
        self.assertEqual(self.status.popup_row(), ("publish", "NOT PUSHING - never got through"))


def make_metrics(status: str) -> SysMetrics:
    return SysMetrics(cpu_percent=10, mem_used_mb=500, mem_total_mb=4000, mem_percent=12.5, disk_free_gb=20,
                      disk_total_gb=32, disk_used_percent=37, status=status, cpu_temp_c=50)


class LampStateTests(unittest.TestCase):
    """sys_lamp_state() reads two module-level singletons, so save/restore them."""

    def setUp(self):
        self._saved = (sysmetrics_monitor._latest, publish_status.enabled, publish_status.consecutive_failures,
                       publish_status.last_ok_at)
        publish_status.enabled = True
        publish_status.consecutive_failures = 0

    def tearDown(self):
        (sysmetrics_monitor._latest, publish_status.enabled, publish_status.consecutive_failures,
         publish_status.last_ok_at) = self._saved

    def fail_push(self):
        publish_status.consecutive_failures = FAILURES_BEFORE_ALERT

    def test_health_status_shows_when_push_is_fine(self):
        for status in ("ok", "warn", "crit"):
            sysmetrics_monitor._latest = make_metrics(status)
            self.assertEqual(sys_lamp_state(), status)

    def test_purple_replaces_green_and_orange(self):
        self.fail_push()
        for status in ("ok", "warn"):
            sysmetrics_monitor._latest = make_metrics(status)
            self.assertEqual(sys_lamp_state(), "publish")

    def test_red_beats_purple(self):
        self.fail_push()
        sysmetrics_monitor._latest = make_metrics("crit")
        self.assertEqual(sys_lamp_state(), "crit")

    def test_purple_even_without_a_health_reading(self):
        self.fail_push()
        sysmetrics_monitor._latest = None
        self.assertEqual(sys_lamp_state(), "publish")

    def test_no_reading_and_no_problem_is_unknown(self):
        sysmetrics_monitor._latest = None
        self.assertIsNone(sys_lamp_state())

    def test_popup_gets_a_store_row_but_the_phone_payload_does_not(self):
        m = make_metrics("ok")
        self.fail_push()
        rows = popup_rows(m)
        self.assertEqual([r.label for r in rows], ["CPU", "MEMORY", "DISK", "TEMP", "DATA STORE"])
        self.assertEqual(rows[-1].level, "publish")
        self.assertEqual(len(summary_rows(m)), 4)  # what system_payload() sends to the store/phone is unchanged

    def test_no_store_row_when_publishing_is_off(self):
        publish_status.enabled = False
        self.assertEqual(len(popup_rows(make_metrics("ok"))), 4)


if __name__ == "__main__":
    unittest.main()
