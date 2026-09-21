# CarpeDiem e-ink dashboard

ESP32-S3 + Waveshare IT8951 e-Paper Driver HAT (B). Polls the Raspberry
Pi's `carpediem/web_server.py` data API over the boat's own WiFi and
renders a small curated subset of `display_data` onto the e-paper panel -
see the main [README.md](../../README.md)'s "Web server (data API)"
section for the Pi side of this.

## Wiring

The Driver HAT (B) is a universal SPI driver board - it doesn't know its
own resolution until queried at runtime (`eink_display.ino` reads that
from the IT8951 itself via `it8951_init()`), so whichever Waveshare panel
is plugged into the driver board's ribbon cable "just works" without
editing the sketch.

| HAT SPI pin | Signal | ESP32-S3 GPIO | Wire color |
|---|---|---|---|
| 2 | 5V | 5V / VBUS | red |
| 6 | GND | GND | black |
| 19 | MOSI | GPIO11 | yellow |
| 21 | MISO | GPIO13 | blue |
| 23 | SCK | GPIO12 | white |
| 24 | CS | GPIO10 | purple |
| 11 | RST | GPIO5 | green |
| 18 | HRDY | GPIO4 | orange |

(Also documented in `it8951.h`'s `IT8951_PIN_*` defines and
`eink_display.ino`'s own header comment, so the wiring table travels with
the code that depends on it, not just this README.)

None of these GPIOs collide with the ESP32-S3's boot-strapping pins (0,
3, 45, 46, 47, 48 on most variants), so no special boot-mode handling is
needed because of the wiring choice itself.

## Build / upload from VS Code (PlatformIO)

This folder is a [PlatformIO](https://platformio.org) project (the
"PlatformIO IDE" VS Code extension) rather than a flat Arduino IDE sketch
folder: `src/` holds `eink_display.ino` + `it8951.cpp`, `include/` holds
the headers, `platformio.ini` holds the board and library config
(ArduinoJson v7, Adafruit GFX - PlatformIO fetches them itself, no Library
Manager step). `it8951.h`/`it8951.cpp` are a trimmed port of Waveshare's
own IT8951 demo protocol code (see `it8951.h`'s header comment) - no
external library needed for those.

1. Copy `include/arduino_secrets.h.example` to `include/arduino_secrets.h`
   and fill in your WiFi SSID/password and the Pi's `PI_API_URL` (its LAN
   IP or hostname + `WEBSERVER_PORT`, default `8080` - see the main
   README.md). `arduino_secrets.h` is git-ignored, same convention as the
   Python side's `.env`. If the Pi has `WEBSERVER_API_KEY` set, also uncomment
   `PI_API_KEY` there with the same value (the sketch sends it as `X-API-Key`).
2. Open the `firmware/eink_display` folder in VS Code (File > Open
   Folder, or add it to your workspace) so PlatformIO picks up
   `platformio.ini`. The status bar gets Build (checkmark), Upload
   (arrow) and Serial Monitor (plug) buttons; or from a terminal in this
   folder: `pio run` (build), `pio run -t upload` (flash), `pio device
   monitor` (Serial at 115200 baud).
3. Plug the ESP32-S3 in over USB and Upload. If it doesn't enter the
   bootloader on its own, hold BOOT while tapping RESET, then retry.

The first build downloads the ESP32 toolchain/framework (~1GB, a minute or
two); it has been verified to compile cleanly (RAM 14%, flash 27%), but
not yet flashed to real hardware here, so treat first bring-up as exactly
that - watch the Serial monitor.

Board is set to the generic `esp32-s3-devkitc-1` in `platformio.ini`. If
Serial reports `Canvas allocation failed` at startup (panel framebuffer
too big for plain SRAM - `width/8 * height` bytes, e.g. ~124KB for
1200x825), uncomment the two PSRAM lines at the bottom of `platformio.ini`
if your board actually has PSRAM populated.

## What it shows

`CURATED_FIELDS` in `eink_display.ino` is a plain array of
`{json_key, label}` pairs - edit it to change which `display_data` fields
show up. The Pi's API returns *everything* with no curation on its end
(see the main README's "Web server (data API)" section); this sketch is
where the "which fields does this particular consumer care about" decision
actually lives, so changing it needs no coordination with the Pi side.

On a failed fetch (WiFi hiccup, Pi unreachable, ...) the display keeps
showing the last successfully-fetched reading rather than blanking, with a
"stale" note showing how long ago that was - check the Serial log (115200
baud) for the actual failure reason.
