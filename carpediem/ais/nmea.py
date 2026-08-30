"""Own-ship GPS ($..RMC / $..GGA) and AIS health-alarm ($AIALR) parsing.

Port of parseGGA/parseRMC/parseALR/nmeaToDecimal from
ais_nearby_vessels_7.ino. splitFieldsKeepEmpty() from the original has no
Python equivalent needed: str.split(",") already preserves empty fields
(unlike C's strtok, which was the whole reason that helper existed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from carpediem.logging_setup import log


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


def parse_alr(line: str) -> Optional[str]:
    """Returns the alarm description if condition is active ('A'), else None.
    Format: $AIALR,time,alarmID,condition,ack,desc*checksum"""
    fields = line.split(",")
    if len(fields) < 6:
        return None
    if fields[3] == "A":
        desc = fields[5].split("*", 1)[0]  # strip trailing NMEA checksum
        log(9, f"*** AIS ALARM ACTIVE: {desc}")
        return desc
    return None
