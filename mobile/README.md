# CarpeDiem iPhone app

Portrait-mode HUD for the boat, fed by the Pi's read-only data API
(`carpediem/web_server.py`). Expo (React Native + TypeScript), so it can be
developed on Windows and run on an iPhone without a Mac.

Tabs mirror the Pi display's top bar: **Main** (compass with speed/heading,
true + relative wind markers, next bridge/lock banner, battery/house/starter/
alternator/solar, AIS radar), **AIS**, **Weather**, **Power**, **Temps**,
**Cam** (status only - no live video yet). The header shows the Pi's eight
status lamps (WiFi/AIS/MQTT/MDB/BLE/WX/RING/SYS) plus a ninth, LINK, for the
app's own connection to the Pi (green live, orange demo, red offline).

Palette matches the Pi's `hmi_qt/theme.py`; fonts are Orbitron + Rajdhani.

## Run it

Needs Node 22.13+ (`node --version`).

```
cd mobile
npm install
npx expo start
```

Install **Expo Go** on the iPhone, scan the QR code. It starts in **Demo
mode** (built-in sample data with a gentle live wobble), so it works with no
Pi. Tap the gear, switch Demo off and enter the Pi's address on the boat's WiFi
(`http://cdpi1.local:8080` or its IP) and, optionally, a second "away" address
(its NordVPN Meshnet name or `100.x` address). Test checks both. In live mode
the app uses whichever answers, tries the last working one first, and the
header pill shows BOAT or AWAY when two are set (`src/data/failover.ts`).

**Security.** If the Pi has `WEBSERVER_API_KEY` set, enter the same key under API
KEY in Settings; it's stored in the iPhone's Keychain (`expo-secure-store`, this
device only), not in the plain settings. **Lock with Face ID** (Settings, on by
default, live mode only) asks for Face ID or your passcode on every launch and
after 30+ seconds in the background, and covers the screen in the app switcher.
A phone with no passcode/Face ID set up can't authenticate, so it opens anyway
rather than locking you out. Face ID itself doesn't work in Expo Go (Expo's
limitation) - use a real build (TestFlight); in a development build the lock
screen has a SKIP button so it can't trap you.

The Pi side must be running `carpediem/main.py` with the web server on
(default) - it serves `GET /api/data` (every `display_data` field) and
`GET /api/vessels` (nearby AIS vessels for the radar, mirroring the Pi
radar's classification) and `GET /api/system` (the Pi's CPU/memory/disk
health and temperature, for the SYS lamp - tap it in the app for the details).

On the radar (Main and AIS tabs), tap a vessel for a detail popup (name/MMSI,
speed, heading, bearing relative to your course, distance); tap empty space to
close it. The hit-testing lives in `src/components/radarGeometry.ts`.

`npx tsc --noEmit` typechecks. `npx expo start --web` runs it in a browser;
`http://localhost:8081/#ais` etc. picks the starting tab (web only).
Browsers block calls to the Pi (CORS), so use Demo mode there.

## Layout

- `App.tsx` - fonts, tab shell
- `src/data/` - `store.tsx` (settings + polling, 3s live / 1s demo), `demo.ts`
  (sample data, same wind-recalibration formula as the Pi), `format.ts`
- `src/components/` - `gauges.tsx` (Compass, RadialGauge, Radar, WindDial),
  `ui.tsx` (Panel, Tile, Led, Chip, Meter), `chrome.tsx` (header, status
  strip, tab bar)
- `src/screens/` - one file per tab, plus the settings sheet

## Getting it onto your phone for real / the App Store

See the conversation notes in the main README ("iPhone app"). Short version:
`eas build` (cloud, no Mac needed) + an Apple Developer account ($99/yr) ->
TestFlight for personal use. `app.json` already sets the bundle id
(`com.vanwijlen.carpediem`) and the iOS network permissions (plain-HTTP to the
Pi needs an App Transport Security exception and a Local Network usage string).
