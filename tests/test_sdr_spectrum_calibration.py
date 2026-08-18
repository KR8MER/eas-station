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

Regression tests for compute_spectrum()'s dB calibration.

Reported live on the SDR Diagnostics page: both the Live Waterfall and
Spectrum Scope looked "zoomed in," with almost the whole passband pegged
to maximum brightness/height. Traced to sdr_hardware_service.py's
compute_spectrum(): the raw FFT magnitude was never divided by the
window's coherent gain (sum(window)) before converting to dB, so a
FFT_SIZE=2048 Hanning-windowed bin's magnitude read tens of dB higher
than the fixed SPECTRUM_DB_MIN=-80/SPECTRUM_DB_MAX=0 window assumed --
confirmed against a live capture where 1781 of 2048 bins (87%) clipped
to the normalized maximum of 1.0.

A single fixed dB window can't hold across every receiver/gain/antenna
combination anyway -- the same real signal reads at wildly different
absolute dBFS depending on gain settings. The fix replaces the fixed
window with per-capture normalization (stretch THIS capture's own
min/max dB span across 0-1), floored by MIN_SPECTRUM_DB_SPAN so a
near-silent capture isn't auto-amplified into apparent noise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sdr_hardware_service as svc


def _make_samples(n, tone_amplitude=0.3, tone_freq=0.05, noise_amplitude=0.01, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * noise_amplitude
    tone = tone_amplitude * np.exp(1j * 2 * np.pi * tone_freq * t)
    return (noise + tone).astype(np.complex64)


def test_returns_none_when_too_few_samples():
    samples = _make_samples(svc.FFT_SIZE - 1)
    assert svc.compute_spectrum(samples, np) is None


def test_output_length_matches_fft_size():
    samples = _make_samples(svc.FFT_SIZE * 2)
    result = svc.compute_spectrum(samples, np)
    assert result is not None
    assert len(result) == svc.FFT_SIZE


def test_output_bounded_to_unit_interval():
    samples = _make_samples(svc.FFT_SIZE * 2)
    result = svc.compute_spectrum(samples, np)
    assert all(0.0 <= v <= 1.0 for v in result)


def test_uses_full_dynamic_range_not_saturated():
    """The core regression: a moderate-strength signal must not pin the
    vast majority of bins to 1.0. Before the fix, an un-normalized FFT
    magnitude against a fixed -80..0 dB window did exactly that."""
    samples = _make_samples(svc.FFT_SIZE * 2, tone_amplitude=0.3, noise_amplitude=0.01)
    result = np.array(svc.compute_spectrum(samples, np))

    saturated_fraction = (result >= 0.999).mean()
    assert saturated_fraction < 0.10, (
        f"{saturated_fraction:.1%} of bins saturated at 1.0 -- spectrum display "
        "will look like a flat 'brick' instead of a legible shape"
    )
    # A real spread should use a meaningful chunk of the 0-1 range, not
    # bunch entirely near either extreme.
    assert result.std() > 0.05


def test_near_silent_capture_does_not_amplify_into_noise():
    """A near-flat input (e.g. no antenna, receiver just started) must not
    be auto-stretched into a wildly noisy-looking display -- the
    MIN_SPECTRUM_DB_SPAN floor should keep the span from collapsing to a
    near-zero divisor."""
    # Amplitude variation across bins for a near-DC, near-silent signal is
    # tiny; without the floor, dividing by that tiny span would blow any
    # residual numerical noise up to fill the whole 0-1 range.
    samples = _make_samples(svc.FFT_SIZE * 2, tone_amplitude=0.0, noise_amplitude=1e-6)
    result = np.array(svc.compute_spectrum(samples, np))
    # With a floored span, near-uniform (very low variance) magnitude
    # should stay clustered rather than spread wall-to-wall.
    assert result.std() < 0.3


def test_stronger_signal_still_spreads_reasonably():
    """A stronger tone (closer to full-scale) should still produce a
    legible, non-saturated spectrum -- the fix must not just move the
    saturation point rather than removing it."""
    samples = _make_samples(svc.FFT_SIZE * 2, tone_amplitude=0.9, noise_amplitude=0.02)
    result = np.array(svc.compute_spectrum(samples, np))
    saturated_fraction = (result >= 0.999).mean()
    assert saturated_fraction < 0.10


def test_peak_bin_reads_near_maximum():
    """Sanity check: the strongest bin (the tone) should still land near
    the top of the normalized range -- per-capture normalization stretches
    to the capture's own max, so the true peak is always ~1.0."""
    samples = _make_samples(svc.FFT_SIZE * 2, tone_amplitude=0.3, noise_amplitude=0.01)
    result = np.array(svc.compute_spectrum(samples, np))
    assert result.max() > 0.95
