"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Helpers for building SAME/AFSK bursts for EAS audio output."""

import math
from fractions import Fraction
from typing import List, Sequence

SAME_BAUD = Fraction(3125, 6)  # 520.83… baud (520 5/6 per §11.31)
SAME_MARK_FREQ = float(SAME_BAUD * 4)  # 2083 1/3 Hz
SAME_SPACE_FREQ = float(SAME_BAUD * 3)  # 1562.5 Hz
SAME_PREAMBLE_BYTE = 0xAB
SAME_PREAMBLE_REPETITIONS = 16


def same_preamble_bits(repeats: int = SAME_PREAMBLE_REPETITIONS) -> List[int]:
    """Encode the SAME preamble (0xAB) bytes per FCC 47 CFR §11.31.

    Each preamble byte is transmitted as 8 bits LSB-first with no start or stop
    framing, exactly as required by the standard.
    """

    bits: List[int] = []
    repeats = max(1, int(repeats))
    for _ in range(repeats):
        for i in range(8):
            bits.append((SAME_PREAMBLE_BYTE >> i) & 1)

    return bits


def encode_terminator_bits(byte_val: int, count: int) -> List[int]:
    """Encode ``count`` copies of ``byte_val`` as 8-bit LSB-first bitstreams.

    Used to append ENDEC-identifying terminator bytes immediately after each
    SAME burst, before the inter-burst silence.  Encoding matches the standard
    SAME data encoding per FCC 47 CFR §11.31 (LSB first, no framing bits).

    Example — EAS Station fingerprint (3 × 0xA9 = 10101001):
        bits: 1,0,0,1,0,1,0,1 × 3  →  24 mostly-alternating space/mark pulses
        sound: rapid trill at ~521 Hz modulation rate (~46 ms)
    """
    bits: List[int] = []
    byte_val = byte_val & 0xFF
    for _ in range(count):
        for i in range(8):
            bits.append((byte_val >> i) & 1)
    return bits


def encode_same_bits(
    message: str,
    *,
    include_preamble: bool = False,
    include_cr: bool = True,
) -> List[int]:
    """Encode an ASCII SAME header per FCC 47 CFR §11.31.

    Each character is transmitted as 8 bits LSB-first: 7 ASCII data bits followed
    by one null bit.  There are no start or stop framing bits.

    Per FCC 47 CFR §11.31: "Characters are ASCII seven bit characters as defined in
    ANSI X3.4-1977 ending with an eighth null bit (either 0 or 1) to constitute a
    full eight-bit byte."

    ``include_cr`` controls whether a carriage-return terminator is appended.
    SAME headers (ZCZC-…) require it; the EOM burst (NNNN) does not — the FCC
    §11.31 EOM section specifies only the four ASCII characters "NNNN" with no
    explicit CR terminator.
    """

    bits: List[int] = []
    if include_preamble:
        bits.extend(same_preamble_bits())

    chars = message + "\r" if include_cr else message
    for char in chars:
        ascii_code = ord(char) & 0x7F

        # 7 data bits (LSB first) + 1 null bit = 8 bits per FCC §11.31
        for i in range(7):
            bits.append((ascii_code >> i) & 1)
        bits.append(0)  # Eighth null bit per FCC §11.31

    return bits


def generate_fsk_samples(
    bits: Sequence[int],
    sample_rate: int,
    bit_rate: float,
    mark_freq: float,
    space_freq: float,
    amplitude: float,
) -> List[int]:
    """Render NRZ AFSK samples while preserving the fractional bit timing."""

    samples: List[int] = []
    phase = 0.0
    delta = math.tau / sample_rate
    samples_per_bit = sample_rate / bit_rate
    carry = 0.0

    for bit in bits:
        freq = mark_freq if bit else space_freq
        step = freq * delta
        total = samples_per_bit + carry
        sample_count = int(total)
        if sample_count <= 0:
            sample_count = 1
        carry = total - sample_count

        for _ in range(sample_count):
            samples.append(int(math.sin(phase) * amplitude))
            phase = (phase + step) % math.tau

    return samples


__all__ = [
    "SAME_BAUD",
    "SAME_MARK_FREQ",
    "SAME_SPACE_FREQ",
    "SAME_PREAMBLE_BYTE",
    "SAME_PREAMBLE_REPETITIONS",
    "same_preamble_bits",
    "encode_same_bits",
    "encode_terminator_bits",
    "generate_fsk_samples",
]
