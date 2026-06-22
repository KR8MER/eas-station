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

"""DTMF (Dual-Tone Multi-Frequency) detection via the Goertzel algorithm."""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

# Standard DTMF frequency grid
_ROW_FREQS: Tuple[int, ...] = (697, 770, 852, 941)
_COL_FREQS: Tuple[int, ...] = (1209, 1336, 1477, 1633)

_DTMF_TABLE = {
    (697, 1209): '1', (697, 1336): '2', (697, 1477): '3', (697, 1633): 'A',
    (770, 1209): '4', (770, 1336): '5', (770, 1477): '6', (770, 1633): 'B',
    (852, 1209): '7', (852, 1336): '8', (852, 1477): '9', (852, 1633): 'C',
    (941, 1209): '*', (941, 1336): '0', (941, 1477): '#', (941, 1633): 'D',
}

_ALL_DTMF_FREQS: Tuple[int, ...] = _ROW_FREQS + _COL_FREQS


@dataclass
class DTMFTone:
    """A single detected DTMF digit with timing information."""

    digit: str
    start_sample: int
    end_sample: int
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return (self.end_sample - self.start_sample) / self.sample_rate

    @property
    def start_seconds(self) -> float:
        return self.start_sample / self.sample_rate

    def to_dict(self):
        return {
            'digit': self.digit,
            'start_sample': self.start_sample,
            'end_sample': self.end_sample,
            'sample_rate': self.sample_rate,
            'duration_seconds': self.duration_seconds,
            'start_seconds': self.start_seconds,
        }


def _goertzel_power(samples: np.ndarray, freq: float, sample_rate: int) -> float:
    """Compute Goertzel power for a single frequency over a block of samples."""
    N = len(samples)
    if N == 0:
        return 0.0
    k = N * freq / sample_rate
    omega = 2.0 * math.pi * k / N
    coeff = 2.0 * math.cos(omega)
    s1 = s2 = 0.0
    for x in samples:
        s0 = float(x) + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return s2 * s2 + s1 * s1 - coeff * s1 * s2


def detect_dtmf(
    samples: np.ndarray,
    sample_rate: int,
    window_ms: float = 40.0,
    min_duration_ms: float = 40.0,
    snr_threshold_db: float = 12.0,
) -> List[DTMFTone]:
    """
    Detect DTMF tones in mono float32 audio samples.

    Args:
        samples: Mono audio samples, float32, normalised to [-1, 1].
        sample_rate: Sample rate in Hz.
        window_ms: Analysis window length in milliseconds.
        min_duration_ms: Minimum digit duration to report.
        snr_threshold_db: Each candidate frequency must exceed the mean of
            its peers in the same row/column group by this many dB.

    Returns:
        List of :class:`DTMFTone` objects in chronological order.
    """
    window_samples = max(8, int(sample_rate * window_ms / 1000.0))
    min_windows = max(1, int(round(min_duration_ms / window_ms)))

    # Per-window digit detection
    window_digits: List[Optional[str]] = []
    window_starts: List[int] = []

    pos = 0
    while pos + window_samples <= len(samples):
        block = samples[pos : pos + window_samples]

        powers = {f: _goertzel_power(block, f, sample_rate) for f in _ALL_DTMF_FREQS}

        # Find dominant row and column frequency
        row_powers = {f: powers[f] for f in _ROW_FREQS}
        col_powers = {f: powers[f] for f in _COL_FREQS}

        best_row = max(row_powers, key=row_powers.__getitem__)
        best_col = max(col_powers, key=col_powers.__getitem__)

        # SNR: dominant tone vs. mean of the other three in its group
        other_rows = [v for f, v in row_powers.items() if f != best_row]
        other_cols = [v for f, v in col_powers.items() if f != best_col]
        row_noise = (sum(other_rows) / len(other_rows)) + 1e-12
        col_noise = (sum(other_cols) / len(other_cols)) + 1e-12

        row_snr = 10.0 * math.log10(max(row_powers[best_row], 1e-12) / row_noise)
        col_snr = 10.0 * math.log10(max(col_powers[best_col], 1e-12) / col_noise)

        digit: Optional[str] = None
        if row_snr >= snr_threshold_db and col_snr >= snr_threshold_db:
            digit = _DTMF_TABLE.get((best_row, best_col))

        window_digits.append(digit)
        window_starts.append(pos)
        pos += window_samples

    if not window_digits:
        return []

    # Merge consecutive windows carrying the same digit
    tones: List[DTMFTone] = []
    run_digit: Optional[str] = None
    run_start: int = 0
    run_count: int = 0
    run_end: int = 0

    def _flush_run() -> None:
        if run_digit is not None and run_count >= min_windows:
            tones.append(DTMFTone(
                digit=run_digit,
                start_sample=run_start,
                end_sample=run_end,
                sample_rate=sample_rate,
            ))

    for i, digit in enumerate(window_digits):
        start = window_starts[i]
        end = start + window_samples

        if digit is not None and digit == run_digit:
            run_count += 1
            run_end = end
        else:
            _flush_run()
            run_digit = digit
            run_start = start
            run_end = end
            run_count = 1 if digit is not None else 0

    _flush_run()
    return tones


__all__ = ['DTMFTone', 'detect_dtmf']
