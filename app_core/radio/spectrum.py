from __future__ import annotations
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

"""Shared FFT/dB-normalization spectrum math.

``compute_spectrum`` moved here verbatim from ``sdr_hardware_service.py``
(still importable as ``sdr_hardware_service.compute_spectrum`` -- a plain
``from ... import`` binds it into that module's namespace too, so nothing
that already calls it needed to change) so it can be reused by
``app_core.radio.demod.fm`` for the demodulated-baseband ("MPX") spectrum
without a service script importing into app_core in the wrong direction.

``compute_real_spectrum`` is the MPX sibling: ``compute_spectrum`` is
written for complex IQ (two-sided spectrum via ``fft`` + ``fftshift``);
the demodulator's ``multiplex`` signal is real-valued (radians/sample of
raw discriminator output), so its natural spectrum is one-sided
(``rfft``, 0 Hz to Nyquist) rather than a shifted two-sided one. The two
functions share the same windowing/dB-floor/per-capture-normalize
approach so the MPX and RF spectrum views look visually consistent, but
are kept as separate, independently-readable functions rather than one
parameterized do-everything function -- there are exactly two call
sites and they differ in real vs. complex input, not in some larger
family of variations.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Spectrum computation constants (moved from sdr_hardware_service.py
# alongside compute_spectrum -- see that function's docstring for why
# each value is what it is).
FFT_SIZE = 2048
FFT_MIN_MAGNITUDE = 1e-10
# Floor on the per-capture dB span used to normalize the spectrum to 0-1
# (see compute_spectrum()/compute_real_spectrum()) -- prevents a
# near-silent capture from being auto-amplified into apparent noise.
MIN_SPECTRUM_DB_SPAN = 10.0


def compute_spectrum(samples, numpy_module) -> Optional[list]:
    """Compute normalized spectrum from complex IQ samples (two-sided)."""
    try:
        if len(samples) < FFT_SIZE:
            return None

        # Remove DC offset
        samples_slice = samples[:FFT_SIZE]
        samples_centered = samples_slice - numpy_module.mean(samples_slice)

        # Apply window and compute FFT
        window = numpy_module.hanning(FFT_SIZE)
        windowed = samples_centered * window
        fft_result = numpy_module.fft.fftshift(numpy_module.fft.fft(windowed))

        # Convert to magnitude (dB), referenced to full-scale (dBFS) so a
        # unit-amplitude input reads ~0 dB at its bin. Without dividing by
        # the window's coherent gain (sum(window)), a raw FFT bin's
        # magnitude scales with FFT_SIZE and the window shape -- for
        # FFT_SIZE=2048 with a Hanning window, a full-scale tone's peak bin
        # sits around +54 dB raw, far above any reasonable fixed ceiling.
        magnitude = numpy_module.abs(fft_result) / numpy_module.sum(window)
        magnitude = numpy_module.where(magnitude > 0, magnitude, FFT_MIN_MAGNITUDE)
        magnitude_db = 20 * numpy_module.log10(magnitude)

        # Normalize to 0-1 range using THIS capture's own dB span, not a
        # fixed SPECTRUM_DB_MIN/MAX window. A fixed window can't hold for
        # every receiver/gain/antenna combination -- the absolute dBFS
        # level of "the same real signal" varies enormously with gain
        # settings and cable loss, so any single fixed calibration either
        # saturates strong signals at 1.0 (clips the useful shape away) or
        # crushes weak ones to 0.0. Reproduced live: with a fixed -80..0 dB
        # window, 87% of bins (1781/2048) on a real, moderate-strength FM
        # signal clipped to 1.0, flattening the waterfall and spectrum
        # scope into a saturated "brick" instead of a legible spectral
        # shape. Per-capture normalization always uses the full available
        # dynamic range instead. MIN_SPECTRUM_DB_SPAN floors the divisor so
        # a near-silent capture (no antenna, receiver just started) isn't
        # auto-amplified into apparent noise.
        db_min = float(numpy_module.min(magnitude_db))
        db_max = float(numpy_module.max(magnitude_db))
        span = max(db_max - db_min, MIN_SPECTRUM_DB_SPAN)
        normalized = numpy_module.clip((magnitude_db - db_min) / span, 0.0, 1.0)

        return normalized.tolist()
    except Exception as e:
        logger.debug(f"Spectrum computation error: {e}")
        return None


def compute_real_spectrum(samples, numpy_module, fft_size: int = FFT_SIZE) -> Optional[list]:
    """Compute a normalized one-sided (0 Hz to Nyquist) spectrum from a
    real-valued signal -- e.g. the FM demodulator's raw multiplex output.

    Same window/dB-floor/per-capture-normalize approach as
    ``compute_spectrum``, but using ``rfft`` (real FFT) instead of a
    complex two-sided FFT + fftshift, since a real input has no negative-
    frequency content to shift into view. Returns ``fft_size // 2 + 1``
    bins spanning 0 Hz to ``sample_rate / 2``.
    """
    try:
        if len(samples) < fft_size:
            return None

        samples_slice = samples[:fft_size]
        samples_centered = samples_slice - numpy_module.mean(samples_slice)

        window = numpy_module.hanning(fft_size)
        windowed = samples_centered * window
        fft_result = numpy_module.fft.rfft(windowed)

        magnitude = numpy_module.abs(fft_result) / numpy_module.sum(window)
        magnitude = numpy_module.where(magnitude > 0, magnitude, FFT_MIN_MAGNITUDE)
        magnitude_db = 20 * numpy_module.log10(magnitude)

        db_min = float(numpy_module.min(magnitude_db))
        db_max = float(numpy_module.max(magnitude_db))
        span = max(db_max - db_min, MIN_SPECTRUM_DB_SPAN)
        normalized = numpy_module.clip((magnitude_db - db_min) / span, 0.0, 1.0)

        return normalized.tolist()
    except Exception as e:
        logger.debug(f"Real-spectrum computation error: {e}")
        return None
