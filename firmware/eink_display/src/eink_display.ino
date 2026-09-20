// CarpeDiem e-ink dashboard
// ESP32-S3 + Waveshare IT8951 e-Paper Driver HAT (B)
//
// Polls the Raspberry Pi's carpediem/web_server.py (GET /api/data - see
// ../../README.md "Web server (data API)") over the boat's own WiFi and
// renders a small curated subset of the fields onto the e-paper panel.
// The Pi's API deliberately returns *everything* in display_data with no
// curation on its end - CURATED_FIELDS below is where this consumer picks
// out just the handful it wants to show; edit that list to taste, no
// firmware-vs-server coordination needed since the Pi doesn't know or
// care which fields any particular consumer reads.
//
// ---------------------------------------------------------------------
// Wiring (ESP32-S3 <-> Waveshare IT8951 Driver HAT (B) SPI header) - see
// ../../README.md "E-ink dashboard" for the full writeup, and it8951.h
// for the corresponding IT8951_PIN_* pin numbers used by the driver.
//
//   HAT SPI pin | Signal | ESP32-S3 GPIO | Wire color
//   ------------|--------|---------------|------------
//   2           | 5V     | 5V / VBUS     | red
//   6           | GND    | GND           | black
//   19          | MOSI   | GPIO11        | yellow
//   21          | MISO   | GPIO13        | blue
//   23          | SCK    | GPIO12        | white
//   24          | CS     | GPIO10        | purple
//   11          | RST    | GPIO5         | green
//   18          | HRDY   | GPIO4         | orange
// ---------------------------------------------------------------------
//
// Built with PlatformIO (VS Code) - libraries (ArduinoJson v7, Adafruit
// GFX) are declared in ../platformio.ini and fetched automatically; see
// ../README.md for build/upload steps. it8951.h/.cpp need no external
// library - see that file's header comment for where its protocol
// implementation comes from.
//
// If the attached panel's 1bpp framebuffer (width/8 * height bytes) needs
// more than the ESP32-S3's plain SRAM, enable the PSRAM lines in
// platformio.ini (e.g. a 1200x825 panel needs ~124KB, which fits either
// way, but larger panels may not without PSRAM).
//
// WiFi credentials and the Pi's address live in include/arduino_secrets.h
// (copy arduino_secrets.h.example to arduino_secrets.h and fill in real
// values - arduino_secrets.h is git-ignored, same convention as the
// Python side's .env/.env.example).

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>

#include "it8951.h"
#include "arduino_secrets.h"

// Which display_data fields to show, and the short label to show them
// under - see carpediem/display_data.py for the full field list this is
// drawn from. Values are shown exactly as the API returns them (whatever
// unit/precision display_data itself already uses for that field).
struct FieldToShow {
    const char* json_key;
    const char* label;
};

static const FieldToShow CURATED_FIELDS[] = {
    {"Battery SOC (%)", "Battery"},
    {"Battery0 Voltage (V)", "Batt Volt"},
    {"BresserTemperature", "Outside Temp"},
    {"BresserHumidity", "Outside Hum"},
    {"sparkfun_elec_bay_temperature", "Elec Bay Temp"},
    {"sparkfun_elec_bay_humidity", "Elec Bay Hum"},
    {"Speed", "Speed"},
    {"Course", "Course"},
};
static const size_t CURATED_FIELD_COUNT = sizeof(CURATED_FIELDS) / sizeof(CURATED_FIELDS[0]);

static const unsigned long POLL_INTERVAL_MS = 60UL * 1000UL;
static const unsigned long HTTP_TIMEOUT_MS = 8UL * 1000UL;

static GFXcanvas1* canvas = nullptr;
static unsigned long last_fetch_ok_millis = 0;
static bool have_fetched_once = false;

// Persists across loop() iterations, deliberately: on a failed fetch,
// fetch_data() leaves this untouched, so render() below keeps drawing the
// last successfully-fetched reading instead of blanking every field.
static JsonDocument last_good_doc;

static void connect_wifi() {
    Serial.printf("WiFi: connecting to %s ...\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\nWiFi: connected, IP %s\n", WiFi.localIP().toString().c_str());
}

// Fetches PI_API_URL (see arduino_secrets.h) and fills `doc` with the
// parsed JSON. Returns false (leaving `doc` untouched) on any network or
// parse failure - the caller keeps showing the last good reading rather
// than blanking the display on a transient WiFi/Pi hiccup.
static bool fetch_data(JsonDocument& doc) {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("fetch: WiFi not connected, skipping");
        return false;
    }

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(PI_API_URL)) {
        Serial.println("fetch: http.begin() failed - check PI_API_URL");
        return false;
    }

    int status = http.GET();
    if (status != HTTP_CODE_OK) {
        Serial.printf("fetch: GET failed, HTTP status %d\n", status);
        http.end();
        return false;
    }

    DeserializationError err = deserializeJson(doc, http.getStream());
    http.end();
    if (err) {
        Serial.printf("fetch: JSON parse failed: %s\n", err.c_str());
        return false;
    }
    return true;
}

