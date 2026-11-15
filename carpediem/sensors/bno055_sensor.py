"""Adafruit BNO055 (STEMMA QT) orientation sensor over I2C: the boat's roll
and pitch for the Attitude page. Feeds the Roll / Pitch / ImuCalibration /
IMU display_data fields - see README.md's "BNO055 attitude sensor" section
for wiring, mounting and the I2C caveat below.

What it reads: not the chip's Euler angles but its fused *gravity vector*
(the direction of "up" in the sensor's own frame, with the boat's own
accelerations - waves, turns, engine vibration - filtered out by the
gyro/accelerometer fusion). Roll and pitch then follow from plain
trigonometry in the boat's frame (boat_attitude() below), which has two
advantages over Euler angles: the sign conventions are ours rather than
Bosch's (their "roll" is about the Y axis, their "pitch" about X, and the
range limits differ per axis), and any mounting orientation works by
declaring which sensor axis points to the bow and which points up
(BNO055_BOW_AXIS / BNO055_UP_AXIS) instead of programming the chip's axis
remap. Roll is positive with the starboard side down, pitch positive bow up.

Hand-rolled on smbus2 (already installed as qwiic_i2c's dependency for the
BME280) rather than Adafruit's CircuitPython/Blinka stack, whose I2C layer
raised [Errno 5] on this Pi for the BME280 - see bme280_sensor.py. Every
register access is retried on OSError for the same reason qwiic_i2c does.

Known BNO055 / Raspberry Pi caveat: the chip stretches the I2C clock, which
the Pi 4's hardware I2C handles badly - symptom is Errno 5 / garbage reads
or a sensor that works for minutes and then stalls. The fix is a slower
bus (`dtparam=i2c_arm_baudrate=10000` in /boot/firmware/config.txt); see
the README. (The Pi 5 doesn't have the bug.)

Follows the same "optional hardware, import lazily, log and no-op if
unavailable" pattern as bme280_sensor.py, except that a missing/failed
sensor blanks Roll/Pitch to None instead of leaving the last value: a
frozen attitude on a boat display is worse than none.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log

# -- register map (BNO055 datasheet, page 0) -------------------------------
CHIP_ID_REG = 0x00
CHIP_ID = 0xA0
PAGE_ID_REG = 0x07
GRAVITY_REG = 0x2E          # 3 x int16 LE, 1 LSB = 0.01 m/s^2
CALIB_STAT_REG = 0x35       # sys[7:6] gyr[5:4] acc[3:2] mag[1:0], 3 = calibrated
OPR_MODE_REG = 0x3D
PWR_MODE_REG = 0x3E
SYS_TRIGGER_REG = 0x3F
OFFSETS_REG = 0x55          # 22 bytes of calibration profile (CONFIG mode only)
OFFSETS_LEN = 22

MODE_CONFIG = 0x00
MODE_IMU = 0x08             # accelerometer + gyro fusion, no magnetometer
MODE_NDOF = 0x0C            # + magnetometer
_MODES = {"IMU": MODE_IMU, "NDOF": MODE_NDOF}

_GRAVITY_LSB = 100.0
_MIN_GRAVITY = 3.0          # m/s^2; below this the fusion hasn't produced a vector yet
_RETRY_SECONDS = 5.0        # between re-probe attempts of a missing/failed sensor
_SAVE_CALIBRATION_EVERY = 600.0
_LEVEL_RECHECK_EVERY = 5.0  # how often to look for a newly written level file
_LOG_FAILURE_EVERY = 60.0

Vector = Tuple[float, float, float]


# -- pure maths (no hardware: unit-tested in tests/test_bno055.py) -----------

def parse_axis(text: str) -> Tuple[int, int]:
    """"+X" / "-y" / "Z" -> (axis index 0-2, sign +1/-1)."""
    t = text.strip().upper()
    sign = 1
    if t and t[0] in "+-":
        sign = -1 if t[0] == "-" else 1
        t = t[1:]
    if t not in ("X", "Y", "Z"):
        raise ValueError(f"axis must be one of +X -X +Y -Y +Z -Z, got {text!r}")
    return "XYZ".index(t), sign


def _unit(axis: Tuple[int, int]) -> Vector:
    v = [0.0, 0.0, 0.0]
    v[axis[0]] = float(axis[1])
    return v[0], v[1], v[2]


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector, b: Vector) -> Vector:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def boat_attitude(gravity: Vector, bow_axis: str, up_axis: str) -> Optional[Tuple[float, float]]:
    """(roll, pitch) in degrees from the sensor-frame gravity vector (what
    an accelerometer reads at rest: +1 g along whichever axis points up).

    bow_axis / up_axis name the sensor axes pointing to the bow and up
    ("+X", "-Z", ...); port = up x bow (X to the bow, Z up -> Y to port).
    Roll is positive starboard side down, pitch positive bow up. None if
    the vector is too short to be a real reading (sensor not fused yet) or
    the two axes aren't distinct.
    """
    bow_i, up_i = parse_axis(bow_axis), parse_axis(up_axis)
    if bow_i[0] == up_i[0]:
        raise ValueError("BNO055_BOW_AXIS and BNO055_UP_AXIS must be different axes")
    if math.sqrt(_dot(gravity, gravity)) < _MIN_GRAVITY:
        return None
    bow, up = _unit(bow_i), _unit(up_i)
    port = _cross(up, bow)
    g_bow, g_port, g_up = _dot(gravity, bow), _dot(gravity, port), _dot(gravity, up)
    roll = math.degrees(math.atan2(g_port, g_up))
    pitch = math.degrees(math.atan2(g_bow, math.hypot(g_port, g_up)))
    return roll, pitch


def decode_calibration(byte: int) -> Tuple[int, int, int, int]:
    """CALIB_STAT -> (sys, gyr, acc, mag), each 0-3."""
    return (byte >> 6) & 3, (byte >> 4) & 3, (byte >> 2) & 3, byte & 3


def relevant_calibration(byte: int, mode: str) -> int:
    """The 0-3 level shown on screen: the weakest of the sensors this mode
    actually uses (gyro + accelerometer, plus the magnetometer in NDOF)."""
    _sys, gyr, acc, mag = decode_calibration(byte)
    levels = [gyr, acc] + ([mag] if mode.upper() == "NDOF" else [])
    return min(levels)


def _to_int16(lo: int, hi: int) -> int:
    v = lo | (hi << 8)
    return v - 0x10000 if v & 0x8000 else v


def decode_gravity(raw: Sequence[int]) -> Vector:
    """6 bytes from GRAVITY_REG -> m/s^2 in the sensor frame."""
    return (_to_int16(raw[0], raw[1]) / _GRAVITY_LSB,
            _to_int16(raw[2], raw[3]) / _GRAVITY_LSB,
            _to_int16(raw[4], raw[5]) / _GRAVITY_LSB)


# -- small persistent files ---------------------------------------------------

def _atomic_write_json(path: Path, data: object) -> None:
    """Temp file + fsync + rename, so a power cut can't leave a truncated file
    (the Pi is meant to survive ungraceful power loss - see the README)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class LevelOffsets:
    """What the sensor reads while the boat sits level; subtracted from every
    reading so that attitude shows 0/0 there."""
    roll: float = 0.0
    pitch: float = 0.0

    @classmethod
    def load(cls, path: Path) -> "LevelOffsets":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(float(data["roll"]), float(data["pitch"]))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log(9, f"BNO055: ignoring unreadable level file {path}: {exc}")
            return cls()

    def save(self, path: Path) -> None:
        _atomic_write_json(Path(path), {"roll": round(self.roll, 3), "pitch": round(self.pitch, 3)})


