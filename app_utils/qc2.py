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

"""QC-II (Motorola Quick Call II) two-tone paging decoder.

Quick Call II is a fixed-timing two-tone selective-calling protocol:
    - 1.0 s of Tone A on a frequency from a fixed group
    - immediately followed by 3-4 s of Tone B on a different frequency

Per-tone frequencies live in ~280-3000 Hz across the standard groups
(A, B, M, Z, etc.).  This decoder detects the temporal A->B pattern
without requiring the exact frequency to match a known group, which
lets it accept legacy and operator-customised tone tables.
"""

import math
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass
class QC2Tone:
    """A detected QC-II two-tone paging sequence."""

    tone_a_freq: float
    tone_b_freq: float
    tone_a_duration: float
    tone_b_duration: float
    start_sample: int
    end_sample: int
    sample_rate: int
    confidence: float

    @property
    def start_seconds(self) -> float:
        return self.start_sample / self.sample_rate

    @property
    def duration_seconds(self) -> float:
        return (self.end_sample - self.start_sample) / self.sample_rate

    def to_dict(self):
        return {
            "tone_a_freq": self.tone_a_freq,
            "tone_b_freq": self.tone_b_freq,
            "tone_a_duration": self.tone_a_duration,
            "tone_b_duration": self.tone_b_duration,
            "start_sample": self.start_sample,
            "end_sample": self.end_sample,
            "sample_rate": self.sample_rate,
            "duration_seconds": self.duration_seconds,
            "start_seconds": self.start_seconds,
            "confidence": self.confidence,
        }


# QC-II tones live in ~280-3000 Hz across all standard groupings.
_QC2_FREQ_MIN = 280.0
_QC2_FREQ_MAX = 3000.0

# 853 + 960 Hz EBS attention is two simultaneous tones, but a noisy
# capture can still leave one of them as the FFT peak.  Refuse runs
# whose peak sits exactly on either EBS frequency to avoid mis-flagging
# attention signals as QC-II.
_EBS_FREQS: Tuple[float, ...] = (853.0, 960.0)
_EBS_FREQ_TOL = 6.0  # Hz

# Tone-A timing window (encoder emits 1.0 s; allow some slack).
_TONE_A_MIN_SEC = 0.6
_TONE_A_MAX_SEC = 1.5

# Tone-B timing window (encoder emits 4.0 s; legacy systems use 3.0 s).
_TONE_B_MIN_SEC = 2.5
_TONE_B_MAX_SEC = 5.0

# Two QC-II tones must be at least this many Hz apart -- otherwise the
# A and B segments are really one continuous tone with FFT-bin jitter.
_AB_FREQ_SEPARATION = 30.0


