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
  rtc.py                  - optional DS3231 RTC support (off by default -
                             the Pi's own NTP-synced clock is normally enough)
  matrix_display.py       - optional MAX7219 LED matrix status display
                             (off by default - superseded by the e-paper screen)
  ais/
    nmea.py                - own-ship GPS ($..RMC/$..GGA) + $AIALR alarm parsing
    decoder.py              - AIS 6-bit payload decoding (position + name)
    vessel_tracker.py        - nearby-vessel table, distance/bearing, range filter
    emtrak_reader.py          - TCP connection to the em-trak, sentence dispatch
    aisstream_client.py        - AISstream.io WebSocket client (vessel names)
    service.py                  - ties the above into the asyncio tasks main.py runs
  main.py                  - entry point (replaces setup()/loop())
```

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
