"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

from __future__ import annotations

"""UBX (u-blox proprietary) protocol helpers — read-only subset.

Phase 2 of the GNSS observability work uses these helpers to poll
two messages from the receiver:

* ``UBX-MON-HW`` (0x0A 0x09) — antenna supervisor status (OK / SHORT /
  OPEN), antenna power, RF jamming indicator, and noise/AGC counters.
  This is the only place the antenna fault state is exposed; NMEA-0183
  has no equivalent sentence.
* ``UBX-NAV-TIMELS`` (0x01 0x26) — authoritative GPS-UTC leap-second
  offset plus the next scheduled leap event (insert/delete and the
  GPS week/day-of-week it lands on).

We deliberately keep this module narrow: only the two readers above
plus the framing primitives needed to send a poll request.  Phase 3
will add ``UBX-CFG-GNSS`` writers for constellation profile
management; this module is the natural home for that code when it
lands.

Frame layout (see u-blox 8 receiver protocol manual §32):

    0xB5 0x62 | class | id | length (LE u16) | payload | CK_A | CK_B

The two checksum bytes are an 8-bit Fletcher computed over
``class || id || length || payload`` (the sync chars are excluded).
"""

import struct
from typing import Any, Dict, Optional, Tuple

# UBX message classes / IDs we care about.
UBX_SYNC_1 = 0xB5
UBX_SYNC_2 = 0x62

CLASS_NAV = 0x01
CLASS_MON = 0x0A

ID_NAV_TIMELS = 0x26
ID_MON_HW = 0x09

# UBX-MON-HW antenna-status enum (aStatus byte at offset 20 in the
# 60-byte payload).  Mapped to the strings the dashboard renders.
_ANT_STATUS = {
    0: "init",
    1: "unknown",
    2: "ok",
    3: "short",
    4: "open",
}

# UBX-MON-HW antenna-power enum (aPower byte at offset 21).
_ANT_POWER = {
    0: "off",
    1: "on",
    2: "unknown",
}

# UBX-MON-HW jammingState — bits 2..3 of the flags byte at offset 22.
_JAMMING_STATE = {
    0: "unknown",
    1: "ok",
    2: "warning",
    3: "critical",
}

# UBX-NAV-TIMELS srcOfCurrLs byte (offset 8) — provenance of the
# currently-applied leap-second value.  Same enum is used for
# srcOfLsChange (offset 10) but with the upper values reserved.
_LS_SOURCE = {
    0: "default",
    1: "gps_glonass_diff",
    2: "gps",
    3: "sbas",
    4: "beidou",
    5: "galileo",
    6: "aided",
    7: "configured",
    8: "navic",
    255: "unknown",
}


def _checksum(payload: bytes) -> Tuple[int, int]:
    """Compute the UBX 8-bit Fletcher checksum over ``payload``.

    ``payload`` should be ``class || id || length || body`` — i.e.
    everything between the sync chars and the checksum bytes.  Returns
    ``(CK_A, CK_B)`` as integers in ``[0, 255]``.
    """
    ck_a = 0
    ck_b = 0
    for byte in payload:
        ck_a = (ck_a + byte) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def build_poll(class_id: int, msg_id: int, body: bytes = b"") -> bytes:
    """Frame a UBX message ready to write to the serial port.

    A "poll request" is just a normal UBX frame with an empty body —
    the receiver replies with the same class/id and the populated
    payload.  ``body`` is exposed so the same helper can serve the
    Phase 3 ``UBX-CFG-*`` writers.
    """
    length = len(body)
    header = struct.pack("<BBH", class_id, msg_id, length)
    ck_a, ck_b = _checksum(header + body)
    return bytes([UBX_SYNC_1, UBX_SYNC_2]) + header + body + bytes([ck_a, ck_b])


def parse_mon_hw(payload: bytes) -> Dict[str, Any]:
    """Decode the fields of ``UBX-MON-HW`` we surface on the dashboard.

    Layout (60 bytes total — see protocol manual):

      offset  size  field
      ------  ----  ---------------------------------------------
        0     U4    pinSel
        4     U4    pinBank
        8     U4    pinDir
       12     U4    pinVal
       16     U2    noisePerMS
       18     U2    agcCnt
       20     U1    aStatus
       21     U1    aPower
       22     U1    flags        (bit 0=rtcCalib, 1=safeBoot,
                                   2..3=jammingState, 4=xtalAbsent)
       23     U1    reserved1
       24..   …     pinIrq, pullH, pullL (unused here)

    Older firmware reports a 56-byte payload instead; we tolerate
    either by only reading what's present.  Returns ``{}`` if the
    payload is too short to contain ``aStatus``.
    """
    if len(payload) < 23:
        return {}

    noise = struct.unpack_from("<H", payload, 16)[0]
    agc = struct.unpack_from("<H", payload, 18)[0]
    a_status = payload[20]
    a_power = payload[21]
    flags = payload[22]
    jamming_bits = (flags >> 2) & 0x03

    return {
        "antenna_status": _ANT_STATUS.get(a_status, "unknown"),
        "antenna_power": _ANT_POWER.get(a_power, "unknown"),
        "jamming_state": _JAMMING_STATE.get(jamming_bits, "unknown"),
        "noise_level": int(noise),
        # AGC is a 16-bit count; receivers usually scale 8192 as the
        # nominal mid-point.  We expose the raw value and let the UI
        # render it.
        "agc_count": int(agc),
        "rtc_calibrated": bool(flags & 0x01),
        "safe_boot": bool(flags & 0x02),
        "xtal_absent": bool(flags & 0x10),
    }


