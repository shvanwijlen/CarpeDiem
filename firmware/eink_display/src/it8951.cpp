// See it8951.h for provenance/scope. Protocol constants and structure
// match Waveshare's own IT8951 demo 1:1 - this is a trim + ESP32
// Arduino SPI adaptation, not a reverse-engineered reimplementation.
#include "it8951.h"
#include <SPI.h>

// ---- IT8951 TCon command codes (built-in) ----
#define IT8951_TCON_REG_RD      0x0010
#define IT8951_TCON_REG_WR      0x0011
#define IT8951_TCON_LD_IMG_AREA 0x0021
#define IT8951_TCON_LD_IMG_END  0x0022

// ---- I80 user-defined command codes ----
#define USDEF_I80_CMD_DPY_AREA     0x0034
#define USDEF_I80_CMD_GET_DEV_INFO 0x0302

// ---- Register addresses ----
#define SYS_REG_BASE     0x0000
#define I80CPCR          (SYS_REG_BASE + 0x04)
#define MCSR_BASE_ADDR   0x0200
#define LISAR            (MCSR_BASE_ADDR + 0x0008)
#define DISPLAY_REG_BASE 0x1000
#define UP1SR            (DISPLAY_REG_BASE + 0x138)
#define LUTAFSR          (DISPLAY_REG_BASE + 0x224)
#define BGVR             (DISPLAY_REG_BASE + 0x250)

// ---- Load-image argument encoding ----
#define IT8951_LDIMG_L_ENDIAN 0
#define IT8951_8BPP            3
#define IT8951_ROTATE_0        0

IT8951DevInfo it8951_dev_info;
static uint32_t s_img_buf_addr;

// ---------------------------------------------------------------------
// Host controller primitives (SPI transaction shape per the IT8951
// datasheet's I80-over-SPI mapping - every word is preceded by a 2-byte
// preamble, and HRDY must be polled high before each 2-byte phase, not
// just once per command).
// ---------------------------------------------------------------------

static void wait_for_ready() {
    // HRDY is the IT8951's own "ready for the next SPI phase" signal. A long
    // e-paper refresh can legitimately hold it low for several seconds, so
    // don't give up - but log once so a miswired/unpowered HAT (HRDY stuck
    // low forever) is visible on Serial instead of a silent hang.
    unsigned long start = millis();
    bool warned = false;
    while (digitalRead(IT8951_PIN_HRDY) == LOW) {
        if (!warned && millis() - start > 5000) {
            Serial.println("IT8951: HRDY stuck low >5s - check HRDY wiring (GPIO4), 5V power, and ribbon cable");
            warned = true;
        }
        delay(1);
    }
}

static void write_cmd_code(uint16_t cmd) {
    wait_for_ready();
    digitalWrite(IT8951_PIN_CS, LOW);
    SPI.transfer(0x60);  // preamble 0x6000, high byte
    SPI.transfer(0x00);  // preamble 0x6000, low byte
    wait_for_ready();
    SPI.transfer(cmd >> 8);
    SPI.transfer(cmd & 0xFF);
    digitalWrite(IT8951_PIN_CS, HIGH);
}

static void write_data(uint16_t data) {
    wait_for_ready();
    digitalWrite(IT8951_PIN_CS, LOW);
    SPI.transfer(0x00);  // preamble 0x0000, high byte
    SPI.transfer(0x00);  // preamble 0x0000, low byte
    wait_for_ready();
    SPI.transfer(data >> 8);
    SPI.transfer(data & 0xFF);
    digitalWrite(IT8951_PIN_CS, HIGH);
}

static uint16_t read_data() {
    wait_for_ready();
    digitalWrite(IT8951_PIN_CS, LOW);
    SPI.transfer(0x10);  // preamble 0x1000, high byte
    SPI.transfer(0x00);  // preamble 0x1000, low byte
    wait_for_ready();
    SPI.transfer(0x00);  // dummy
    SPI.transfer(0x00);  // dummy
    wait_for_ready();
    uint16_t val = (uint16_t)SPI.transfer(0x00) << 8;
    val |= SPI.transfer(0x00);
    digitalWrite(IT8951_PIN_CS, HIGH);
    return val;
}

static void read_n_data(uint16_t* buf, uint32_t count) {
    wait_for_ready();
    digitalWrite(IT8951_PIN_CS, LOW);
    SPI.transfer(0x10);
    SPI.transfer(0x00);
    wait_for_ready();
    SPI.transfer(0x00);  // dummy
    SPI.transfer(0x00);  // dummy
    wait_for_ready();
    for (uint32_t i = 0; i < count; i++) {
        uint16_t val = (uint16_t)SPI.transfer(0x00) << 8;
        val |= SPI.transfer(0x00);
        buf[i] = val;
    }
    digitalWrite(IT8951_PIN_CS, HIGH);
}

static void send_cmd_arg(uint16_t cmd, const uint16_t* args, uint16_t n_args) {
    write_cmd_code(cmd);
    for (uint16_t i = 0; i < n_args; i++) {
        write_data(args[i]);
    }
}

