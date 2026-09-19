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
  wunderground_client.py    - Bresser 7-in-1 weather station readings, via
                               Weather Underground's PWS API
  bresser_rtl_client.py      - same Bresser readings, decoded directly from
                                its own 868MHz broadcast via rtl_433 instead
  rtc.py                  - optional DS3231 RTC support (off by default -
                             the Pi's own NTP-synced clock is normally enough)
  matrix_display.py       - optional MAX7219 LED matrix status display
                             (off by default - superseded by the e-paper screen)
  status_monitor.py        - aggregates every subsystem's health into the
                              matrix's heart-vs-status-dots decision
  wifi_monitor.py           - real WiFi/network connectivity check, for the
                              matrix's "WiFi" status dot
  ups_monitor.py           - optional Geekworm X-UPS PLD (Power Loss
                              Detection) shutdown monitor (off by default)
  sensors/
    bme280_sensor.py          - optional SparkFun SEN-15440 BME280 temp/
                                 humidity/pressure sensor over I2C (off by
                                 default) - feeds the matrix's Weather dot
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
continuously: it opens the Bluetooth radio for `BLE_SCAN_WINDOW_SECONDS`
(default 60s - long enough to hear from every known puck at least once,
they advertise every few seconds) and then closes it again until the next
cycle. `BLE` is 1 while a scan window is open (or just completed), 0 if
the radio failed to start.

The gap between scans is speed-adaptive rather than a single fixed
interval, to save house-battery power at rest without going stale while
underway: above `BLE_MOVING_SPEED_THRESHOLD` km/h (default 1 - i.e. the
`Speed` display field, so real GPS/AIS speed, or `fake_data.py`'s value in
fake mode) it polls every `BLE_MOVING_POLL_INTERVAL_SECONDS` (default
300s / 5 min); at or below that threshold - including before the first
GPS/AIS fix, when `Speed` is still unknown - it polls only every
`BLE_STATIONARY_POLL_INTERVAL_SECONDS` (default 21600s / 6 hours).

## Ring cameras

`ring_client.py` polls Ring's cloud API every `RING_POLL_INTERVAL_SECONDS`
(default 600s / 10 min) for the battery level of the 4 cameras named in
`RING_CAM_SALON_NAME`/`RING_CAM_BAKBOORD_NAME`/`RING_CAM_STUURBOORD_NAME`/
`RING_CAM_CONSOLE_NAME` (must match the names shown in the Ring app
exactly), writing them to the `RingBatterySalon`/`RingBatteryBakboord`/
`RingBatteryStuurboord`/`RingBatteryConsole` display fields, plus each
camera's `"online"`/`"offline"` connection status to
`RingConnectionSalon`/`RingConnectionBakboord`/`RingConnectionStuurboord`/
`RingConnectionConsole`. Console is a wired Pan-Tilt cam - Ring's API
still reports a `battery_life` for it (pinned at 100, no real cell behind
it), so that field gets populated like the others even though it's
meaningless for this camera. `Cam` is 1 while the last poll succeeded, 0
if the API is unreachable or auth has failed.

Setting `RING_FETCH_SNAPSHOTS=true` also fetches a still JPEG per camera
each poll, written to `RING_SNAPSHOT_DIR` (default `./ring_snapshots`) as
`<key>.jpg` (e.g. `salon.jpg` - see `ring_client.py`'s `snapshot_key()`).
This is the Cam page's "level 2": basic battery/connection info always
shows, and each camera's tile additionally shows its latest snapshot when
one exists on disk. Off by default since a boat's internet connection is
often metered and a JPEG per camera every poll is far more data than the
battery/connection poll alone.

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

## Bresser weather station (Weather Underground or local RTL-SDR)

The boat's Bresser 7-in-1 weather station's readings can come from either
of two independent sources - pick one via the feature flags below (running
both at once is harmless, just redundant: whichever last wrote a reading
wins). A third option, reading back a ProWeatherLive public station page
over HTTPS, was tried first and removed - this station's ProWeatherLive
setup was never reliable enough to depend on.

Both sources feed the same `Bresser*` display fields the HMI weather page
already reads (`BresserTemperature`, `BresserHumidity`,
`BresserWindDirection`, `BresserWindAverageSpeed`, `BresserWindGustSpeed`,
`BresserRainfall`, `BresserLightIntensity`, `BresserUVindex`,
`BresserSensorBatteryStatus`), plus the top bar's "WX" indicator (the
`Weather` field - not to be confused with the status matrix's separate
combined `Weather` slot for the BME280/RTL-SDR pair, see "Status matrix"
above).

**Weather Underground** (`CARPEDIEM_DO_WUNDERGROUND=true`, forced off
under `CARPEDIEM_DO_FAKE` since it's a cloud API call): `wunderground_client.py`
polls Weather Underground's PWS API. Needs the Bresser gateway/app to
already be uploading to Weather Underground (most WiFi weather station
gateways, including Bresser's, support this alongside whatever else
they're already sending to - check the gateway/app's upload settings)
plus a free API key from your Wunderground account (Member Settings ->
API Keys). Set `WUNDERGROUND_STATION_ID` (the PWS ID assigned when you
registered the station, e.g. `KXXTOWN123`) and `WUNDERGROUND_API_KEY` in
`.env` - leave either empty to skip. The API doesn't expose per-sensor
battery status, so `BresserSensorBatteryStatus` isn't populated by this
client.

**Local RTL-SDR** (`CARPEDIEM_USE_BRESSER_RTL=true`, *not* forced off
under `CARPEDIEM_DO_FAKE` - like the BME280, it's local hardware you
should be able to test on the bench): `bresser_rtl_client.py` runs the
`rtl_433` binary (`sudo apt install rtl-433`) against an RTL-SDR dongle +
antenna and decodes the station's own 868.3MHz FSK broadcast directly, no
internet/cloud account needed. See scripts/rtl433_sniff.py (the throwaway
diagnostic this is based on) for confirming the dongle/antenna/rtl_433
install work at all before relying on this. Optionally set
`BRESSER_RTL_STATION_ID` (rtl_433's decoded `id` field for *this* station)
if you're ever docked near another identical-model Bresser 7-in-1 and want
to make sure its broadcast never gets mistaken for your own.

## Next bridge/lock (Main page banner)

`vaarweg_client.py` polls Rijkswaterstaat's public "Blauwe Golf,
Verbindend" REST API (`https://api.vaarweginformatie.nl/bgv/information/`
- no API key needed) every `VAARWEG_POLL_INTERVAL_SECONDS` (default 30s)
to find the nearest bridge or lock ahead of the boat's current position
and course, writing a one-line summary (name, VHF/phone contact,
distance) to the `NextObject` display field, or `None` when there's no
position/course fix or nothing found within range. Its live status
(`OPEN`/`CLOSED`/`OPENING`/`CLOSING`/`BLOCKED`, or a lock's equivalent)
goes to a separate `NextObjectStatus` field instead of into that text -
the Main page banner shows it as a colored status dot (green = open, red
= blocked, amber = opening/closing/locking, no special color for closed)
so a long bridge name plus a long status string never has to fight for
banner space.

"Ahead" means within `VAARWEG_AHEAD_HALF_ANGLE_DEG` (default 90°, i.e.
the whole forward half - matches the same ahead/behind convention the
Main page's AIS radar already uses) of the current course, and within
range - a search radius that's at least `VAARWEG_MIN_RANGE_KM` (default
3 km) but grows with speed (`VAARWEG_LOOKAHEAD_MINUTES`, default 30 -
however far the boat would travel at its current speed in that time), so
a faster boat looks further ahead. Bridges are re-queried each poll
within a bounding box around the current position (the API can't
geofilter any other way); the ~50 locks nationwide have no geofilter at
all, so that list is fetched in full once and cached
(`VAARWEG_LOCKS_CACHE_SECONDS`, default 600) since locks don't move.

Position/course/speed come from the `Lat`/`Lng`/`Course`/`Speed` display
fields (real GPS/AIS fix, or `fake_data.py`'s illustrative values in fake
mode) - this is deliberately **not** disabled by `CARPEDIEM_DO_FAKE`
(unlike most other real-network clients), since it's a real lookup
against a real government API cross-referenced against whatever position
is current, so it stays testable without actually being underway.

The banner also appends the operator's VHF channel (e.g. `VHF 22`), or
their phone number (`TEL 070-4417731`) when no VHF channel is published
for that bridge/lock - common for smaller, phone-operated crossings.
Neither is in the live BGV API at all; both come from Rijkswaterstaat's
"Bedieningstijden van sluizen en bruggen" PDF, extracted once into
`carpediem/data/vaarweg_contacts.json` by
`scripts/build_vaarweg_contacts.py` (needs poppler's `pdftotext`, dev
machine only - not a runtime dependency). Re-run that script and commit
the updated JSON whenever you download a newer PDF from
[vaarweginformatie.nl's downloads page](https://www.vaarweginformatie.nl/frp/page/downloads);
until then the file just doesn't grow more entries, it doesn't go stale
in a way that breaks anything.

A bridge's vertical clearance - the height that actually decides whether
you need it to open at all - is read from the live API's
`bridgeDetails.bridgeOpenings[].heightClosed` (a bridge can have several
separately-operable openings; the tallest one's `heightClosed` is what
gets reported, since you'd pick that one) into `NextObjectClearanceM`,
appended to the banner text as e.g. `3.2 M` when present. In practice
RWS marks this field optional and, as of this writing, doesn't actually
publish it for any bridge nationwide (checked all ~400+ live) - so this
mostly stays `None` today, but the code picks it up automatically the day
that changes, at no extra cost. A static per-bridge height table does
exist in RWS's "Vaarwegen" publication, but it's organized by waterway
and river-km marker rather than by name or ISRS code, so matching it to
live API results would need unreliable fuzzy name-matching - not
attempted here.

## GPX track log

`gpx_logger.py` records one GPX track file per run of the app, from
startup to shutdown, so a trip can be replayed later in any GPX-compatible
chartplotter, phone app, or web tool. Every `GPX_POLL_INTERVAL_SECONDS`
(default 15s) it appends the current `Lat`/`Lng` as a track point (real
GPS/AIS fix, or `fake_data.py`'s value in fake mode - like `vaarweg`
above, this is deliberately **not** disabled by `CARPEDIEM_DO_FAKE`, so
both the file-writing and the geocoding call below stay testable at a
desk); the file is written to `GPX_OUTPUT_DIR` (default `./gpx_tracks`,
git-ignored) on shutdown, or skipped entirely if the run never got a
single fix (`GPX_MIN_POINTS_TO_WRITE`, default 1).

Filenames follow the user's own convention:

    carpe diem_<YYYYMMDD>_<start HHMMSS>-<end HHMMSS>_<nearest city>.gpx
    carpe diem_20260913_143201-161045_Leiden.gpx

The date/start/end time are local (matching the rest of the app's clock
display), while the track points inside the file use UTC timestamps (GPX's
own spec convention, for compatibility with other tools). The nearest
city comes from one reverse-geocode lookup against OpenStreetMap's free
Nominatim API (no key needed - `GPX_REVERSE_GEOCODE_URL` if that ever
needs pointing elsewhere), done once against the run's first fix; if that
lookup fails (no internet yet, Nominatim unreachable, or no city/town/
village in the result) the file is still written, just without a city in
the name.

## Status matrix (MAX7219)

When `CARPEDIEM_USE_MATRIX=true`, the matrix shows a heart whenever every
tracked subsystem is healthy, and switches to a grid of status dots the
moment one or more aren't - one dot per subsystem, using rows 1 and 2 of
the 8x8 grid (row 1 = columns 1-8, row 2 = columns 9-10):

| Row | Col | Subsystem |
|---|---|---|
| 1 | 1 | Fake mode (lit whenever `CARPEDIEM_DO_FAKE=true`) |
| 1 | 2 | WiFi (`wifi_monitor.py`) |
| 1 | 3 | Modbus (Victron Cerbo GX) |
| 1 | 4 | MQTT (Venus OS/VRM) |
| 1 | 5 | BLE (Teltonika Blue Puck) |
| 1 | 6 | AIS (em-trak B954) |
| 1 | 7 | AISstream.io API |
| 1 | 8 | Ring API |
| 2 | 9 | Weather - combined BME280 (see "BME280 environment sensor" below) + RTL-SDR/rtl_433 (see "Bresser weather station" above) |
| 2 | 10 | WebServer (not wired up yet) |

The Weather dot covers two separate peripherals in one matrix slot: the
BME280 and the RTL-SDR/rtl_433 receiver. They still report through their
own separate display fields (`Weather280`/`Weather433`) - only the matrix
representation is merged, and only whichever of the two is actually
enabled (`CARPEDIEM_USE_BME280`/`CARPEDIEM_USE_BRESSER_RTL`) counts towards
it (see `status_monitor.py`'s `_weather_ok()`).

In fake mode, only WiFi gets a real check - all the boat-dependent
subsystems are simulated, so a heart just means "WiFi is up". Outside fake
mode, a subsystem you've deliberately turned off (e.g.
`CARPEDIEM_DO_RING=false`, `CARPEDIEM_USE_BME280=false`, or
`CARPEDIEM_USE_BRESSER_RTL=false`) or one that isn't implemented yet
(WebServer) never blocks the heart or lights its dot - see
`status_monitor.py` for the exact rules.

Startup order matters here: the matrix comes up right after
logging/clock, before WiFi is checked, before any boat-network subsystem
is started - see `main.py`'s `run()`.

LED brightness is set once at startup from `CARPEDIEM_MATRIX_BRIGHTNESS_PERCENT`
(0-100, default 50).

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

## BME280 environment sensor (I2C)

A SparkFun SEN-15440 BME280 breakout (temperature/humidity/barometric
pressure) reads over I2C bus 1, the Pi's default. Wiring:

| BME280 pin | Raspberry Pi pin |
|---|---|
| VCC | Pin 1 (3.3V) |
| GND | Pin 6 (GND) |
| SDA | Pin 3 (GPIO2 / SDA1, yellow) |
| SCL | Pin 5 (GPIO3 / SCL1, blue) |
| CSB | leave unconnected (board pulls it high - selects I2C mode, not SPI) |
| SDO | leave unconnected for address `0x77` (board pulls it high by default), or tie to GND for `0x76` |

One-time setup on the Pi:

```bash
sudo raspi-config   # Interface Options -> I2C -> enable, then reboot
sudo apt install -y i2c-tools
i2cdetect -y 1       # should show the sensor at 77 (or 76 if SDO is grounded)
```

Enable it with `CARPEDIEM_USE_BME280=true` (off by default, and *not*
forced off under `CARPEDIEM_DO_FAKE`, same as the UPS monitor/matrix - it's
local hardware you should be able to test on the bench). `BME280_I2C_ADDRESS`
(default `119` / `0x77`), `BME280_I2C_BUS` (default `1`, which /dev/i2c-N
to open) and `BME280_POLL_INTERVAL_SECONDS` (default `30`) are configurable
in `.env`. Readings land in the `sparkfun_elec_bay_temperature` (°C),
`sparkfun_elec_bay_humidity` (% RH) and `BME280-Barometer` (hPa, station pressure - not sea-level-
adjusted) display fields, and a `Weather280` field reflects whether the
last read succeeded, which feeds into the status matrix's combined
`Weather` dot (see "Status matrix" above).

Needs `sparkfun-qwiic-bme280` (already in `requirements.txt`) -
`sensors/bme280_sensor.py` reads the sensor via SparkFun's own
`qwiic_bme280` library rather than a hand-rolled driver. An earlier version
of this module talked to `/dev/i2c-<N>` directly with its own register-
level driver, after Adafruit's CircuitPython/Blinka stack raised `[Errno 5]
Input/output error` reading this exact sensor (even though a raw `smbus2`
transaction worked fine) and the `bme280` PyPI package turned out to have
real bugs in its calibration parsing. `qwiic_bme280` was confirmed working
against the same sensor/wiring via SparkFun's own example script
(`scripts/sf_ex_bme280.py`, used to rule out a hardware fault before
reporting the sensor to SparkFun as defective), so the hand-rolled driver
was replaced with it. If the sensor isn't found at startup (wrong
address/bus, I2C not enabled, nothing wired up), `sensors/bme280_sensor.py`
logs why and keeps retrying every poll interval rather than crashing -
plugging it in later recovers without a restart.

Lives in `sensors/`. The RTL-SDR/rtl_433 receiver (`Weather433`) lives at
the top level instead, as `bresser_rtl_client.py` - see "Bresser weather
station" above; the status matrix merges the two into one "weather" dot
(see "Status matrix" above).

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