def parse_nav_timels(payload: bytes) -> Dict[str, Any]:
    """Decode the fields of ``UBX-NAV-TIMELS`` we surface on the
    dashboard.

    Layout (24 bytes):

      offset  size  field
      ------  ----  ---------------------------------------------
        0     U1    version
        1..3  reserved
        4     U4    iTOW
        8     U1    srcOfCurrLs
        9     I1    currLs                (current GPS-UTC offset, s)
       10     U1    srcOfLsChange
       11     I1    lsChange              (signed, +1/-1/0)
       12     I4    timeToLsEvent         (signed seconds)
       16     U2    dateOfLsGpsWn         (week the event lands in)
       18     U2    dateOfLsGpsDn         (1=Sun..7=Sat within wn)
       20..22  reserved
       23     U1    valid                 (bit 0=currLsValid,
                                           bit 1=timeToLsEventValid)

    Returns ``{}`` for short or zero-version payloads (some firmwares
    emit the message before they've sourced a value).
    """
    if len(payload) < 24:
        return {}

    src_curr = payload[8]
    curr_ls = struct.unpack_from("<b", payload, 9)[0]
    src_change = payload[10]
    ls_change = struct.unpack_from("<b", payload, 11)[0]
    time_to_event = struct.unpack_from("<i", payload, 12)[0]
    date_wn = struct.unpack_from("<H", payload, 16)[0]
    date_dn = struct.unpack_from("<H", payload, 18)[0]
    valid = payload[23]

    curr_valid = bool(valid & 0x01)
    event_valid = bool(valid & 0x02)

    return {
        "leap_seconds": int(curr_ls) if curr_valid else None,
        "leap_source": _LS_SOURCE.get(src_curr, "unknown"),
        "leap_pending": bool(event_valid and ls_change != 0),
        "leap_change": int(ls_change),
        "leap_change_source": _LS_SOURCE.get(src_change, "unknown"),
        "leap_seconds_to_event": int(time_to_event) if event_valid else None,
        "leap_event_gps_week": int(date_wn) if event_valid else None,
        "leap_event_gps_dow": int(date_dn) if event_valid else None,
    }


def find_frame(buf: bytearray) -> Optional[Tuple[int, int, int, bytes]]:
    """Look for a complete UBX frame at the start of ``buf``.

    The buffer is scanned for the ``0xB5 0x62`` sync pair.  If a
    well-formed frame is found, its bytes are removed from ``buf`` and
    we return ``(start_offset, class_id, msg_id, payload)``.

    Returns ``None`` when no complete frame is present yet — caller
    should keep accumulating bytes and retry.  On checksum failure the
    frame is consumed and dropped (the caller learns nothing about it,
    which matches u-blox's own approach: bad frames are noise).

    The ``start_offset`` returned tells the caller how many leading
    bytes were skipped before the frame began (typically 0; non-zero
    means stray bytes that should be re-checked for NMEA framing by
    the caller).
    """
    # Find the sync pair.
    for start in range(len(buf) - 1):
        if buf[start] == UBX_SYNC_1 and buf[start + 1] == UBX_SYNC_2:
            break
    else:
        return None

    # Need at least sync + class + id + length = 6 bytes before we
    # can read the payload size.
    if len(buf) - start < 6:
        return None

    class_id = buf[start + 2]
    msg_id = buf[start + 3]
    length = buf[start + 4] | (buf[start + 5] << 8)

    # Sanity-clamp the length so a corrupt header can't make us wait
    # forever (u-blox max payload is well under 1 KiB for the messages
    # we poll).
    if length > 4096:
        # Drop the bogus sync and let the caller retry.
        del buf[: start + 1]
        return None

    total = 6 + length + 2  # header + payload + checksum
    if len(buf) - start < total:
        return None

    payload = bytes(buf[start + 6 : start + 6 + length])
    ck_a_recv = buf[start + 6 + length]
    ck_b_recv = buf[start + 6 + length + 1]

    ck_a, ck_b = _checksum(bytes(buf[start + 2 : start + 6 + length]))
    if (ck_a, ck_b) != (ck_a_recv, ck_b_recv):
        # Drop just the leading sync byte and let the caller retry —
        # otherwise we'd discard real NMEA traffic that follows.
        del buf[: start + 1]
        return None

    leading = start
    del buf[: start + total]
    return leading, class_id, msg_id, payload


# Convenience constants for callers that only need the polls.
POLL_MON_HW = build_poll(CLASS_MON, ID_MON_HW)
POLL_NAV_TIMELS = build_poll(CLASS_NAV, ID_NAV_TIMELS)
