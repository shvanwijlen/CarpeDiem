"""CPU/memory/disk monitor - feeds the top bar's SYS status LED (the
previously-unused 8th/"spare" indicator slot - see hmi/topbar.py and
hmi_qt/topbar.py, both of which read this module's `sysmetrics_monitor`
singleton the same way they read display_data for the other 7).

Deliberately not routed through display_data: these are HMI-only host
stats about the Pi running this process, not boat telemetry, so they don't
belong in the DisplayInfo[] table port - see display_data.py.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from typing import Optional

import psutil

from carpediem.config import config
from carpediem.logging_setup import log

Status = str  # "ok" | "warn" | "crit"


@dataclass
class SysMetrics:
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float
    mem_percent: float
    disk_free_gb: float
    disk_total_gb: float
    disk_used_percent: float
    status: Status


def _level(value: float, warn: float, crit: float) -> Status:
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


_SEVERITY = {"ok": 0, "warn": 1, "crit": 2}


def _worst(*levels: Status) -> Status:
    return max(levels, key=lambda s: _SEVERITY[s])


class SysMetricsMonitor:
    def __init__(self) -> None:
        self._latest: Optional[SysMetrics] = None
        # cpu_percent(interval=None) measures the delta since its *last*
        # call - if that gap is too short (e.g. this priming call and the
        # first real sample() landing milliseconds apart at startup), the
        # reading is noisy/meaningless, occasionally spiking to a false
        # "crit". A one-time blocking 0.1s call here establishes a clean,
        # accurate baseline so every later interval=None call (including
        # the very first real sample()) measures a real window instead.
        psutil.cpu_percent(interval=0.1)

    @property
    def latest(self) -> Optional[SysMetrics]:
        return self._latest

    def sample(self) -> SysMetrics:
        cfg = config.sysmetrics
        cpu_percent = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        disk = shutil.disk_usage(cfg.disk_path)
        disk_used_percent = disk.used / disk.total * 100 if disk.total else 0.0

        status = _worst(
            _level(cpu_percent, cfg.cpu_warn_percent, cfg.cpu_crit_percent),
            _level(vm.percent, cfg.mem_warn_percent, cfg.mem_crit_percent),
            _level(disk_used_percent, cfg.disk_warn_percent, cfg.disk_crit_percent),
        )

        metrics = SysMetrics(
            cpu_percent=cpu_percent,
            mem_used_mb=vm.used / (1024 ** 2),
            mem_total_mb=vm.total / (1024 ** 2),
            mem_percent=vm.percent,
            disk_free_gb=disk.free / (1024 ** 3),
            disk_total_gb=disk.total / (1024 ** 3),
            disk_used_percent=disk_used_percent,
            status=status,
        )
        self._latest = metrics
        return metrics

    async def run_forever(self) -> None:
        while True:
            try:
                m = self.sample()
                log(9, f"SysMetrics: CPU {m.cpu_percent:.1f}% | "
                        f"MEM {m.mem_used_mb:.0f}/{m.mem_total_mb:.0f} MB ({m.mem_percent:.1f}%) | "
                        f"DISK {m.disk_free_gb:.1f}/{m.disk_total_gb:.1f} GB free "
                        f"({m.disk_used_percent:.1f}% used) | status={m.status}")
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(9, f"SysMetrics: sample failed, will retry: {exc}")
            await asyncio.sleep(config.sysmetrics.poll_interval_seconds)


# Module-level singleton, same pattern as display_data.py - both HMI
# engines' top bars import this directly rather than threading it through
# every page/widget constructor.
sysmetrics_monitor = SysMetricsMonitor()
