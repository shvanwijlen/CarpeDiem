"""Convert the FRAMEBUFFER_BEGIN/END hex dump from eink_display.ino into a PNG.

Usage:
    python framebuffer_to_png.py serial_log.txt out.png

Capture the log with e.g. `pio device monitor --filter log2file` (writes
platformio-device-monitor-*.log) or by copy/pasting the monitor output.

Buffer layout matches Adafruit GFX GFXcanvas1 / what is sent to the
IT8951: 1 bit per pixel, MSB first, rows padded to whole bytes. A 1 bit is
drawn text (rendered black), a 0 bit is background (white) - the same
mapping the firmware passes to the panel (bg_gray=15, fg_gray=0).

Requires Pillow: pip install pillow
"""
import re
import sys

from PIL import Image


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()

    m = re.search(r"FRAMEBUFFER_BEGIN (\d+) (\d+)\s*(.*?)\s*FRAMEBUFFER_END", text, re.S)
    if not m:
        print("No complete FRAMEBUFFER_BEGIN...FRAMEBUFFER_END block found in the log")
        return 1
    w, h = int(m.group(1)), int(m.group(2))
    hex_data = re.sub(r"[^0-9A-Fa-f]", "", m.group(3))
    data = bytes.fromhex(hex_data)

    expected = w // 8 * h
    if len(data) != expected:
        print(f"Size mismatch: got {len(data)} bytes, expected {expected} for {w}x{h}")
        return 1

    # PIL mode "1" is MSB-first, rows padded to bytes - same layout. It treats
    # 1 as white, and our 1 means black text, so invert.
    img = Image.frombytes("1", (w, h), data).point(lambda p: 255 - p).convert("1")
    img.save(sys.argv[2])
    print(f"Wrote {sys.argv[2]} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
