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

"""Generic DSP helpers shared by the demodulators.

FM discrimination, decimation, FIR filter design and rate conversion. This is
the single source of truth for filter design and resampling in the radio
package.
"""

import math
from typing import Tuple

import numpy as np

from app_core.radio.demod.kernels import (
    _NUMBA_AVAILABLE,
    _fm_discriminator_declick_numba,
    _fm_discriminator_numba,
)


def fm_discriminator(iq_samples: np.ndarray) -> np.ndarray:
    """FM phase discriminator - dispatches to JIT or NumPy implementation.

    Args:
        iq_samples: Complex IQ samples (complex64)

    Returns:
        Audio samples (float32)
    """
    if _NUMBA_AVAILABLE and len(iq_samples) > 100:
        # Use JIT-compiled version for larger arrays
        return _fm_discriminator_numba(
            iq_samples.real.astype(np.float32),
            iq_samples.imag.astype(np.float32)
        )
    else:
        # Pure NumPy fallback
        phase_diff = iq_samples[1:] * np.conj(iq_samples[:-1])
        return np.angle(phase_diff).astype(np.float32)


def fm_discriminator_declick(
    iq_samples: np.ndarray,
    suppression_fraction: float,
    prev_phase: float = 0.0,
) -> Tuple[np.ndarray, int, float]:
    """FM phase discriminator with magnitude-aware click suppression.

    On strong-but-imperfect signals (e.g., Class B FM at 7 mi through
    suburban multipath) the IQ envelope dips momentarily to near zero
    during fades; the raw discriminator output during those dips is
    near-uniformly-distributed phase noise, which spectrally is a flat
    impulse floor that obliterates the 19 kHz pilot and 57 kHz RBDS
    subcarriers.  This routine detects those fades by their magnitude
    collapse and forward-fills the previous good phase.

    The threshold is recomputed per-chunk from the chunk's own RMS power,
    so it adapts to AGC gain changes without manual tuning.

    Args:
        iq_samples: Complex IQ samples (complex64)
        suppression_fraction: Fraction of mean |z|^2 below which a sample
            is treated as a click.  0.0 disables suppression; typical
            useful range is 0.05 to 0.3.  At 0.1 the threshold is 10 % of
            mean power per sample (i.e. ~20 % of peak instantaneous
            power for a CW signal), which catches deep fades without
            triggering on legitimate modulation peaks.
        prev_phase: Phase output of the last good sample from the
            previous chunk (or 0.0 on first call) — used as the
            forward-fill seed so a click at sample 0 doesn't have to
            wait for the next good sample.

    Returns:
        Tuple of:
            audio: Discriminator output (float32, length len(iq)-1)
            click_count: Number of samples that were suppressed
            last_phase: Phase of the last good sample (pass back as
                prev_phase on the next chunk)
    """
    if len(iq_samples) < 2:
        return np.array([], dtype=np.float32), 0, float(prev_phase)

    iq_array = np.ascontiguousarray(iq_samples)

    # Compute the per-chunk magnitude threshold.  Using the mean of |z|^2
    # rather than the median is a numpy one-liner and gives a result that
    # matches the dispersion of an AWGN-only chunk closely enough; on real
    # FM the envelope is dominated by the carrier so the mean and median
    # agree to within a few percent.
    mag_sq = (iq_array.real.astype(np.float64) ** 2
              + iq_array.imag.astype(np.float64) ** 2)
    mean_mag_sq = float(mag_sq.mean()) if mag_sq.size else 0.0

    # mag_threshold_sq is compared against |z[n]|^2 · |z[n-1]|^2.
    # A "click" is roughly |z| < frac · sqrt(mean|z|^2), so on the
    # product the threshold is (frac · mean|z|^2)^2.  Since we already
    # have mean|z|^2 this is one multiply.
    threshold_per_sample = suppression_fraction * mean_mag_sq
    mag_threshold_sq = threshold_per_sample * threshold_per_sample

    if _NUMBA_AVAILABLE and len(iq_array) > 100 and suppression_fraction > 0.0:
        audio, click_count, last_phase = _fm_discriminator_declick_numba(
            iq_array.real.astype(np.float32),
            iq_array.imag.astype(np.float32),
            np.float32(mag_threshold_sq),
            np.float32(prev_phase),
        )
        return audio, int(click_count), float(last_phase)

    # Pure NumPy fallback: compute the unsuppressed discriminator first,
    # then mask + forward-fill on the click positions.  Forward-fill in
    # pure numpy uses the classic "cumulative-max of an index column" trick
    # to vectorise; it's still O(N) and ~5× slower than the numba loop on
    # 1M-sample chunks but produces bit-identical output.
    phase_diff_complex = iq_array[1:] * np.conj(iq_array[:-1])
    audio = np.angle(phase_diff_complex).astype(np.float32)

    if suppression_fraction <= 0.0 or mag_threshold_sq <= 0.0:
        return audio, 0, float(audio[-1]) if audio.size else float(prev_phase)

    mag_product_sq = np.abs(phase_diff_complex) ** 2  # = |z1|^2·|z0|^2
    bad = mag_product_sq < mag_threshold_sq
    click_count = int(bad.sum())

    if click_count == 0:
        return audio, 0, float(audio[-1])

    # Forward-fill: build an index array that is i where good, and the
    # last good index otherwise.  Seed the first element with -1 mapping
    # to prev_phase via a prepend.
    good_idx = np.where(~bad, np.arange(audio.size), -1)
    np.maximum.accumulate(good_idx, out=good_idx)

    # Materialise values: indices that are still -1 (run of clicks at
    # head) get prev_phase, others get audio[idx].
    out = np.where(good_idx >= 0, audio[np.clip(good_idx, 0, None)],
                   np.float32(prev_phase)).astype(np.float32)

    # last_phase = last good sample's phase (or prev_phase if all clicks)
    last_phase = float(out[-1])
    return out, click_count, last_phase


