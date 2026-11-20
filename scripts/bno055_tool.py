"""Bench/boat helper for the BNO055 attitude sensor (sensors/bno055_sensor.py).
Reads the same .env as the app (BNO055_* settings), so run it on the Pi from
the repo root with the app's venv:

    python -m scripts.bno055_tool live          # roll/pitch/calibration, 4 x per second
    python -m scripts.bno055_tool level         # boat is level: make this attitude read 0/0 (5 s average)
    python -m scripts.bno055_tool level -s 10   # ...averaged over 10 s instead
    python -m scripts.bno055_tool level --clear # forget the level offset again
    python -m scripts.bno055_tool save-cal      # wait for full calibration, save the profile

First-time check (`live`): tip the board so the starboard side goes DOWN -
roll must go positive; lift the bow - pitch must go positive. If not, the
mounting settings (BNO055_BOW_AXIS / BNO055_UP_AXIS, which sensor axis points
to the bow and which points up) are wrong, not the sensor.

`level` and `live` can run while the app is running (the tool only reads if
the sensor is already running, and the app picks up a new level file within
a few seconds). `save-cal` interrupts the sensor briefly - the app saves the
profile by itself once the sensor reports full calibration, so this is only
for saving it without the app running (stop the service first).

Calibration (IMU mode needs gyro + accelerometer at 3/3): gyro - leave the
board still for a few seconds; accelerometer - hold it still in 6 poses (each
face of a cube pointing up) for ~3 s each.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time

from carpediem.config import config
from carpediem.sensors import bno055_sensor as bno
from carpediem.sensors.bno055_sensor import Bno055, LevelOffsets


def attach() -> tuple[Bno055, str]:
    """Open the sensor, starting fusion only if nothing (the app) has yet."""
    cfg = config.bno055
    mode_name = "NDOF" if cfg.mode.strip().upper() == "NDOF" else "IMU"
    sensor = bno.open_sensor()
    if sensor.chip_id() != bno.CHIP_ID:
        sys.exit("No BNO055 at that address - check wiring, BNO055_I2C_ADDRESS / BNO055_I2C_BUS (i2cdetect -y 1).")
    if sensor.operating_mode() == bno.MODE_CONFIG:
        print("sensor wasn't running - starting it")
        sensor.begin(bno.MODE_NDOF if mode_name == "NDOF" else bno.MODE_IMU, cfg.external_crystal,
                     bno.load_calibration(cfg.calibration_file))
        time.sleep(0.5)
    return sensor, mode_name


def raw_attitude(sensor: Bno055) -> tuple[float, float]:
    """Roll/pitch in the boat frame, *without* the level offset."""
    cfg = config.bno055
    att = bno.boat_attitude(sensor.gravity(), cfg.bow_axis, cfg.up_axis)
    if att is None:
        raise RuntimeError("no gravity vector yet - the sensor is still starting; try again in a second")
    return att


def cmd_live(_args) -> None:
    cfg = config.bno055
    sensor, mode_name = attach()
    level = LevelOffsets.load(cfg.level_file)
    print(f"mode {mode_name}, bow={cfg.bow_axis} up={cfg.up_axis}, level offset roll {level.roll:+.2f} pitch {level.pitch:+.2f}")
    print("roll + = starboard side down, pitch + = bow up.  Ctrl+C to stop.\n")
    try:
        while True:
            gx, gy, gz = sensor.gravity()
            att = bno.boat_attitude((gx, gy, gz), cfg.bow_axis, cfg.up_axis)
            cal = bno.decode_calibration(sensor.calibration_byte())
            if att is None:
                text = "roll    ?   pitch    ?  "
            else:
                text = f"roll {att[0] - level.roll:+6.1f}   pitch {att[1] - level.pitch:+6.1f}  "
            print(f"{text}| gravity x{gx:+6.2f} y{gy:+6.2f} z{gz:+6.2f} | cal sys{cal[0]} gyr{cal[1]} acc{cal[2]} mag{cal[3]}")
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass


def cmd_level(args) -> None:
    path = config.bno055.level_file
    if args.clear:
        LevelOffsets().save(path)
        print(f"level offset cleared ({path})")
        return
    sensor, _mode = attach()
    print(f"Averaging {args.seconds:.0f} s - keep the boat as still and level as you can...")
    rolls, pitches = [], []
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        r, p = raw_attitude(sensor)
        rolls.append(r)
        pitches.append(p)
        time.sleep(0.1)
    roll0, pitch0 = statistics.fmean(rolls), statistics.fmean(pitches)
    spread = max(statistics.pstdev(rolls), statistics.pstdev(pitches))
    if spread > 0.7:
        print(f"WARNING: readings wandered (std dev {spread:.2f} deg) - the boat was moving; saving anyway, "
              f"repeat `level` in calmer water if the page doesn't sit at 0.")
    LevelOffsets(roll0, pitch0).save(path)
    print(f"saved {path}: roll {roll0:+.2f}, pitch {pitch0:+.2f} now read as 0/0 "
          f"(a running app picks this up within a few seconds).")


def cmd_save_cal(_args) -> None:
    cfg = config.bno055
    sensor, mode_name = attach()
    print("Waiting for full calibration (gyro still, accelerometer in 6 poses) - Ctrl+C to give up.")
    try:
        while True:
            byte = sensor.calibration_byte()
            sys_, gyr, acc, mag = bno.decode_calibration(byte)
            print(f"\rcal sys{sys_} gyr{gyr} acc{acc} mag{mag}   ", end="", flush=True)
            if gyr == 3 and acc == 3 and (mode_name != "NDOF" or mag == 3):
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\ngave up, nothing saved")
        return
    profile = sensor.read_offsets()
    bno._atomic_write_json(cfg.calibration_file, profile)
    print(f"\nsaved calibration profile to {cfg.calibration_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="BNO055 attitude sensor helper.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("live", help="print roll/pitch/calibration continuously").set_defaults(func=cmd_live)
    level = sub.add_parser("level", help="treat the current attitude as level")
    level.add_argument("-s", "--seconds", type=float, default=5.0, help="averaging time (default 5)")
    level.add_argument("--clear", action="store_true", help="remove the level offset instead")
    level.set_defaults(func=cmd_level)
    sub.add_parser("save-cal", help="wait for full calibration and save the profile").set_defaults(func=cmd_save_cal)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
