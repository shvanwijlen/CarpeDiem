"""6-bit AIS payload decoding. Port of getBits/signExtend/decodeSixbitText/
decodeType5 and the type 1/2/3/18/19/24 handling from parseAIVDM() in
ais_nearby_vessels_7.ino.

Field bit offsets match ITU-R M.1371 (the AIS standard) and are unchanged
from the original - ported as pure functions here since they're easy to
verify by inspection and the original sketch's comments note they're
already working well ("Runs well now").

Deliberately kept as a faithful, hand-rolled port rather than switching to
a full AIS library (e.g. pyais): the original only decodes exactly the
fields this app uses (position + name), is well-understood, and a
from-scratch third-party dependency swap isn't something I can verify
against your real em-trak stream from here. If you later want the fuller
message-type coverage a library like pyais provides (IMO, callsign, ship
dimensions, more message types), that's a drop-in upgrade for this one
file - nothing else in the app would need to change.

Same intentional scope limits as the original:
    - only message types 1/2/3/18/19 (position) and 5/24A (name)
    - only fragment counts 1 and 2 (nothing uses more)
    - no NMEA checksum verification
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def get_bits(payload: str, start: int, length: int) -> int:
    """Extract `length` bits starting at bit offset `start` from an
    armoured AIS payload (6 bits per printable character, offset by the
    AIS 6-bit ASCII scheme: values 40-63 need -8 to align)."""
    result = 0
    payload_len = len(payload)
    for i in range(length):
        bit_pos = start + i
        char_index = bit_pos // 6
        bit_in_char = 5 - (bit_pos % 6)
        if char_index >= payload_len:
            result <<= 1  # pad with 0 past the end of the payload
            continue
        v = ord(payload[char_index]) - 48
        if v > 40:
            v -= 8
        bit = (v >> bit_in_char) & 1
        result = (result << 1) | bit
    return result


def sign_extend(value: int, bits: int) -> int:
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def decode_sixbit_text(payload: str, start_bit: int, num_chars: int) -> str:
    """Decode a run of 6-bit AIS text characters (names/callsigns), trimming
    trailing '@' padding and spaces."""
    chars = []
    for i in range(num_chars):
        v = get_bits(payload, start_bit + i * 6, 6)
        c = v + 64 if v < 32 else v
        chars.append(chr(c))
    text = "".join(chars).rstrip("@ ")
    return text


@dataclass
class PositionReport:
    mmsi: int
    lat: float
    lon: float
    sog: float  # knots
    cog: float  # degrees


def decode_position_report(payload: str) -> Optional[PositionReport]:
    """Types 1/2/3 (Class A) and 18/19 (Class B). Returns None for any
    other message type, or if lat/lon come back as AIS's "not available"
    sentinel (91 / 181)."""
    if len(payload) < 20:
        return None  # too short to be a position report

    msg_type = get_bits(payload, 0, 6)
    mmsi = get_bits(payload, 8, 30)

    if msg_type in (1, 2, 3):
        sog = get_bits(payload, 50, 10) / 10.0
        lon = sign_extend(get_bits(payload, 61, 28), 28) / 600000.0
        lat = sign_extend(get_bits(payload, 89, 27), 27) / 600000.0
        cog = get_bits(payload, 116, 12) / 10.0
    elif msg_type in (18, 19):
        sog = get_bits(payload, 46, 10) / 10.0
        lon = sign_extend(get_bits(payload, 57, 28), 28) / 600000.0
        lat = sign_extend(get_bits(payload, 85, 27), 27) / 600000.0
        cog = get_bits(payload, 112, 12) / 10.0
    else:
        return None

    if lat > 90.0 or lat < -90.0 or lon > 180.0 or lon < -180.0:
        return None  # "not available" sentinel

    return PositionReport(mmsi=mmsi, lat=lat, lon=lon, sog=sog, cog=cog)


def decode_type24a_name(payload: str) -> Optional[tuple[int, str]]:
    """Type 24 part A: vessel name, single-fragment. Returns (mmsi, name)
    or None if this isn't part A (part B - callsign/dimensions/type - is
    not decoded, same as the original)."""
    part_no = get_bits(payload, 38, 2)
    if part_no != 0:
        return None
    mmsi = get_bits(payload, 8, 30)
    name = decode_sixbit_text(payload, 40, 20)
    return mmsi, name


def decode_type5_name(payload: str) -> Optional[tuple[int, str]]:
    """Type 5 (static/voyage data), reassembled from its 2 fragments by the
    caller (see FragmentReassembler). Only the name field (bits 112-231) is
    decoded - IMO/callsign/ship type/dimensions are skipped, same as the
    original."""
    if get_bits(payload, 0, 6) != 5:
        return None
    mmsi = get_bits(payload, 8, 30)
    name = decode_sixbit_text(payload, 112, 20)
    return mmsi, name


def decode_aivdo_message_type(payload: str) -> Optional[int]:
    """Own-ship echo (!AIVDO): just need the message type for the
    transmit-count tally, same as the original's parseAIVDO()."""
    if len(payload) < 6:
        return None
    return get_bits(payload, 0, 6)


class FragmentReassembler:
    """Port of the pendingPayload/pendingSeq/pendingChannel buffering in
    the original: type 5 always arrives as exactly 2 fragments, so this
    holds fragment 1 until fragment 2 with a matching sequence ID and
    channel arrives."""

    def __init__(self) -> None:
        self._pending_payload: Optional[str] = None
        self._pending_seq: Optional[int] = None
        self._pending_channel: Optional[str] = None

    def add_fragment(self, total_fragments: int, frag_num: int, seq_id: int,
                      channel: str, payload: str) -> Optional[str]:
        """Feed one !AIVDM fragment. Returns the combined payload once both
        fragments of a 2-part message have arrived, else None."""
        if frag_num == 1:
            self._pending_payload = payload
            self._pending_seq = seq_id
            self._pending_channel = channel
            return None
        if frag_num == 2 and self._pending_seq == seq_id and self._pending_channel == channel:
            combined = (self._pending_payload or "") + payload
            self._pending_seq = None  # consumed - don't let a stray later fragment 2 reuse it
            return combined
        return None