// Formats one field's value the way display_data's own JSON shows it:
// numbers with up to 2 decimal places (trimmed), strings as-is, null/
// missing as "--" (matches how this project's own HMI treats an
// unpopulated display_data field, rather than showing a misleading 0).
static String format_value(JsonVariantConst v) {
    if (v.isNull()) {
        return "--";
    }
    if (v.is<const char*>()) {
        return String(v.as<const char*>());
    }
    if (v.is<float>() || v.is<double>()) {
        double d = v.as<double>();
        char buf[32];
        snprintf(buf, sizeof(buf), "%.2f", d);
        return String(buf);
    }
    return v.as<String>();
}

static void render(bool fetch_ok) {
    canvas->fillScreen(0);  // 0 = black pixel value, but see fg/bg args to it8951_display_1bpp below
    canvas->setTextColor(1);
    canvas->setTextWrap(false);

    int16_t x = 10;
    int16_t y = 10;
    const int16_t line_h = 28;

    canvas->setTextSize(3);
    canvas->setCursor(x, y);
    canvas->print("CARPE DIEM");
    y += line_h + 10;

    canvas->setTextSize(2);
    for (size_t i = 0; i < CURATED_FIELD_COUNT; i++) {
        const FieldToShow& f = CURATED_FIELDS[i];
        String value = have_fetched_once ? format_value(last_good_doc[f.json_key]) : "--";
        canvas->setCursor(x, y);
        canvas->printf("%-14s %s", f.label, value.c_str());
        y += line_h;
    }

    y += 10;
    canvas->setTextSize(1);
    canvas->setCursor(x, y);
    if (!have_fetched_once) {
        canvas->print("Waiting for first successful fetch...");
    } else if (fetch_ok) {
        canvas->print("Last updated: just now");
    } else {
        unsigned long stale_s = (millis() - last_fetch_ok_millis) / 1000UL;
        canvas->printf("Last updated %lus ago - fetch failing, see Serial log", stale_s);
    }

    // Colors are 0-15 (0=black, 15=white); fg=black text (1-bits) on a
    // white background (0-bits), matching fillScreen(0) + setTextColor(1)
    // above. usDpyMode 2 = GC16, a normal ghost-free grayscale refresh -
    // see it8951.h.
    it8951_load_1bpp_image(canvas->getBuffer());
    it8951_display_1bpp(2, /*bg_gray=*/15, /*fg_gray=*/0);
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\nCarpeDiem e-ink dashboard starting...");

    if (!it8951_init()) {
        Serial.println("IT8951 init failed - check the ribbon cable and SPI wiring, then reset");
        while (true) {
            delay(1000);
        }
    }
    Serial.printf("IT8951: panel %ux%u\n", it8951_dev_info.usPanelW, it8951_dev_info.usPanelH);
    if (it8951_dev_info.usPanelW % 8 != 0) {
        // it8951_load_1bpp_image()'s byte-packing math assumes a whole
        // number of bytes per row (GFXcanvas1's own row stride is
        // (width+7)/8, only equal to width/8 when width%8==0) - every
        // real e-paper panel's width satisfies this, so this should never
        // actually fire, but a silently-sheared image would be a much
        // more confusing failure mode than this message.
        Serial.println("Panel width is not a multiple of 8 - 1bpp packing math needs updating for this panel");
        while (true) {
            delay(1000);
        }
    }

    canvas = new GFXcanvas1(it8951_dev_info.usPanelW, it8951_dev_info.usPanelH);
    if (canvas->getBuffer() == nullptr) {
        Serial.println("Canvas allocation failed - panel resolution may need PSRAM enabled (Tools > PSRAM)");
        while (true) {
            delay(1000);
        }
    }

    connect_wifi();

    // One full INIT-mode clear at startup (mode 0) - flashier than the
    // GC16 mode used afterwards, but clears any leftover image from a
    // previous session/power cycle properly. See it8951.h.
    canvas->fillScreen(0);
    Serial.println("setup: loading startup clear image...");
    it8951_load_1bpp_image(canvas->getBuffer());
    Serial.println("setup: image loaded, refreshing panel (INIT mode)...");
    it8951_display_1bpp(0, 15, 0);
    Serial.println("setup: startup clear done");
}

void loop() {
    Serial.println("loop: fetching data...");
    bool ok = fetch_data(last_good_doc);
    if (ok) {
        last_fetch_ok_millis = millis();
        have_fetched_once = true;
        Serial.println("loop: fetch OK");
    }
    Serial.println("loop: rendering...");
    render(ok);
    Serial.println("loop: render done");

    delay(POLL_INTERVAL_MS);
}
