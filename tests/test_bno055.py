"""Run from the repo root:  python -m unittest discover -s tests -v

Covers the BNO055 attitude maths and register decoding (sensors/bno055_sensor.py)
- everything that doesn't need the actual chip.
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.sensors import bno055_sensor
from carpediem.sensors.bno055_sensor import (
    CALIB_STAT_REG, CHIP_ID, CHIP_ID_REG, GRAVITY_REG, MODE_CONFIG, OPR_MODE_REG, Bno055, Bno055Monitor,
    LevelOffsets, boat_attitude, decode_calibration, decode_gravity, parse_axis, relevant_calibration,
)

G = 9.81


class ParseAxisTests(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_axis("+X"), (0, 1))
        self.assertEqual(parse_axis("-y"), (1, -1))
        self.assertEqual(parse_axis(" Z "), (2, 1))

    def test_rejects_garbage(self):
        for bad in ("", "+", "W", "+XY", "1"):
            with self.assertRaises(ValueError, msg=bad):
                parse_axis(bad)


class BoatAttitudeTests(unittest.TestCase):
    """Default mounting: sensor X to the bow, Z up, so Y points to port."""

    def att(self, gravity, bow="+X", up="+Z"):
        return boat_attitude(gravity, bow, up)

    def assertAtt(self, got, roll, pitch):
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got[0], roll, places=6)
        self.assertAlmostEqual(got[1], pitch, places=6)

    def test_level(self):
        self.assertAtt(self.att((0, 0, G)), 0, 0)

    def test_starboard_down_is_positive_roll(self):
        # Starboard side down = port side (+Y) up = "up" tips toward +Y.
        a = math.radians(20)
        self.assertAtt(self.att((0, G * math.sin(a), G * math.cos(a))), 20, 0)

    def test_port_down_is_negative_roll(self):
        a = math.radians(20)
        self.assertAtt(self.att((0, -G * math.sin(a), G * math.cos(a))), -20, 0)

    def test_bow_up_is_positive_pitch(self):
        # Bow up = the +X axis points upward, so the accelerometer reads +X.
        a = math.radians(10)
        self.assertAtt(self.att((G * math.sin(a), 0, G * math.cos(a))), 0, 10)

    def test_bow_down_is_negative_pitch(self):
        a = math.radians(10)
        self.assertAtt(self.att((-G * math.sin(a), 0, G * math.cos(a))), 0, -10)

    def test_combined_heel_and_trim(self):
        # 10 deg bow up, then 15 deg starboard down, as a gravity vector.
        pitch, roll = math.radians(10), math.radians(15)
        gx = G * math.sin(pitch)
        gy = G * math.cos(pitch) * math.sin(roll)
        gz = G * math.cos(pitch) * math.cos(roll)
        self.assertAtt(self.att((gx, gy, gz)), 15, 10)

    def test_board_rotated_90_degrees(self):
        # Board turned so its +Y points to the bow, Z still up: port = up x bow
        # = Z x Y = -X. Starboard down tips "up" toward port (-X).
        a = math.radians(12)
        self.assertAtt(self.att((-G * math.sin(a), 0, G * math.cos(a)), bow="+Y"), 12, 0)

    def test_board_on_a_bulkhead(self):
        # Mounted vertically: sensor Z to the bow, sensor +Y up; port = Y x Z = +X.
        a = math.radians(8)
        # Bow up 8 deg: the +Z (bow) axis tips upward -> reads +Z component.
        self.assertAtt(self.att((0, G * math.cos(a), G * math.sin(a)), bow="+Z", up="+Y"), 0, 8)

    def test_upside_down_board(self):
        # Z down (up = -Z): level reading is -G on Z.
        self.assertAtt(self.att((0, 0, -G), up="-Z"), 0, 0)

    def test_rejects_same_axis(self):
        with self.assertRaises(ValueError):
            boat_attitude((0, 0, G), "+X", "-X")

    def test_no_reading_yet(self):
        self.assertIsNone(self.att((0, 0, 0)))


class DecodeTests(unittest.TestCase):
    def test_gravity_decoding_signed_little_endian(self):
        # x = +981 (0x03D5), y = -50 (0xFFCE), z = 0
        raw = [0xD5, 0x03, 0xCE, 0xFF, 0x00, 0x00]
        self.assertEqual(decode_gravity(raw), (9.81, -0.5, 0.0))

    def test_calibration_fields(self):
        self.assertEqual(decode_calibration(0b11_10_01_00), (3, 2, 1, 0))

    def test_relevant_calibration_ignores_mag_in_imu_mode(self):
        byte = 0b11_11_11_00  # sys/gyr/acc fully calibrated, mag 0
        self.assertEqual(relevant_calibration(byte, "IMU"), 3)
        self.assertEqual(relevant_calibration(byte, "NDOF"), 0)
        self.assertEqual(relevant_calibration(0b11_01_11_00, "IMU"), 1)  # gyro still at 1


class FakeBus:
    """Just enough of smbus2.SMBus: a register file, optionally failing the first N reads."""

    def __init__(self, regs=None, fail_first=0):
        self.regs = dict(regs or {})
        self.fail_first = fail_first
        self.writes = []

    def _maybe_fail(self):
        if self.fail_first > 0:
            self.fail_first -= 1
            raise OSError(5, "Input/output error")

    def read_byte_data(self, addr, reg):
        self._maybe_fail()
        return self.regs.get(reg, 0)

    def write_byte_data(self, addr, reg, value):
        self.writes.append((reg, value))
        self.regs[reg] = value

    def read_i2c_block_data(self, addr, reg, length):
        self._maybe_fail()
        return [self.regs.get(reg + i, 0) for i in range(length)]

    def write_i2c_block_data(self, addr, reg, data):
        for i, b in enumerate(data):
            self.regs[reg + i] = b


class DriverTests(unittest.TestCase):
    def test_retries_transient_io_errors(self):
        bus = FakeBus({CHIP_ID_REG: CHIP_ID}, fail_first=3)
        self.assertEqual(Bno055(bus, 0x28).chip_id(), CHIP_ID)

    def test_gives_up_after_persistent_errors(self):
        bus = FakeBus({CHIP_ID_REG: CHIP_ID}, fail_first=10_000)
        with self.assertRaises(OSError):
            Bno055(bus, 0x28).chip_id(wait=0.0)

    def test_gravity_read(self):
        bus = FakeBus({GRAVITY_REG: 0xD5, GRAVITY_REG + 1: 0x03, GRAVITY_REG + 4: 0x2C, GRAVITY_REG + 5: 0x01})
        self.assertEqual(Bno055(bus, 0x28).gravity(), (9.81, 0.0, 3.0))

    def test_begin_rejects_wrong_chip(self):
        with self.assertRaises(RuntimeError):
            Bno055(FakeBus({CHIP_ID_REG: 0x55}), 0x28).begin(0x08, True)

    def test_begin_ends_in_requested_mode_with_crystal(self):
        bus = FakeBus({CHIP_ID_REG: CHIP_ID})
        Bno055(bus, 0x28).begin(0x08, True, offsets=list(range(22)))
        mode_writes = [v for reg, v in bus.writes if reg == OPR_MODE_REG]
        self.assertEqual(mode_writes, [MODE_CONFIG, 0x08])  # config first, then the fusion mode
        self.assertIn((0x3F, 0x80), bus.writes)             # external crystal selected
        self.assertEqual([bus.regs[0x55 + i] for i in range(22)], list(range(22)))  # profile restored

    def test_read_offsets_restores_mode(self):
        bus = FakeBus({CHIP_ID_REG: CHIP_ID, OPR_MODE_REG: 0x08})
        for i in range(22):
            bus.regs[0x55 + i] = i + 1
        profile = Bno055(bus, 0x28).read_offsets()
        self.assertEqual(profile, [i + 1 for i in range(22)])
        self.assertEqual([v for reg, v in bus.writes if reg == OPR_MODE_REG], [MODE_CONFIG, 0x08])


def _gravity_regs(gx, gy, gz):
    regs = {}
    for i, v in enumerate((gx, gy, gz)):
        raw = int(round(v * 100)) & 0xFFFF
        regs[GRAVITY_REG + 2 * i] = raw & 0xFF
        regs[GRAVITY_REG + 2 * i + 1] = raw >> 8
    return regs


class MonitorTests(unittest.TestCase):
    """Bno055Monitor end to end: fake I2C bus -> display_data."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        bno = config.bno055
        saved = (bno.level_file, bno.calibration_file, bno.bow_axis, bno.up_axis, bno.mode)
        bno.level_file, bno.calibration_file = tmp / "level.json", tmp / "cal.json"
        bno.bow_axis, bno.up_axis, bno.mode = "+X", "+Z", "IMU"
        self.addCleanup(lambda: (setattr(bno, "level_file", saved[0]), setattr(bno, "calibration_file", saved[1]),
                                 setattr(bno, "bow_axis", saved[2]), setattr(bno, "up_axis", saved[3]),
                                 setattr(bno, "mode", saved[4])))

    def monitor_with(self, gx, gy, gz, cal_byte=0b00_11_11_00):
        regs = {CHIP_ID_REG: CHIP_ID, OPR_MODE_REG: 0x08, CALIB_STAT_REG: cal_byte, **_gravity_regs(gx, gy, gz)}
        bus = FakeBus(regs)
        patcher = mock.patch.object(bno055_sensor, "open_sensor", lambda: Bno055(bus, 0x28))
        patcher.start()
        self.addCleanup(patcher.stop)
        return Bno055Monitor(), bus

    def test_publishes_roll_pitch_and_calibration(self):
        a = math.radians(10)
        monitor, _bus = self.monitor_with(0.0, G * math.sin(a), G * math.cos(a))
        self.assertTrue(monitor._read_once())
        self.assertEqual(display_data.get("Roll"), 10.0)
        self.assertEqual(display_data.get("Pitch"), 0.0)
        self.assertEqual(display_data.get("ImuCalibration"), 3)
        self.assertEqual(display_data.get("IMU"), 1)

    def test_level_offset_is_subtracted(self):
        LevelOffsets(2.0, -1.0).save(config.bno055.level_file)
        a = math.radians(10)
        monitor, _bus = self.monitor_with(0.0, G * math.sin(a), G * math.cos(a))
        self.assertTrue(monitor._read_once())
        self.assertEqual(display_data.get("Roll"), 8.0)
        self.assertEqual(display_data.get("Pitch"), 1.0)

    def test_no_gravity_blanks_the_fields_rather_than_keeping_stale_values(self):
        monitor, _bus = self.monitor_with(0.0, 0.0, G)
        self.assertTrue(monitor._read_once())
        self.assertEqual(display_data.get("Roll"), 0.0)
        for reg in range(GRAVITY_REG, GRAVITY_REG + 6):
            monitor._sensor._bus.regs[reg] = 0  # sensor reset / not fused: all-zero gravity
        self.assertFalse(monitor._read_once())
        Bno055Monitor._publish_invalid()
        self.assertIsNone(display_data.get("Roll"))
        self.assertIsNone(display_data.get("Pitch"))
        self.assertEqual(display_data.get("IMU"), 0)

    def test_calibration_profile_saved_once_fully_calibrated_and_restored_at_start(self):
        monitor, bus = self.monitor_with(0.0, 0.0, G, cal_byte=0b11_11_11_00)
        for i in range(22):
            bus.regs[0x55 + i] = 100 + i
        self.assertTrue(monitor._read_once())
        saved = json.loads(config.bno055.calibration_file.read_text())
        self.assertEqual(saved, [100 + i for i in range(22)])

        # A fresh start restores that profile into the chip before entering fusion mode.
        monitor2, bus2 = self.monitor_with(0.0, 0.0, G)
        self.assertTrue(monitor2.init())
        self.assertEqual([bus2.regs[0x55 + i] for i in range(22)], saved)

    def test_not_calibrated_yet_saves_nothing(self):
        monitor, _bus = self.monitor_with(0.0, 0.0, G, cal_byte=0b11_01_11_00)  # gyro still at 1
        self.assertTrue(monitor._read_once())
        self.assertFalse(config.bno055.calibration_file.exists())

    def test_bad_axis_config_fails_init_without_raising(self):
        config.bno055.up_axis = "+X"  # same axis as the bow
        monitor, _bus = self.monitor_with(0.0, 0.0, G)
        self.assertFalse(monitor.init())

    def test_unreadable_level_file_is_ignored(self):
        config.bno055.level_file.write_text("{not json")
        self.assertEqual(LevelOffsets.load(config.bno055.level_file), LevelOffsets())


if __name__ == "__main__":
    unittest.main()
