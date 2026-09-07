# CarpeDiem

Boat data collection & (eventually) display app. Python port of the
ESP32-S3 Arduino sketch `CarpeDiem_v4_5`, targeting a Raspberry Pi 4.

Collects Victron Cerbo GX data (Modbus TCP + MQTT), Teltonika Blue Puck
BLE temperature/humidity sensors, and own-ship + nearby-vessel AIS data
from an em-trak B954, into one shared in-memory data store. A display
layer (the Waveshare e-Paper board, or whatever the "magedok" screen turns
out to be) reads from that store - not built yet, this port is the data
layer it will sit on top of.

See `PORTING_NOTES.md` for a full list of what changed (and why) versus
the original Arduino sketches, including two real bugs that got fixed
along the way.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: Cerbo GX IP, MQTT/VRM portal ID, em-trak IP, AISstream.io key, ...
```

## Running

```bash
python -m carpediem.main
```

Ctrl-C (or SIGTERM) shuts everything down cleanly.

### Developing away from the boat: `CARPEDIEM_DO_FAKE`

Set `CARPEDIEM_DO_FAKE=true` in `.env` (the default) and every
boat-dependent subsystem - Modbus, MQTT, BLE, AIS - is skipped entirely,
and the shared data store is populated with fixed fake values instead.
This is the direct equivalent of the sketch's `DoFake` global: it's how
you work on the screen/data layer at home with no hardware attached.

Set it to `false` on the Pi once it's actually on the boat's network.

Individual subsystems can also be toggled independently
(`CARPEDIEM_DO_MODBUS`, `CARPEDIEM_DO_MQTT`, `CARPEDIEM_DO_BLE`,
`CARPEDIEM_DO_AIS`) when `CARPEDIEM_DO_FAKE=false` - e.g. to test just the
AIS piece without also needing the Cerbo reachable.

## Module map

```
carpediem/
  config.py            - all settings, loaded from .env / environment variables
  logging_setup.py      - rotating log file + console output, replaces the
                           sketch's hand-rolled SD-card logger entirely
  display_data.py       - the shared data store (port of DisplayInfo[] /
                           UpdateDisplayTable())
  fake_data.py           - DoFake's fixed dataset (port of SetFakeData())
  modbus_client.py       - Victron Cerbo GX via Modbus TCP (pymodbus)
  mqtt_client.py         - Venus OS / VRM MQTT (paho-mqtt)
  ble_client.py           - Teltonika Blue Puck BLE scanning (bleak)
  ring_client.py          - Ring camera battery levels (ring-doorbell)
  rtc.py                  - optional DS3231 RTC support (off by default -
                             the Pi's own NTP-synced clock is normally enough)
  matrix_display.py       - optional MAX7219 LED matrix status display
                             (off by default - superseded by the e-paper screen)
  ups_monitor.py           - optional Geekworm X-UPS PLD (Power Loss
                              Detection) shutdown monitor (off by default)
  ais/
    nmea.py                - own-ship GPS ($..RMC/$..GGA) + $AIALR alarm parsing
    decoder.py              - AIS 6-bit payload decoding (position + name)
    vessel_tracker.py        - nearby-vessel table, distance/bearing, range filter
    emtrak_reader.py          - TCP connection to the em-trak, sentence dispatch
    aisstream_client.py        - AISstream.io WebSocket client (vessel names)
    service.py                  - ties the above into the asyncio tasks main.py runs
  main.py                  - entry point (replaces setup()/loop())
```

## Bluetooth (BLE) sensors

`ble_client.py` scans for the Teltonika Blue Pucks in bursts rather than
continuously: every `BLE_POLL_INTERVAL_SECONDS` (default 900s / 15 min)
it opens the Bluetooth radio for `BLE_SCAN_WINDOW_SECONDS` (default 60s -
long enough to hear from every known puck at least once, they advertise
every few seconds) and then closes it again until the next cycle. `BLE`
is 1 while a scan window is open (or just completed), 0 if the radio
failed to start.

## Ring cameras

`ring_client.py` polls Ring's cloud API every `RING_POLL_INTERVAL_SECONDS`
(default 600s / 10 min) for the battery level of the 3 cameras named in
`RING_CAM_SALON_NAME`/`RING_CAM_BAKBOORD_NAME`/`RING_CAM_STUURBOORD_NAME`
(must match the names shown in the Ring app exactly), writing them to the
`RingBatterySalon`/`RingBatteryBakboord`/`RingBatteryStuurboord` display
fields, plus each camera's `"online"`/`"offline"` connection status to
`RingConnectionSalon`/`RingConnectionBakboord`/`RingConnectionStuurboord`.
`Cam` is 1 while the last poll succeeded, 0 if the API is unreachable or
auth has failed.

Ring has no official public API, so this uses the same unofficial,
reverse-engineered client ([ring-doorbell](https://github.com/tchellomello/python-ring-doorbell))
Home Assistant's Ring integration is built on - it can break if Ring
changes their backend, and can be rate-limited/locked out by polling too
aggressively, so don't lower the poll interval much below the default.

`ring_client.py` runs unattended and only ever reads a cached refresh
token - it can't prompt for a password or a 2FA code. Authenticate once,
by hand, before starting the app for the first time (or whenever
`ring_token.cache` is deleted or Ring revokes it):

```
python -m scripts.ring_auth_setup
```

That prompts for your Ring username/password (or reads `RING_USERNAME`/
`RING_PASSWORD` from `.env` if set) and, if required, a 2FA code, then
caches the resulting token to `RING_TOKEN_FILE` (default
`./ring_token.cache`, git-ignored - never commit it).

## UPS power-loss shutdown

A Geekworm X-UPS's PLD (Power Loss Detection) pin is wired to GPIO23
(physical pin 16). When mains power is lost and the UPS switches to
battery, it drives that pin to its active level; `ups_monitor.py` treats
that as "shut down now" - there's no way to read remaining battery
capacity from the Pi side, so any power loss is treated as urgent.

Enable it with `CARPEDIEM_USE_UPS_MONITOR=true` (off by default, and
forced off under `CARPEDIEM_DO_FAKE`, same as the RTC/matrix). On
trigger it logs `UPS PLD signal received: external power lost, shutting
down` and runs `scripts/pld_shutdown.sh`, which:

1. Best-effort blanks the Pi's HDMI output (`vcgencmd display_power 0`)
   so the Magedok display gets a "no signal" it can react to - most small
   HDMI monitors auto power off on signal loss, but there's no separate
   control line to force a screen that ignores it to actually switch off.
2. Shuts the Pi down (`shutdown -h now`).

Both of those need passwordless sudo - see the comment at the top of
`scripts/pld_shutdown.sh` for the exact `/etc/sudoers.d` entry. Needs
`gpiozero` (`pip install gpiozero`, already in requirements.txt) and, if
your UPS drives PLD low instead of high on power loss, flip
`UPS_PLD_ACTIVE_HIGH=false` in `.env`.

## Architecture note

The original was a single-threaded Arduino `loop()` polling every
subsystem in turn, with a hand-rolled "only reconnect every 5 minutes"
gate to avoid one slow subsystem stalling the others. The Python port
instead runs each subsystem as its own `asyncio` task, all writing into
the same lock-protected `display_data` store - there's no shared loop to
stall, and each task retries itself on its own schedule.

## Original Arduino sketches

`reference/arduino/` keeps the two source sketches this was ported from
(`CarpeDiem_v4_5_20260830c.ino`, `ais_nearby_vessels_7.ino`), for
provenance and side-by-side comparison. They're not used by anything at
runtime.

## What's not here yet

- The actual display renderer (waiting on the "magedok" screen / possibly
  reusing the Waveshare e-Paper ESP32 Driver Board as a second display
  fed by a small webservice from this app - see PORTING_NOTES.md).
- A systemd unit for running this as a service on boot (straightforward
  to add once the Pi is set up: `ExecStart=.venv/bin/python -m
  carpediem.main`, `Restart=on-failure`).