def load_calibration(path: Path) -> Optional[List[int]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) == OFFSETS_LEN and all(isinstance(b, int) and 0 <= b <= 255 for b in data):
            return data
        log(9, f"BNO055: calibration file {path} has the wrong shape, ignoring it")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log(9, f"BNO055: ignoring unreadable calibration file {path}: {exc}")
    return None


# -- the chip ---------------------------------------------------------------

class Bno055:
    """Thin register-level driver. `bus` is anything with smbus2.SMBus's
    read_byte_data / write_byte_data / read_i2c_block_data methods (a fake
    in the tests)."""

    def __init__(self, bus, address: int) -> None:
        self._bus = bus
        self._addr = address

    def _retry(self, fn, *args):
        last: Optional[OSError] = None
        for _ in range(4):
            try:
                return fn(self._addr, *args)
            except OSError as exc:
                last = exc
                time.sleep(0.005)
        raise last  # type: ignore[misc]

    def _read(self, reg: int) -> int:
        return self._retry(self._bus.read_byte_data, reg)

    def _write(self, reg: int, value: int) -> None:
        self._retry(self._bus.write_byte_data, reg, value)

    def _read_block(self, reg: int, length: int) -> List[int]:
        return list(self._retry(self._bus.read_i2c_block_data, reg, length))

    def chip_id(self, wait: float = 1.5) -> int:
        """Chip ID, retried for up to `wait` s - the chip needs ~650 ms
        after power-up before it answers at all."""
        deadline = time.monotonic() + wait
        while True:
            try:
                return self._read(CHIP_ID_REG)
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def operating_mode(self) -> int:
        return self._read(OPR_MODE_REG) & 0x0F

    def set_mode(self, mode: int) -> None:
        self._write(OPR_MODE_REG, mode)
        time.sleep(0.03)  # datasheet: 7 ms into a fusion mode, 19 ms back to CONFIG

    def begin(self, mode: int, external_crystal: bool, offsets: Optional[Sequence[int]] = None) -> None:
        if self.chip_id() != CHIP_ID:
            raise RuntimeError("unexpected chip ID (not a BNO055 at this address)")
        self.set_mode(MODE_CONFIG)
        self._write(PWR_MODE_REG, 0x00)
        self._write(PAGE_ID_REG, 0x00)
        if offsets is not None:
            self._retry(self._bus.write_i2c_block_data, OFFSETS_REG, list(offsets))
        self._write(SYS_TRIGGER_REG, 0x80 if external_crystal else 0x00)
        time.sleep(0.01)
        self.set_mode(mode)

    def gravity(self) -> Vector:
        return decode_gravity(self._read_block(GRAVITY_REG, 6))

    def calibration_byte(self) -> int:
        return self._read(CALIB_STAT_REG)

    def read_offsets(self) -> List[int]:
        """The sensor's current calibration profile. Only readable in CONFIG
        mode, so this briefly interrupts fusion and puts the mode back."""
        mode = self.operating_mode()
        self.set_mode(MODE_CONFIG)
        try:
            return self._read_block(OFFSETS_REG, OFFSETS_LEN)
        finally:
            self.set_mode(mode)