def fast_decimate(samples: np.ndarray, factor: int) -> np.ndarray:
    """Box-filter decimation by averaging non-overlapping groups of samples.

    Crude anti-aliasing — a single zero-pole IIR or proper polyphase FIR
    would have a flatter passband — but the box filter is sufficient for
    moderate decimation ratios on the audio path and is essentially free:
    numpy's reshape+mean runs at ~1.5 ms per million samples, comfortably
    under 1% of real-time at 1 MHz.  A numba-JIT'd version used to live
    here too; benchmarking showed no measurable speedup over numpy, so
    the JIT branch was deleted along with its dispatcher.
    """
    if factor <= 1:
        return samples
    n_complete = (len(samples) // factor) * factor
    if n_complete == 0:
        return samples
    return (
        samples[:n_complete]
        .astype(np.float32)
        .reshape(-1, factor)
        .mean(axis=1)
        .astype(np.float32)
    )


# ---------------------------------------------------------------------------
# DSP helpers — single source of truth for filter design and resampling.
# ---------------------------------------------------------------------------


def design_fir_lowpass(cutoff: float, sample_rate: int, taps: int = 101) -> np.ndarray:
    """Blackman-windowed lowpass FIR via scipy.signal.firwin.

    Returns float32 coefficients normalised so |H(0)| = 1.
    """
    from scipy import signal as scipy_signal
    taps = int(taps) | 1  # firwin requires odd taps; harmless if already odd.
    h = scipy_signal.firwin(taps, cutoff, window='blackman', fs=sample_rate)
    return h.astype(np.float32)


def design_fir_bandpass(
    low: float, high: float, sample_rate: int, taps: int = 101
) -> np.ndarray:
    """Blackman-windowed bandpass FIR via scipy.signal.firwin.

    Returns float32 coefficients normalised so the passband centre has unity
    gain — the same contract the previous hand-rolled designer documented.
    scipy's `firwin` enforces odd `numtaps` for `pass_zero=False`, so we
    coerce to odd here too.
    """
    from scipy import signal as scipy_signal
    taps = int(taps) | 1
    h = scipy_signal.firwin(
        taps, [low, high], window='blackman', pass_zero=False, fs=sample_rate
    )
    return h.astype(np.float32)


def resample_to(signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Polyphase resample with a numpy-only fallback for ImportError.

    Handles both 1-D (mono / IQ) and 2-D shape-``(N, channels)`` inputs.
    This used to live as three near-identical methods on the demodulator
    classes; it's a free function now so they can share one implementation.
    """
    if from_rate == to_rate:
        return signal
    try:
        from scipy import signal as scipy_signal
        import math
        gcd = math.gcd(int(from_rate), int(to_rate))
        up = int(to_rate // gcd)
        down = int(from_rate // gcd)
        # Stereo arrays come through with shape (N, 2); pass axis=0 so each
        # channel is resampled independently.  1-D arrays default to axis=-1
        # which is the same axis for them, so this is safe in both cases.
        axis = 0 if signal.ndim == 2 else -1
        return scipy_signal.resample_poly(signal, up, down, axis=axis).astype(signal.dtype)
    except ImportError:
        new_length = int(len(signal) * to_rate / from_rate)
        old_indices = np.arange(len(signal))
        new_indices = np.linspace(0, len(signal) - 1, new_length)
        if signal.ndim == 2:
            channels = [
                np.interp(new_indices, old_indices, signal[:, ch])
                for ch in range(signal.shape[1])
            ]
            return np.column_stack(channels).astype(signal.dtype)
        if np.iscomplexobj(signal):
            real_resampled = np.interp(new_indices, old_indices, np.real(signal))
            imag_resampled = np.interp(new_indices, old_indices, np.imag(signal))
            return (real_resampled + 1j * imag_resampled).astype(signal.dtype)
        return np.interp(new_indices, old_indices, signal).astype(signal.dtype)


class StreamingResampler:
    """Sample-continuous rational resampler (polyphase FIR).

    :func:`scipy.signal.resample_poly` is stateless: applied per chunk it
    zero-feeds the filter at both edges and restarts the output grid on an
    integer sample boundary, so chunked streams pick up a fractional-sample
    time jump at every chunk boundary (an audible tick a few times per
    second) plus cumulative timing drift.  This class keeps the filter
    history *and* the output-grid phase across calls, making chunked output
    bit-identical to resampling one continuous stream.

    The anti-alias filter follows the same design rule as
    ``resample_poly``'s default (Kaiser beta=5.0, half-length
    10*max(up, down), cutoff at the lower of the two Nyquists).
    """

    def __init__(self, from_rate: int, to_rate: int):
        from scipy import signal as scipy_signal

        self.from_rate = int(from_rate)
        self.to_rate = int(to_rate)
        g = math.gcd(self.from_rate, self.to_rate)
        self.up = self.to_rate // g
        self.down = self.from_rate // g

        max_rate = max(self.up, self.down)
        half_len = 10 * max_rate
        h = scipy_signal.firwin(
            2 * half_len + 1, 1.0 / max_rate, window=("kaiser", 5.0)
        )
        h = (h * self.up).astype(np.float64)
        # Polyphase decomposition: branch p holds h[p], h[p+up], h[p+2*up]…
        taps_per_branch = -(-len(h) // self.up)
        h = np.concatenate([h, np.zeros(taps_per_branch * self.up - len(h))])
        # _hpoly[p, k] = h[p + k*up]
        self._hpoly = h.reshape(taps_per_branch, self.up).T.copy()
        self._taps = taps_per_branch
        # Last (taps-1) input samples, zero "history" before the stream
        # starts (matches a causal filter ringing up from silence).
        self._hist = np.zeros(self._taps - 1, dtype=np.float64)
        self._n_in = 0   # total input samples consumed
        self._m_out = 0  # total output samples emitted

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Resample the next chunk of the stream."""
        if self.up == self.down:
            return samples
        n_new = len(samples)
        if n_new == 0:
            return samples
        xext = np.concatenate([self._hist, np.asarray(samples, dtype=np.float64)])

        # Output m sits at upsampled-domain position m*down and needs
        # inputs up to n_max = floor(m*down / up); emit every m whose
        # inputs have fully arrived.
        m_end = -(-((self._n_in + n_new) * self.up) // self.down)
        ms = np.arange(self._m_out, m_end, dtype=np.int64)
        if ms.size:
            pos = ms * self.down
            phases = pos % self.up
            # Index of n_max within xext (xext[0] is input n_in - (taps-1)).
            nloc = pos // self.up - self._n_in + (self._taps - 1)
            idx = nloc[:, None] - np.arange(self._taps)[None, :]
            out = np.einsum("mk,mk->m", xext[idx], self._hpoly[phases])
        else:
            out = np.zeros(0, dtype=np.float64)

        if self._taps > 1:
            self._hist = xext[-(self._taps - 1):]
        self._n_in += n_new
        self._m_out = m_end
        return out.astype(samples.dtype, copy=False)

