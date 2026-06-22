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

"""Tests for FMDemodulator stereo (L-R) decoding.

Synthesizes a baseband FM multiplex signal (L+R + 19 kHz pilot + L-R modulated
on 38 kHz DSB-SC) with known L and R tones, runs it through ``_decode_stereo``
and verifies that the recovered channels achieve good separation.

These tests pin down the regression that was hiding behind the CHANGELOG entry
"FM stereo decoding (L-R separation) not yet implemented; only pilot detection
works".  Before the fix, the decoder used a free-running 38 kHz oscillator that
reset its phase on every chunk, so with any pilot frequency offset (always the
case in practice — SDR clocks differ from the broadcaster's by tens of ppm) the
L-R signal slowly rotated against the carrier and channel separation collapsed
to near zero.  After the fix the 38 kHz reference is derived from the recovered
pilot itself (cos²ωt = ½(1 + cos 2ωt)), making it phase-coherent by
construction.
"""

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.demodulation import (  # noqa: E402
    DemodulatorConfig,
    FMDemodulator,
)


SR = 250_000  # 250 kHz multiplex sample rate (typical FM broadcast IF)


def _make_fm_demodulator(sample_rate: int = SR) -> FMDemodulator:
    cfg = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=sample_rate,
        audio_sample_rate=48_000,
        stereo_enabled=True,
        enable_rbds=False,
    )
    return FMDemodulator(cfg)


def _synthesize_multiplex(
    left: np.ndarray,
    right: np.ndarray,
    sample_rate: int = SR,
    pilot_hz: float = 19_000.0,
    pilot_phase: float = 0.0,
    pilot_amplitude: float = 0.10,
) -> np.ndarray:
    """Build a baseband FM multiplex: (L+R) + pilot + (L-R) DSB-SC at 2·pilot_hz.

    Both the pilot and the 38 kHz subcarrier inherit ``pilot_phase`` so the
    decoded L-R aligns correctly with the L+R component.
    """
    n = len(left)
    t = np.arange(n) / sample_rate
    lpr = (left + right) * 0.5  # baseband L+R, ≤15 kHz tones expected
    lmr = (left - right) * 0.5  # baseband L-R, will be DSB-SC modulated
    pilot = pilot_amplitude * np.cos(2 * np.pi * pilot_hz * t + pilot_phase)
    subcarrier = lmr * np.cos(2 * np.pi * (2 * pilot_hz) * t + 2 * pilot_phase)
    return lpr + pilot + subcarrier


def _power_at(sig: np.ndarray, freq: float, sr: int = SR) -> float:
    """Single-bin Goertzel-style spectral power estimate."""
    n = len(sig)
    t = np.arange(n) / sr
    c = float(np.sum(sig * np.cos(2 * np.pi * freq * t)) / n)
    s = float(np.sum(sig * np.sin(2 * np.pi * freq * t)) / n)
    return 2.0 * (c * c + s * s)


def _separation_db(channel: np.ndarray, signal_freq: float, leak_freq: float) -> float:
    p_signal = _power_at(channel, signal_freq)
    p_leak = max(_power_at(channel, leak_freq), 1e-12)
    return 10.0 * float(np.log10(p_signal / p_leak))


def _make_test_signals(sample_rate: int = SR, duration: float = 0.5):
    n = int(sample_rate * duration)
    t = np.arange(n) / sample_rate
    left = 0.4 * np.cos(2 * np.pi * 1000 * t)   # 1 kHz tone in L only
    right = 0.4 * np.cos(2 * np.pi * 2000 * t)  # 2 kHz tone in R only
    return left, right


def _trim_filter_ramp(stereo: np.ndarray, samples: int = 5000):
    return stereo[samples:-samples, 0], stereo[samples:-samples, 1]


