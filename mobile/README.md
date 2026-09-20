# CarpeDiem iPhone app

Portrait-mode HUD for the boat, fed by the Pi's read-only data API
(`carpediem/web_server.py`). Expo (React Native + TypeScript), so it can be
developed on Windows and run on an iPhone without a Mac.

Tabs mirror the Pi display's top bar: **Main** (compass with speed/heading,
true + relative wind markers, next bridge/lock banner, battery/house/starter/
alternator/solar, AIS radar), **AIS**, **Weather**, **Power**, **Temps**,
**Cam** (status only - no live video yet). The header shows the same eight
status lamps as the Pi (WiFi/AIS/MQTT/MDB/BLE/WX/RING + LINK to the Pi).

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
Pi. Tap the gear, switch Demo off, enter the Pi's address (boat LAN
`http://192.168.x.x:8080`, or its NordVPN Meshnet `http://100.x.x.x:8080`
when away) and Test.

The Pi side must be running `carpediem/main.py` with the web server on
(default) - it serves `GET /api/data` (every `display_data` field) and
`GET /api/vessels` (nearby AIS vessels for the radar, mirroring the Pi
radar's classification).

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
