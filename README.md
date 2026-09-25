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

**Changing fake values while it runs.** In a second terminal on the Pi (same
venv as the app):

```
python -m scripts.set_fake_value
```

It asks for a field name (any part of it - e.g. `soc` - then pick from the
matches) and a new value (`15`, `12.5`, `true`, `null`, or plain text), shows
the change, and asks again. Or in one shot: `python -m scripts.set_fake_value
"Battery SOC (%)" 15`; `--list` shows what you've changed and `--reset FIELD` /
`--reset-all` puts values back to their original fake value. Every screen (the
Pi's, the iPhone app, the e-ink board) sees the change. A changed value stays
put even against things that normally overwrite fake values (the wind
calculation, Wunderground). Restarting the app resets everything too.

How it works: the fake table lives inside the running app, so the script goes
through the app's web server (`POST/DELETE /api/fake`). That is refused unless
`CARPEDIEM_DO_FAKE=true`, so it can never alter real boat data, and refused
from any address but the Pi itself, since the API has no login.

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
  web_server.py            - read-only JSON data API (Arduino/e-ink
                              display, iPhone app - see README below)
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

### Camera feeds over the web API

`web_server.py` exposes the Cam page's two tiers over HTTP so the iPhone
app can show them too, without needing a WebRTC stack on the phone:

- `GET /api/cam/<name>/snapshot.jpg` - the disk file `RING_FETCH_SNAPSHOTS`
  writes (404 if that's off, or none has arrived yet). `<name>` is the Ring
  device name, e.g. `Salon`.
- `GET /api/cam/<name>/live.jpg` - starts (or reuses) a real-time WebRTC
  Live View session for that camera and returns its latest frame as a
  JPEG. A client polls this a couple of times a second for a "live" feel;
  the Pi automatically stops the session again once nothing has polled it
  for about 12 seconds, so leaving the app's Cam tab doesn't leave a video
  decode running in the background. Needs `pip install aiortc Pillow`
  (both optional - see `requirements.txt`) and a cached Ring token, same
  as the Qt Cam page's own Live View.

Both routes are covered by `WEBSERVER_API_KEY` like the rest of `/api/`.

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

**Weather Underground** (`CARPEDIEM_DO_WUNDERGROUND=true`, forced *on*
under `CARPEDIEM_DO_FAKE` - a plain internet API call, reachable from
anywhere with a connection, unlike RTL-SDR below): `wunderground_client.py`
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

**Local RTL-SDR** (`CARPEDIEM_USE_BRESSER_RTL=true`, *forced off* under
`CARPEDIEM_DO_FAKE` - unlike the BME280/UPS monitor/matrix, RTL reception
only works within range of the boat's own antenna, so it's not
meaningfully testable away from the boat the way those are; `CARPEDIEM_DO_WUNDERGROUND`
is forced *on* instead, so there's still real weather data to look at from
anywhere with internet, e.g. developing at home): `bresser_rtl_client.py` runs the
`rtl_433` binary (`sudo apt install rtl-433`) against an RTL-SDR dongle +
antenna and decodes the station's own 868.3MHz FSK broadcast directly, no
internet/cloud account needed. See scripts/rtl433_sniff.py (the throwaway
diagnostic this is based on) for confirming the dongle/antenna/rtl_433
install work at all before relying on this. Optionally set
`BRESSER_RTL_STATION_ID` (rtl_433's decoded `id` field for *this* station)
if you're ever docked near another identical-model Bresser 7-in-1 and want
to make sure its broadcast never gets mistaken for your own.

### Wind direction recalibration

The Bresser 7-in-1 isn't designed for a moving platform: its wind vane has
no internal compass, and is rigidly bolted to the hull rather than a
compass-stabilized masthead unit. It was calibrated once while moored,
with the boat sitting at `WIND_CALIBRATION_COURSE_DEG` (default `259`,
CDPI1's own mooring heading) - at that moment its raw `BresserWindDirection`
reading was aligned to the TRUE wind direction. Since the vane rotates
with the boat afterwards, that raw reading silently drifts by however far
the current course has swung away from that calibration heading, so
`wind_calibration.py` derives two corrected readings every 5s from
`BresserWindDirection` + `Course` (real or fake - it runs unconditionally,
not gated by any feature flag):

- `WindspeedCalculatedRecalibrated`: the TRUE (absolute/compass) wind
  direction right now, valid at any course.
- `WindspeedCalculatedAsExperienced`: where the wind is coming from
  relative to the boat's own current bow/heading - the Weather page's
  "RELATIVE TO COURSE" wind circle. Algebraically this one turns out to be
  independent of the live course (a hull-fixed vane's raw reading is
  already bow-relative at every instant except for the one fixed
  calibration-time offset) - not a bug if it doesn't visibly move when
  Course changes but the wind itself hasn't.

Only change `WIND_CALIBRATION_COURSE_DEG` if the sensor gets physically
remounted (necessarily while moored, reading the boat's course at that
moment) - it's a one-time installation constant, not something to tune
per-session.

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

The live BGV bounding-box query only lists ~400 bridges (those with a
live status feed), so small crossings such as Pier-Christiaanbrug at
Echtenerbrug would never be found by it. To cover them, the full
Rijkswaterstaat bridge list (~6600 bridges, same ISRS codes) is extracted
into `carpediem/data/vaarweg_bridges.json` by
`python -m scripts.build_vaarweg_bridges` (plain HTTP download, no extra
dependencies) and merged with the live results. Re-run it every few
months; such bridges show distance and contact but no live status.

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
| 2 | 10 | WebServer - read-only data API (see "Web server (data API)" below) |

The Weather dot covers two separate peripherals in one matrix slot: the
BME280 and the RTL-SDR/rtl_433 receiver. They still report through their
own separate display fields (`Weather280`/`Weather433`) - only the matrix
representation is merged, and only whichever of the two is actually
enabled (`CARPEDIEM_USE_BME280`/`CARPEDIEM_USE_BRESSER_RTL`) counts towards
it (see `status_monitor.py`'s `_weather_ok()`).

In fake mode, only WiFi gets a real check - all the boat-dependent
subsystems are simulated, so a heart just means "WiFi is up". Outside fake
mode, a subsystem you've deliberately turned off (e.g.
`CARPEDIEM_DO_RING=false`, `CARPEDIEM_USE_BME280=false`,
`CARPEDIEM_USE_BRESSER_RTL=false`, or `CARPEDIEM_USE_WEBSERVER=false`)
never blocks the heart or lights its dot - see `status_monitor.py` for the
exact rules.

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

Enable it with `CARPEDIEM_USE_BME280=true` (off by default, and *forced*
off under `CARPEDIEM_DO_FAKE` - unlike the UPS monitor/matrix, a real
reading only makes sense with the sensor actually wired up in front of
you; fake_data.py's illustrative `sparkfun_elec_bay_temperature`/`humidity`
values show instead). `BME280_I2C_ADDRESS`
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

## Web server (data API)

`web_server.py` runs a small read-only HTTP JSON API (via `aiohttp.web`,
already a project dependency - no separate framework) exposing everything
in `display_data`, for consumers other than this app's own HMI: an Arduino
sketch driving a Waveshare e-ink display, and eventually an iPhone app.
`GET /api/data` returns the full snapshot as one flat JSON object
(`{internal_label: value, ...}` - see `display_data.py` for the field
list); nothing here curates a subset, so each consumer just picks out
whichever fields it cares about.

On (`CARPEDIEM_USE_WEBSERVER=true`) by default, and *not* forced off under
`CARPEDIEM_DO_FAKE` - it's a pure software service with no real-world side
effects, so it's just as useful for developing the Arduino/iPhone
consumers against fake data as for the real thing. `WEBSERVER_HOST`
(default `0.0.0.0`, i.e. every interface) and `WEBSERVER_PORT` (default
`8080`) are configurable in `.env`. A `WebServer` field reflects whether
the server is actually listening, feeding the status matrix's `WebServer`
dot (see "Status matrix" above).

Authentication is **optional**. The intended reachability is the boat's own LAN
(for a locally-wired Arduino) and this account's NordVPN Meshnet overlay (for a
remote iPhone) - neither is the public internet - so by default there is no
login. But the API includes your GPS position, so set `WEBSERVER_API_KEY` in the
Pi's `.env` (and restart the app) once the app goes beyond TestFlight or you're
on a shared network like a marina's WiFi:

```
python -c "import secrets; print(secrets.token_urlsafe(24))"     # generate one
```

With a key set, every `/api/` request must send it as an `X-API-Key` header,
otherwise the answer is `401` (`/` stays open and only says what this is). The
comparison is constant-time. Then give the same key to each client:

- **iPhone app:** Settings (gear) > API KEY. Stored in the iPhone's Keychain.
- **E-ink board:** uncomment `PI_API_KEY` in `firmware/eink_display/include/arduino_secrets.h`
  and re-flash (it sends the header only if that's defined).
- **This repo's scripts** (`web_server_sniff`, `set_fake_value`) read the key from the same `.env`.
- **curl:** `curl -H "X-API-Key: <key>" http://<pi>:8080/api/data`

It's a shared secret over plain HTTP, so it stops casual/accidental access but
not someone who can capture your network traffic - fine for the boat LAN and
Meshnet (which is encrypted), not a substitute for HTTPS on the open internet.

`GET /api/vessels` returns the nearby AIS vessels (`{max_range_km,
vessels: [{mmsi, name, bearing_deg, distance_km, speed_knots, heading_deg,
category}]}`, category = moored / overtaking / fast / ok, same logic as the
Pi radar) - a list, not a scalar, so it lives outside `display_data`. Used by
the iPhone app's radar.

`GET /api/system` returns the Pi's own CPU/memory/disk health and CPU temperature
(`{status: ok|warn|crit | null, cpu_percent, mem_percent, disk_used_percent,
cpu_temp_c, rows: [{label, value, level, fraction}]}`) from
`sysmetrics_monitor.py` - the same thing that feeds the HMI top bar's SYS lamp,
and a separate endpoint for the same reason that monitor stays out of
`display_data` (host stats, not boat telemetry). `rows` are the pre-formatted
lines of the SYS popup, so every display shows identical numbers and colors.

**Tapping the SYS lamp** (top bar, either HMI engine, and the iPhone app) opens
that popup: CPU, memory and disk usage plus the Pi's own temperature (from
`psutil`, or `/sys/class/thermal` as a fallback; `n/a` where there's no sensor,
e.g. a Windows dev machine). Tap anywhere to close. The temperature is colored
by `CARPEDIEM_SYSMETRICS_TEMP_WARN_C`/`_CRIT_C` (default 70/80, from Raspberry
Pi's documented limits: the CPU throttles itself from 80C, the GPU from 85C)
and, like CPU/memory/disk, feeds the SYS lamp - a hot Pi turns it orange, then
red. A missing sensor never counts as a fault.

## iPhone app

`mobile/` is a portrait-mode iPhone app (Expo / React Native / TypeScript) that
mirrors the Pi display's main screen and tabs from the web server above - see
[mobile/README.md](mobile/README.md). It starts in demo mode with built-in
sample data; point it at the Pi's LAN or NordVPN Meshnet address in its
settings. It needs Node to build (`npm install` in `mobile/`); note
`node_modules/` is big, so keep this repo out of OneDrive sync if you can.

## E-ink dashboard

`firmware/eink_display/` is a separate ESP32-S3 Arduino sketch (kept in
this repo alongside the Python app and `reference/arduino/`'s original
sketch, rather than a separate repo) - an e-ink instrument display driven
by a Waveshare IT8951 e-Paper Driver HAT (B), polling the web server
above over the boat's own WiFi. See
[firmware/eink_display/README.md](firmware/eink_display/README.md) for
the full wiring table (signal, GPIO, wire color), library requirements,
and setup steps.

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
