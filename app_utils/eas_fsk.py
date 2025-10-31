"""Helpers for building SAME/AFSK bursts for EAS audio output."""

from __future__ import annotations

import math
from fractions import Fraction
from typing import List, Sequence

SAME_BAUD = Fraction(3125, 6)  # 520.83… baud (520 5/6 per §11.31)
SAME_MARK_FREQ = float(SAME_BAUD * 4)  # 2083 1/3 Hz
SAME_SPACE_FREQ = float(SAME_BAUD * 3)  # 1562.5 Hz
SAME_PREAMBLE_BYTE = 0xAB
SAME_PREAMBLE_REPETITIONS = 16


def same_preamble_bits(repeats: int = SAME_PREAMBLE_REPETITIONS) -> List[int]:
    """Encode the SAME preamble (0xAB) bytes with start/stop framing."""

    bits: List[int] = []
    repeats = max(1, int(repeats))
    for _ in range(repeats):
        bits.append(0)
        for i in range(8):
            bits.append((SAME_PREAMBLE_BYTE >> i) & 1)
        bits.append(1)

    return bits


def encode_same_bits(message: str, *, include_preamble: bool = False) -> List[int]:
    """Encode an ASCII SAME header using NRZ AFSK framing."""

    bits: List[int] = []
    if include_preamble:
        bits.extend(same_preamble_bits())

    for char in message + "\r":
        ascii_code = ord(char) & 0x7F

        char_bits: List[int] = [0]
        ones_count = 0
        for i in range(7):
            bit = (ascii_code >> i) & 1
            ones_count += bit
            char_bits.append(bit)

        parity_bit = ones_count & 1
        char_bits.append(parity_bit)
        char_bits.append(1)
        bits.extend(char_bits)

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
    "generate_fsk_samples",
]
