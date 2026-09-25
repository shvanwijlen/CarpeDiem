# CarpeDiem data store

The boat's Raspberry Pi **pushes** its data here; the phone app **reads** it from
here. Nothing connects into the boat, and no VPN is involved.

```
 Pi on the boat ──PUT /v1/state (every ~10 s, HTTPS, write key)──►  store  ◄──GET /v1/state (every 5 s, HTTPS, read key)── iPhone
                                                                (Synology)
```

It runs as one small Docker container on the Synology (Python + SQLite, about
150 lines of routes). The datastore behind it is swappable - see
[Choosing a different datastore](#choosing-a-different-datastore).

## Setup on the Synology (DS923+, DSM 7.2)

1. **Get the code onto the NAS.** Copy this `server/` folder to a shared folder,
   e.g. `/volume1/docker/carpediem-store/` (File Station, or `git clone` over SSH).
2. **Create `.env`** from `.env.example` in that folder and fill in the two keys
   (`python -c "import secrets; print(secrets.token_urlsafe(24))"`, twice - they must
   differ). `WRITE_API_KEY` goes on the Pi, `READ_API_KEY` into the phone app.
3. **Create the data folder, then start it.** Docker on Synology does not create
   missing bind-mount folders, so first create an empty folder named `data` right next
   to `docker-compose.yml` (e.g. `/volume1/docker/carpediem-store/data`); the database
   lives there. Without it the start fails with `bind mount failed ... does not exist`.
   Then Container Manager > Project > Create > set the path to the folder holding
   `docker-compose.yml`; it builds the image and starts it. (Or over SSH:
   `mkdir data && sudo docker compose up -d --build`.) Check
   `http://<nas-ip>:8090/health` answers `{"ok": true}`.
4. **Make it reachable from the internet over HTTPS.** The Pi (on the boat) and the
   phone (anywhere) both need to reach it, and the API keys travel in a header, so
   use HTTPS:
   - A hostname: DSM Control Panel > External Access > DDNS (a free `*.synology.me`
     name is fine), or your own domain.
   - A certificate: Control Panel > Security > Certificate > Add > Let's Encrypt.
   - A reverse proxy: Control Panel > Login Portal > Advanced > Reverse Proxy >
     Create: source `HTTPS` / your hostname / `443`, destination `HTTP` / `localhost` /
     `8090`. (Menu names shift a little between DSM versions.)
   - Your router: forward TCP 443 to the NAS.

   No port-forward wanted? A Cloudflare Tunnel (a `cloudflared` container pointing at
   `http://carpediem-store:8090`) gives you an HTTPS hostname with no open ports.
5. **Point the Pi at it** - `.env` on the Pi:
   ```
   PUBLISH_BACKEND=synology
   PUBLISH_URL=https://carpediem.example.synology.me
   PUBLISH_API_KEY=<the WRITE_API_KEY>
   ```
   and restart the app. The log says `Publisher: pushing to synology store ...`.
6. **Point the phone at it** - Settings (gear): DATA STORE ADDRESS = the same URL,
   READ KEY = `READ_API_KEY`, then TEST.

The API keys are the only protection on a public address, so keep them long and
random, and don't reuse the read key as the write key (the server refuses to start
if they're equal or missing).

## Automatic cleanup

`RETENTION_DAYS` in `.env`:

| value | meaning |
|---|---|
| `-1` | never delete anything |
| `30` | delete history older than 30 days (any whole number >= 1) |

The cleanup runs at startup and then every `CLEANUP_INTERVAL_MINUTES` (default 60),
and gives the freed space back to the NAS. Things to know:

- It only removes **history**. The latest state and the latest camera snapshots are
  never deleted, so a phone opened after a long outage still shows the last known
  data - flagged orange as old.
- The Pi pushes every ~10 s, but only one push per `HISTORY_INTERVAL_SECONDS`
  (default 60) is also kept as a history row, otherwise the database would grow by
  hundreds of MB a day. At the default that is roughly 10-15 MB/day; `0` keeps no
  history at all.
- `0` and other negative numbers for `RETENTION_DAYS` are rejected at startup.

## The API (v1)

This is the contract everything else depends on: the Pi's `PUBLISH_BACKEND=synology`
client and the phone's `StoreSource` know only these routes. `GET` needs the
read key and `PUT` the write key, sent as an `X-API-Key` header. Times are Unix
seconds on the **store's** clock, and the store works out `age_seconds` itself, so
neither the Pi's nor the phone's clock has to be right.

| | |
|---|---|
| `PUT /v1/state` | Body (gzip allowed): `{"sent_at": <unix s>, "data": {...}, "vessels": {...}?, "system": {...}?}`. `data` is the flat `{internal_label: value}` object of `GET /api/data` on the Pi; `vessels`/`system` match `/api/vessels` and `/api/system`. Replaces the latest state and, at most once per `HISTORY_INTERVAL_SECONDS`, adds a history row. |
| `GET /v1/state` | `{"server_time", "received_at", "age_seconds", "sent_at", "data", "vessels", "system"}`. If nothing was ever pushed: `age_seconds` and `received_at` are `null`, `data` is `{}` (still HTTP 200). |
| `GET /v1/history?since=&until=&limit=` | `{"states": [...]}`, newest first, each with `received_at`. `limit` max 1000. |
| `PUT /v1/cam/<name>/snapshot` | JPEG body; `<name>` is lower-case `a-z 0-9 _ -` (the Pi uses `salon`, `bakboord`, ...). Keeps the latest one per camera. |
| `GET /v1/cam/<name>/snapshot.jpg` | The latest snapshot, or 404. |
| `GET /health` | `{"ok": true}`, no key needed (for the Docker healthcheck). |
| `GET /privacy` | The phone app's privacy policy as a web page, no key needed. It is the App Store's Privacy Policy URL; the text lives in `carpediem_store/static/privacy.html`. |

## How the phone decides green / orange / red

The LINK lamp and the header pill in the app:

- **green (LIVE)** - the store answered and the boat reported within the last
  2 minutes (`STALE_AFTER_SECONDS` in `mobile/src/data/source.ts`).
- **orange (OLD DATA)** - the store answered, but its newest data is older than that
  (Pi off, boat has no internet, ...), or it has no data at all yet. The pill shows
  how old.
- **red (OFFLINE)** - the store didn't answer, or refused the key.

## Choosing a different datastore

Three seams, so moving off the Synology later doesn't mean rewriting everything:

1. **A different backend behind this server** - implement `Storage`
   (`carpediem_store/storage/base.py`: latest state, history, snapshots, delete
   history before a date) in a new module next to `sqlite.py`, register it in
   `storage/__init__.py`, select it with `STORAGE_BACKEND`. Routes, auth and the
   cleanup schedule come for free. Suits e.g. Postgres/Supabase, with this server
   hosted anywhere that runs a container.
2. **A serverless store that speaks the same API** - e.g. a Cloudflare Worker with
   KV or D1 implementing the table above. The Pi and the phone can't tell the
   difference: set `PUBLISH_BACKEND=http` and both URLs to the Worker. The
   retention setting becomes a Cron Trigger deleting old history rows.
3. **A store with its own wire protocol** (Supabase's REST API directly, ...) -
   add a `PublishBackend` subclass in `carpediem/publisher.py` (Pi side) and a
   `DataSource` in `mobile/src/data/source.ts` (phone side), and register them in
   `BACKENDS` / `createSource()`.

## Tests

```
cd server
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Covers the auth split, gzip uploads, history throttling, snapshots, and the
retention rules (30 days, -1, the latest state surviving cleanup, cleanup at
startup). Not run against a real Synology - that part of the setup is on you to
verify (step 3's health check is the quickest test).
