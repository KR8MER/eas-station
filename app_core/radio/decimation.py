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

"""Canonical early-decimation math, shared by the SDR drivers and the web layer.

High sample-rate SDRs (Airspy at 2.5-10 MHz, RTL-SDR at 2.4 MHz) are
decimated in the USB callback *before* samples reach the ring buffer --
Python cannot process multi-megahertz IQ in real time. Every downstream
consumer therefore sees ``effective_sample_rate``, not the configured
hardware rate, and the RF span the samples actually cover is
``effective_sample_rate`` wide, not ``config.sample_rate`` wide.

That distinction used to live only inside
``_SoapySDRReceiver._initialize_sample_buffer``. The web layer had no way
to reach it, so ``/api/radio/spectrum`` labelled the live waterfall and
spectrum scope axes with the *configured* rate -- drawing a 200 kHz-wide
FM broadcast signal as if it were 1 MHz wide on a receiver configured for
1.024 MHz (decim 4, effective 256 kHz). These helpers are the single
source of truth so the driver and the axis labels can never disagree.

Deliberately free of numpy/SciPy/SoapySDR imports so the webapp can use
it without pulling in the SDR stack.
"""

# Target intermediate rate after early decimation (Hz). 250 kHz comfortably
# passes the full FM multiplex -- 19 kHz pilot, 38 kHz stereo L-R, 57 kHz
# RBDS -- while being slow enough for real-time NumPy processing.
EARLY_DECIM_TARGET_RATE = 250_000

__all__ = [
    "EARLY_DECIM_TARGET_RATE",
    "early_decimation_factor",
    "effective_sample_rate",
    "spectrum_span_hz",
]


def early_decimation_factor(configured_sample_rate) -> int:
    """Return the integer decimation factor applied at stream start.

    Mirrors ``_SoapySDRReceiver._initialize_sample_buffer`` exactly:
    decimation only engages above 2x the target rate, so rates at or below
    500 kHz pass through untouched (factor 1).

    Args:
        configured_sample_rate: Hardware sample rate in Hz, as configured
            on the ``RadioReceiver`` row.

    Returns:
        Decimation factor >= 1.
    """
    try:
        rate = int(configured_sample_rate or 0)
    except (TypeError, ValueError):
        return 1
    if rate <= EARLY_DECIM_TARGET_RATE * 2:
        return 1
    return max(1, rate // EARLY_DECIM_TARGET_RATE)


def effective_sample_rate(configured_sample_rate) -> int:
    """Return the post-decimation sample rate downstream consumers see.

    This is the rate the ring buffer, the demodulator, the FFT in
    ``compute_spectrum`` and every capture are all clocked at.

    Args:
        configured_sample_rate: Hardware sample rate in Hz.

    Returns:
        Effective sample rate in Hz, or 0 when the input is unusable.

    Example:
        >>> effective_sample_rate(1_024_000)   # decim 4
        256000
        >>> effective_sample_rate(250_000)     # no decimation
        250000
    """
    try:
        rate = int(configured_sample_rate or 0)
    except (TypeError, ValueError):
        return 0
    if rate <= 0:
        return 0
    return rate // early_decimation_factor(rate)


def spectrum_span_hz(configured_sample_rate) -> int:
    """Return the RF bandwidth an FFT of the published samples covers.

    For complex IQ the visible span equals the sample rate, so this is
    simply :func:`effective_sample_rate` under a name that makes the
    intent obvious at the call site that labels a frequency axis.
    """
    return effective_sample_rate(configured_sample_rate)
