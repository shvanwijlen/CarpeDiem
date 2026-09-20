"""CPU/memory/disk monitor - feeds the top bar's SYS status LED (the
previously-unused 8th/"spare" indicator slot - see hmi/topbar.py and
hmi_qt/topbar.py, both of which read this module's `sysmetrics_monitor`
singleton the same way they read display_data for the other 7).

Deliberately not routed through display_data: these are HMI-only host
stats about the Pi running this process, not boat telemetry, so they don't
belong in the DisplayInfo[] table port - see display_data.py.

Tapping the SYS lamp on either HMI (or in the iPhone app) shows the detail
behind it - CPU / memory / disk usage and the Pi's own temperature. All
three read the same summary_rows() below, so the numbers, wording and
warn/crit coloring can't drift apart between displays.
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
    cpu_temp_c: Optional[float] = None  # None where the platform has no sensor (e.g. Windows dev machine)


def _level(value: float, warn: float, crit: float) -> Status:
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


def read_cpu_temp_c() -> Optional[float]:
    """The Pi's CPU temperature in Celsius, or None if it can't be read.
    Tries psutil's sensor API first (Linux), then the thermal zone file the
    Pi kernel exposes directly."""
    try:
        sensors = getattr(psutil, "sensors_temperatures", lambda: {})()
        for name in ("cpu_thermal", "cpu-thermal", "coretemp", "k10temp"):
            readings = sensors.get(name)
            if readings:
                return float(readings[0].current)
        for readings in sensors.values():
            if readings:
                return float(readings[0].current)
    except Exception:  # noqa: BLE001 - sensor APIs vary by platform; fall through to the file
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


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
            cpu_temp_c=read_cpu_temp_c(),
        )
        self._latest = metrics
        return metrics

    async def run_forever(self) -> None:
        while True:
            try:
                m = self.sample()
                if m.status != "ok":
                    log(1, f"SysMetrics: status={m.status} | "
                           f"CPU {m.cpu_percent:.1f}% | "
                           f"MEM {m.mem_percent:.1f}% | "
                           f"DISK {m.disk_used_percent:.1f}% used")
                else:
                    log(10, f"SysMetrics: CPU {m.cpu_percent:.1f}% | "
                            f"MEM {m.mem_used_mb:.0f}/{m.mem_total_mb:.0f} MB ({m.mem_percent:.1f}%) | "
                            f"DISK {m.disk_free_gb:.1f}/{m.disk_total_gb:.1f} GB free "
                            f"({m.disk_used_percent:.1f}% used) | "
                            f"TEMP {('%.1f' % m.cpu_temp_c) if m.cpu_temp_c is not None else 'n/a'}C | status={m.status}")
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                log(1, f"SysMetrics: sample failed, will retry: {exc}")
            await asyncio.sleep(config.sysmetrics.poll_interval_seconds)


@dataclass
class SysRow:
    label: str
    value: str  # already formatted, e.g. "47%  1.8 / 3.8 GB"
    level: Status  # "ok" | "warn" | "crit" - drives the row's color
    fraction: Optional[float]  # 0..1 for a bar, or None for no bar


def summary_rows(m: SysMetrics) -> list[SysRow]:
    """The four lines of the SYS popup. CPU/MEM/DISK levels are the same
    thresholds that drive the SYS LED; TEMP is colored by its own thresholds
    but, being display-only, never changes the LED (see SysMetricsConfig)."""
    cfg = config.sysmetrics
    rows = [
        SysRow("CPU", f"{m.cpu_percent:.0f}%", _level(m.cpu_percent, cfg.cpu_warn_percent, cfg.cpu_crit_percent),
               min(1.0, m.cpu_percent / 100)),
        SysRow("MEMORY", f"{m.mem_percent:.0f}%   {m.mem_used_mb / 1024:.1f} / {m.mem_total_mb / 1024:.1f} GB",
               _level(m.mem_percent, cfg.mem_warn_percent, cfg.mem_crit_percent), min(1.0, m.mem_percent / 100)),
        SysRow("DISK", f"{m.disk_used_percent:.0f}%   {m.disk_free_gb:.1f} GB free",
               _level(m.disk_used_percent, cfg.disk_warn_percent, cfg.disk_crit_percent),
               min(1.0, m.disk_used_percent / 100)),
    ]
    if m.cpu_temp_c is None:
        rows.append(SysRow("TEMP", "n/a", "ok", None))
    else:
        rows.append(SysRow("TEMP", f"{m.cpu_temp_c:.1f} °C",
                           _level(m.cpu_temp_c, cfg.cpu_temp_warn_c, cfg.cpu_temp_crit_c),
                           max(0.0, min(1.0, m.cpu_temp_c / 100))))
    return rows


# Module-level singleton, same pattern as display_data.py - both HMI
# engines' top bars import this directly rather than threading it through
# every page/widget constructor.
sysmetrics_monitor = SysMetricsMonitor()
