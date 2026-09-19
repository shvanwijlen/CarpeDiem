#!/usr/bin/env python3
"""
rf_scan.py - discover every 433/868 MHz device in range with an RTL-SDR.

Drives rtl_433 (which decodes 200+ sensor protocols: Bresser, Oregon Scientific,
LaCrosse, Fine Offset, TPMS, doorbells, remotes, ...) and hops between the
ISM frequencies where such devices live. Every decoded message is collected
and summarised per device (model + id + channel) with message count, signal
strength, first/last seen and the latest readings.

Requirements
    - An RTL-SDR dongle + antenna (use an 868 MHz antenna for the 868 band)
    - rtl_433 installed:  sudo apt install rtl-433
    - Python 3.8+, standard library only

Examples
    ./rf_scan.py                          # EU bands, 10 minutes
    ./rf_scan.py --duration 0             # run until Ctrl-C
    ./rf_scan.py --freq 868.3M            # only the Bresser band, no hopping
    ./rf_scan.py --region us --json out.json --csv out.csv
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

REGIONS = {
    "eu": ["433.92M", "868.3M", "868.95M"],
    "us": ["315M", "433.92M", "915M"],
    "all": ["315M", "433.92M", "868.3M", "868.95M", "915M"],
}

# Fields that identify the device / radio, not "readings".
NON_READING_FIELDS = {
    "time", "model", "id", "channel", "mic", "protocol", "mod",
    "freq", "freq1", "freq2", "rssi", "snr", "noise", "subtype",
}


def normalise_freq(text):
    """'868.3' -> '868.3M' (bare numbers are MHz); '433920k' / '868.3M' pass through."""
    text = text.strip()
    if text[-1:].isalpha():
        return text
    return text + "M"


def parse_args():
    p = argparse.ArgumentParser(
        description="Scan for all RF sensors/devices in range using rtl_433.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--region", choices=sorted(REGIONS), default="eu",
                   help="preset list of frequencies to scan")
    p.add_argument("--freq", action="append", metavar="FREQ",
                   help="scan this frequency instead of a preset (repeatable), e.g. 868.3M")
    p.add_argument("--dwell", type=int, default=30, metavar="SEC",
                   help="seconds to stay on each frequency before hopping")
    p.add_argument("--duration", type=int, default=600, metavar="SEC",
                   help="total scan time in seconds, 0 = until Ctrl-C")
    p.add_argument("--rate", default="1024k",
                   help="sample rate (1024k is needed for the 868 MHz FSK sensors)")
    p.add_argument("--gain", metavar="DB", help="tuner gain in dB (default: auto)")
    p.add_argument("--ppm", metavar="PPM", help="frequency correction in ppm")
    p.add_argument("--device", metavar="N", help="RTL-SDR device index or serial")
    p.add_argument("--all-protocols", action="store_true",
                   help="also enable decoders that are off by default "
                        "(finds more devices, but more false positives)")
    p.add_argument("--json", metavar="FILE", help="write the device summary to a JSON file")
    p.add_argument("--csv", metavar="FILE", help="write the device summary to a CSV file")
    p.add_argument("--verbose", action="store_true",
                   help="print every message and rtl_433's own log output")
    p.add_argument("--rtl433", metavar="PATH", help="path to the rtl_433 binary")
    return p.parse_args()


def build_command(exe, args, freqs):
    cmd = [exe, "-F", "json", "-M", "level", "-M", "protocol", "-s", args.rate]
    for f in freqs:
        cmd += ["-f", f]
    if len(freqs) > 1:
        cmd += ["-H", str(args.dwell)]
    if args.duration > 0:
        cmd += ["-T", str(args.duration)]
    if args.gain:
        cmd += ["-g", args.gain]
    if args.ppm:
        cmd += ["-p", args.ppm]
    if args.device:
        cmd += ["-d", args.device]
    if args.all_protocols:
        cmd += ["-G"]
    return cmd


def readings_of(msg):
    return {k: v for k, v in msg.items() if k not in NON_READING_FIELDS}


def short_readings(readings, width=48):
    text = " ".join(f"{k}={v}" for k, v in readings.items())
    return text if len(text) <= width else text[: width - 1] + "…"


def record(devices, msg):
    """Fold one decoded message into the per-device table. Returns (key, is_new)."""
    key = (str(msg.get("model")), str(msg.get("id", "-")), str(msg.get("channel", "-")))
    freq = msg.get("freq", msg.get("freq1"))
    now = datetime.now()
    dev = devices.get(key)
    is_new = dev is None
    if is_new:
        dev = devices[key] = {
            "model": key[0], "id": key[1], "channel": key[2],
            "messages": 0, "first_seen": now, "rssi_sum": 0.0, "rssi_n": 0,
            "freq_mhz": None, "readings": {},
        }
    dev["messages"] += 1
    dev["last_seen"] = now
    if freq is not None:
        dev["freq_mhz"] = round(float(freq), 3)
    if isinstance(msg.get("rssi"), (int, float)):
        dev["rssi_sum"] += msg["rssi"]
        dev["rssi_n"] += 1
    dev["readings"] = readings_of(msg)
    return key, is_new


def avg_rssi(dev):
    return dev["rssi_sum"] / dev["rssi_n"] if dev["rssi_n"] else None


def print_summary(devices, elapsed):
    print()
    print(f"=== Scan finished after {elapsed:.0f} s: {len(devices)} device(s) found ===")
    if not devices:
        print("Nothing decoded. Check antenna/gain, try a longer --duration, "
              "or add --all-protocols.")
        return
    header = f"{'Model':<34} {'ID':<10} {'Ch':<4} {'MHz':>8} {'Msgs':>5} {'RSSI dB':>8}  {'Last seen':<8}  Latest reading"
    print(header)
    print("-" * len(header))
    for dev in sorted(devices.values(), key=lambda d: -d["messages"]):
        rssi = avg_rssi(dev)
        freq = f"{dev['freq_mhz']:.3f}" if dev["freq_mhz"] is not None else "-"
        print(f"{dev['model'][:34]:<34} {dev['id'][:10]:<10} {dev['channel'][:4]:<4} "
              f"{freq:>8} {dev['messages']:>5} "
              f"{(f'{rssi:.1f}' if rssi is not None else '-'):>8}  "
              f"{dev['last_seen'].strftime('%H:%M:%S'):<8}  {short_readings(dev['readings'])}")


def export(devices, json_path, csv_path):
    rows = []
    for dev in sorted(devices.values(), key=lambda d: -d["messages"]):
        rssi = avg_rssi(dev)
        rows.append({
            "model": dev["model"], "id": dev["id"], "channel": dev["channel"],
            "freq_mhz": dev["freq_mhz"], "messages": dev["messages"],
            "avg_rssi": round(rssi, 1) if rssi is not None else None,
            "first_seen": dev["first_seen"].isoformat(timespec="seconds"),
            "last_seen": dev["last_seen"].isoformat(timespec="seconds"),
            "last_reading": dev["readings"],
        })
    if json_path:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False)
        print(f"Saved JSON: {json_path}")
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["model"])
            writer.writeheader()
            for row in rows:
                row = dict(row)
                row["last_reading"] = json.dumps(row["last_reading"], ensure_ascii=False)
                writer.writerow(row)
        print(f"Saved CSV: {csv_path}")


def main():
    args = parse_args()

    exe = args.rtl433 or shutil.which("rtl_433")
    if not exe:
        sys.exit("rtl_433 not found. Install it with:  sudo apt install rtl-433")

    freqs = [normalise_freq(f) for f in args.freq] if args.freq else REGIONS[args.region]
    cmd = build_command(exe, args, freqs)

    print("Scanning:", ", ".join(freqs))
    if len(freqs) > 1:
        cycle = args.dwell * len(freqs)
        print(f"Hopping every {args.dwell} s (each frequency is listened to for "
              f"{args.dwell} s out of every {cycle} s).")
        if args.dwell < 15:
            print("Note: many sensors transmit only every 12-60 s; a dwell under "
                  "15 s can miss them.")
    print("Duration:", "until Ctrl-C" if args.duration == 0 else f"{args.duration} s")
    print("Listening... (new devices are listed as they appear)\n")

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)
    except OSError as exc:
        sys.exit(f"Could not start rtl_433: {exc}")

    stderr_lines = []

    def drain_stderr():
        for line in proc.stderr:
            line = line.rstrip()
            stderr_lines.append(line)
            if args.verbose:
                print(f"[rtl_433] {line}", file=sys.stderr)

    threading.Thread(target=drain_stderr, daemon=True).start()

    devices = {}
    started = time.time()
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict) or "model" not in msg:
                continue
            key, is_new = record(devices, msg)
            if is_new:
                dev = devices[key]
                freq = f"{dev['freq_mhz']:.3f} MHz" if dev["freq_mhz"] is not None else "?"
                print(f"[{dev['first_seen'].strftime('%H:%M:%S')}] NEW  {key[0]}  "
                      f"id={key[1]}  ch={key[2]}  {freq}  {short_readings(dev['readings'], 70)}")
            elif args.verbose:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] msg  {key[0]} id={key[1]} "
                      f"{short_readings(readings_of(msg), 70)}")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if proc.returncode not in (0, None, -15) and not devices:
        print("\nrtl_433 exited with an error:", file=sys.stderr)
        for line in stderr_lines[-8:]:
            print("  " + line, file=sys.stderr)
        print("\nCommon causes: no dongle plugged in, or the kernel DVB driver has "
              "claimed it (blacklist dvb_usb_rtl28xxu and re-plug).", file=sys.stderr)

    print_summary(devices, time.time() - started)
    export(devices, args.json, args.csv)


if __name__ == "__main__":
    main()
