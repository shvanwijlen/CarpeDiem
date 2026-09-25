# CarpeDiem iPhone app

Portrait-mode HUD for the boat, reading the data the Pi pushes to the data store
(`server/`, `carpediem/publisher.py`). Expo (React Native + TypeScript), so it can be
developed on Windows and run on an iPhone without a Mac.

Tabs mirror the Pi display's top bar: **Main** (compass with speed/heading,
true + relative wind markers, next bridge/lock banner, battery/house/starter/
alternator/solar, AIS radar), **AIS**, **Weather**, **Power**, **Temps**,
**Cam** (latest snapshots from the store; live video only on the boat's WiFi). The
header shows the Pi's eight status lamps (WiFi/AIS/MQTT/MDB/BLE/WX/RING/SYS)
plus a ninth, LINK, for the app's own connection to the data store: **green**
when the store answers with fresh data, **orange** when it answers but the
newest data is old (more than 2 minutes - the boat stopped reporting; the pill
says OLD DATA and how old), **red** when the store can't be reached. Demo mode
is orange too.

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
store. Tap the gear, switch Demo off and enter the **data store address** (your
Synology, e.g. `https://carpediem.example.synology.me` - set up in
[server/README.md](../server/README.md)) and its **read key**. TEST fetches the
latest data and tells you how old it is. The app polls every 5 s.

**Live camera** is the one thing that can't go through the store: it streams
straight from the Pi. Optionally enter the Pi's address on the boat's WiFi
(`http://cdpi1.local:8080`) under "PI ON BOAT WIFI"; live views then work while
your phone is on the boat's network. Camera snapshots (thumbnails) come from the
store and work anywhere.

**Security.** The store's read key is entered in Settings and kept in the iPhone's
Keychain (`expo-secure-store`, this device only), not in the plain settings; the
same goes for the optional Pi API key. **Lock with Face ID** (Settings, on by
default, live mode only) asks for Face ID or your passcode on every launch and
after 30+ seconds in the background, and covers the screen in the app switcher.
A phone with no passcode/Face ID set up can't authenticate, so it opens anyway
rather than locking you out. Face ID itself doesn't work in Expo Go (Expo's
limitation) - use a real build (TestFlight); in a development build the lock
screen has a SKIP button so it can't trap you.

Settings saved by an older version of the app keep working: the old boat address
becomes the "Pi on boat WiFi" address, and the old "away" address is dropped.

The store must be running with the Pi pushing to it (`PUBLISH_BACKEND` in the Pi's
`.env`). `GET /v1/state` returns everything in one request: every `display_data`
field, the nearby AIS vessels for the radar, and the Pi's CPU/memory/disk health for
the SYS lamp (tap it in the app for the details).

On the radar (Main and AIS tabs), tap a vessel for a detail popup (name/MMSI,
speed, heading, bearing relative to your course, distance); tap empty space to
close it. The hit-testing lives in `src/components/radarGeometry.ts`.

`npx tsc --noEmit` typechecks. `npx expo start --web` runs it in a browser;
`http://localhost:8081/#ais` etc. picks the starting tab (web only).
Browsers block calls to the Pi (CORS), so use Demo mode there.

## Layout

- `App.tsx` - fonts, tab shell
- `src/data/` - `store.tsx` (settings + polling, 5s live / 1s demo), `source.ts`
  (`DataSource` interface, the store reader, and the fresh/old rule), `demo.ts`
  (sample data, same wind-recalibration formula as the Pi), `format.ts`
- `src/components/` - `gauges.tsx` (Compass, RadialGauge, Radar, WindDial),
  `ui.tsx` (Panel, Tile, Led, Chip, Meter), `chrome.tsx` (header, status
  strip, tab bar)
- `src/screens/` - one file per tab, plus the settings sheet

## Version

The app's version is the Pi app's version: the git tag (`v1.2.0` -> `1.2.0`, the
`version` in `app.json`); EAS numbers the builds itself. To release:

```
python scripts/sync_version.py 1.2.0        # from the repo root: writes mobile/app.json
git commit -am "Release 1.2.0" && git tag v1.2.0 && git push --tags
npm run release:ios                         # in mobile/: checks app.json matches the tag, then eas build
```

On the Pi, `git pull --tags` and the log then says `version v1.2.0`. (If you re-tag,
move the old tag rather than adding a second one on the same commit - `git describe`
picks one of them arbitrarily.)

## Getting it onto your phone for real / the App Store

See the conversation notes in the main README ("iPhone app"). Short version:
`eas build` (cloud, no Mac needed) + an Apple Developer account ($99/yr) ->
TestFlight for personal use. `app.json` already sets the bundle id
(`com.vanwijlen.carpediem`) and the iOS network permissions (plain-HTTP to the
Pi needs an App Transport Security exception and a Local Network usage string).
