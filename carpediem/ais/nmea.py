"""Own-ship GPS ($..RMC / $..GGA) and AIS health-alarm ($AIALR) parsing.

Port of parseGGA/parseRMC/parseALR/nmeaToDecimal from
ais_nearby_vessels_7.ino. splitFieldsKeepEmpty() from the original has no
Python equivalent needed: str.split(",") already preserves empty fields
(unlike C's strtok, which was the whole reason that helper existed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


def nmea_to_decimal(raw: float, hemisphere: str) -> float:
    """ddmm.mmmm / dddmm.mmmm -> decimal degrees."""
    degrees = int(raw / 100)
    minutes = raw - degrees * 100
    dec = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        dec = -dec
    return dec


@dataclass
class OwnShipFix:
    lat: Optional[float] = None
    lon: Optional[float] = None
    cog: Optional[float] = None  # course over ground, degrees; None while not moving fast enough to be meaningful
    sog_knots: Optional[float] = None  # speed over ground

    @property
    def has_fix(self) -> bool:
        return self.lat is not None and self.lon is not None


def parse_gga(line: str, fix: OwnShipFix) -> None:
    fields = line.split(",")
    if len(fields) < 6:
        return
    if fields[2] and fields[4]:
        fix.lat = nmea_to_decimal(float(fields[2]), fields[3][:1])
        fix.lon = nmea_to_decimal(float(fields[4]), fields[5][:1])


def parse_rmc(line: str, fix: OwnShipFix) -> None:
    fields = line.split(",")
    if len(fields) < 7:
        return
    if fields[2] == "A" and fields[3] and fields[5]:
        fix.lat = nmea_to_decimal(float(fields[3]), fields[4][:1])
        fix.lon = nmea_to_decimal(float(fields[5]), fields[6][:1])
    if len(fields) > 7 and fields[7]:
        fix.sog_knots = float(fields[7])  # not read by the original AIS sketch, added for parity
        # with CarpeDiem's original "Speed" display field (was TinyGPSPlus's gps.speed.kmph())
    if len(fields) > 8 and fields[8]:
        fix.cog = float(fields[8])


def parse_alr(line: str) -> Optional[Tuple[str, str, str]]:
    """Format: $AIALR,time,alarmID,condition,ack,desc*checksum
    Returns (alarm_id, condition, desc) - condition is "A" (active) or "V"
    (not active) - or None if malformed. Deliberately stateless (doesn't
    decide overall antenna-ok/not-ok, doesn't log) - the em-trak reports
    each alarm ID periodically regardless of state, and there are several
    IDs, so deciding "is anything currently wrong" needs to track the last
    condition per ID across calls - see emtrak_reader.py's _handle_alr."""
    fields = line.split(",")
    if len(fields) < 6:
        return None
    alarm_id = fields[2]
    condition = fields[3]
    desc = fields[5].split("*", 1)[0]  # strip trailing NMEA checksum
    return alarm_id, condition, desc