def open_sensor() -> Bno055:
    """smbus2 import and bus open, kept lazy so importing this module is
    always safe (no smbus2 on a dev PC)."""
    from smbus2 import SMBus  # type: ignore

    return Bno055(SMBus(config.bno055.i2c_bus), config.bno055.i2c_address)


# -- the monitor ----------------------------------------------------------------

class Bno055Monitor:
    def __init__(self) -> None:
        self._sensor: Optional[Bno055] = None
        self._mode = _MODES.get(config.bno055.mode.strip().upper(), MODE_IMU)
        self._mode_name = "NDOF" if self._mode == MODE_NDOF else "IMU"
        self._level = LevelOffsets()
        self._level_mtime: Optional[float] = None
        self._last_level_check = 0.0
        self._saved_profile: Optional[List[int]] = None
        self._last_save_attempt = 0.0
        self._last_failure_log = 0.0

    def init(self) -> bool:
        """Probe and start the sensor. Returns True once it's running; logs
        and returns False if smbus2 is missing, nothing answers or the
        config is invalid - never raises."""
        cfg = config.bno055
        try:
            boat_attitude((0.0, 0.0, 9.8), cfg.bow_axis, cfg.up_axis)  # validates the axis settings
        except ValueError as exc:
            log(9, f"BNO055: bad mounting config: {exc}")
            return False
        if cfg.mode.strip().upper() not in _MODES:
            log(9, f"BNO055: unknown BNO055_MODE {cfg.mode!r} (use IMU or NDOF), using IMU")

        try:
            sensor = open_sensor()
        except Exception as exc:  # noqa: BLE001 - not on a Pi, smbus2 missing, no /dev/i2c-N
            log(9, f"BNO055 not available (I2C open failed): {exc}")
            return False

        try:
            self._saved_profile = load_calibration(cfg.calibration_file)
            sensor.begin(self._mode, cfg.external_crystal, self._saved_profile)
            self._sensor = sensor
            self._level = LevelOffsets.load(cfg.level_file)
            self._level_mtime = self._file_mtime(cfg.level_file)
            log(9, f"BNO055 found on I2C bus {cfg.i2c_bus} at address 0x{cfg.i2c_address:02x}, mode {self._mode_name}, "
                   f"axes bow={cfg.bow_axis} up={cfg.up_axis}, level offset roll {self._level.roll:+.1f} "
                   f"pitch {self._level.pitch:+.1f}"
                   + (", calibration profile restored" if self._saved_profile else ", no saved calibration profile"))
            return True
        except Exception as exc:  # noqa: BLE001 - wrong address/bus, not wired up, I2C not enabled, ...
            log(9, f"BNO055 not found on I2C bus {cfg.i2c_bus} at address 0x{cfg.i2c_address:02x} "
                   f"(check wiring, raspi-config's I2C interface, the ADR jumper, that BNO055_I2C_BUS matches "
                   f"`i2cdetect -y {cfg.i2c_bus}`, and the I2C clock-stretching note in the README): {exc}")
            self._close_bus(sensor)
            self._sensor = None
            return False

    async def run_forever(self) -> None:
        period = 1.0 / max(1.0, config.bno055.poll_hz)
        while True:
            try:
                ok = await asyncio.to_thread(self._read_once)
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive
                self._log_failure(f"BNO055: read failed, will retry: {exc}")
                self.close()  # free the bus; _read_once re-probes next time
                ok = False
            if ok:
                await asyncio.sleep(period)
            else:
                self._publish_invalid()
                await asyncio.sleep(_RETRY_SECONDS)

    async def run_simulated(self) -> None:
        """CARPEDIEM_DO_FAKE: a gentle swell so the Attitude page moves on a
        dev machine with no sensor (use_bno055 is forced off in fake mode)."""
        period = 1.0 / max(1.0, config.bno055.poll_hz)
        t0 = time.monotonic()
        while True:
            t = time.monotonic() - t0
            roll = 2.0 + 5.0 * math.sin(2 * math.pi * t / 6.0) + 1.5 * math.sin(2 * math.pi * t / 2.3)
            pitch = 0.8 + 2.5 * math.sin(2 * math.pi * t / 4.2 + 1.0) + 0.7 * math.sin(2 * math.pi * t / 1.7)
            self._publish(roll, pitch, 3)
            await asyncio.sleep(period)

    def _read_once(self) -> bool:
        if self._sensor is None and not self.init():
            return False
        sensor = self._sensor
        assert sensor is not None
        cfg = config.bno055

        gravity = sensor.gravity()
        attitude = boat_attitude(gravity, cfg.bow_axis, cfg.up_axis)
        if attitude is None:
            self._log_failure("BNO055: no gravity vector yet (still starting up?)")
            return False
        self._maybe_reload_level()
        roll = attitude[0] - self._level.roll
        pitch = attitude[1] - self._level.pitch

        cal_byte = sensor.calibration_byte()
        self._publish(roll, pitch, relevant_calibration(cal_byte, self._mode_name))
        self._maybe_save_calibration(sensor, cal_byte)
        return True

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _file_mtime(path: Path) -> Optional[float]:
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def _maybe_reload_level(self) -> None:
        """Pick up a level file written by `scripts.bno055_tool level` while
        the app is running, without a restart."""
        now = time.monotonic()
        if now - self._last_level_check < _LEVEL_RECHECK_EVERY:
            return
        self._last_level_check = now
        mtime = self._file_mtime(config.bno055.level_file)
        if mtime != self._level_mtime:
            self._level_mtime = mtime
            self._level = LevelOffsets.load(config.bno055.level_file)
            log(9, f"BNO055: level offset now roll {self._level.roll:+.1f} pitch {self._level.pitch:+.1f}")

    def _maybe_save_calibration(self, sensor: Bno055, cal_byte: int) -> None:
        """Once the sensor reports itself fully calibrated, keep a copy of
        the profile so a power cut doesn't throw the calibration away."""
        _sys, gyr, acc, mag = decode_calibration(cal_byte)
        if gyr < 3 or acc < 3 or (self._mode_name == "NDOF" and mag < 3):
            return
        now = time.monotonic()
        if self._saved_profile is not None and now - self._last_save_attempt < _SAVE_CALIBRATION_EVERY:
            return
        self._last_save_attempt = now
        profile = sensor.read_offsets()
        if profile != self._saved_profile:
            _atomic_write_json(config.bno055.calibration_file, profile)
            self._saved_profile = profile
            log(9, f"BNO055: calibration profile saved to {config.bno055.calibration_file}")

    def _log_failure(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_failure_log >= _LOG_FAILURE_EVERY:
            self._last_failure_log = now
            log(9, message)

    @staticmethod
    def _publish(roll: float, pitch: float, calibration: int) -> None:
        display_data.update("Roll", round(roll, 1), source="I")
        display_data.update("Pitch", round(pitch, 1), source="I")
        display_data.update("ImuCalibration", calibration, source="I")
        display_data.update("IMU", 1, source="S")

    @staticmethod
    def _publish_invalid() -> None:
        display_data.update("Roll", None, source="I")
        display_data.update("Pitch", None, source="I")
        display_data.update("ImuCalibration", None, source="I")
        display_data.update("IMU", 0, source="S")

    @staticmethod
    def _close_bus(sensor: Optional[Bno055]) -> None:
        bus = getattr(sensor, "_bus", None)
        if bus is not None and hasattr(bus, "close"):
            try:
                bus.close()
            except Exception:  # noqa: BLE001 - already failing / shutting down
                pass

    def close(self) -> None:
        sensor, self._sensor = self._sensor, None
        self._close_bus(sensor)
