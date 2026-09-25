"""Whether the Pi's pushes to the remote data store (publisher.py) are getting
through - what turns the top bar's SYS lamp purple (see sysmetrics_monitor.py's
sys_lamp_state()).

Deliberately its own tiny module: the display engines read it every frame, and
it must not drag in the publisher's HTTP/Ring imports. Same module-level
singleton pattern as display_data.py / sysmetrics_monitor.py.

"Failing" needs FAILURES_BEFORE_ALERT pushes in a row to fail (about 20 s at
the default 10 s interval), so one dropped packet on a marina/cellular link
doesn't flash the lamp purple; a first success clears it immediately.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

FAILURES_BEFORE_ALERT = 2


def _ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h"


class PublishStatus:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        # Only True while a Publisher is running. Without one (PUBLISH_BACKEND=none)
        # nothing is expected to be pushed, so nothing can be "failing".
        self.enabled = False
        self.consecutive_failures = 0
        self.last_ok_at: Optional[float] = None
        self.last_error: Optional[str] = None

    def mark_ok(self) -> None:
        self.consecutive_failures = 0
        self.last_ok_at = self._clock()
        self.last_error = None

    def mark_failed(self, error: str, alert_now: bool = False) -> None:
        """A push failed. alert_now: don't wait for a second failure - for
        problems that can't fix themselves, like a missing URL or key."""
        self.consecutive_failures = (max(self.consecutive_failures + 1, FAILURES_BEFORE_ALERT)
                                     if alert_now else self.consecutive_failures + 1)
        self.last_error = error

    @property
    def failing(self) -> bool:
        return self.enabled and self.consecutive_failures >= FAILURES_BEFORE_ALERT

    def popup_row(self) -> Optional[tuple[str, str]]:
        """(level, text) for the SYS popup's "DATA STORE" row, or None when
        publishing is off. level is "ok" or "publish" (the purple one)."""
        if not self.enabled:
            return None
        if self.failing:
            since = f"last OK {_ago(self._clock() - self.last_ok_at)} ago" if self.last_ok_at else "never got through"
            return "publish", f"NOT PUSHING - {since}"
        if self.last_ok_at is None:
            return "ok", "connecting..."
        return "ok", f"OK - pushed {_ago(self._clock() - self.last_ok_at)} ago"


publish_status = PublishStatus()
