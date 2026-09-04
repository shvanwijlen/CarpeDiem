"""Entry point. Replaces the Arduino sketch's setup() + loop().

Architecture change from the original: instead of one single-threaded
loop() polling every subsystem in sequence (with a 5-minute "only
reconnect stuff every N ms" gate bolted on top), each subsystem now runs
as its own asyncio task, all writing into the shared, lock-protected
display_data store. This removes an entire class of bug the original had
to work around (e.g. one slow/blocked subsystem stalling everything else
in the loop) and there's no more need for the previousMillis/interval
reconnect-gate dance - each task just retries itself on its own schedule.

DoShow cleanup: the original printed the whole display table every single
pass of loop() - as fast as possible in DoFake mode (the sketch's own
TODO comment flags this as confusing/wrong: "klopt het dat hij in DoFake
mode maar 1x per seconde data langsloopt?"). It's now a plain timer
(SHOW_INTERVAL_SECONDS), independent of DoFake.
"""
from __future__ import annotations

import asyncio
from pydoc import __version__
import signal

from carpediem.config import config
from carpediem.logging_setup import log, setup_logging
from carpediem.display_data import display_data
from carpediem.fake_data import set_fake_data
from carpediem.modbus_client import ModbusPoller
from carpediem.mqtt_client import VictronMqttClient
from carpediem.ble_client import BleScanner
from carpediem.ais.service import AisService, log_vessel_proximity
from carpediem import rtc
from carpediem.matrix_display import MatrixDisplay
from carpediem.hdmi_display import HdmiDisplayMonitor

SHOW_INTERVAL_SECONDS = 5
MQTT_TICK_INTERVAL_SECONDS = 1
MATRIX_TICK_INTERVAL_SECONDS = 5


async def _mqtt_tick_loop(mqtt_client: VictronMqttClient) -> None:
    while True:
        mqtt_client.tick()
        await asyncio.sleep(MQTT_TICK_INTERVAL_SECONDS)


async def _matrix_tick_loop(matrix: MatrixDisplay) -> None:
    while True:
        now = rtc.now()
        matrix.tick(now.hour, now.minute)
        await asyncio.sleep(MATRIX_TICK_INTERVAL_SECONDS)


async def _show_loop(ais_service: AisService | None) -> None:
    """Port of the DoShow block in loop(), on a fixed timer instead of a
    tight/DoFake-dependent loop - see module docstring."""
    while True:
        await asyncio.sleep(SHOW_INTERVAL_SECONDS)
        if not config.flags.do_show:
            continue
        log(9, "+" * 72)
        for field in display_data.snapshot().values():
            log(9, f"Display : {field.display_label} : {field.value}")

        # Real AIS data is logged by AisService's own _print_loop; in fake
        # mode that task never runs (do_fake forces do_ais off), so the
        # fake nearby-vessel table is logged here instead, right after the
        # rest of the fake data.
        if config.flags.do_fake and ais_service is not None:
            results = ais_service.nearby_vessels()
            log(9, f"---- Nearby vessels (fake, {len(results)}) ----")
            for r in results:
                log_vessel_proximity(r)


async def _ble_task(scanner: BleScanner) -> None:
    await scanner.start()
    try:
        await asyncio.Event().wait()  # run until cancelled
    finally:
        await scanner.stop()


async def run() -> None:
    setup_logging()
    log(9, "=" * 40)
    log(9, "CarpeDiem starting (Raspberry Pi port) version ", __version__)
    log(9, "=" * 40)

    if config.flags.use_rtc:
        rtc.init_rtc()

    matrix = MatrixDisplay()
    if config.flags.use_matrix:
        matrix.init()

    ais_service: AisService | None = None
    if config.flags.do_ais or config.flags.do_fake:
        ais_service = AisService()

    if config.flags.do_fake:
        log(9, "DoFake is on: boat-dependent subsystems are disabled, using fake data")
        set_fake_data(ais_service)

    tasks: list[asyncio.Task] = [asyncio.create_task(_show_loop(ais_service))]

    if config.flags.use_matrix:
        tasks.append(asyncio.create_task(_matrix_tick_loop(matrix)))

    if config.flags.check_hdmi:
        tasks.append(asyncio.create_task(HdmiDisplayMonitor().run_forever()))

    modbus_poller: ModbusPoller | None = None
    if config.flags.do_modbus:
        modbus_poller = ModbusPoller()
        tasks.append(asyncio.create_task(modbus_poller.run_forever()))

    mqtt_client: VictronMqttClient | None = None
    if config.flags.do_mqtt:
        mqtt_client = VictronMqttClient()
        mqtt_client.start()
        tasks.append(asyncio.create_task(_mqtt_tick_loop(mqtt_client)))

    ble_scanner: BleScanner | None = None
    if config.flags.do_ble:
        ble_scanner = BleScanner()
        tasks.append(asyncio.create_task(_ble_task(ble_scanner)))

    if config.flags.do_ais:
        tasks.append(asyncio.create_task(ais_service.run_forever()))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows' default event loop (ProactorEventLoop) doesn't support
            # add_signal_handler - it's POSIX-only. Falls back to catching
            # Ctrl+C as a plain KeyboardInterrupt below instead. Only matters
            # when developing on Windows; the Pi target (Linux) always has
            # add_signal_handler available, so this is a no-op there.
            break

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    log(9, "Shutting down...")

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    if modbus_poller is not None:
        await modbus_poller.close()
    if mqtt_client is not None:
        mqtt_client.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
