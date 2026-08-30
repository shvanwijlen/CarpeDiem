"""Port of the Mudbus polling block in loop() that reads Victron Cerbo GX
registers (com.victronenergy.system, .battery, .temperature, ...).

Targets pymodbus >=3.8's async client API (`device_id=` kwarg on
read_holding_registers - pymodbus renamed this from `slave=` in 3.8). If
you're pinned to an older 3.6.x/3.7.x pymodbus, change `device_id=` back
to `slave=` in `_read_register` below.

Bug fixed while porting: the original regs[] table had a register labeled
"Battery Voltage (V)", but DisplayInfo's matching field is called
"Battery0 Voltage (V)" - UpdateDisplayTable() does an exact string match,
so that register's value was silently never making it into the display
table. Renamed here to actually match.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log


@dataclass(frozen=True)
class RegInfo:
    label: str
    unit_id: int
    register: int
    scale: float


# com.victronenergy.system       100
# com.victronenergy.battery      224
# com.victronenergy.temperature  20 (electronics bay) / 21 (engine room)
# GPS: not via Modbus - comes from the em-trak AIS stream instead
REGISTERS: List[RegInfo] = [
    RegInfo("Grid (W)", 100, 820, 1.0),
    RegInfo("Active input source", 100, 826, 1.0),  # 0=Unknown;1=Grid;2=Generator;3=Shore;240=Not connected
    RegInfo("AC Loads (W)", 100, 817, 1.0),
    RegInfo("Battery SOC (%)", 100, 843, 1.0),
    RegInfo("Battery0 Voltage (V)", 100, 840, 0.1),  # was "Battery Voltage (V)" - fixed, see module docstring
    RegInfo("PV Power (W)", 100, 850, 1.0),
    RegInfo("Starter battery (V)", 224, 260, 0.01),
    RegInfo("Electronics bay (C)", 20, 3304, 0.01),
    RegInfo("Engine room (C)", 21, 3304, 0.01),
]

POLL_INTERVAL_SECONDS = 10


class ModbusPoller:
    """Maintains a connection to the Cerbo GX and polls REGISTERS on a
    fixed interval, writing results into the shared display_data store."""

    def __init__(self) -> None:
        self._client: AsyncModbusTcpClient | None = None

    async def _ensure_connected(self) -> bool:
        if self._client is None:
            self._client = AsyncModbusTcpClient(config.cerbo.host, port=config.cerbo.port)
        if not self._client.connected:
            log(9, f"MODBUS: connecting to Cerbo GX at {config.cerbo.host}:{config.cerbo.port} ...")
            await self._client.connect()
        connected = self._client.connected
        display_data.update("MODBUS", 1 if connected else 0, source="S")
        return connected

    async def _read_register(self, reg: RegInfo) -> None:
        try:
            result = await self._client.read_holding_registers(
                address=reg.register, count=1, device_id=reg.unit_id
            )
        except ModbusException as exc:
            log(9, f"MODBUS: read error for {reg.label}: {exc}")
            return

        if result.isError():
            log(9, f"MODBUS: <no valid data returned> for {reg.label} (unit {reg.unit_id}, reg {reg.register})")
            return

        raw = result.registers[0]
        value = raw * reg.scale
        display_data.update(reg.label, value, source="M")

    async def poll_once(self) -> None:
        if not await self._ensure_connected():
            return
        for reg in REGISTERS:
            await self._read_register(reg)

    async def run_forever(self) -> None:
        """Equivalent of the DoMODBUS block inside loop(), run as its own
        asyncio task instead of a shared polling loop."""
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - keep the poller alive
                log(9, f"MODBUS: unexpected error, will retry: {exc}")
                display_data.update("MODBUS", 0, source="S")
                if self._client is not None:
                    await self._client.close()
                    self._client = None
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
