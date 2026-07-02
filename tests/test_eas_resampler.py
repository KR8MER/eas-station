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

Tests for the stateful EAS ingest resampler.

Covers the chunk-boundary continuity fix: the previous implementation
resampled every ~100 ms capture chunk independently, stamping a filter-edge
transient onto each boundary (~10 glitches/second on 44.1 kHz sources) and
dropping ``len % factor`` samples per chunk on the integer-decimation path.
The streaming resampler must produce output identical to resampling the
whole signal at once, regardless of how the stream is chunked.
"""

import sys
from math import gcd
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.eas_resampler import (
    StreamingIntegerDecimator,
    StreamingPolyphaseResampler,
    make_eas_resampler,
)

TARGET = 16000


def _same_band_signal(rate: int, seconds: float = 6.0) -> np.ndarray:
    """Attention-tone + SAME FSK mark-tone content — what the EAS path carries."""
    t = np.arange(int(seconds * rate)) / rate
    return (
        0.3 * np.sin(2 * np.pi * 853 * t)
        + 0.3 * np.sin(2 * np.pi * 960 * t)
        + 0.2 * np.sin(2 * np.pi * 2083 * t)
    ).astype(np.float32)


def _stream_in_ragged_chunks(resampler, signal: np.ndarray, rate: int, seed: int = 0):
    """Feed the signal in random 50-150 ms chunks like the capture loop."""
    rng = np.random.default_rng(seed)
    out = []
    i = 0
    while i < len(signal):
        n = int(rng.uniform(0.05, 0.15) * rate)
        piece = resampler.process(signal[i:i + n])
        if piece is not None and len(piece):
            out.append(piece)
        i += n
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)


def _whole_signal_reference(signal: np.ndarray, rate: int) -> np.ndarray:
    from scipy.signal import firwin, resample_poly

    g = gcd(rate, TARGET)
    up, down = TARGET // g, rate // g
    max_rate = max(up, down)
    half_len = 10 * max_rate
    taps = firwin(2 * half_len + 1, 1.0 / max_rate, window=('kaiser', 5.0))
    return resample_poly(signal, up, down, window=taps.copy())


def test_polyphase_streamed_output_matches_whole_signal_resample():
    for rate in (44100, 22050, 24000, 11025):
        sig = _same_band_signal(rate)
        streamed = _stream_in_ragged_chunks(
            StreamingPolyphaseResampler(rate, TARGET), sig, rate
        )
        ref = _whole_signal_reference(sig, rate)
        n = min(len(streamed), len(ref))
        assert n > TARGET * 4, f"{rate}: too little output ({n} samples)"
        err = streamed[:n] - ref[:n]
        rms_ratio = np.sqrt((err ** 2).mean()) / np.sqrt((ref[:n] ** 2).mean())
        # Float32 rounding only — the old per-chunk implementation measured
        # ~1 % rms (-40 dB) with 13 % boundary spikes.
        assert rms_ratio < 1e-5, (
            f"{rate}: streamed resample deviates from whole-signal reference "
            f"({20 * np.log10(rms_ratio):.1f} dB)"
        )


def test_polyphase_no_chunk_boundary_spikes():
    rate = 44100
    sig = _same_band_signal(rate)
    streamed = _stream_in_ragged_chunks(
        StreamingPolyphaseResampler(rate, TARGET), sig, rate
    )
    ref = _whole_signal_reference(sig, rate)
    n = min(len(streamed), len(ref))
    err = np.abs(streamed[:n] - ref[:n])
    # Old implementation: worst 1 ms window ~13 % of signal amplitude.
    assert err.max() < 1e-4, f"boundary spike detected: max err {err.max():.4f}"


def test_integer_decimator_drops_no_samples():
    factor = 3
    dec = StreamingIntegerDecimator(factor)
    rng = np.random.default_rng(7)
    total_in = 0
    total_out = 0
    # Chunk sizes deliberately NOT divisible by the factor (old code dropped
    # len % factor samples on every such chunk).
    for _ in range(200):
        n = int(rng.integers(1000, 5000))
        if n % factor == 0:
            n += 1
        chunk = rng.standard_normal(n).astype(np.float32)
        out = dec.process(chunk)
        total_in += n
        total_out += len(out)
    assert total_out == total_in // factor


def test_integer_decimator_output_matches_whole_signal():
    factor = 3
    rate = 48000
    sig = _same_band_signal(rate, seconds=3.0)
    dec = StreamingIntegerDecimator(factor)
    out = []
    for i in range(0, len(sig), 4096):  # 4096 % 3 != 0 — the failing case
        out.append(dec.process(sig[i:i + 4096]))
    got = np.concatenate(out)
    expect_n = len(sig) // factor
    whole = sig[: expect_n * factor].reshape(-1, factor).mean(axis=1)
    n = min(len(got), len(whole))
    assert n == expect_n
    assert np.abs(got[:n] - whole[:n]).max() < 1e-6


def test_make_eas_resampler_selects_correct_implementation():
    assert make_eas_resampler(16000) is None
    assert isinstance(make_eas_resampler(48000), StreamingIntegerDecimator)
    assert isinstance(make_eas_resampler(32000), StreamingIntegerDecimator)
    assert isinstance(make_eas_resampler(44100), StreamingPolyphaseResampler)
    assert isinstance(make_eas_resampler(22050), StreamingPolyphaseResampler)


def test_polyphase_handles_empty_and_none_chunks():
    rs = StreamingPolyphaseResampler(44100, TARGET)
    assert len(rs.process(np.empty(0, dtype=np.float32))) == 0
    assert len(rs.process(None)) == 0
    # Still works after the degenerate calls
    sig = _same_band_signal(44100, seconds=1.0)
    out = rs.process(sig)
    assert len(out) > 0