def test_stereo_decode_basic_separation():
    """With a perfect 19 kHz pilot, L and R should be cleanly separated."""
    demod = _make_fm_demodulator()
    left, right = _make_test_signals()
    multiplex = _synthesize_multiplex(left, right, pilot_phase=0.7)

    stereo = demod._decode_stereo(multiplex, np.arange(len(multiplex), dtype=np.float64))
    assert stereo is not None, "stereo decode returned None despite strong pilot"
    assert stereo.ndim == 2 and stereo.shape[1] == 2

    L, R = _trim_filter_ramp(stereo)
    sep_L = _separation_db(L, 1000, 2000)
    sep_R = _separation_db(R, 2000, 1000)

    # Real FM stereo decoders typically achieve 30-40 dB; in this clean
    # synthetic test we expect significantly more.
    assert sep_L > 30, f"L-channel separation only {sep_L:.1f} dB"
    assert sep_R > 30, f"R-channel separation only {sep_R:.1f} dB"


def test_stereo_decode_tracks_pilot_frequency_offset():
    """A pilot offset by +12 Hz must not collapse channel separation.

    This is the regression that motivated the fix: a free-running 38 kHz
    oscillator (the previous implementation) loses lock against any pilot
    that isn't *exactly* 19000 Hz.  The pilot-derived carrier (cos²ωt) is
    phase-coherent with the actual recovered pilot, so frequency offsets
    inherent to SDR clock error don't matter.
    """
    demod = _make_fm_demodulator()
    left, right = _make_test_signals()
    multiplex = _synthesize_multiplex(
        left, right,
        pilot_hz=19_012.0,         # +12 Hz from nominal (≈630 ppm clock skew)
        pilot_phase=1.3,
    )

    stereo = demod._decode_stereo(multiplex, np.arange(len(multiplex), dtype=np.float64))
    assert stereo is not None

    L, R = _trim_filter_ramp(stereo)
    sep_L = _separation_db(L, 1000, 2000)
    sep_R = _separation_db(R, 2000, 1000)
    assert sep_L > 30, f"L-channel separation collapsed under pilot offset: {sep_L:.1f} dB"
    assert sep_R > 30, f"R-channel separation collapsed under pilot offset: {sep_R:.1f} dB"


def test_stereo_decode_returns_none_on_silent_multiplex():
    """An effectively silent multiplex must not produce stereo output.

    A real mono FM broadcast has no 19 kHz pilot and no L-R subcarrier — the
    multiplex is just (L+R) below 15 kHz.  ``_decode_stereo`` should refuse to
    fabricate a stereo image from such a signal, so the caller falls back to
    mono cleanly.  (The higher-level ``demodulate()`` already guards on the
    pilot-lock threshold; this exercises the safety check inside the decoder
    itself.)
    """
    demod = _make_fm_demodulator()
    n = int(SR * 0.5)
    multiplex = np.zeros(n, dtype=np.float32)  # pure silence

    stereo = demod._decode_stereo(multiplex, np.arange(n, dtype=np.float64))
    assert stereo is None, "stereo decode should yield None when no pilot is present"


def test_stereo_decode_chunk_phase_independence():
    """Splitting a signal into chunks must not break channel separation.

    The previous synthetic-oscillator implementation reset its phase to 0
    every chunk, so the second half of a stream would decode against a
    completely different carrier phase than the first half.  The pilot-
    derived carrier is locked to the pilot in *each* chunk independently,
    so per-chunk decode should match the joint decode.
    """
    demod = _make_fm_demodulator()
    left, right = _make_test_signals(duration=0.6)
    multiplex = _synthesize_multiplex(left, right, pilot_phase=2.1)

    half = len(multiplex) // 2
    s1 = demod._decode_stereo(multiplex[:half], np.arange(half, dtype=np.float64))
    s2 = demod._decode_stereo(multiplex[half:], np.arange(len(multiplex) - half, dtype=np.float64))
    assert s1 is not None and s2 is not None

    # Drop the filter ramp at each chunk's edges so we evaluate steady-state.
    pad = 5000
    L1 = s1[pad:-pad, 0]
    R1 = s1[pad:-pad, 1]
    L2 = s2[pad:-pad, 0]
    R2 = s2[pad:-pad, 1]

    for label, ch, sig_f, leak_f in [
        ("L chunk 1", L1, 1000, 2000),
        ("R chunk 1", R1, 2000, 1000),
        ("L chunk 2", L2, 1000, 2000),
        ("R chunk 2", R2, 2000, 1000),
    ]:
        sep = _separation_db(ch, sig_f, leak_f)
        assert sep > 30, f"{label} separation only {sep:.1f} dB (chunk-boundary regression)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
