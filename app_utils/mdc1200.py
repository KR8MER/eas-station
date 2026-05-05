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

"""MDC1200 selective-calling encoder.

MDC1200 is Motorola's 1200-baud FFSK signalling protocol for two-way LMR
radios.  It is widely used for PTT-ID (transmitter unit identification on
each push-to-talk), emergency alarms, and a handful of supervisory
operations.  This module produces the audio waveform a station can transmit
so that a receiving Motorola (or compatible) radio displays the originating
unit ID and any associated event (PTT-ID start / stop, emergency, etc.).

Frame format — single packet (PTT-ID, Emergency, Request-to-Talk, Remote
Monitor, …):

    [3 byte preamble = 0x00 0x00 0x00]
    [5 byte frame sync = 0x07 0x09 0x2A 0x44 0x6F]
    [14 byte payload]
    [4 byte post-preamble = 0x00 0x00 0x00 0x00]   -> 26 bytes total

The trailing 4-byte post-preamble continues the mark tone for one extra
symbol time (~26.67 ms) so a receiving Motorola subscriber sees a clean
transition back to idle after the CRC passes — without it, some
CPS-programmed radios refuse to commit the decoded ID to their call
list.  At 1200 baud the full single frame is 26 × 8 / 1200 ≈ **173.33 ms**
of audio.

Frame format — double packet (Call Alert, Selective Call, Status messages,
GPS, …) — the 4-byte tail is reused as an *inter-packet* preamble that
gives the receiver's symbol tracker a re-sync window before a second
14-byte payload arrives, giving a 40-byte frame:

    [3 byte preamble]
    [5 byte frame sync]
    [14 byte payload #1 — source ID + op/arg/CRC/status]
    [4 byte inter-packet preamble = 0x00 0x00 0x00 0x00]
    [14 byte payload #2 — target ID + reserved + CRC + status]

Under differential modulation an all-zero input continues the current
logical level (no transitions → mark tone after inversion), so the
receiver's PLL stays locked to the 1200 Hz mark while its symbol
tracker resets in time for the second 14-byte interleaved payload.  At
1200 baud the full double frame is 40 × 8 / 1200 ≈ **266.67 ms** of audio.

The 14-byte payload is built from a 7-byte information block:

    payload[0] = opcode
    payload[1] = argument
    payload[2] = unit_id high byte           (source ID in packet 1,
    payload[3] = unit_id low byte             target ID in packet 2)
    payload[4] = CRC low byte    (CRC-16 of bytes 0..3, reverse poly 0x8408)
    payload[5] = CRC high byte
    payload[6] = status byte     (0x00 for PTT-ID, 0x76 for STS / MSG, ...)

For a packet 2 in double-packet mode the layout is the same shape, but
``opcode`` and ``argument`` are repurposed as the high/low bytes of the
target unit ID, and ``unit_id`` slots are zeroed:

    payload2[0] = target_id high byte
    payload2[1] = target_id low byte
    payload2[2] = 0x00  (reserved)
    payload2[3] = 0x00  (reserved)
    payload2[4] = CRC low byte    (CRC-16 of bytes 0..3 of packet 2)
    payload2[5] = CRC high byte
    payload2[6] = 0x00  (status)

A K=7 rate-1/2 convolutional encoder appends 7 FEC bytes derived from each
7-byte information block, giving 14 bytes (112 bits) of data per block.
Those bits are then run through a 16-row × 7-column bit interleaver
(per block), after which the **entire** frame (preamble + sync +
interleaved payload(s)) is differentially modulated (each output bit
signals "input bit changed?", then inverted) as one contiguous stream so
the receiver's transition tracker stays in sync across the boundary
between the two payloads.

The result is finally rendered as 1200-baud FFSK audio:

    mark  = 1200 Hz   (logical 1, 1 cycle per bit)
    space = 1800 Hz   (logical 0, 1.5 cycles per bit)

Bytes are transmitted **MSB first** at 1200 baud.

This implementation was developed clean-room from the algorithmic
description publicly documented in the `mdc1200.c` source of the
`uv-k5-firmware-custom` project (GPL-3.0); the algorithm itself
(differential modulation, taps at K=7 positions {6, 5, 2, 0}, the 16×7
interleaver, and the reverse-poly CRC-16) is a 1980s Motorola
specification not subject to copyright.

Common opcodes (verified against multiple receiver implementations):

    op   arg
    0x01 0x80   PTT-ID pre  (transmit start)
    0x00 0x80   PTT-ID post (transmit end)
    0x40 0x80   Emergency alarm
    0x35 0x89   Request to talk
    0x11 0x80   Remote monitor
    0x63 0x85   Call Alert  (page a specific target unit ID)
    0x35 0x80   Selective Call (voice selective call to a target unit ID)

For unit-only paging without an operational meaning, ``PTT_ID_PRE`` is the
standard choice — virtually every Motorola subscriber decodes it.

For Call Alert and Selective Call, the ``unit_id`` field carries the
**target** subscriber's ID (the radio to wake), not the transmitting
station.  Receiving radios programmed with that ID will alert the user
(Call Alert: beep + display) or unmute their speaker (Selective Call: open
audio path) when the packet is received.

References
----------
* Public algorithm summary published in the firmware comments at
  https://github.com/OneOfEleven/uv-k5-firmware-custom/blob/master/mdc1200.c
  (algorithm only — no code copied; see clean-room note above).
* multimon-ng MDC decoder (https://github.com/EliasOenal/multimon-ng) —
  useful for verifying generated waveforms with ``multimon-ng -a MDC``.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Modem parameters
# ---------------------------------------------------------------------------

#: Audio carrier baud rate.  Motorola defines MDC1200 at exactly 1200 baud.
MDC1200_BAUD: float = 1200.0

#: Mark (logical 1) carrier — one cycle per bit at 1200 baud.
MDC1200_MARK_FREQ: float = 1200.0

#: Space (logical 0) carrier — 1.5 cycles per bit at 1200 baud.
MDC1200_SPACE_FREQ: float = 1800.0

#: Preamble bytes transmitted before the sync word.  After differential
#: modulation, three null bytes produce a steady mark tone that lets the
#: receiver's PLL settle before bit timing recovery on the sync word.
MDC1200_PREAMBLE: Tuple[int, ...] = (0x00, 0x00, 0x00)

#: 40-bit frame sync word that flags the start of the data payload.
#: This is the canonical Motorola pattern recognised by every MDC decoder.
MDC1200_SYNC: Tuple[int, ...] = (0x07, 0x09, 0x2A, 0x44, 0x6F)

#: 4-byte post-preamble appended after every payload.  In a *single*
#: packet it sits at the end of the frame so the receiver sees a clean
#: trailing mark-tone segment after the CRC; in a *double* packet the
#: same 4-byte sequence sits between payload #1 and payload #2 as an
#: inter-packet re-sync window.  Under differential modulation an
#: all-zero input emits a continuous mark tone (no transitions → all
#: 0xFF after inversion), giving the receiver's symbol tracker a 32-bit
#: window to settle.
MDC1200_POST_PREAMBLE: Tuple[int, ...] = (0x00, 0x00, 0x00, 0x00)

#: Backwards-compatible alias for callers that only care about the
#: double-packet semantics of :data:`MDC1200_POST_PREAMBLE`.
MDC1200_INTER_PACKET_PREAMBLE: Tuple[int, ...] = MDC1200_POST_PREAMBLE

#: Number of information bytes per packet half (op + arg + 2 ID + 2 CRC + 1 status).
_FEC_K: int = 7


# ---------------------------------------------------------------------------
# Op-code presets
# ---------------------------------------------------------------------------

#: Built-in symbolic op-code presets.  Maps name -> (opcode, argument).
#: Names use lowercase ASCII with underscores so they round-trip cleanly
#: through HTML form values.
MDC1200_OP_PRESETS: Dict[str, Tuple[int, int]] = {
    "ptt_id_pre":     (0x01, 0x80),  # PTT-ID at the start of a transmission
    "ptt_id_post":    (0x00, 0x80),  # PTT-ID at the end of a transmission
    "emergency":      (0x40, 0x80),  # Emergency alarm
    "request_to_talk": (0x35, 0x89),  # Request-to-talk paging
    "remote_monitor": (0x11, 0x80),  # Remote-monitor command
    "call_alert":     (0x63, 0x85),  # Call Alert (page target subscriber)
    "selective_call": (0x35, 0x80),  # Voice Selective Call (unmute target)
}

#: Default preset when the operator hasn't picked one explicitly.
MDC1200_DEFAULT_PRESET: str = "ptt_id_pre"

#: ``(opcode, arg)`` pairs that traditionally use the **double-packet**
#: variant on real Motorola subscribers — a second 7-byte info block is
#: appended carrying the **target** unit ID (the radio being paged or
#: addressed).  The first info block still carries the transmitting
#: station's own (source) ID, so a receiver can both unmute for the right
#: target and display who originated the call.
#:
#: When an operator picks one of these op-codes via a preset *and* a
#: target unit ID is configured, ``generate_mdc1200_samples`` emits the
#: 36-byte double-packet frame.  When no target is configured, it falls
#: back to a single-packet frame whose ``unit_id`` field acts as the
#: target — some receivers tolerate this, but Motorola CPS-programmed
#: subscribers usually expect the double form.
MDC1200_DOUBLE_PACKET_OPS: frozenset = frozenset({
    (0x63, 0x85),  # Call Alert (page target)
    (0x35, 0x80),  # Voice Selective Call (unmute target)
})


def is_double_packet_op(opcode: int, arg: int) -> bool:
    """Return ``True`` if ``(opcode, arg)`` is a known double-packet op.

    Used by :func:`generate_mdc1200_samples` to decide whether to emit
    the 22-byte single packet or the 36-byte double packet variant.
    """
    return (opcode & 0xFF, arg & 0xFF) in MDC1200_DOUBLE_PACKET_OPS


# ---------------------------------------------------------------------------
# CRC-16
# ---------------------------------------------------------------------------

def compute_crc(data: Sequence[int]) -> int:
    """Compute the MDC1200 CRC-16.

    Polynomial: x^16 + x^12 + x^5 + 1 (CRC-CCITT, value 0x1021), evaluated
    in *bit-reversed* form (poly 0x8408, LSB-first feedback) with an init
    value of ``0x0000`` and a final XOR of ``0xFFFF``.  This matches the
    on-the-wire CRC produced by Motorola subscribers and validated by
    multimon-ng's MDC decoder.

    Verified against the documented vector ``01 80 12 34`` → ``0x3E2E``.

    Args:
        data: Iterable of integers in 0..255 (the information bytes to
            protect — typically the 4-byte op/arg/ID block).

    Returns:
        16-bit CRC as a Python ``int`` in the range 0..65535.
    """
    crc = 0
    for byte in data:
        crc ^= byte & 0xFF
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return (crc ^ 0xFFFF) & 0xFFFF


# ---------------------------------------------------------------------------
# Forward error correction (K=7, rate 1/2 convolutional code)
# ---------------------------------------------------------------------------

def _apply_fec(info: List[int]) -> List[int]:
    """Append 7 FEC bytes to a 7-byte information block.

    The FEC is a K=7 rate-1/2 convolutional code with output bit
    ``b[n] = b[n-0] ^ b[n-2] ^ b[n-5] ^ b[n-6]`` (taps at shift-register
    positions {0, 2, 5, 6}).  Information bits are fed in **LSB-first per
    byte**, and the resulting parity bits are packed back **LSB-first per
    byte** into the appended FEC region.

    The shift register is 8 bits wide and is *not* reset between bytes —
    it carries state across the whole 7-byte block, exactly as Motorola's
    on-air implementation does.

    Args:
        info: The 7-byte information block (op, arg, idH, idL, crcL, crcH,
            status), modified in place by appending 7 parity bytes.

    Returns:
        A new 14-byte list (information + parity).  The original list is
        not mutated.
    """
    if len(info) != _FEC_K:
        raise ValueError(f"MDC1200 FEC requires exactly {_FEC_K} information bytes")

    output = list(info)
    shift_reg = 0
    for byte in info:
        bo = 0
        for bit_num in range(8):
            bit_in = (byte >> bit_num) & 1
            shift_reg = ((shift_reg << 1) | bit_in) & 0xFF
            parity = (
                ((shift_reg >> 6) & 1)
                ^ ((shift_reg >> 5) & 1)
                ^ ((shift_reg >> 2) & 1)
                ^ ((shift_reg >> 0) & 1)
            )
            bo |= parity << bit_num
        output.append(bo & 0xFF)
    return output


# ---------------------------------------------------------------------------
# Bit interleaver
# ---------------------------------------------------------------------------

def _interleave(payload: List[int]) -> List[int]:
    """Apply the 16×7 bit interleaver to a 14-byte payload.

    Each input bit is read **LSB-first per byte** in source order
    (byte 0 bit 0, byte 0 bit 1, …, byte 13 bit 7) and placed into the
    output bit array at index ``k = (i * 16 + bit_num * 16) mod 111``,
    where the source-byte index is ``i`` and ``bit_num`` is the bit
    position within that byte.  Concretely the source-bit walking order
    increments the output index by 16 and wraps via ``-= 111`` whenever
    it would exceed ``112`` — this is the classic distance-16 spreading
    used by MDC1200 to break up burst errors.

    Output bits are then packed **MSB-first per byte** into the 14
    output bytes.

    Args:
        payload: 14-byte payload (info + FEC), modified by interleaving.

    Returns:
        New 14-byte interleaved list.
    """
    if len(payload) != _FEC_K * 2:
        raise ValueError(f"MDC1200 interleaver expects {_FEC_K * 2} bytes")

    total_bits = _FEC_K * 2 * 8  # 112
    interleaved = [0] * total_bits
    k = 0
    for i, byte in enumerate(payload):
        for bit_num in range(8):
            interleaved[k] = (byte >> bit_num) & 1
            k += 16
            if k >= total_bits:
                k -= total_bits - 1

    out: List[int] = []
    j = 0
    for _ in range(_FEC_K * 2):
        b = 0
        for bit_num in range(7, -1, -1):
            if interleaved[j]:
                b |= 1 << bit_num
            j += 1
        out.append(b & 0xFF)
    return out


# ---------------------------------------------------------------------------
# Differential ("XOR") modulation
# ---------------------------------------------------------------------------

def _xor_modulate(buf: List[int]) -> List[int]:
    """Differentially encode and invert the entire frame.

    For each output bit, ``out_bit = (input_bit != previous_input_bit)``.
    Bits are processed **MSB-first per byte** across the buffer, with the
    initial previous-bit state set to 0.  The completed byte is then
    inverted (``^ 0xFF``) — Motorola's wire format expresses "no change"
    as logical 1 (mark) rather than 0, so the inversion converts the
    transition encoder's natural output into the on-air convention.

    Args:
        buf: Pre-modulation byte buffer (preamble + sync + interleaved payload).

    Returns:
        New list of bytes ready to be serialised to FFSK bits.
    """
    out: List[int] = []
    prev_bit = 0
    for byte in buf:
        b = 0
        for bit_num in range(7, -1, -1):
            new_bit = (byte >> bit_num) & 1
            if new_bit != prev_bit:
                b |= 1 << bit_num
            prev_bit = new_bit
        out.append((b ^ 0xFF) & 0xFF)
    return out


# ---------------------------------------------------------------------------
# Top-level encoder
# ---------------------------------------------------------------------------

def encode_packet(
    opcode: int,
    arg: int,
    unit_id: int,
    *,
    status: int = 0x00,
) -> List[int]:
    """Build a complete MDC1200 single packet, ready for FFSK modulation.

    Args:
        opcode: 8-bit op-code (e.g. 0x01 for PTT-ID pre).
        arg: 8-bit op-code argument (e.g. 0x80 for the standard PTT variant).
        unit_id: 16-bit subscriber unit ID (1..65535; 0 is reserved).
        status: 8-bit status byte appended to the information block.
            ``0x00`` for PTT-ID variants, ``0x76`` for STS / MSG variants.

    Returns:
        List of 26 bytes — the on-air frame (3 preamble + 5 sync + 14
        differentially-modulated interleaved payload + 4 post-preamble).
        Each byte is transmitted MSB-first at 1200 baud, giving a total
        airtime of 26 × 8 / 1200 ≈ 173.33 ms.

    Raises:
        ValueError: If any input is out of its allowed range.
    """
    if not 0 <= opcode <= 0xFF:
        raise ValueError("opcode must be in 0..255")
    if not 0 <= arg <= 0xFF:
        raise ValueError("arg must be in 0..255")
    if not 0 <= unit_id <= 0xFFFF:
        raise ValueError("unit_id must be in 0..65535")
    if not 0 <= status <= 0xFF:
        raise ValueError("status must be in 0..255")

    # 7-byte information block
    info = [
        opcode & 0xFF,
        arg & 0xFF,
        (unit_id >> 8) & 0xFF,
        unit_id & 0xFF,
    ]
    crc = compute_crc(info)
    info.append(crc & 0xFF)        # CRC low byte first on the wire
    info.append((crc >> 8) & 0xFF)
    info.append(status & 0xFF)

    # FEC + interleave
    payload = _apply_fec(info)
    payload = _interleave(payload)

    # Assemble full frame and apply differential modulation across the
    # entire transmission (preamble + sync + payload + post-preamble).
    # The 4-byte trailing post-preamble continues the mark tone for an
    # extra ~26.67 ms so receivers see a clean idle transition after the
    # CRC passes — without it some Motorola subscribers refuse to commit
    # the decoded ID to their call list.
    frame = (
        list(MDC1200_PREAMBLE)
        + list(MDC1200_SYNC)
        + payload
        + list(MDC1200_POST_PREAMBLE)
    )
    return _xor_modulate(frame)


def encode_double_packet(
    opcode: int,
    arg: int,
    src_unit_id: int,
    target_unit_id: int,
    *,
    status: int = 0x00,
) -> List[int]:
    """Build a 40-byte MDC1200 double packet (Call Alert / Selective Call).

    The double packet appends a 4-byte inter-packet preamble plus a
    second 14-byte interleaved payload (built from a 7-byte info block
    carrying the target subscriber's ID).  The two info blocks go
    through the K=7 FEC and 16×7 interleaver independently and the
    **entire** 40-byte buffer (preamble + sync + payload1 +
    inter-packet preamble + payload2) is then differentially modulated
    as a single stream so the receiver's transition tracker carries
    cleanly across the payload-1 → preamble → payload-2 boundary.

    At 1200 baud the resulting waveform is 40 × 8 / 1200 ≈ 266.67 ms.

    Second info block layout (7 bytes):

        ``[target_id_high, target_id_low, 0x00, 0x00, crc_lo, crc_hi, 0x00]``

    Args:
        opcode: 8-bit op-code for packet 1 (e.g. 0x63 for Call Alert).
        arg: 8-bit op-code argument for packet 1 (e.g. 0x85).
        src_unit_id: 16-bit transmitting station's unit ID (1..65535).
        target_unit_id: 16-bit target subscriber's unit ID (1..65535) —
            the radio that should be paged or unmuted.
        status: Status byte for packet 1 (defaults to 0x00).

    Returns:
        List of 40 bytes (3 preamble + 5 sync + 14 payload-1 + 4
        inter-packet preamble + 14 payload-2) ready for FFSK modulation.

    Raises:
        ValueError: If any input is out of its allowed range.
    """
    if not 0 <= opcode <= 0xFF:
        raise ValueError("opcode must be in 0..255")
    if not 0 <= arg <= 0xFF:
        raise ValueError("arg must be in 0..255")
    if not 0 <= src_unit_id <= 0xFFFF:
        raise ValueError("src_unit_id must be in 0..65535")
    if not 0 <= target_unit_id <= 0xFFFF:
        raise ValueError("target_unit_id must be in 0..65535")
    if not 0 <= status <= 0xFF:
        raise ValueError("status must be in 0..255")

    # Packet 1: source ID + op/arg
    info1 = [
        opcode & 0xFF,
        arg & 0xFF,
        (src_unit_id >> 8) & 0xFF,
        src_unit_id & 0xFF,
    ]
    crc1 = compute_crc(info1)
    info1.append(crc1 & 0xFF)
    info1.append((crc1 >> 8) & 0xFF)
    info1.append(status & 0xFF)
    payload1 = _interleave(_apply_fec(info1))

    # Packet 2: target ID + reserved + CRC + status.  The Motorola wire
    # format puts the target ID in bytes 0..1 of the second info block,
    # leaves bytes 2..3 zero, and protects bytes 0..3 with an independent
    # CRC-16 computed exactly the same way as packet 1's CRC.
    info2 = [
        (target_unit_id >> 8) & 0xFF,
        target_unit_id & 0xFF,
        0x00,
        0x00,
    ]
    crc2 = compute_crc(info2)
    info2.append(crc2 & 0xFF)
    info2.append((crc2 >> 8) & 0xFF)
    info2.append(0x00)  # status byte 2 — always 0x00 for the known double-packet ops
    payload2 = _interleave(_apply_fec(info2))

    # Differential modulation runs across the entire 40-byte buffer in
    # one pass — splitting it would corrupt the inter-payload transition
    # bit and break the receiver's tracker at the boundary.  The 4-byte
    # inter-packet preamble (all 0x00) becomes a 32-bit mark-tone window
    # under differential modulation, giving the receiver's symbol tracker
    # time to re-lock before the second interleaved payload starts.
    frame = (
        list(MDC1200_PREAMBLE)
        + list(MDC1200_SYNC)
        + payload1
        + list(MDC1200_POST_PREAMBLE)
        + payload2
    )
    return _xor_modulate(frame)


def bytes_to_bits_msb(data: Sequence[int]) -> List[int]:
    """Serialise a byte sequence to bits in MDC1200 transmission order.

    MDC1200 transmits each byte MSB-first.  Use this helper to feed
    ``app_utils.eas_fsk.generate_fsk_samples`` (which expects an
    iterable of bits).
    """
    bits: List[int] = []
    for byte in data:
        for bit_num in range(7, -1, -1):
            bits.append((byte >> bit_num) & 1)
    return bits


def generate_mdc1200_samples(
    opcode: int,
    arg: int,
    unit_id: int,
    sample_rate: int,
    amplitude: float,
    *,
    status: int = 0x00,
    target_unit_id: Optional[int] = None,
) -> List[int]:
    """Generate the FFSK PCM samples for a complete MDC1200 packet.

    Produces a phase-continuous 1200-baud FFSK waveform suitable for
    transmission alongside or immediately before/after a SAME burst.  Use
    16 kHz or higher sample rates for best fidelity (8 kHz is also
    decodable at the cost of some quantisation noise on the 1800 Hz
    space tone).

    Single vs. double packet selection:

    * If ``(opcode, arg)`` is in :data:`MDC1200_DOUBLE_PACKET_OPS` (Call
      Alert, Selective Call) **and** ``target_unit_id`` is provided and
      non-zero, a 36-byte double packet is emitted with the source ID in
      packet 1 and ``target_unit_id`` in packet 2.
    * Otherwise the classic 22-byte single packet is emitted (and
      ``target_unit_id`` is ignored).

    Args:
        opcode: 8-bit op-code (see ``MDC1200_OP_PRESETS``).
        arg: 8-bit op-code argument.
        unit_id: 16-bit subscriber unit ID.  Acts as the *source* ID in
            double-packet mode and as the only ID in single-packet mode.
        sample_rate: Output sample rate in Hz.
        amplitude: Peak signed-int amplitude (e.g. ``0.7 * 32767``).
        status: Status byte (defaults to 0x00 for PTT-ID variants).
        target_unit_id: 16-bit target subscriber ID for double-packet
            ops (Call Alert / Selective Call).  ``None`` or 0 forces
            single-packet emission.

    Returns:
        Phase-continuous int16-range PCM samples for the entire packet.
        At 16 kHz this is approximately:

        * single packet: 26 bytes × 8 bits / 1200 baud × 16000
          ≈ 2773 samples (≈ 173.33 ms)
        * double packet: 40 bytes × 8 bits / 1200 baud × 16000
          ≈ 4267 samples (≈ 266.67 ms)
    """
    # Re-use the shared phase-continuous FFSK renderer that is already
    # tested for the SAME modem (8333.5 / 8333.5 Hz at 520.83 baud).
    from app_utils.eas_fsk import generate_fsk_samples

    if (
        target_unit_id is not None
        and int(target_unit_id) != 0
        and is_double_packet_op(opcode, arg)
    ):
        frame_bytes = encode_double_packet(
            opcode,
            arg,
            src_unit_id=unit_id,
            target_unit_id=int(target_unit_id),
            status=status,
        )
    else:
        frame_bytes = encode_packet(opcode, arg, unit_id, status=status)

    bits = bytes_to_bits_msb(frame_bytes)
    return generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=MDC1200_BAUD,
        mark_freq=MDC1200_MARK_FREQ,
        space_freq=MDC1200_SPACE_FREQ,
        amplitude=amplitude,
    )


def resolve_op_preset(name: str) -> Tuple[int, int]:
    """Return the ``(opcode, arg)`` tuple for a named preset.

    Falls back to the ``ptt_id_pre`` preset for unknown names so the
    encoder always produces a valid frame even when the operator picks
    "custom" without filling in raw values.
    """
    key = (name or "").strip().lower()
    return MDC1200_OP_PRESETS.get(key, MDC1200_OP_PRESETS[MDC1200_DEFAULT_PRESET])


__all__ = [
    "MDC1200_BAUD",
    "MDC1200_MARK_FREQ",
    "MDC1200_SPACE_FREQ",
    "MDC1200_PREAMBLE",
    "MDC1200_SYNC",
    "MDC1200_POST_PREAMBLE",
    "MDC1200_INTER_PACKET_PREAMBLE",
    "MDC1200_OP_PRESETS",
    "MDC1200_DEFAULT_PRESET",
    "MDC1200_DOUBLE_PACKET_OPS",
    "compute_crc",
    "encode_packet",
    "encode_double_packet",
    "is_double_packet_op",
    "bytes_to_bits_msb",
    "generate_mdc1200_samples",
    "resolve_op_preset",
]
