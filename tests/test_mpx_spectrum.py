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

"""Tests for compute_real_spectrum (app_core/radio/spectrum.py) and its
rate-limited use in FMDemodulator.demodulate() for the MPX spectrum.

compute_real_spectrum is the one genuinely new piece of math in this
feature -- a one-sided (rfft) sibling of the existing compute_spectrum,
for the demodulator's real-valued multiplex signal rather than complex
IQ. Correctness here means "a signal with tones at known frequencies
produces peaks at the right bins," not just "the field threads through."
"""

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.spectrum import compute_real_spectrum, FFT_SIZE  # noqa: E402
from app_core.radio.demod import DemodulatorConfig, FMDemodulator  # noqa: E402


SR = 250_000


def _bin_freq(bin_index: int, fft_size: int, sample_rate: int) -> float:
    """Center frequency of an rfft bin (0 Hz to Nyquist)."""
    return bin_index * sample_rate / fft_size


def test_two_known_tones_produce_peaks_at_the_right_bins():
    """A synthetic multiplex with pure tones at 19 kHz and 57 kHz must
    show its spectrum peaks within one FFT bin of those frequencies."""
    n = FFT_SIZE
    t = np.arange(n) / SR
    signal = (
        1.0 * np.cos(2 * np.pi * 19_000.0 * t)
        + 0.5 * np.cos(2 * np.pi * 57_000.0 * t)
    ).astype(np.float64)

    spectrum = compute_real_spectrum(signal, np)
    assert spectrum is not None
    spectrum = np.array(spectrum)

    bin_width_hz = SR / FFT_SIZE
    # Only search the lower half (below ~95 kHz) -- matches the frontend's
    # default zoom and keeps this test from accidentally matching a
    # spurious peak elsewhere in a 125 kHz-wide one-sided spectrum.
    search_max_bin = int(95_000 / bin_width_hz)

    pilot_bin_expected = int(round(19_000.0 / bin_width_hz))
    rds_bin_expected = int(round(57_000.0 / bin_width_hz))

    search_region = spectrum[:search_max_bin]
    # The two loudest peaks (separated enough not to be adjacent bins of
    # the same lobe) should land near the two known tone frequencies.
    peak_bin_1 = int(np.argmax(search_region))
    assert abs(peak_bin_1 - pilot_bin_expected) <= 1, (
        f"Expected a peak near bin {pilot_bin_expected} (19 kHz), "
        f"found the global peak at bin {peak_bin_1} "
        f"({_bin_freq(peak_bin_1, FFT_SIZE, SR):.0f} Hz)"
    )

    # Zero out a window around the first peak and find the next one.
    window = max(2, int(2_000 / bin_width_hz))
    masked = search_region.copy()
    masked[max(0, peak_bin_1 - window):peak_bin_1 + window] = 0
    peak_bin_2 = int(np.argmax(masked))
    assert abs(peak_bin_2 - rds_bin_expected) <= 1, (
        f"Expected a second peak near bin {rds_bin_expected} (57 kHz), "
        f"found it at bin {peak_bin_2} "
        f"({_bin_freq(peak_bin_2, FFT_SIZE, SR):.0f} Hz)"
    )


def test_output_is_one_sided_half_length():
    """rfft output length is fft_size // 2 + 1, not the full two-sided
    fft_size a complex spectrum would have -- confirms this is genuinely
    using the real-FFT path, not accidentally the complex one."""
    n = FFT_SIZE
    t = np.arange(n) / SR
    signal = np.cos(2 * np.pi * 19_000.0 * t)

    spectrum = compute_real_spectrum(signal, np)
    assert spectrum is not None
    assert len(spectrum) == FFT_SIZE // 2 + 1


def test_returns_none_for_too_few_samples():
    spectrum = compute_real_spectrum(np.zeros(10), np)
    assert spectrum is None


def test_output_bounded_to_unit_interval():
    n = FFT_SIZE
    t = np.arange(n) / SR
    signal = np.cos(2 * np.pi * 19_000.0 * t) + 0.01 * np.random.randn(n)

    spectrum = compute_real_spectrum(signal, np)
    assert spectrum is not None
    arr = np.array(spectrum)
    assert arr.min() >= 0.0
    assert arr.max() <= 1.0


def test_demodulator_rate_limits_mpx_spectrum_computation():
    """demodulate() must not recompute the MPX spectrum on every chunk --
    only when _MPX_SPECTRUM_INTERVAL_S has elapsed since the last one."""
    cfg = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=SR,
        audio_sample_rate=48_000,
        stereo_enabled=True,
        enable_rbds=False,
    )
    demod = FMDemodulator(cfg)
    assert demod.last_mpx_spectrum is None
    assert demod.last_mpx_spectrum_fresh is False

    chunk = np.exp(1j * np.cumsum(
        2 * np.pi * 6_750.0 * np.cos(2 * np.pi * 19_000.0 * np.arange(4096) / SR) / SR
    )).astype(np.complex64)

    # First call: interval has "elapsed" (initialized to 0.0), so this
    # should compute and mark fresh.
    demod.demodulate(chunk)
    assert demod.last_mpx_spectrum is not None
    assert demod.last_mpx_spectrum_fresh is True

    # Immediately calling again must NOT recompute -- fresh flag clears.
    demod.demodulate(chunk)
    assert demod.last_mpx_spectrum_fresh is False

    # Force the gate to look elapsed and confirm it recomputes again.
    demod._last_mpx_spectrum_at = 0.0
    demod.demodulate(chunk)
    assert demod.last_mpx_spectrum_fresh is True


