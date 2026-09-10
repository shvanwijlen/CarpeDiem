"""Throwaway diagnostic: run rtl_433 against the RTL-SDR Blog V3 dongle and
print every decoded transmission it hears, so you can confirm the dongle +
antenna actually work before trying to pick up the boat's Bresser weather
station on the 433MHz ISM band (see README.md's Weather433 status slot).

Away from the boat, this won't see the Bresser station itself, but rtl_433
decodes dozens of other common 433MHz devices (other weather stations, tyre
pressure sensors, remote doorbells/sensors, ...) - hearing *anything* here
confirms the hardware chain (dongle, antenna, rtl_433 install) works.

Needs rtl_433 installed separately - it's a C binary, not a pip package:
    sudo apt install rtl-433
(or build from source: https://github.com/merbanan/rtl_433)

Run on the Pi:
    python -m scripts.rtl433_sniff

Ctrl+C to stop.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

RTL_433_BIN = "rtl_433"
FREQUENCY_HZ = 433_920_000  # standard EU / most-common ISM band center frequency


def main() -> None:
    if shutil.which(RTL_433_BIN) is None:
        print(f"'{RTL_433_BIN}' not found on PATH - install it first:\n"
              f"    sudo apt install rtl-433", file=sys.stderr)
        raise SystemExit(1)

    print(f"Listening on {FREQUENCY_HZ / 1e6:.3f} MHz via {RTL_433_BIN} - Ctrl+C to stop")
    proc = subprocess.Popen(
        [RTL_433_BIN, "-f", str(FREQUENCY_HZ), "-F", "json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                print(line)  # rtl_433's own startup/status text, not JSON
                continue
            model = msg.get("model", "?")
            time_ = msg.get("time", "")
            rest = {k: v for k, v in msg.items() if k not in ("model", "time")}
            print(f"{time_}  {model}  {rest}")
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