static uint16_t read_reg(uint16_t reg_addr) {
    write_cmd_code(IT8951_TCON_REG_RD);
    write_data(reg_addr);
    return read_data();
}

static void write_reg(uint16_t reg_addr, uint16_t value) {
    write_cmd_code(IT8951_TCON_REG_WR);
    write_data(reg_addr);
    write_data(value);
}

static void set_img_buf_base_addr(uint32_t addr) {
    write_reg(LISAR + 2, (uint16_t)((addr >> 16) & 0xFFFF));
    write_reg(LISAR, (uint16_t)(addr & 0xFFFF));
}

static void get_system_info() {
    write_cmd_code(USDEF_I80_CMD_GET_DEV_INFO);
    read_n_data((uint16_t*)&it8951_dev_info, sizeof(IT8951DevInfo) / 2);
}

// ---------------------------------------------------------------------
// Public API - see it8951.h
// ---------------------------------------------------------------------

bool it8951_init() {
    pinMode(IT8951_PIN_CS, OUTPUT);
    pinMode(IT8951_PIN_HRDY, INPUT);
    pinMode(IT8951_PIN_RESET, OUTPUT);
    digitalWrite(IT8951_PIN_CS, HIGH);

    SPI.begin(IT8951_PIN_SCK, IT8951_PIN_MISO, IT8951_PIN_MOSI, IT8951_PIN_CS);
    SPI.beginTransaction(SPISettings(20000000, MSBFIRST, SPI_MODE0));

    digitalWrite(IT8951_PIN_RESET, LOW);
    delay(1000);  // 100ms per the datasheet is not enough in practice - see the ESP32 reference port
    digitalWrite(IT8951_PIN_RESET, HIGH);

    get_system_info();
    if (it8951_dev_info.usPanelW == 0 || it8951_dev_info.usPanelH == 0) {
        return false;  // no panel answered - check the ribbon cable and the wiring table in the README
    }
    s_img_buf_addr = it8951_dev_info.usImgBufAddrL | ((uint32_t)it8951_dev_info.usImgBufAddrH << 16);

    write_reg(I80CPCR, 0x0001);  // enable I80 packed mode
    return true;
}

void it8951_wait_for_display_ready() {
    while (read_reg(LUTAFSR) != 0) {
        // spin - non-zero means the LUT engine is still busy from a previous update
    }
}

void it8951_load_1bpp_image(const uint8_t* buf) {
    const uint16_t w = it8951_dev_info.usPanelW;
    const uint16_t h = it8951_dev_info.usPanelH;

    set_img_buf_base_addr(s_img_buf_addr);

    // Loading claims IT8951_8BPP (the IT8951 has no true 1bpp load mode)
    // but with the area width divided by 8 - each "byte" handed to the
    // load-image transfer below is really 8 packed monochrome pixels, not
    // one 8bpp grayscale pixel. This matches Adafruit GFX's GFXcanvas1
    // buffer layout (1 bit per pixel, MSB-first, row-padded to a whole
    // byte) exactly, so `buf` can be passed straight from canvas.getBuffer().
    uint16_t args[5];
    args[0] = (IT8951_LDIMG_L_ENDIAN << 8) | (IT8951_8BPP << 4) | IT8951_ROTATE_0;
    args[1] = 0;      // x
    args[2] = 0;      // y
    args[3] = w / 8;  // width, in packed bytes
    args[4] = h;      // height
    send_cmd_arg(IT8951_TCON_LD_IMG_AREA, args, 5);

    // Combine each pair of buffer bytes into one big-endian word by hand,
    // rather than casting buf to uint16_t* and dereferencing - on the
    // ESP32's little-endian CPU that would silently transmit every byte
    // pair swapped (invisible in Waveshare's own reference examples,
    // which only ever load uniform memset() fills where byte order
    // doesn't matter - not the case for real varying pixel data).
    uint32_t byte_count = (uint32_t)w / 8 * h;
    for (uint32_t i = 0; i + 1 < byte_count; i += 2) {
        write_data(((uint16_t)buf[i] << 8) | buf[i + 1]);
    }

    write_cmd_code(IT8951_TCON_LD_IMG_END);
}

void it8951_display_1bpp(uint16_t usDpyMode, uint8_t bg_gray, uint8_t fg_gray) {
    // 1bpp display mode bit - see UP1SR in the IT8951 programming guide.
    write_reg(UP1SR + 2, read_reg(UP1SR + 2) | (1 << 2));
    // BGVR: bits[15:8] = background gray level, bits[7:0] = foreground.
    write_reg(BGVR, ((uint16_t)bg_gray << 8) | fg_gray);

    write_cmd_code(USDEF_I80_CMD_DPY_AREA);
    write_data(0);
    write_data(0);
    write_data(it8951_dev_info.usPanelW);
    write_data(it8951_dev_info.usPanelH);
    write_data(usDpyMode);
    it8951_wait_for_display_ready();

    // Restore normal (non-1bpp) mode for whatever runs next.
    write_reg(UP1SR + 2, read_reg(UP1SR + 2) & ~(1 << 2));
}
