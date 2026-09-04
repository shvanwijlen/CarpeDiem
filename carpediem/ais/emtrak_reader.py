"""em-trak TCP stream reader: connects, reads NMEA lines, dispatches by
sentence type. Port of connectAIS()/the loop() read block/
processSentence() from ais_nearby_vessels_7.ino, merged with what used to
be CarpeDiem's own connectToEmtrak() (the two sketches were talking to the
same TCP stream for overlapping purposes - this is now one reader instead
of two separate connections to the same em-trak unit).

Simplification: asyncio.StreamReader.readline() replaces the hand-rolled
lineBuf/lineLen/LINE_BUF_LEN char-by-char buffering - Python's stream
reader already does line buffering correctly and has no fixed-size limit
to overrun.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from carpediem.config import config
from carpediem.display_data import display_data
from carpediem.logging_setup import log
from carpediem.ais import nmea
from carpediem.ais.decoder import (
    FragmentReassembler,
    decode_aivdo_message_type,
    decode_position_report,
    decode_type5_name,
    decode_type24a_name,
    get_bits,
)
from carpediem.ais.vessel_tracker import VesselTracker

RECONNECT_INTERVAL_SECONDS = 5
STALE_DATA_WARNING_SECONDS = 10


class EmtrakReader:
    def __init__(self, tracker: VesselTracker) -> None:
        self._tracker = tracker
        self.own_fix = nmea.OwnShipFix()
        self._fragments = FragmentReassembler()
        self._last_byte_time: Optional[float] = None

        # Own-ship transmission counters (from !AIVDO echoes) - a live tally
        # since this process started, not a lifetime device statistic (the
        # em-trak doesn't expose that over NMEA/TCP).
        self.own_reports_type18 = 0
        self.own_reports_type19 = 0
        self.own_reports_other = 0

    def own_position(self) -> Optional[tuple[float, float]]:
        if self.own_fix.has_fix:
            return self.own_fix.lat, self.own_fix.lon
        return None

    async def run_forever(self) -> None:
        while True:
            try:
                await self._connect_and_read()
            except (ConnectionError, OSError) as exc:
                log(9, f"em-trak: connection error: {exc}")
            display_data.update("AIS", 0, source="S")
            await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)

    async def _connect_and_read(self) -> None:
        log(9, f"em-trak: connecting to {config.emtrak.host}:{config.emtrak.port} ...")
        reader, writer = await asyncio.open_connection(config.emtrak.host, config.emtrak.port)
        log(9, "em-trak: connected")
        display_data.update("AIS", 1, source="S")
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break  # connection closed by the far end
                self._last_byte_time = time.monotonic()
                line = raw.decode("ascii", errors="replace").strip()
                if line:
                    self._process_sentence(line)
        finally:
            writer.close()

    def data_is_stale(self) -> bool:
        if self._last_byte_time is None:
            return False
        return (time.monotonic() - self._last_byte_time) > STALE_DATA_WARNING_SECONDS

    # -- sentence dispatch, port of processSentence() -----------------
    def _process_sentence(self, line: str) -> None:
        if line.startswith("!AIVDM"):
            self._parse_aivdm(line)
        elif line.startswith("!AIVDO"):
            self._parse_aivdo(line)
        elif line.startswith("$AIALR"):
            log(9, f"em-trak: {line}")
            nmea.parse_alr(line)
        elif "RMC" in line:
            nmea.parse_rmc(line, self.own_fix)
            self._publish_own_position()
        elif "GGA" in line:
            nmea.parse_gga(line, self.own_fix)
            self._publish_own_position()

    def _publish_own_position(self) -> None:
        if self.own_fix.lat is not None:
            display_data.update("Lat", self.own_fix.lat, source="G")
        if self.own_fix.lon is not None:
            display_data.update("Lng", self.own_fix.lon, source="G")
        if self.own_fix.sog_knots is not None:
            display_data.update("Speed", self.own_fix.sog_knots * 1.852, source="G")  # knots -> km/h
        if self.own_fix.cog is not None:
            display_data.update("Course", self.own_fix.cog, source="G")

    def _parse_aivdo(self, line: str) -> None:
        fields = line.split(",")
        if len(fields) < 6:
            return
        try:
            total_fragments = int(fields[1])
        except ValueError:
            return
        if total_fragments != 1:
            return  # own-ship position reports are always single-fragment
        msg_type = decode_aivdo_message_type(fields[5])
        if msg_type == 18:
            self.own_reports_type18 += 1
        elif msg_type == 19:
            self.own_reports_type19 += 1
        elif msg_type is not None:
            self.own_reports_other += 1

    def _parse_aivdm(self, line: str) -> None:
        fields = line.split(",")
        if len(fields) < 6:
            return  # malformed

        try:
            total_fragments = int(fields[1])
            frag_num = int(fields[2])
            seq_id = int(fields[3]) if fields[3] else -1
        except ValueError:
            return
        channel = fields[4][:1]
        payload = fields[5]

        if total_fragments == 2:
            combined = self._fragments.add_fragment(total_fragments, frag_num, seq_id, channel, payload)
            if combined is not None:
                result = decode_type5_name(combined)
                if result is not None:
                    mmsi, name = result
                    self._tracker.set_name(mmsi, name)
            return

        if total_fragments != 1:
            return  # only 1- and 2-fragment messages are handled

        if len(payload) < 20:
            return  # too short to be a position report

        # decode_type24a_name assumes type 24, so check the message type first
        msg_type = get_bits(payload, 0, 6)
        if msg_type == 24:
            result = decode_type24a_name(payload)
            if result is not None:
                mmsi, name = result
                self._tracker.set_name(mmsi, name)
            return

        report = decode_position_report(payload)
        if report is not None:
            self._tracker.update_position(report.mmsi, report.lat, report.lon, report.sog, report.cog)