def _fm_modulate(inst_freq_hz: np.ndarray, sample_rate: int) -> np.ndarray:
    """Synthesize complex baseband IQ for an instantaneous-frequency
    trajectory -- same helper as test_fm_deviation_injection_metrics.py."""
    phase = np.cumsum(2.0 * np.pi * inst_freq_hz / sample_rate)
    return np.exp(1j * phase).astype(np.complex64)


def test_mpx_waveform_is_captured_alongside_the_spectrum():
    """The raw MPX oscilloscope trace is captured on the same gate as the
    spectrum FFT -- present and length-bounded whenever the spectrum is
    fresh, in Hz units (not raw radians/sample)."""
    cfg = DemodulatorConfig(
        modulation_type="FM", sample_rate=SR, audio_sample_rate=48_000,
        stereo_enabled=True, enable_rbds=False,
    )
    demod = FMDemodulator(cfg)
    assert demod.last_mpx_waveform is None

    n = 8192
    t = np.arange(n) / SR
    inst_freq = 6_750.0 * np.cos(2 * np.pi * 19_000.0 * t)
    chunk = _fm_modulate(inst_freq, SR)

    demod.demodulate(chunk)
    assert demod.last_mpx_spectrum_fresh is True
    assert demod.last_mpx_waveform is not None
    assert 0 < len(demod.last_mpx_waveform) <= demod._SCOPE_SNAPSHOT_SAMPLES
    # Hz-scale, not radians/sample -- a 6.75 kHz-peak tone shouldn't produce
    # a trace with values in the thousands-of-radians range a unit mixup
    # would cause.
    assert max(abs(v) for v in demod.last_mpx_waveform) < 50_000.0


def test_mpx_waveform_length_capped_when_chunk_is_larger():
    """A chunk longer than _SCOPE_SNAPSHOT_SAMPLES must still only capture
    a fixed-size slice, not the whole chunk."""
    cfg = DemodulatorConfig(
        modulation_type="FM", sample_rate=SR, audio_sample_rate=48_000,
        stereo_enabled=True, enable_rbds=False,
    )
    demod = FMDemodulator(cfg)
    n = demod._SCOPE_SNAPSHOT_SAMPLES * 4
    t = np.arange(n) / SR
    inst_freq = 6_750.0 * np.cos(2 * np.pi * 19_000.0 * t)
    chunk = _fm_modulate(inst_freq, SR)

    demod.demodulate(chunk)
    assert len(demod.last_mpx_waveform) == demod._SCOPE_SNAPSHOT_SAMPLES


def _synthesize_stereo_multiplex_hz(left_hz, right_hz, sample_rate, pilot_hz=19_000.0, pilot_amplitude_hz=6_750.0):
    """Composite (L+R) + pilot + (L-R) DSB-SC multiplex, expressed directly
    in Hz (instantaneous-frequency-contribution units), matching how
    test_fm_deviation_injection_metrics.py treats single-tone signals."""
    n = len(left_hz)
    t = np.arange(n) / sample_rate
    lpr = (left_hz + right_hz) * 0.5
    lmr = (left_hz - right_hz) * 0.5
    pilot = pilot_amplitude_hz * np.cos(2 * np.pi * pilot_hz * t)
    subcarrier = lmr * np.cos(2 * np.pi * (2 * pilot_hz) * t)
    return lpr + pilot + subcarrier


def test_audio_scope_present_when_stereo_is_locked():
    """L/R oscilloscope traces are populated once the pilot is locked."""
    cfg = DemodulatorConfig(
        modulation_type="FM", sample_rate=SR, audio_sample_rate=48_000,
        stereo_enabled=True, enable_rbds=False,
    )
    demod = FMDemodulator(cfg)
    n = int(SR * 0.05)
    t = np.arange(n) / SR
    left_hz = 10_000.0 * np.cos(2 * np.pi * 300.0 * t)
    right_hz = 10_000.0 * np.cos(2 * np.pi * 300.0 * t)
    multiplex_hz = _synthesize_stereo_multiplex_hz(left_hz, right_hz, SR)
    chunk = _fm_modulate(multiplex_hz, SR)

    audio, status = demod.demodulate(chunk)
    assert status.stereo_pilot_locked
    assert demod.last_audio_scope_left is not None
    assert demod.last_audio_scope_right is not None
    assert 0 < len(demod.last_audio_scope_left) <= demod._SCOPE_SNAPSHOT_SAMPLES
    assert len(demod.last_audio_scope_left) == len(demod.last_audio_scope_right)


def test_audio_scope_absent_for_mono_signal():
    """No pilot -> mono path -> no separate L/R trace to show, and any
    stale trace from an earlier stereo-locked chunk must be cleared."""
    cfg = DemodulatorConfig(
        modulation_type="FM", sample_rate=SR, audio_sample_rate=48_000,
        stereo_enabled=True, enable_rbds=False,
    )
    demod = FMDemodulator(cfg)
    n = int(SR * 0.02)
    t = np.arange(n) / SR
    # A plain audio-band tone with no 19 kHz pilot at all -- never locks.
    inst_freq = 5_000.0 * np.cos(2 * np.pi * 1_000.0 * t)
    chunk = _fm_modulate(inst_freq, SR)

    audio, status = demod.demodulate(chunk)
    assert not status.stereo_pilot_locked
    assert demod.last_audio_scope_left is None
    assert demod.last_audio_scope_right is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
