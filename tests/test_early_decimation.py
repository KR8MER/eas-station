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

Tests for the early decimator in app_core/radio/drivers.py.

These verify that the FIR anti-alias filter installed at stream start
actually rejects out-of-band energy that would otherwise fold onto the
57 kHz RBDS subcarrier (and 38 kHz FM-stereo L-R) after the 10x
decimation Airspy uses (2.5 MHz → 250 kHz), and that the in-band
response across the RBDS passband is flat.
"""

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.drivers import RTLSDRReceiver, _SCIPY_AVAILABLE
from app_core.radio.manager import ReceiverConfig


pytestmark = pytest.mark.skipif(
    not _SCIPY_AVAILABLE,
    reason="SciPy is required for FIR-based early decimation",
)


SAMPLE_RATE = 2_500_000  # Airspy-style high rate that triggers early decim
TARGET_RATE = 250_000     # Post-decim rate (RBDSWorker's design point)


def _make_receiver():
    config = ReceiverConfig(
        identifier="early-decim-test",
        driver="rtlsdr",
        frequency_hz=98_500_000,
        sample_rate=SAMPLE_RATE,
        gain=10.0,
        auto_start=False,
    )
    receiver = RTLSDRReceiver(config)
    receiver._initialize_sample_buffer(np)
    return receiver


def _filter_and_decimate(receiver, signal):
    """Run a single chunk through the FIR + stride-N downsample, the
    way the driver's hot path does it (zi carried across calls)."""
    from scipy import signal as scipy_signal

    h = receiver._early_decim_aa_filter
    decim = receiver._early_decim_factor
    # Seed zi as the hot path does on the first chunk.
    zi = scipy_signal.lfilter_zi(h, 1.0).astype(np.complex64) * signal[0]
    filtered, _ = scipy_signal.lfilter(h, 1.0, signal, zi=zi)
    n = (len(filtered) // decim) * decim
    return filtered[:n:decim].astype(np.complex64)


def test_effective_sample_rate_matches_target():
    receiver = _make_receiver()
    # 2.5 MHz / 250 kHz target -> decim=10, effective=250 kHz
    assert receiver._early_decim_factor == 10
    assert receiver.get_effective_sample_rate() == TARGET_RATE


def test_fir_anti_alias_filter_was_built():
    receiver = _make_receiver()
    h = receiver._early_decim_aa_filter
    assert h is not None
    # Linear-phase symmetric FIR: odd tap count, real coefficients.
    assert len(h) % 2 == 1
    assert 127 <= len(h) <= 1025
    # Tap-count heuristic: (sample_rate / 4000) | 1, clamped to [127, 1025].
    # 2.5 MHz / 4000 = 625, which is already odd, so | 1 is a no-op here.
    assert len(h) == 625


def test_alias_image_is_rejected():
    """A complex tone at an alias image (input-rate frequency that
    folds onto 57 kHz after decim) must be suppressed by at least 45 dB.

    With decim=10, the first alias image of the 57 kHz post-decim bin
    sits at 250_000 - 57_000 = 193_000 Hz in the input spectrum.  The
    legacy boxcar (block-average) gave only ~18-25 dB rejection there.
    """
    receiver = _make_receiver()
    fs = SAMPLE_RATE
    duration = 0.05  # 50 ms — enough to flush filter transient
    n = int(fs * duration)
    t = np.arange(n) / fs
    alias_freq = 193_000.0   # folds to 57 kHz post-decim-10
    signal = np.exp(2j * np.pi * alias_freq * t).astype(np.complex64)

    out = _filter_and_decimate(receiver, signal)
    # Trim the FIR group delay's startup transient before measuring.
    settle = len(receiver._early_decim_aa_filter) // receiver._early_decim_factor + 32
    trimmed = out[settle:]
    peak = float(np.max(np.abs(trimmed)))
    # Reference is unity input amplitude.
    rejection_db = -20.0 * np.log10(max(peak, 1e-12))
    assert rejection_db >= 45.0, (
        f"Alias image at {alias_freq:.0f} Hz rejected by only "
        f"{rejection_db:.1f} dB (need ≥45 dB)"
    )


@pytest.mark.parametrize("tone_hz", [54_000.0, 57_000.0, 60_000.0])
def test_rbds_passband_is_flat(tone_hz):
    """The 54-60 kHz RBDS passband must come through within ±0.5 dB so
    the subcarrier isn't tilted across its 4 kHz of bandwidth.
    """
    receiver = _make_receiver()
    fs = SAMPLE_RATE
    duration = 0.05
    n = int(fs * duration)
    t = np.arange(n) / fs
    signal = np.exp(2j * np.pi * tone_hz * t).astype(np.complex64)

    out = _filter_and_decimate(receiver, signal)
    settle = len(receiver._early_decim_aa_filter) // receiver._early_decim_factor + 32
    trimmed = out[settle:]
    peak = float(np.max(np.abs(trimmed)))
    # Linear-phase FIR has unity DC gain; in-band tones should ride
    # near 1.0.  Allow ±0.5 dB across the RBDS band.
    gain_db = 20.0 * np.log10(max(peak, 1e-12))
    assert -0.5 <= gain_db <= 0.5, (
        f"In-band tone at {tone_hz:.0f} Hz had gain {gain_db:+.2f} dB "
        f"(need within ±0.5 dB)"
    )


def test_low_rate_receiver_bypasses_early_decim():
    """RTL-SDR-style 250 kHz native rate must not enable early decim
    (no filter built, no effective-rate change)."""
    config = ReceiverConfig(
        identifier="rtl-passthrough",
        driver="rtlsdr",
        frequency_hz=98_500_000,
        sample_rate=250_000,
        gain=10.0,
        auto_start=False,
    )
    receiver = RTLSDRReceiver(config)
    receiver._initialize_sample_buffer(np)
    assert receiver._early_decim_factor == 1
    assert receiver._early_decim_aa_filter is None
    assert receiver.get_effective_sample_rate() == 250_000
