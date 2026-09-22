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
    apply_edge_ramp,
    apply_low_pass_filter,
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


def test_apply_edge_ramp_fades_through_zero_without_changing_length():
    # A constant-amplitude "tone" concatenated with silence would otherwise
    # step straight from 0 to full scale -- an audible click. The ramp must
    # bring the very first/last sample to (near) zero and leave the middle
    # of the segment untouched.
    sample_rate = 8000
    peak = 30000
    samples = [peak] * 400  # 50 ms, well over the ~5 ms ramp window

    ramped = apply_edge_ramp(samples, sample_rate)

    assert len(ramped) == len(samples)
    assert ramped[0] == 0
    assert ramped[-1] == 0
    assert ramped[len(ramped) // 2] == peak
    # Monotonically rises from 0 up to full scale over the ramp window.
    ramp_window = ramped[:40]
    assert ramp_window == sorted(ramp_window)


def test_apply_edge_ramp_leaves_short_segments_unchanged():
    # A segment shorter than 4 samples has no meaningful "edge" to ramp;
    # returning it unchanged avoids degenerate zero-length ramp windows.
    tiny = [100, -100, 100]
    assert apply_edge_ramp(tiny, sample_rate=8000) == tiny


def test_same_header_burst_edges_are_softened_end_to_end():
    """Regression test for the harsh/splattery software-encoder audio
    reported vs. a hardware ENDEC (e.g. Sage 3644): every generated burst
    must fade in/out at its edges rather than stepping to full scale."""
    sample_rate = 11025
    amplitude = 0.7 * 32767
    bits = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0]

    burst = apply_edge_ramp(
        generate_fsk_samples(
            bits,
            sample_rate=sample_rate,
            bit_rate=BIT_RATE,
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        ),
        sample_rate,
    )

    assert burst[0] == 0
    assert burst[-1] == 0
    # Well inside the burst, samples should be free to reach full scale --
    # only the edges are tamed.
    assert max(abs(s) for s in burst[100:-100]) > 0.9 * amplitude


def _rms(samples):
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _tone(freq_hz, sample_rate, seconds, amplitude=20000):
    n = int(seconds * sample_rate)
    return [
        int(math.sin(2 * math.pi * freq_hz * i / sample_rate) * amplitude)
        for i in range(n)
    ]


def test_apply_low_pass_filter_attenuates_above_cutoff_preserves_below():
    sample_rate = 44100
    low_tone = _tone(1000.0, sample_rate, 0.2)  # well below the 4 kHz default cutoff
    high_tone = _tone(12000.0, sample_rate, 0.2)  # well above it

    low_filtered = apply_low_pass_filter(low_tone, sample_rate)
    high_filtered = apply_low_pass_filter(high_tone, sample_rate)

    assert len(low_filtered) == len(low_tone)
    assert len(high_filtered) == len(high_tone)
    # In-band content should survive largely intact...
    assert _rms(low_filtered) > 0.8 * _rms(low_tone)
    # ...while content well above the cutoff should be substantially cut.
    assert _rms(high_filtered) < 0.2 * _rms(high_tone)


def test_apply_low_pass_filter_clamps_cutoff_below_nyquist_at_8khz():
    # This codebase also supports 8 kHz operation (test_8khz_stress_test.py);
    # the default 4 kHz cutoff sits exactly at Nyquist there and scipy
    # rejects that outright unless the cutoff is clamped down first.
    sample_rate = 8000
    tone = _tone(1000.0, sample_rate, 0.2)
    filtered = apply_low_pass_filter(tone, sample_rate)
    assert len(filtered) == len(tone)


def test_apply_low_pass_filter_leaves_short_segments_unchanged():
    tiny = [100, -100, 100]
    assert apply_low_pass_filter(tiny, sample_rate=8000) == tiny