def detect_qc2(
    samples: np.ndarray,
    sample_rate: int,
    window_ms: float = 50.0,
    hop_ms: float = 25.0,
    stability_tol_hz: float = 8.0,
    min_snr_db: float = 12.0,
) -> List[QC2Tone]:
    """Detect QC-II two-tone paging sequences in mono audio.

    Args:
        samples: Mono audio samples, float32 normalised to [-1, 1].
        sample_rate: Sample rate in Hz.
        window_ms: Analysis window length.  50 ms gives ~20 Hz FFT
            resolution after zero-padding to 1024 bins -- fine enough
            to distinguish adjacent QC-II group frequencies.
        hop_ms: Hop between consecutive analysis windows.
        stability_tol_hz: A run of windows is considered the same tone
            while peak frequencies stay within this many Hz of each
            other.
        min_snr_db: Minimum peak-vs-band-mean SNR for a window to be
            considered "tone present".

    Returns:
        List of :class:`QC2Tone` matches in chronological order.
    """
    if sample_rate <= 0 or len(samples) == 0:
        return []

    win = max(64, int(sample_rate * window_ms / 1000.0))
    hop = max(16, int(sample_rate * hop_ms / 1000.0))
    if win > len(samples):
        return []

    hann = np.hanning(win).astype(np.float32)
    fft_size = int(2 ** math.ceil(math.log2(max(win, 1024))))
    freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)

    band_idx = np.where((freqs >= _QC2_FREQ_MIN) & (freqs <= _QC2_FREQ_MAX))[0]
    if band_idx.size == 0:
        return []
    bin_hz = sample_rate / fft_size
    excl_bins = max(1, int(round(30.0 / bin_hz)))

    peak_freqs: List[float] = []
    peak_starts: List[int] = []
    peak_snrs: List[float] = []

    pos = 0
    samples_f = samples.astype(np.float32, copy=False)
    while pos + win <= len(samples_f):
        block = samples_f[pos : pos + win] * hann
        spec = np.abs(np.fft.rfft(block, fft_size))
        band_spec = spec[band_idx]
        peak_local = int(np.argmax(band_spec))
        peak_global = int(band_idx[peak_local])
        peak_power = float(spec[peak_global] ** 2)

        # Noise floor: mean power across the band excluding +/- excl_bins
        # around the peak so the peak doesn't pollute its own reference.
        excl_mask = (band_idx < peak_global - excl_bins) | (band_idx > peak_global + excl_bins)
        if excl_mask.any():
            noise = float(np.mean(band_spec[excl_mask] ** 2)) + 1e-12
        else:
            noise = float(np.mean(band_spec ** 2)) + 1e-12
        snr_db = 10.0 * math.log10(max(peak_power, 1e-12) / noise)

        peak_freqs.append(float(freqs[peak_global]))
        peak_starts.append(pos)
        peak_snrs.append(snr_db)
        pos += hop

    if not peak_freqs:
        return []

    # Group consecutive high-SNR windows of stable frequency into runs.
    runs: List[Tuple[int, int, float]] = []  # (start_idx, end_idx_exclusive, mean_freq)
    i = 0
    n = len(peak_freqs)
    while i < n:
        if peak_snrs[i] < min_snr_db:
            i += 1
            continue
        f0 = peak_freqs[i]
        if any(abs(f0 - ef) < _EBS_FREQ_TOL for ef in _EBS_FREQS):
            i += 1
            continue
        j = i
        while (
            j < n
            and peak_snrs[j] >= min_snr_db
            and abs(peak_freqs[j] - f0) <= stability_tol_hz
        ):
            j += 1
        if j > i:
            runs.append((i, j, float(np.mean(peak_freqs[i:j]))))
        i = max(j, i + 1)

    if len(runs) < 2:
        return []

    detections: List[QC2Tone] = []
    used = [False] * len(runs)
    # Allow up to ~100 ms of dropout / silence between Tone A and Tone B.
    max_gap_windows = max(1, int(0.10 * sample_rate / hop))

    for a_idx in range(len(runs) - 1):
        if used[a_idx]:
            continue
        a_start, a_end, a_freq = runs[a_idx]
        a_dur = (peak_starts[a_end - 1] + win - peak_starts[a_start]) / sample_rate
        if not (_TONE_A_MIN_SEC <= a_dur <= _TONE_A_MAX_SEC):
            continue

        b_idx = a_idx + 1
        while b_idx < len(runs) and runs[b_idx][0] - a_end > max_gap_windows:
            b_idx += 1
        if b_idx >= len(runs) or used[b_idx]:
            continue
        b_start, b_end, b_freq = runs[b_idx]
        b_dur = (peak_starts[b_end - 1] + win - peak_starts[b_start]) / sample_rate
        if not (_TONE_B_MIN_SEC <= b_dur <= _TONE_B_MAX_SEC):
            continue
        if abs(a_freq - b_freq) < _AB_FREQ_SEPARATION:
            continue

        start_sample = peak_starts[a_start]
        end_sample = min(len(samples_f), peak_starts[b_end - 1] + win)
        snrs = peak_snrs[a_start:a_end] + peak_snrs[b_start:b_end]
        mean_snr = float(np.mean(snrs)) if snrs else min_snr_db
        confidence = max(0.0, min(1.0, (mean_snr - min_snr_db) / 18.0 + 0.5))

        detections.append(QC2Tone(
            tone_a_freq=a_freq,
            tone_b_freq=b_freq,
            tone_a_duration=a_dur,
            tone_b_duration=b_dur,
            start_sample=start_sample,
            end_sample=end_sample,
            sample_rate=sample_rate,
            confidence=confidence,
        ))
        used[a_idx] = True
        used[b_idx] = True

    return detections


__all__ = ["QC2Tone", "detect_qc2"]
