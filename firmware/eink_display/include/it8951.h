// Low-level driver for the Waveshare IT8951 e-Paper Driver HAT (B), over
// SPI. Ported from Waveshare's own IT8951 demo code (github.com/waveshare/
// IT8951), via a community ESP32/Arduino port (github.com/andantesys/
// IT8951-for-esp32-with-arduino-code) - the SPI transaction protocol
// (preamble words 0x6000/0x0000/0x1000, TCON command codes, register
// addresses) is the vendor's own, not reverse-engineered here. Trimmed to
// the functions eink_display.ino actually calls; see the two source repos
// above for the fuller command set (memory burst read/write, 8bpp/2bpp/
// 3bpp load, rotation modes, ...) if you need more than plain 1bpp text.
//
// Pin assignment - see ../../README.md "E-ink dashboard" and this
// sketch's own eink_display.ino header comment for the full wiring table
// (signal, ESP32-S3 GPIO, wire color).
#pragma once

#include <Arduino.h>

#define IT8951_PIN_MISO  13  // blue
#define IT8951_PIN_MOSI  11  // yellow
#define IT8951_PIN_SCK   12  // white
#define IT8951_PIN_CS    10  // purple
#define IT8951_PIN_RESET 5   // green
#define IT8951_PIN_HRDY  4   // orange

typedef struct {
    uint16_t usPanelW;
    uint16_t usPanelH;
    uint16_t usImgBufAddrL;
    uint16_t usImgBufAddrH;
    uint16_t usFWVersion[8];   // 16-byte string
    uint16_t usLUTVersion[8];  // 16-byte string
} IT8951DevInfo;

// Populated by it8951_init() - actual panel resolution as reported by the
// IT8951 itself over SPI, not something to hardcode: the "Driver HAT (B)"
// is a universal board sold separately from the panel, so this sketch
// doesn't otherwise know the resolution of whichever Waveshare panel is
// plugged into it via the ribbon cable.
extern IT8951DevInfo it8951_dev_info;

// Returns true on success (a panel answered with a non-zero W/H). Brings
// up SPI, pulses RESET, and queries the device info above.
bool it8951_init();

// Blocks (spin-polls HRDY) until the LUT engine has finished the previous
// display update - call before starting a new one.
void it8951_wait_for_display_ready();

// Uploads a 1bpp (1 bit per pixel, MSB-first, matching Adafruit GFX's
// GFXcanvas1 buffer layout exactly) image to the IT8951's internal image
// buffer, covering the whole panel (0,0,panelW,panelH).
//
// bg_gray/fg_gray are 0-15 (0 = black, 15 = white) or the usual 0x00/0xFF
// byte values also work (only the top nibble is used) - see
// IT8951_MODE_* below for usDpyMode.
void it8951_load_1bpp_image(const uint8_t* buf);

// Triggers the actual e-paper refresh for the whole panel, using
// bg_gray/fg_gray as the two 1bpp colors and usDpyMode as the IT8951
// waveform mode (0 = INIT - full flashing clear, use once at startup;
// 2 = GC16 - normal ghost-free grayscale update, use for every
// subsequent redraw). Blocks until the panel has actually finished
// updating.
void it8951_display_1bpp(uint16_t usDpyMode, uint8_t bg_gray, uint8_t fg_gray);
