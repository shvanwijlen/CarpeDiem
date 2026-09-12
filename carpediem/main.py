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
import signal

from carpediem import __version__
from carpediem.config import config
from carpediem.logging_setup import log, setup_logging
from carpediem.display_data import display_data
from carpediem.fake_data import set_fake_data
from carpediem.modbus_client import ModbusPoller
from carpediem.mqtt_client import VictronMqttClient
from carpediem.ble_client import BleScanner
from carpediem.ring_client import RingClient
from carpediem.bresser_client import BresserClient
from carpediem.wunderground_client import WundergroundClient
from carpediem.ais.service import AisService, log_vessel_proximity
from carpediem import rtc
from carpediem.matrix_display import MatrixDisplay
from carpediem.hmi.app import HmiApp
from carpediem.hmi_qt.app import QtHmiApp
from carpediem.hdmi_display import HdmiDisplayMonitor
from carpediem.ups_monitor import UpsMonitor
from carpediem.wifi_monitor import WifiMonitor
from carpediem.sysmetrics_monitor import sysmetrics_monitor
from carpediem.sensors.bme280_sensor import Bme280Monitor

SHOW_INTERVAL_SECONDS = 5
MQTT_TICK_INTERVAL_SECONDS = 1
MATRIX_TICK_INTERVAL_SECONDS = 5


async def _mqtt_tick_loop(mqtt_client: VictronMqttClient) -> None:
    while True:
        mqtt_client.tick()
        await asyncio.sleep(MQTT_TICK_INTERVAL_SECONDS)


async def _matrix_tick_loop(matrix: MatrixDisplay) -> None:
    while True:
        try:
            matrix.tick()
        except Exception as exc:  # noqa: BLE001 - a bad SPI write must not kill the retry loop
            log(9, f"Matrix: tick failed, will retry: {exc}")
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
            log(10, f"Display : {field.display_label} : {field.value}")

        # Real AIS data is logged by AisService's own _print_loop; in fake
        # mode that task never runs (do_fake forces do_ais off), so the
        # fake nearby-vessel table is logged here instead, right after the
        # rest of the fake data.
        if config.flags.do_fake and ais_service is not None:
            results = ais_service.nearby_vessels()
            log(10, f"---- Nearby vessels (fake, {len(results)}) ----")
            for r in results:
                log_vessel_proximity(r)


async def run() -> None:
    setup_logging()
    log(9, "=" * 60)
    log(9, "CarpeDiem starting (Raspberry Pi port) version ", __version__)
    log(9, "=" * 60)

    if config.flags.use_rtc:
        rtc.init_rtc()

    # Matrix goes up first, right after logging/clock - it's the one thing
    # that can show startup progress/status before anything else (wifi,
    # boat network) is even attempted.
    matrix = MatrixDisplay()
    if config.flags.use_matrix:
        matrix.init()

    wifi_monitor = WifiMonitor()
    if config.flags.check_wifi:
        wifi_monitor.check_once()  # have a real WiFi reading before the first matrix tick

    if config.flags.check_sysmetrics:
        sysmetrics_monitor.sample()  # have a real reading before the first HMI frame

    ups_monitor = UpsMonitor()
    if config.flags.use_ups_monitor:
        ups_monitor.init()

    bme280_monitor = Bme280Monitor()
    if config.flags.use_bme280:
        bme280_monitor.init()  # logs and no-ops if the sensor isn't found - run_forever() below just keeps retrying

    ais_service: AisService | None = None
    if config.flags.do_ais or config.flags.do_fake:
        ais_service = AisService()

    if config.flags.do_fake:
        log(9, "DoFake is on: boat-dependent subsystems are disabled, using fake data")
        set_fake_data(ais_service)

    # HMI needs ais_service (for the Main page's vessel radar), so it's
    # built after that - and after set_fake_data(), so a fake-mode run has
    # something to show on the radar from the first frame.
    #
    # CARPEDIEM_HMI_THEME picks the engine, not just a color palette:
    # "startrek" (default) is the pygame renderer in hmi/; "StartrekGraphical"
    # is the PySide6/Qt renderer in hmi_qt/ - a heavier but truly
    # widget-based/anti-aliased alternative, added alongside (not instead
    # of) the pygame one. Both implement the same init()/run_forever()/
    # close() interface, so nothing below here needs to know which one it's
    # driving.
    if config.hmi.theme.strip().lower() == "startrekgraphical":
        hmi = QtHmiApp(ais_service)
    else:
        hmi = HmiApp(ais_service)
    if config.flags.use_hmi:
        hmi.init()

    tasks: list[asyncio.Task] = [asyncio.create_task(_show_loop(ais_service))]

    if config.flags.use_matrix:
        tasks.append(asyncio.create_task(_matrix_tick_loop(matrix)))

    if config.flags.use_hmi:
        tasks.append(asyncio.create_task(hmi.run_forever()))

    if config.flags.check_wifi:
        tasks.append(asyncio.create_task(wifi_monitor.run_forever()))

    if config.flags.check_sysmetrics:
        tasks.append(asyncio.create_task(sysmetrics_monitor.run_forever()))

    if config.flags.use_bme280:
        tasks.append(asyncio.create_task(bme280_monitor.run_forever()))

    # -- everything below here is "connect to the rest": the boat network
    # subsystems, in the order the original loop() started them. --

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
        tasks.append(asyncio.create_task(ble_scanner.run_forever()))

    if config.flags.do_ais:
        tasks.append(asyncio.create_task(ais_service.run_forever()))

    ring_client: RingClient | None = None
    if config.flags.do_ring:
        ring_client = RingClient()
        tasks.append(asyncio.create_task(ring_client.run_forever()))

    bresser_client: BresserClient | None = None
    if config.flags.do_bresser:
        bresser_client = BresserClient()
        tasks.append(asyncio.create_task(bresser_client.run_forever()))

    wunderground_client: WundergroundClient | None = None
    if config.flags.do_wunderground:
        wunderground_client = WundergroundClient()
        tasks.append(asyncio.create_task(wunderground_client.run_forever()))

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
    if ble_scanner is not None:
        await ble_scanner.close()
    if ring_client is not None:
        await ring_client.close()
    if bresser_client is not None:
        await bresser_client.close()
    if wunderground_client is not None:
        await wunderground_client.close()
    ups_monitor.close()
    bme280_monitor.close()
    hmi.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
