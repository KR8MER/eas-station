import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_utils.eas_fsk import (
    SAME_BAUD,
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    encode_same_bits,
    generate_fsk_samples,
)


BIT_RATE = float(SAME_BAUD)
BIT_PERIOD = 1.0 / BIT_RATE


def _reference_bit_samples(bit: int, sample_rate: int, amplitude: float) -> list[int]:
    freq = SAME_MARK_FREQ if bit else SAME_SPACE_FREQ
    # Match the reference script's four-cycle tone per bit by computing the
    # absolute sample count first, then reproducing its sine progression.
    samples_per_bit = int(round(BIT_PERIOD * sample_rate))
    samples = []
    for index in range(samples_per_bit):
        time_point = index / sample_rate
        samples.append(int(math.sin(2 * math.pi * freq * time_point) * amplitude))
    return samples


def _reference_samples(bits: list[int], sample_rate: int, amplitude: float) -> list[int]:
    reference = []
    for bit in bits:
        reference.extend(_reference_bit_samples(bit, sample_rate, amplitude))
    return reference


def test_generate_fsk_samples_matches_reference_script():
    sample_rate = 43_750  # Matches the standalone SAME generator script
    amplitude = 0.7 * 32767
    bits = [1, 0, 1, 1, 0, 0, 1]

    expected = _reference_samples(bits, sample_rate, amplitude)
    actual = generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=BIT_RATE,
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=amplitude,
    )

    assert actual == expected
    assert len(actual) == len(bits) * int(round(sample_rate / BIT_RATE))


def _char_bits(message: str, index: int) -> list[int]:
    bits = encode_same_bits(message, include_preamble=False)
    start = index * 10
    return bits[start : start + 10]


def test_encode_same_bits_includes_even_parity_for_odd_weight_chars() -> None:
    # 'C' (0x43) has three set bits and requires the parity bit to be 1 to
    # maintain even parity across the ASCII payload.
    bits = _char_bits("C", 0)
    data_bits = bits[1:8]
    parity_bit = bits[8]

    assert parity_bit == 1
    assert (sum(data_bits) + parity_bit) % 2 == 0


def test_encode_same_bits_includes_even_parity_for_even_weight_chars() -> None:
    # 'A' (0x41) already has an even number of set bits so the parity bit
    # should remain 0.
    bits = _char_bits("A", 0)
    data_bits = bits[1:8]
    parity_bit = bits[8]

    assert parity_bit == 0
    assert (sum(data_bits) + parity_bit) % 2 == 0
