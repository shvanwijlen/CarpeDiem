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

## Libraries (Arduino IDE Library Manager)

- **ArduinoJson** (v7.x) - github.com/bblanchon/ArduinoJson
- **Adafruit GFX Library** - github.com/adafruit/Adafruit-GFX-Library

`it8951.h`/`it8951.cpp` (this folder) are a trimmed, from-scratch-typed
port of Waveshare's own IT8951 demo protocol code (see `it8951.h`'s header
comment for provenance) - no external library needed for those, but they
haven't been tested against real hardware here, so treat the first bring-up
as exactly that.

## Setup

1. Copy `arduino_secrets.h.example` to `arduino_secrets.h` and fill in
   your WiFi SSID/password and the Pi's `PI_API_URL` (its LAN IP or
   hostname + `WEBSERVER_PORT`, default `8080` - see the main README.md).
   `arduino_secrets.h` is git-ignored, same convention as the Python
   side's `.env`.
2. Board: ESP32S3 Dev Module (or your board's specific entry) in the
   Arduino IDE. Enable PSRAM (Tools > PSRAM) if your panel's resolution
   needs more than the ESP32-S3's ~512KB of plain SRAM for its 1bpp
   framebuffer (`width/8 * height` bytes - e.g. 1200x825 needs ~124KB,
   fine either way, but larger panels may not fit without PSRAM).
3. Flash `eink_display.ino`.

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
