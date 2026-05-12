"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""
Audio demodulation for SDR receivers.

Supports FM (wideband and narrowband), AM, and includes stereo decoding and RBDS extraction.
"""

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import oaconvolve

logger = logging.getLogger(__name__)

# Try to import Numba for JIT compilation of hot DSP functions
# Falls back to pure NumPy if Numba is not available
_NUMBA_AVAILABLE = False
# Numba's internal byteflow/SSA/interpreter passes log at DEBUG, and each
# JIT compile emits *megabytes* of those lines. On an RPi-class box the
# synchronous journald writes alone add real latency to the audio thread,
# and the root logger is typically at DEBUG during development. Pin every
# numba sub-logger to WARNING so compile-time chatter can't leak through
# regardless of the process-wide log level.
for _numba_logger_name in ('numba', 'numba.core', 'numba.core.ssa',
                           'numba.core.byteflow', 'numba.core.interpreter',
                           'numba.core.typeinfer', 'numba.core.compiler',
                           'llvmlite'):
    logging.getLogger(_numba_logger_name).setLevel(logging.WARNING)

try:
    from numba import jit, prange
    _NUMBA_AVAILABLE = True
    logger.info("Numba JIT compilation available - FM demodulation will use optimized code paths")
except ImportError:
    logger.warning(
        "Numba not available - RBDS processing will use pure Python (much slower). "
        "Install with: pip install numba"
    )
    # Create a no-op decorator for when numba isn't available
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    prange = range


# =============================================================================
# JIT-compiled DSP functions for real-time FM demodulation
# These functions are the hot path and benefit significantly from JIT compilation
# =============================================================================

@jit(nopython=True, cache=True, fastmath=True)
def _fm_discriminator_numba(iq_real: np.ndarray, iq_imag: np.ndarray) -> np.ndarray:
    """JIT-compiled FM phase discriminator.

    Extracts instantaneous frequency from IQ samples using the arctangent
    of the product of consecutive samples. This is the core FM demodulation
    algorithm and runs millions of times per second.

    Args:
        iq_real: Real component of IQ samples (float32)
        iq_imag: Imaginary component of IQ samples (float32)

    Returns:
        Audio samples as phase differences (float32)
    """
    n = len(iq_real) - 1
    audio = np.empty(n, dtype=np.float32)

    for i in prange(n):
        # Compute: angle(iq[i+1] * conj(iq[i]))
        # = angle((r1 + j*i1) * (r0 - j*i0))
        # = angle((r1*r0 + i1*i0) + j*(i1*r0 - r1*i0))
        r0, i0 = iq_real[i], iq_imag[i]
        r1, i1 = iq_real[i + 1], iq_imag[i + 1]

        real_part = r1 * r0 + i1 * i0
        imag_part = i1 * r0 - r1 * i0

        audio[i] = np.arctan2(imag_part, real_part)

    return audio


@jit(nopython=True, cache=True, fastmath=True)
def _costas_loop_numba(
    samples_real: np.ndarray,
    samples_imag: np.ndarray,
    phase: float,
    freq: float,
    alpha: float,
    beta: float
) -> tuple:
    """JIT-compiled Costas loop for BPSK frequency synchronization.

    This is the hot path in RBDS decoding - a pure Python loop was causing
    audio stalling due to the per-sample iteration overhead.

    Args:
        samples_real: Real component of complex samples (float64)
        samples_imag: Imaginary component of complex samples (float64)
        phase: Current phase state
        freq: Current frequency offset state
        alpha: Phase gain (damping parameter)
        beta: Frequency gain (bandwidth parameter)

    Returns:
        Tuple of (out_real, out_imag, final_phase, final_freq)
    """
    n = len(samples_real)
    out_real = np.empty(n, dtype=np.float64)
    out_imag = np.empty(n, dtype=np.float64)
    two_pi = 2.0 * np.pi

    for i in range(n):
        # Apply phase correction using Euler's formula
        cos_phase = np.cos(phase)
        sin_phase = np.sin(phase)

        s_real = samples_real[i]
        s_imag = samples_imag[i]

        # Complex multiply by exp(-j*phase): rotate backwards by phase
        out_real[i] = s_real * cos_phase + s_imag * sin_phase
        out_imag[i] = s_imag * cos_phase - s_real * sin_phase

        # BPSK phase error: real * imag
        error = out_real[i] * out_imag[i]

        # Update frequency and phase with loop filter
        freq += beta * error
        phase += freq + alpha * error

        # Wrap phase efficiently (modulo is expensive, only do when needed)
        if phase >= two_pi:
            phase -= two_pi
        elif phase < 0:
            phase += two_pi

    return out_real, out_imag, phase, freq


@jit(nopython=True, cache=True, fastmath=True)
def _mm_timing_loop_numba(
    samples_interp_real: np.ndarray,
    samples_interp_imag: np.ndarray,
    mu: float,
    max_out: int,
) -> tuple:
    """JIT-compiled M&M symbol timing recovery inner loop.

    Operates on 16x-upsampled samples and recovers one symbol per ~16
    original input samples.  The loop runs at symbol rate so the per-call
    Python overhead of a pure-Python while loop — not the iteration cost —
    is the bottleneck this eliminates.

    Args:
        samples_interp_real: Real component of 16x-upsampled samples (float64)
        samples_interp_imag: Imaginary component of 16x-upsampled samples (float64)
        mu: Initial fractional timing offset state (0 ≤ mu < 1)
        max_out: Upper bound on the number of output symbols to produce

    Returns:
        Tuple of (out_real, out_imag, i_out, i_in, mu)
        where out_real/out_imag are the recovered symbol values (length max_out),
        i_out is the number of symbols written (output slice is [2:i_out]),
        i_in is the consumed original-sample index (for leftover calculation),
        and mu is the final fractional timing offset.
    """
    sps = 16
    n_interp = len(samples_interp_real)

    out_real = np.zeros(max_out, dtype=np.float64)
    out_imag = np.zeros(max_out, dtype=np.float64)
    out_rail_real = np.zeros(max_out, dtype=np.float64)
    out_rail_imag = np.zeros(max_out, dtype=np.float64)

    i_in = 0
    i_out = 2  # first two outputs stay zero (history initialization)

    while i_out < max_out - 1:
        interp_idx = i_in * 16 + int(mu * 16)
        if interp_idx >= n_interp - 1:
            break

        s_real = samples_interp_real[interp_idx]
        s_imag = samples_interp_imag[interp_idx]
        out_real[i_out] = s_real
        out_imag[i_out] = s_imag

        # Rail values use 0/1 to match the pure-Python fallback which does
        # int(np.real(out[i_out]) > 0).  Standard M&M typically uses ±1, but
        # matching the fallback exactly preserves identical mm_val scaling.
        rail_r = 1.0 if s_real > 0.0 else 0.0
        rail_i = 1.0 if s_imag > 0.0 else 0.0
        out_rail_real[i_out] = rail_r
        out_rail_imag[i_out] = rail_i

        # x = (out_rail[i] - out_rail[i-2]) * conj(out[i-1])
        # y = (out[i]      - out[i-2])      * conj(out_rail[i-1])
        # mm_val = real(y - x)  — only the real part is needed
        dr_r = out_rail_real[i_out] - out_rail_real[i_out - 2]
        dr_i = out_rail_imag[i_out] - out_rail_imag[i_out - 2]
        do_r = out_real[i_out] - out_real[i_out - 2]
        do_i = out_imag[i_out] - out_imag[i_out - 2]
        prev_out_r = out_real[i_out - 1]
        prev_out_i = out_imag[i_out - 1]
        prev_rail_r = out_rail_real[i_out - 1]
        prev_rail_i = out_rail_imag[i_out - 1]
        # real part of complex multiply a*conj(b): re(a)*re(b) + im(a)*im(b)
        x_real = dr_r * prev_out_r + dr_i * prev_out_i
        y_real = do_r * prev_rail_r + do_i * prev_rail_i
        mm_val = y_real - x_real

        mu += sps + 0.05 * mm_val
        i_in += int(np.floor(mu))
        mu = mu - np.floor(mu)
        i_out += 1

    return out_real, out_imag, i_out, i_in, mu


@jit(nopython=True, cache=True, fastmath=True)
def _calc_syndrome_numba(x: int, mlen: int) -> int:
    """JIT-compiled RDS/RBDS syndrome calculator.

    Evaluates the standard (26,16) RBDS block-code syndrome via the
    shift-register circuit from IEC 62106 Annex B.  Generator polynomial:
    g(x) = x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1  (= 0x5B9).

    This is called twice per bit during presync scanning and once per
    block (plus up to 26× per FEC attempt) in synced decode — making it
    the tightest remaining Python loop after Costas/M&M were JIT'd.

    Args:
        x:    Integer word to evaluate (≤ 26 bits for a full block,
              16 bits for a dataword-only parity check).
        mlen: Bit-length of *x* (26 or 16 in practice).

    Returns:
        10-bit syndrome value (0–1023).
    """
    reg = 0
    plen = 10
    mask = 1 << plen
    poly = 0x5B9
    for ii in range(mlen, 0, -1):
        reg = (reg << 1) | ((x >> (ii - 1)) & 1)
        if reg & mask:
            reg ^= poly
    for ii in range(plen, 0, -1):
        reg = reg << 1
        if reg & mask:
            reg ^= poly
    return reg & (mask - 1)


# Precomputed RBDS offset syndromes (IEC 62106 Table 2).
# Stored as a module-level int64 array so _presync_scan_numba can reference
# it without allocating on every call.  Values correspond to block offsets
# A / B / C / D / C' in that order.
_RBDS_SYNDROMES = np.array([383, 14, 303, 663, 748], dtype=np.int64)


@jit(nopython=True, cache=True, fastmath=True)
def _presync_scan_numba(
    bits: np.ndarray,
    initial_reg: int,
    syndromes: np.ndarray,
) -> tuple:
    """JIT-compiled RBDS presync bit scanner.

    Scans an int8 bit buffer for RBDS syndrome matches in a single native
    pass, eliminating the 2× _calc_syndrome Python-loop overhead that
    dominates the presync hot path.  For each bit the 26-bit shift register
    is advanced and the resulting syndrome is checked against all five RBDS
    offset words (normal and bit-inverted).  Only the *first* matching
    syndrome per bit is recorded, preserving the break-on-first-match
    semantics of the Python fallback path in _decode_rbds_groups.

    Calling this once per batch replaces len(bits) × 2 Python-level
    syndrome computations with a single native loop.

    Args:
        bits:        int8 numpy array of decoded bits (values 0 or 1).
        initial_reg: 26-bit shift-register state carried over from the
                     previous batch.
        syndromes:   int64 array of the 5 RBDS offset syndromes [A,B,C,D,C'].

    Returns:
        Tuple of three equally-sized arrays (length = number of matches):
        - match_positions: int32 bit indices where a syndrome was found.
        - match_j:         int32 syndrome-table index (0–4) that matched.
        - match_polarity:  bool array; False = normal, True = inverted.
    """
    n = len(bits)
    match_positions = np.empty(n, dtype=np.int32)
    match_j_arr = np.empty(n, dtype=np.int32)
    match_polarity = np.empty(n, dtype=np.bool_)
    n_matches = 0

    reg = np.int64(initial_reg)
    full_mask = np.int64(0x3FFFFFF)

    for i in range(n):
        reg = ((reg << np.int64(1)) | np.int64(bits[i])) & full_mask
        syn = _calc_syndrome_numba(reg, 26)
        syn_inv = _calc_syndrome_numba(reg ^ full_mask, 26)

        for j in range(5):
            if syn == syndromes[j]:
                match_positions[n_matches] = np.int32(i)
                match_j_arr[n_matches] = np.int32(j)
                match_polarity[n_matches] = False
                n_matches += 1
                break
            elif syn_inv == syndromes[j]:
                match_positions[n_matches] = np.int32(i)
                match_j_arr[n_matches] = np.int32(j)
                match_polarity[n_matches] = True
                n_matches += 1
                break

    return (
        match_positions[:n_matches],
        match_j_arr[:n_matches],
        match_polarity[:n_matches],
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


# RT+ (RadioText Plus) ODA Application Identifier per RDS Forum R03/040.1.
# Stations broadcast it on the group type assigned in their Group 3A
# registration (most US music stations use 11A, some use 12A).
RT_PLUS_AID = 0xCD46

# Content type codes from the RT+ specification (R03/040.1 §6.2 Table 1).
# Codes 0 and >= 53 are dummy / reserved-for-future-use; we still expose
# the raw code so receivers can render unknown classes generically.
RT_PLUS_CONTENT_TYPES: Dict[int, str] = {
    0: "DUMMY", 1: "ITEM.TITLE", 2: "ITEM.ALBUM", 3: "ITEM.TRACKNUMBER",
    4: "ITEM.ARTIST", 5: "ITEM.COMPOSITION", 6: "ITEM.MOVEMENT",
    7: "ITEM.CONDUCTOR", 8: "ITEM.COMPOSER", 9: "ITEM.BAND",
    10: "ITEM.COMMENT", 11: "ITEM.GENRE", 12: "INFO.NEWS",
    13: "INFO.NEWS.LOCAL", 14: "INFO.STOCKMARKET", 15: "INFO.SPORT",
    16: "INFO.LOTTERY", 17: "INFO.HOROSCOPE", 18: "INFO.DAILY_DIVERSION",
    19: "INFO.HEALTH", 20: "INFO.EVENT", 21: "INFO.SCENE",
    22: "INFO.CINEMA", 23: "INFO.TV", 24: "INFO.DATE_TIME",
    25: "INFO.WEATHER", 26: "INFO.TRAFFIC", 27: "INFO.ALARM",
    28: "INFO.ADVERTISEMENT", 29: "INFO.URL", 30: "INFO.OTHER",
    31: "STATIONNAME.SHORT", 32: "STATIONNAME.LONG",
    33: "PROGRAMME.NOW", 34: "PROGRAMME.NEXT", 35: "PROGRAMME.PART",
    36: "PROGRAMME.HOST", 37: "PROGRAMME.EDITORIAL_STAFF",
    38: "PROGRAMME.FREQUENCY", 39: "PROGRAMME.HOMEPAGE",
    40: "PROGRAMME.SUBCHANNEL", 41: "PHONE.HOTLINE",
    42: "PHONE.STUDIO", 43: "PHONE.OTHER", 44: "SMS.STUDIO",
    45: "SMS.OTHER", 46: "EMAIL.HOTLINE", 47: "EMAIL.STUDIO",
    48: "EMAIL.OTHER", 49: "MMS.OTHER", 50: "CHAT", 51: "CHAT.CENTRE",
    52: "VOTE.QUESTION", 53: "VOTE.CENTRE",
    58: "PLACE", 59: "APPOINTMENT", 60: "IDENTIFIER",
    61: "PURCHASE", 62: "GET_DATA",
}


RBDS_LANGUAGE_CODES: Dict[int, str] = {
    0x01: "Albanian", 0x02: "Breton", 0x03: "Catalan", 0x04: "Croatian",
    0x05: "Welsh", 0x06: "Czech", 0x07: "Danish", 0x08: "German",
    0x09: "English", 0x0A: "Spanish", 0x0B: "Esperanto", 0x0C: "Estonian",
    0x0D: "Basque", 0x0E: "Faroese", 0x0F: "French", 0x10: "Frisian",
    0x11: "Irish", 0x12: "Gaelic", 0x13: "Galician", 0x14: "Icelandic",
    0x15: "Italian", 0x16: "Lappish", 0x17: "Latin", 0x18: "Latvian",
    0x19: "Luxembourgian", 0x1A: "Lithuanian", 0x1B: "Hungarian",
    0x1C: "Macedonian", 0x1D: "Maltese", 0x1E: "Norwegian", 0x1F: "Occitan",
    0x20: "Polish", 0x21: "Portuguese", 0x22: "Romanian", 0x23: "Romansh",
    0x24: "Serbian", 0x25: "Slovak", 0x26: "Slovene", 0x27: "Finnish",
    0x28: "Swedish", 0x29: "Turkish", 0x2A: "Flemish", 0x2B: "Walloon",
    0x40: "Background sound", 0x45: "Zulu", 0x46: "Vietnamese", 0x47: "Uzbek",
    0x48: "Urdu", 0x49: "Ukrainian", 0x4A: "Thai", 0x4B: "Telugu",
    0x4C: "Tatar", 0x4D: "Tamil", 0x4E: "Tajik", 0x4F: "Swahili",
    0x50: "Sranan Tongo", 0x51: "Somali", 0x52: "Sinhalese", 0x53: "Shona",
    0x54: "Serbo-Croat", 0x55: "Ruthenian", 0x56: "Russian", 0x57: "Quechua",
    0x58: "Pushtu", 0x59: "Punjabi", 0x5A: "Persian", 0x5B: "Papamiento",
    0x5C: "Oriya", 0x5D: "Nepali", 0x5E: "Ndebele", 0x5F: "Marathi",
    0x60: "Moldovian", 0x61: "Malaysian", 0x62: "Malagasy", 0x63: "Macedonian",
    0x64: "Laotian", 0x65: "Korean", 0x66: "Khmer", 0x67: "Kazakh",
    0x68: "Kannada", 0x69: "Japanese", 0x6A: "Indonesian", 0x6B: "Hindi",
    0x6C: "Hebrew", 0x6D: "Hausa", 0x6E: "Gurani", 0x6F: "Gujurati",
    0x70: "Greek", 0x71: "Georgian", 0x72: "Fulah", 0x73: "Dari",
    0x74: "Churash", 0x75: "Chinese", 0x76: "Burmese", 0x77: "Bulgarian",
    0x78: "Bengali", 0x79: "Belorussian", 0x7A: "Bambora", 0x7B: "Azerbaijani",
    0x7C: "Assamese", 0x7D: "Armenian", 0x7E: "Arabic", 0x7F: "Amharic",
}


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


@dataclass
class DemodulatorConfig:
    """Configuration for audio demodulator."""
    modulation_type: str  # 'FM', 'WFM', 'NFM', 'AM', 'IQ'
    sample_rate: int  # Input sample rate (Hz)
    audio_sample_rate: int = 44100  # Output audio sample rate (native for streams/outputs)
    stereo_enabled: bool = True  # Enable FM stereo decoding
    deemphasis_us: float = 75.0  # De-emphasis time constant (75μs NA, 50μs EU, 0 to disable)
    enable_rbds: bool = False  # Extract RBDS data from FM multiplex
    # Optional RBDS robustness tuning (None = use built-in defaults).
    rbds_pilot_snr_threshold: Optional[float] = None
    rbds_presync_spacing_tolerance_bits: Optional[int] = None
    rbds_burst_fec_suppress_after: Optional[int] = None
    rbds_interference_rejection_enabled: bool = False
    rbds_interference_guard_hz: Optional[float] = None


@dataclass
class RBDSData:
    """Decoded RBDS/RDS data from FM broadcast."""
    pi_code: Optional[str] = None  # Program Identification (raw 16-bit hex)
    # PI is structured as 4 bits country code + 4 bits area/coverage code +
    # 8 bits programme reference (Annex D of NRSC-4-B).  For US stations
    # this is a synthetic-call-sign mapping; for European stations the
    # split is the actual country/region/programme identifier.
    pi_country_code: Optional[int] = None       # high 4 bits
    pi_area_code: Optional[int] = None          # next 4 bits (coverage area)
    pi_program_ref: Optional[int] = None        # low 8 bits
    call_sign: Optional[str] = None  # Decoded US call letters (e.g. "WXYZ"), if PI is US
    ps_name: Optional[str] = None  # Program Service name (8 chars)
    pty_name: Optional[str] = None  # Program Type Name (PTYN, 8 chars, Group 10A)
    radio_text: Optional[str] = None  # Radio Text (up to 64 chars)
    # RT A/B flag.  The station toggles this every time the displayed
    # message restarts; the UI can use it to detect when an RT change is
    # in progress (vs. just being extended segment-by-segment).
    radio_text_ab: Optional[int] = None
    pty: Optional[int] = None  # Program Type
    tp: Optional[bool] = None  # Traffic Program flag
    ta: Optional[bool] = None  # Traffic Announcement flag
    ms: Optional[bool] = None  # Music/Speech flag
    di_stereo: Optional[bool] = None  # Decoder Identification: stereo
    di_artificial_head: Optional[bool] = None  # Decoder Identification: artificial head
    di_compressed: Optional[bool] = None  # Decoder Identification: compressed audio
    di_dynamic_pty: Optional[bool] = None  # Decoder Identification: dynamic PTY
    clock_time_utc: Optional[str] = None  # ISO-8601 UTC timestamp from Group 4A
    clock_time_local: Optional[str] = None  # ISO-8601 local timestamp from Group 4A
    # Group 0A Block C - Alternative Frequencies
    af_list: Optional[List[float]] = None  # list of AF frequencies in MHz
    # Method-A AF list count (codes 224-249).  None until announced; once
    # set, len(af_list) == af_method_a_count means the list is complete.
    af_method_a_count: Optional[int] = None
    # True if the station has signalled an LF/MF follow-on (code 250),
    # i.e. the AF list extends to non-VHF frequencies we can't represent
    # in MHz directly.  Pure indicator — no further data captured.
    af_follow_on_indicator: Optional[bool] = None
    # True once the station has emitted a Method-B regional-variant
    # marker (an AF pair where both bytes are the same direct code).
    # Method B and Method A both still produce frequencies in af_list;
    # this flag plus af_tuning_frequency just say "this station also
    # broadcasts the AF list paired against the tuned frequency".
    af_method_b: Optional[bool] = None
    af_tuning_frequency: Optional[float] = None
    # Group 1A/1B - Programme Item Number + Slow Labeling Codes
    pin_day: Optional[int] = None
    pin_hour: Optional[int] = None
    pin_minute: Optional[int] = None
    ecc: Optional[int] = None  # Extended Country Code
    language_code: Optional[int] = None
    language_name: Optional[str] = None
    linkage_set_number: Optional[int] = None
    linkage_actuator: Optional[bool] = None
    linkage_soft_coupling: Optional[bool] = None
    # Group 1A variant-1: 12-bit TMC identification provider code.
    paging_tmc_id: Optional[int] = None
    # Group 1A variant-2: 12-bit paging operator code.
    paging_operator_code: Optional[int] = None
    # Group 1A variant-7: 12-bit EWS slow-labelling channel identifier
    # (which EWS provider feeds the Group 9A messages on this station).
    ews_channel_identifier: Optional[int] = None
    # Raw 16-bit Block-D payload per Group 1A variant (0..7), so the UI
    # can show every variant byte the station broadcasts even where no
    # decoder semantics apply.
    slow_labelling_raw: Optional[Dict[int, int]] = None
    # Group 3A - Open Data Application registration
    oda_apps: Optional[List[int]] = None
    # Full ODA assignment table — list of {group, version, aid, aid_hex,
    # name?} items so the UI can show *which* group type carries each
    # registered application instead of just listing AIDs.
    oda_assignments: Optional[List[dict]] = None
    # Per-AID raw payload buffer for ODAs we don't have a specific
    # decoder for.  Each entry: {aid, aid_hex, group, count,
    # last_b_low, last_c, last_d, last_seen_unix}.
    oda_payloads: Optional[List[dict]] = None
    # Group 7A / 13A paging messages.  Each is a list of dicts with
    # the raw bytes and a unix timestamp; format is operator-defined,
    # so the decoder doesn't try to interpret the payload.
    paging_messages: Optional[List[dict]] = None
    enhanced_paging_messages: Optional[List[dict]] = None
    # Group 5A/5B - Transparent Data Channel
    # tdc_data is channel 0 (kept for backwards compat); tdc_channels
    # exposes every channel TS the station broadcasts.
    tdc_data: Optional[bytes] = None
    tdc_channels: Optional[Dict[int, bytes]] = None
    # Group 6A/6B - In-House Applications
    in_house_data: Optional[List[int]] = None
    # Group 8A - Traffic Message Channel
    tmc_present: Optional[bool] = None
    # Group 9A - Emergency Warning System
    ews_channel: Optional[int] = None
    ews_message_c: Optional[int] = None
    ews_message_d: Optional[int] = None
    # Group 14A/14B - Enhanced Other Networks
    eon_list: Optional[List[dict]] = None
    # Group 15B - Fast Switching Information
    fast_tp: Optional[bool] = None
    fast_ta: Optional[bool] = None
    fast_ms: Optional[bool] = None
    fast_di_bits: Optional[int] = None
    # RT+ (ODA AID 0xCD46) - structured tags pointing into Radio Text.
    # Each tag is a dict {content_type, content_type_name, text, start, length}.
    rt_plus_item_running: Optional[bool] = None
    rt_plus_item_toggle: Optional[int] = None
    rt_plus_tags: Optional[List[dict]] = None


@dataclass
class RBDSDecoderStats:
    """Snapshot of RBDS decoder health and traffic.

    Reset on every sync acquisition (so values reflect the *current* lock
    rather than lifetime totals across station changes), except for
    ``sync_lost_count`` which is cumulative since the worker was started.
    Surfaces what redsea calls "block error rate" plus a per-group-type
    traffic histogram so operators can tell *why* a station is missing
    metadata (e.g. it doesn't broadcast any 2A groups, so RT will never
    appear).
    """
    blocks_total: int = 0
    blocks_ok: int = 0          # passed CRC without FEC
    blocks_fec_single: int = 0  # repaired by single-bit corrector
    blocks_fec_burst: int = 0   # repaired by burst-trapping decoder
    blocks_uncorrected: int = 0
    groups_decoded: int = 0
    sync_acquired_unix: Optional[float] = None
    sync_lost_count: int = 0
    # Number of sample chunks dropped because the worker queue was full.
    # A non-zero value here means the DSP thread is behind real-time;
    # it triggers M&M timing phase errors because state carries over
    # across the resulting time gaps.
    chunks_dropped: int = 0
    # Keys are e.g. "0A", "2A", "11A" — bare "A"/"B" suffixes match what
    # the RDS specs use everywhere so the UI doesn't have to translate.
    group_type_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def raw_block_error_rate(self) -> Optional[float]:
        """Fraction of received blocks that didn't pass CRC on first try.

        This is the NRSC-4-B §7.4.2 definition of BLER — any block whose
        syndrome was non-zero before FEC counts as an error, regardless
        of whether FEC later repaired it.  Returns None until at least
        one block has been processed (so the UI doesn't display 0/0).
        """
        if self.blocks_total == 0:
            return None
        return (self.blocks_total - self.blocks_ok) / self.blocks_total

    @property
    def net_block_error_rate(self) -> Optional[float]:
        """Fraction of blocks the decoder still couldn't recover after FEC.

        Operationally what users care about — this is what drives PS/RT
        gaps.  raw - net = "how much FEC saved us".
        """
        if self.blocks_total == 0:
            return None
        return self.blocks_uncorrected / self.blocks_total


@dataclass
class DemodulatorStatus:
    """Status information from FM demodulator."""
    rbds_data: Optional[RBDSData] = None  # RBDS data if available
    stereo_pilot_locked: bool = False  # 19 kHz stereo pilot detected
    stereo_pilot_strength: float = 0.0  # Pilot signal strength (0.0 to 1.0)
    is_stereo: bool = False  # Stereo decoding active
    # Mean magnitude of the IQ samples for this chunk (linear, 0.0-1.0 range
    # for normalized float samples).  The UI converts this to dBFS for the
    # RF RSSI meter.
    signal_strength: float = 0.0
    # True once the RBDS bit-level sync state machine has locked.  Lets the
    # UI show a "LOCKING" vs "LOCKED" indicator instead of leaving users
    # guessing why no data has appeared yet.
    rbds_synced: bool = False
    # True if the demodulator is even attempting RBDS decoding (i.e. the
    # receiver has enable_rbds set and the IQ sample rate is high enough
    # to preserve the 57 kHz subcarrier).  Without this flag a receiver
    # configured with enable_rbds=False looked indistinguishable from one
    # that was still acquiring sync — both produced rbds_synced=False —
    # and users could wait forever for a lock the decoder never even
    # tried to obtain.
    rbds_enabled: bool = False
    # Decoder-side health metrics — block error rate, FEC correction
    # split, and group-type histogram.  None until an RBDS worker is
    # running; otherwise updated each frame.
    rbds_decoder_stats: Optional[RBDSDecoderStats] = None


class RBDSWorker:
    """Threaded RBDS processor - processes RBDS in background without blocking audio.

    RBDS runs in its own thread. Audio demodulation drops samples into a
    queue; the worker processes them independently and publishes results.
    This ensures RBDS processing NEVER blocks the audio path.
    """
    
    # RBDS processing constants
    RBDS_MIN_SAMPLE_RATE = 120000  # Minimum sample rate for 57 kHz subcarrier extraction (Hz)
    RBDS_INTERMEDIATE_RATE = 25000  # Target rate after decimation before resampling (Hz)

    # Sliding-window decode thresholds (samples at the 19 kHz RBDS rate).
    # M&M and Costas state is carried forward across batches (see comments
    # in _process_rbds) so the loops keep converging between iterations
    # even with a short window — the only thing batching protects is
    # per-call DSP overhead, not signal continuity.
    #
    # Before sync the threshold is the dominant contributor to first-PS
    # latency: nothing reaches the bit-level state machine until a full
    # window has accumulated.  A 1 s window left users staring at an
    # empty section while their car radio decoded the same broadcast in
    # ~1 s end-to-end.  Drop the cold-start window to ~250 ms (about 300
    # symbols at 1187.5 baud — well above the 100–150 symbols Costas
    # needs to converge) so _decode_rbds_groups gets to attempt presync
    # four times per second.  Once locked we go back to a 1 s window so
    # steady-state CPU load stays the same.
    RBDS_UNSYNCED_WINDOW = 4750    # ~250 ms @ 19 kHz - fast initial lock
    RBDS_SYNCED_WINDOW = 19000     # ~1 second @ 19 kHz - low steady-state overhead

    # Pilot-frequency estimator tunables.  Underscore-prefixed because they
    # are internal implementation details, not user-facing API.
    _PILOT_EST_MIN_SAMPLES = 32768           # Smallest chunk we trust for FFT-based estimation
    _PILOT_EST_MAX_NFFT = 1 << 18            # Cap FFT size at 262 144 bins (~1 Hz @ 250 kHz)
    _PARABOLIC_INTERP_MIN_DENOM = 1e-12      # Avoid division-by-zero when peak bins are colinear
    _PILOT_SNR_THRESHOLD = 4.0               # Peak must be ≥ 4× the in-band median to count
    _MAX_PILOT_DEVIATION_HZ = 4.0            # ~210 ppm; beyond this is broken hardware
    _RBDS_PRESYNC_SPACING_TOLERANCE_BITS = 4

    # Periodic pilot re-measurement.  The transmitter's crystal is exact, but
    # cheap-SDR TCXOs drift 1–3 ppm with temperature swings (cold start →
    # warm operation can easily move the recovered pilot 0.5–1 Hz over a few
    # minutes).  Tripling that for the 57 kHz mix leaves a residual the
    # Costas loop has to absorb, narrow but enough to push a marginally-
    # locked Costas into cycle slips.  Re-measure every 30 s and blend the
    # new estimate with the previous one via EMA so transient FFT noise
    # can't yank the reference around.  Implausibly large jumps are
    # rejected outright (see _PILOT_REMEASURE_MAX_DRIFT_HZ) — at 1 ppm per
    # 30 s the legitimate drift between samples is well under 0.1 Hz, so
    # anything bigger is an artifact (e.g. station change in flight, brief
    # de-sense from a stronger adjacent signal) and best ignored.
    _PILOT_REMEASURE_INTERVAL_SEC = 30.0
    _PILOT_REMEASURE_MAX_DRIFT_HZ = 1.0
    _PILOT_REMEASURE_EMA_ALPHA = 0.3

    def __init__(
        self,
        sample_rate: int,
        intermediate_rate: int,
        rbds_tuning_options: Optional[Dict[str, object]] = None,
    ):
        """Initialize RBDS worker thread.

        Args:
            sample_rate: Original sample rate before any decimation
            intermediate_rate: Rate after decimation (where RBDS processing happens)
        """
        self._sample_rate = sample_rate
        self._intermediate_rate = intermediate_rate
        self._apply_tuning_options(rbds_tuning_options)

        # Thread-safe queue for incoming multiplex samples
        # maxsize=5 means we drop old samples if processing is too slow (never block audio)
        self._sample_queue: queue.Queue = queue.Queue(maxsize=5)

        # Thread-safe storage for latest RBDS data
        self._latest_data: Optional[RBDSData] = None
        self._data_lock = threading.Lock()

        # Decoder health stats (FEC counts, sync lifecycle, group histogram).
        # The dataclass and the lock are owned here so all reads/writes go
        # through one mutex regardless of which thread updates a counter.
        self._stats: RBDSDecoderStats = RBDSDecoderStats()
        self._stats_lock = threading.Lock()

        # Count of sample chunks dropped because the queue was full (audio
        # thread writes this, worker thread reads it via get_stats).  Using
        # a plain int protected by _stats_lock so the UI can surface it in
        # the Decoder Health panel without a separate atomic/lock.
        self._chunks_dropped: int = 0

        # Worker thread
        self._stop_event = threading.Event()
        # Set by callers (e.g. frequency change) to ask the worker to drop
        # all sync / loop / decoder state on its next iteration.  Doing the
        # reset inside the worker thread avoids racing with _process_rbds
        # reading filters or sync-state that the caller is rewriting.
        self._reset_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # RBDS processing state (initialized in _init_rbds_state)
        self._rbds_decoder: Optional['RBDSDecoder'] = None
        self._init_rbds_state()

        # Start worker thread
        self._start()

    def _apply_tuning_options(self, options: Optional[Dict[str, object]]) -> None:
        """Apply optional RBDS tuning overrides with bounds checking."""
        options = options or {}
        pilot_snr = options.get('pilot_snr_threshold')
        spacing_tol = options.get('presync_spacing_tolerance_bits')
        burst_suppress = options.get('burst_fec_suppress_after')
        interference_enabled = options.get('interference_rejection_enabled')
        interference_guard_hz = options.get('interference_guard_hz')

        self._pilot_snr_threshold = (
            float(pilot_snr)
            if isinstance(pilot_snr, (float, int)) and float(pilot_snr) >= 1.0
            else float(self._PILOT_SNR_THRESHOLD)
        )
        self._rbds_presync_spacing_tolerance_bits = (
            int(spacing_tol)
            if isinstance(spacing_tol, int) and spacing_tol >= 1
            else int(self._RBDS_PRESYNC_SPACING_TOLERANCE_BITS)
        )
        self._rbds_burst_fec_suppress_after = (
            int(burst_suppress)
            if isinstance(burst_suppress, int) and burst_suppress >= 0
            else int(self._BURST_FEC_SUPPRESS_AFTER)
        )
        self._rbds_interference_rejection_enabled = bool(interference_enabled)
        self._rbds_interference_guard_hz = (
            float(interference_guard_hz)
            if isinstance(interference_guard_hz, (float, int))
            and float(interference_guard_hz) >= self._RBDS_INTERFERENCE_MIN_OFFSET_HZ
            else float(self._RBDS_INTERFERENCE_GUARD_HZ)
        )
        self._rbds_interference_min_offset_hz = float(self._RBDS_INTERFERENCE_MIN_OFFSET_HZ)
        self._rbds_interference_notch_q = float(self._RBDS_INTERFERENCE_NOTCH_Q)

    def _init_rbds_state(self) -> None:
        """Initialize all RBDS processing state."""
        # RBDSDecoder is defined in this same file (no import needed)
        self._rbds_decoder = RBDSDecoder()

        # CRITICAL FIX: Design filters at the ACTUAL sample rate they'll be used at!
        # For Airspy after early decimation: sample_rate = 250 kHz
        # Bandpass filter to extract 57 kHz RBDS subcarrier (54-60 kHz range)
        # Only design bandpass if sample rate is high enough (need > 120 kHz for 60 kHz filter)
        if self._sample_rate >= self.RBDS_MIN_SAMPLE_RATE:
            rbds_filter_taps = min(101, max(31, int(self._sample_rate / 3000)))
            self._rbds_bandpass = self._design_fir_bandpass(
                54000.0, 60000.0, self._sample_rate, taps=rbds_filter_taps
            )
        else:
            # If sample rate too low, skip bandpass (RBDS won't work but won't crash)
            self._rbds_bandpass = None
            logger.warning(
                "RBDS: Sample rate %d Hz too low for 57 kHz subcarrier extraction (need >%d Hz). "
                "RBDS decoding will not work.",
                self._sample_rate,
                self.RBDS_MIN_SAMPLE_RATE
            )

        # Lowpass filter for post-mixing (removes aliases, keeps baseband RBDS).
        # Design this at sample_rate since we mix BEFORE lowpass filtering.
        #
        # Cutoff = 2.4 kHz: This is the standard matched-filter bandwidth for
        # the 1187.5-baud biphase-coded RBDS BPSK signal.  The biphase spectrum
        # has its peak at 1187.5 Hz and a null at 2375 Hz, so 2.4 kHz preserves
        # the entire main lobe while sharply attenuating everything beyond it.
        #
        # Why this is critical: the 57 kHz mix down-converts the FM stereo DSB
        # upper sideband (38 + 15 = 53 kHz) to ~4 kHz in the RBDS baseband.
        # A 7.5 kHz lowpass passes that 4 kHz stereo artifact untouched, and
        # because stereo modulation depth (~45%) is more than 10× the RBDS
        # depth (~3%), the stereo bleed-through buries the BPSK and the
        # Costas/M&M loops cannot settle.  This was producing 85%+ raw BLER
        # and constant sync drops on stations with strong RF (see Audio
        # Monitoring report from 2026-04).  A 2.4 kHz cutoff puts the 4 kHz
        # stereo artifact firmly into the stopband.
        #
        # 501 taps gives a Blackman transition of ~5.5*fs/N ≈ 2.7 kHz at
        # 250 kHz, so 2.4 kHz cutoff reaches -60 dB by ~3.8 kHz, comfortably
        # ahead of the 4 kHz interferer.
        self._rbds_lowpass = self._design_fir_lowpass(2400.0, self._sample_rate, taps=501)

        # Filter delay-line state, preserved across _process_rbds calls. FIR
        # filters implemented with np.convolve are stateless, so every chunk
        # produced ~(N_taps - 1) samples of transient at its start. With
        # 101-tap filters on 205-sample chunks the transient ate half the
        # output, which looked like noise to the RBDS bit synchroniser. Using
        # scipy.signal.lfilter with a persisted zi delay line eliminates the
        # seam between consecutive chunks.
        self._rbds_bandpass_zi: Optional[np.ndarray] = None
        self._rbds_lowpass_zi_real: Optional[np.ndarray] = None
        self._rbds_lowpass_zi_imag: Optional[np.ndarray] = None
        self._rbds_interference_notch_a: Optional[np.ndarray] = None
        self._rbds_interference_notch_b: Optional[np.ndarray] = None
        self._rbds_interference_notch_freq_hz: Optional[float] = None
        self._rbds_interference_notch_zi_real: Optional[np.ndarray] = None
        self._rbds_interference_notch_zi_imag: Optional[np.ndarray] = None

        # CRITICAL: 19 kHz pilot extraction for phase-coherent demodulation
        # Redsea/GNU Radio architecture: Use pilot × 3 to generate 57 kHz carrier
        # This ensures phase coherence with the transmitter!
        pilot_filter_taps = min(101, max(31, int(self._sample_rate / 3000)))
        self._pilot_bandpass = self._design_fir_bandpass(
            18500.0, 19500.0, self._sample_rate, taps=pilot_filter_taps
        )

        # Crystal-locked 19 kHz pilot reference (no PLL needed!)
        # FM stations use crystal oscillators - pilot is EXACTLY 19000 Hz
        # Just count samples to generate perfect phase reference
        self._pilot_sample_counter = 0  # Running sample count for phase continuity

        # Measured pilot frequency (Hz). The transmitter's crystal is exact,
        # but the *receiver* SDR clock often has 25-100 ppm error which shifts
        # the recovered pilot by ±0.5-2 Hz. Tripling that for the 57 kHz mix
        # leaves a 1.5-6 Hz residual that the Costas loop has to track on top
        # of phase noise. Measuring the pilot once per station and using it as
        # the carrier reference puts the RBDS subcarrier at DC after mixing,
        # so Costas only has to track residual phase noise. None until we've
        # collected enough samples; falls back to 19000.0 for compatibility.
        self._measured_pilot_freq: Optional[float] = None

        # Sample-budget counter for periodic pilot re-measurement.  Reset to 0
        # whenever a fresh measurement (initial or remeasure) is captured.
        self._pilot_samples_since_remeasure: int = 0

        # RBDS symbol timing
        self._rbds_symbol_rate = 1187.5
        self._rbds_samples_per_symbol = 16
        self._rbds_target_rate = self._rbds_symbol_rate * self._rbds_samples_per_symbol

        # M&M clock recovery state (Mueller & Müller algorithm)
        self._rbds_mm_mu = 0.01  # Initial mu estimate
        self._rbds_mm_out_prev = complex(0.0)  # sample[n-1]
        self._rbds_mm_out_prev2 = complex(0.0)  # sample[n-2] - needed for M&M error formula
        self._rbds_mm_rail_prev = complex(0.0)  # decision[n-1]
        # Unconsumed samples carried forward across batches to prevent bit-count drift.
        # The M&M loop always leaves up to ~sps-1 samples at the end of each batch;
        # without buffering them the block boundary drifts by ~1 symbol per batch,
        # causing every block to CRC-fail immediately after sync is acquired.
        self._rbds_mm_leftover = np.array([], dtype=np.complex64)

        # Costas loop state
        # Parameters are matched to the 19 kHz sample rate at which the loop now
        # runs (before M&M, per the PySDR / GNU Radio standard).  At 19 kHz the
        # PySDR values (alpha=8.7e-3, beta=3.2e-5) give:
        #   loop BW ≈ 17 Hz   damping ≈ 0.77
        # This comfortably handles the ±5.7 Hz carrier offset produced by an
        # RTL-SDR with ±100 ppm clock error at 57 kHz.  The old streaming values
        # (0.026 / 0.00035) gave only 3.5 Hz at symbol rate — too narrow to
        # acquire the carrier reliably.
        self._rbds_costas_phase = 0.0
        self._rbds_costas_freq  = 0.0
        self._rbds_costas_alpha = 8.7e-3   # PySDR / GNU Radio standard value
        self._rbds_costas_beta  = 3.2e-5   # PySDR / GNU Radio standard value

        # Bit buffer and decoding
        self._rbds_bit_buffer: List[int] = []
        self._rbds_expected_block: Optional[int] = None
        self._rbds_partial_group: List[int] = []
        # Previous symbol for differential decoding (0 or 1)
        # Initialized to 0, but will be set by first actual symbol
        self._rbds_prev_symbol: int = 0
        self._rbds_carrier_phase: float = 0.0
        self._rbds_consecutive_crc_failures: int = 0
        self._rbds_synchronized: bool = False  # Require A→B confirmation before trusting data

        # Sample tracking for phase-continuous 57kHz carrier
        self._sample_index: int = 0
        self._carrier_phase_57k: float = 0.0  # Phase of 57kHz carrier for mixing

    @staticmethod
    def _design_fir_lowpass(cutoff: float, sample_rate: int, taps: int = 101) -> np.ndarray:
        """Thin shim around the module-level :func:`design_fir_lowpass`."""
        return design_fir_lowpass(cutoff, sample_rate, taps=taps)

    @staticmethod
    def _design_fir_bandpass(low: float, high: float, sample_rate: int, taps: int = 101) -> np.ndarray:
        """Thin shim around the module-level :func:`design_fir_bandpass`."""
        return design_fir_bandpass(low, high, sample_rate, taps=taps)

    def _estimate_pilot_frequency(self, multiplex: np.ndarray) -> Optional[float]:
        """Measure the actual 19 kHz pilot frequency in *multiplex*.

        Locates the strongest spectral peak in the 18.5-19.5 kHz band using a
        zero-padded RFFT and parabolic interpolation around the peak bin for
        sub-bin accuracy. This compensates for SDR clock error (typical
        RTL-SDR dongles have 25-100 ppm) so the 57 kHz RBDS subcarrier lands
        at exactly DC after mixing.

        Args:
            multiplex: Real-valued FM multiplex samples at self._sample_rate.

        Returns:
            Measured pilot frequency in Hz, or None if no usable peak was
            found (e.g. mono station, very weak signal, or chunk too short).
        """
        sr = self._sample_rate
        n = len(multiplex)
        # Need enough samples for a useful FFT bin width.  At 250 kHz a
        # 65 536-point FFT gives 3.8 Hz bins; parabolic interpolation around
        # the peak gets that down to well below 0.5 Hz, more than enough to
        # eliminate the SDR clock-error residual.
        if n < self._PILOT_EST_MIN_SAMPLES:
            return None
        # Use the largest power-of-two FFT size that fits in *n*, capped at
        # 2**18 (~1 Hz bins at 250 kHz) for performance.
        n_fft = min(1 << int(np.floor(np.log2(n))), self._PILOT_EST_MAX_NFFT)
        data = multiplex[:n_fft].astype(np.float64)
        # Hann window suppresses spectral leakage from the (much larger)
        # audio components below 15 kHz, giving a cleaner pilot peak.
        spectrum = np.abs(np.fft.rfft(data * np.hanning(n_fft)))
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
        mask = (freqs >= 18500.0) & (freqs <= 19500.0)
        if not np.any(mask):
            return None
        idx_in_mask = int(np.argmax(spectrum[mask]))
        idx = int(np.where(mask)[0][idx_in_mask])
        if 0 < idx < len(spectrum) - 1:
            # Parabolic interpolation: refine the peak to sub-bin accuracy.
            # The denominator vanishes when the three samples are colinear;
            # that almost never happens with windowed FFT magnitudes, but
            # guard against it to avoid producing inf when it does.
            a, b, c = float(spectrum[idx - 1]), float(spectrum[idx]), float(spectrum[idx + 1])
            denom = a - 2.0 * b + c
            delta = (
                0.5 * (a - c) / denom
                if abs(denom) > self._PARABOLIC_INTERP_MIN_DENOM
                else 0.0
            )
            peak_hz = float(freqs[idx]) + delta * (freqs[1] - freqs[0])
        else:
            peak_hz = float(freqs[idx])
        # SNR sanity check: the peak amplitude must clearly stand above the
        # noise floor of the search band, otherwise we're locking onto stereo
        # subcarrier sidebands or noise on a mono station. 4× the median
        # rejects monolithically flat (mono / noise-only) bands while still
        # accepting weak pilots — a real broadcast pilot is typically 10×+
        # over the median in this band.
        band = spectrum[mask]
        median = float(np.median(band))
        if median > 0 and float(spectrum[idx]) < self._pilot_snr_threshold * median:
            return None
        # Reject obvious nonsense.  At ±4 Hz (~210 ppm at 19 kHz) we're well
        # past anything an even loosely-calibrated SDR produces (typical
        # 25-100 ppm), so anything further out signals broken hardware or a
        # mis-detection — fall back to the 19 000.0 Hz nominal instead.
        if abs(peak_hz - 19000.0) > self._MAX_PILOT_DEVIATION_HZ:
            return None
        return peak_hz

    def _detect_off_frequency_interferer_hz(self, multiplex: np.ndarray) -> Optional[float]:
        """Return baseband offset (Hz) of a strong 55–59 kHz spur vs pilot×3."""
        if (
            not self._rbds_interference_rejection_enabled
            or self._measured_pilot_freq is None
            or len(multiplex) < self._PILOT_EST_MIN_SAMPLES
        ):
            return None
        sr = self._sample_rate
        n_fft = min(1 << int(np.floor(np.log2(len(multiplex)))), self._PILOT_EST_MAX_NFFT)
        if n_fft < 4096:
            return None
        data = multiplex[:n_fft].astype(np.float64)
        spectrum = np.abs(np.fft.rfft(data * np.hanning(n_fft)))
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
        mask = (freqs >= 55000.0) & (freqs <= 59000.0)
        if not np.any(mask):
            return None
        band = spectrum[mask]
        idx_in_mask = int(np.argmax(band))
        idx = int(np.where(mask)[0][idx_in_mask])
        peak_amp = float(spectrum[idx])
        median = float(np.median(band))
        if median <= 0.0 or peak_amp < self._pilot_snr_threshold * median:
            return None
        peak_hz = float(freqs[idx])
        expected_hz = 3.0 * float(self._measured_pilot_freq)
        offset_hz = peak_hz - expected_hz
        abs_offset = abs(offset_hz)
        if (
            abs_offset < self._rbds_interference_min_offset_hz
            or abs_offset > self._rbds_interference_guard_hz
        ):
            return None
        return offset_hz

    def _apply_interference_notch(
        self, samples: np.ndarray, sample_rate: int, offset_hz: Optional[float]
    ) -> np.ndarray:
        """Apply a narrow notch around an off-frequency post-mix interferer."""
        if offset_hz is None or len(samples) == 0:
            self._rbds_interference_notch_zi_real = None
            self._rbds_interference_notch_zi_imag = None
            return samples
        from scipy import signal as scipy_signal
        notch_hz = abs(float(offset_hz))
        nyq = sample_rate / 2.0
        if notch_hz <= 0.0 or notch_hz >= nyq:
            return samples
        if (
            self._rbds_interference_notch_b is None
            or self._rbds_interference_notch_a is None
            or self._rbds_interference_notch_freq_hz is None
            or abs(self._rbds_interference_notch_freq_hz - notch_hz) > 10.0
        ):
            w0 = notch_hz / nyq
            b, a = scipy_signal.iirnotch(w0, self._rbds_interference_notch_q)
            self._rbds_interference_notch_b = b.astype(np.float64)
            self._rbds_interference_notch_a = a.astype(np.float64)
            self._rbds_interference_notch_freq_hz = notch_hz
            zi_len = max(len(a), len(b)) - 1
            self._rbds_interference_notch_zi_real = np.zeros(zi_len, dtype=np.float64)
            self._rbds_interference_notch_zi_imag = np.zeros(zi_len, dtype=np.float64)
        real_out, self._rbds_interference_notch_zi_real = scipy_signal.lfilter(
            self._rbds_interference_notch_b,
            self._rbds_interference_notch_a,
            samples.real,
            zi=self._rbds_interference_notch_zi_real,
        )
        imag_out, self._rbds_interference_notch_zi_imag = scipy_signal.lfilter(
            self._rbds_interference_notch_b,
            self._rbds_interference_notch_a,
            samples.imag,
            zi=self._rbds_interference_notch_zi_imag,
        )
        return real_out + 1j * imag_out

    def _generate_pilot_reference(self, n: int, sample_offset: int) -> np.ndarray:
        """Generate phase-coherent 19 kHz pilot reference.

        FM broadcast stations use crystal oscillators - the 19 kHz pilot is
        EXACTLY 19000.0 Hz at the transmitter (accurate to parts per million).
        However the *receiver* SDR clock typically has 25-100 ppm error, which
        shifts the recovered pilot by ±0.5-2 Hz.  ``self._measured_pilot_freq``
        captures that actual recovered frequency so the 57 kHz mix lands the
        RBDS subcarrier exactly at DC. When no measurement is available yet
        (very first chunk after reset) we fall back to the nominal 19000.0 Hz
        — the residual error will be picked up by the Costas loop.

        This is simpler, more accurate, and noise-free compared to PLL or
        Hilbert transform approaches which try to extract phase from noisy signals.

        Args:
            n: Number of samples to generate.
            sample_offset: Absolute position of the first sample in the FM
                           stream.  Must come from the caller so that the
                           reference phase is correct even when the RBDS queue
                           has dropped some chunks (see submit_samples).

        Returns:
            Array of pilot phases for generating 57 kHz carrier (pilot × 3)
        """
        if n == 0:
            return np.array([], dtype=np.float64)

        # Use the absolute sample offset supplied by the caller so that the
        # generated phase is always aligned with the true FM stream position,
        # regardless of how many chunks were previously dropped from the queue.
        t = (np.arange(n, dtype=np.float64) + sample_offset) / self._sample_rate

        # Use the measured pilot frequency if available, else fall back to
        # the nominal 19 kHz.  The measured value is locked in once per
        # station (cleared on reset) so phase stays continuous across chunks.
        pilot_hz = (
            self._measured_pilot_freq if self._measured_pilot_freq is not None else 19000.0
        )

        # Crystal-locked pilot reference phase
        pilot_phases = 2.0 * np.pi * pilot_hz * t

        return pilot_phases

    def _start(self) -> None:
        """Start the worker thread."""
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="rbds-worker",
            daemon=True
        )
        self._thread.start()
        logger.info("RBDS worker thread started (non-blocking)")

    def stop(self) -> None:
        """Stop the worker thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("RBDS worker thread stopped")

    def submit_samples(self, multiplex: np.ndarray, sample_offset: int) -> None:
        """Submit multiplex samples for RBDS processing (non-blocking).

        If the queue is full, samples are dropped. This ensures the audio
        thread is NEVER blocked by RBDS processing.

        Args:
            multiplex: FM multiplex signal at the configured sample rate.
            sample_offset: Absolute sample position of the first sample in
                           this chunk within the continuous FM stream.  This
                           is used to generate a phase-coherent 57 kHz mixing
                           reference that is correct even when chunks are
                           dropped from the queue.
        """
        try:
            # Pass the chunk together with its absolute time offset so the
            # worker can generate the correct crystal-locked carrier phase
            # regardless of how many chunks were dropped in between.
            self._sample_queue.put_nowait((multiplex, sample_offset))
        except queue.Full:
            # RBDS is lower priority than audio — dropping is expected when
            # the DSP worker can't keep up.  Count it so the UI can surface
            # "chunks dropped" in the Decoder Health panel.
            with self._stats_lock:
                self._chunks_dropped += 1

    def get_latest_data(self) -> Optional[RBDSData]:
        """Get the latest RBDS data (thread-safe)."""
        with self._data_lock:
            return self._latest_data

    def is_synced(self) -> bool:
        """Whether the RBDS bit-level sync state machine has locked."""
        return bool(getattr(self, '_rbds_synced', False))

    def get_stats(self) -> RBDSDecoderStats:
        """Return a thread-safe snapshot of decoder health/traffic stats.

        Merges the worker's own counters (block-level FEC stats and sync
        lifecycle) with the decoder's group-type histogram so callers
        get one combined view per call.
        """
        with self._stats_lock:
            snap = RBDSDecoderStats(
                blocks_total=self._stats.blocks_total,
                blocks_ok=self._stats.blocks_ok,
                blocks_fec_single=self._stats.blocks_fec_single,
                blocks_fec_burst=self._stats.blocks_fec_burst,
                blocks_uncorrected=self._stats.blocks_uncorrected,
                groups_decoded=self._stats.groups_decoded,
                sync_acquired_unix=self._stats.sync_acquired_unix,
                sync_lost_count=self._stats.sync_lost_count,
                chunks_dropped=self._chunks_dropped,
                group_type_counts={},
            )
        # Group histogram lives on the RBDSDecoder; pull a copy here so
        # the snapshot is internally consistent.
        if self._rbds_decoder is not None:
            snap.group_type_counts = dict(
                getattr(self._rbds_decoder, '_group_type_counts', {}) or {}
            )
        return snap

    def reset(self) -> None:
        """Request the worker thread to drop all sync/decoder state.

        Used when the tuned frequency changes: the carrier/symbol-timing
        state from the previous station is meaningless for the new one, and
        the last decoded PS/PI/radiotext belongs to a different station and
        must not keep displaying.

        The actual reset runs inside the worker thread (via
        _apply_reset) to avoid racing with _process_rbds.
        """
        # Drop cached decoded metadata immediately so get_latest_data()
        # stops returning the previous station's PS/PI/radiotext.
        with self._data_lock:
            self._latest_data = None

        # Drain samples the audio thread has already queued, so the worker
        # doesn't chew through a second of stale samples before noticing
        # the reset request.
        try:
            while True:
                self._sample_queue.get_nowait()
        except queue.Empty:
            pass

        self._reset_event.set()

    def _apply_reset(self) -> None:
        """Runs in the worker thread to rebuild RBDS state cleanly."""
        # Rebuild filters / loop / decoder.  RBDSDecoder is recreated so
        # PS/RT buffers start blank.
        self._init_rbds_state()

        # Wipe per-station stats but keep cumulative sync_lost_count so
        # the UI can show "this receiver has dropped sync N times since
        # boot" across station changes.
        with self._stats_lock:
            sync_lost_count = self._stats.sync_lost_count
            self._stats = RBDSDecoderStats(sync_lost_count=sync_lost_count)

        # _init_rbds_state doesn't own the bit-level sync state machine
        # vars (they're lazily created in _decode_rbds_groups), so clear
        # them explicitly here.  Next call to _decode_rbds_groups will
        # re-initialize them from scratch.
        for attr in (
            '_rbds_synced',
            '_rbds_presync',
            '_rbds_presync_hits',
            '_rbds_presync_polarity',
            '_rbds_wrong_blocks_counter',
            '_rbds_blocks_counter',
            '_rbds_group_good_blocks_counter',
            '_rbds_reg',
            '_rbds_lastseen_offset_counter',
            '_rbds_lastseen_offset',
            '_rbds_block_bit_counter',
            '_rbds_block_number',
            '_rbds_group_assembly_started',
            '_rbds_bytes_array',
            '_rbds_global_bit_counter',
            '_rbds_inverted_polarity',
            '_rbds_sync_tentative',
            '_rbds_tentative_good_groups',
            '_rbds_sample_buffer',
        ):
            if hasattr(self, attr):
                delattr(self, attr)

        # Clear any bits already accumulated at the old carrier phase.
        self._rbds_bit_buffer = []
        self._sample_index = 0

        logger.info("RBDS worker state reset (new station or forced resync)")

    def _worker_loop(self) -> None:
        """Main worker loop - processes RBDS samples from queue."""
        logger.info("RBDS worker thread started")
        samples_processed = 0
        groups_decoded = 0

        while not self._stop_event.is_set():
            # Apply pending reset before touching any filter/sync state so
            # we never read half-updated buffers from the caller's thread.
            if self._reset_event.is_set():
                self._reset_event.clear()
                self._apply_reset()

            try:
                # Wait for samples with timeout (allows checking stop_event)
                multiplex, sample_offset = self._sample_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                samples_processed += 1
                # Process RBDS - this can take as long as needed since we're in our own thread
                rbds_data = self._process_rbds(multiplex, sample_offset)

                if rbds_data:
                    groups_decoded += 1
                    with self._data_lock:
                        self._latest_data = rbds_data
                    logger.info(
                        "RBDS decoded: PS='%s' PI=%s (samples=%d, groups=%d)",
                        rbds_data.ps_name,
                        rbds_data.pi_code,
                        samples_processed,
                        groups_decoded
                    )

                # Periodic status logging (every 100 samples processed)
                if samples_processed % 100 == 0:
                    logger.debug(
                        "RBDS worker status: %d samples processed, %d groups decoded, buffer=%d bits, crc_fails=%d",
                        samples_processed,
                        groups_decoded,
                        len(self._rbds_bit_buffer),
                        self._rbds_consecutive_crc_failures
                    )

            except Exception as e:
                logger.warning("RBDS processing error: %s", e, exc_info=True)

        logger.info("RBDS worker thread exited (samples=%d, groups=%d)", samples_processed, groups_decoded)

    def _process_rbds(self, multiplex: np.ndarray, sample_offset: int) -> Optional[RBDSData]:
        """Process multiplex samples to extract RBDS data.

        Based on PySDR's working implementation:
        https://pysdr.org/content/rds.html

        Processing order: Costas carrier-phase loop FIRST (at 19 kHz), then M&M
        symbol timing recovery.  This is the standard order used by PySDR, GNU Radio,
        and redsea: running M&M on a phase-rotating signal produces noisy timing
        estimates and prevents the Costas loop from acquiring carrier lock.

        CRITICAL FIX for Airspy: The multiplex arrives at 250 kHz after early decimation.
        We must extract the 57 kHz RBDS subcarrier BEFORE any lowpass filtering that would
        remove it. Correct order: bandpass → mix → lowpass → decimate.

        Args:
            multiplex: FM multiplex signal (real-valued, at self._sample_rate Hz).
            sample_offset: Absolute position of the first sample in the FM stream.
                           Used to compute the correct crystal-locked 57 kHz carrier
                           phase even when earlier chunks were dropped from the queue.
        """
        if len(multiplex) == 0:
            return None

        # Start with multiplex at original sample rate (250 kHz for Airspy after early decim)
        x = multiplex.astype(np.float32)
        sample_rate = self._sample_rate

        # Step 1: Generate phase-coherent 57 kHz carrier from crystal-locked 19 kHz reference
        # CRITICAL ARCHITECTURE FIX: FM stations use crystal oscillators
        # The 19 kHz pilot is EXACTLY 19000.0 Hz (parts per million accuracy)
        # We don't need PLL/Hilbert - just generate perfect reference!
        # 57 kHz = pilot × 3 ensures phase coherence with transmitter.
        #
        # IMPORTANT: Use sample_offset (the absolute position of this chunk in the
        # FM stream) rather than a local counter.  When the queue is full the audio
        # thread drops chunks; if we use a local counter it lags behind real time and
        # the resulting 57 kHz reference phase is completely wrong for every subsequent
        # chunk, making the extracted RBDS bits pure noise.
        n = len(multiplex)
        interferer_offset_hz = self._detect_off_frequency_interferer_hz(multiplex)

        # On the first chunk after a reset, measure the actual recovered pilot
        # frequency.  RTL-SDR dongles often have 25-100 ppm clock error, which
        # shifts the recovered pilot by 0.5-2 Hz.  Tripling that for the 57 kHz
        # mix leaves a 1.5-6 Hz residual the Costas loop has to track on top
        # of phase noise.  Locking the carrier reference to the measured
        # frequency puts the RBDS subcarrier at DC after mixing, eliminating
        # that systematic offset entirely.  We measure once and freeze: the
        # *transmitter* is crystal-locked and the *receiver* clock drifts on
        # the order of tens of ppb per minute, far below what Costas tracks.
        if self._measured_pilot_freq is None:
            measured = self._estimate_pilot_frequency(multiplex)
            if measured is not None:
                self._measured_pilot_freq = measured
                self._pilot_samples_since_remeasure = 0
                ppm = (measured - 19000.0) / 19000.0 * 1e6
                logger.info(
                    "RBDS pilot measured: %.3f Hz (offset %+0.3f Hz, %+.1f ppm SDR clock error). "
                    "57 kHz reference will be %.3f Hz.",
                    measured,
                    measured - 19000.0,
                    ppm,
                    3.0 * measured,
                )
        else:
            # Periodic re-measurement to track slow TCXO thermal drift.  We
            # accumulate sample count rather than wall-clock time so this
            # behaves identically across queue stalls and is trivially
            # testable.  Implausibly large jumps and SNR-fail returns from
            # _estimate_pilot_frequency (None) are rejected; only small
            # drifts blend in via EMA.
            self._pilot_samples_since_remeasure += len(multiplex)
            remeasure_interval_samples = int(
                self._PILOT_REMEASURE_INTERVAL_SEC * self._sample_rate
            )
            if self._pilot_samples_since_remeasure >= remeasure_interval_samples:
                self._pilot_samples_since_remeasure = 0
                new_measure = self._estimate_pilot_frequency(multiplex)
                if (
                    new_measure is not None
                    and abs(new_measure - self._measured_pilot_freq)
                    <= self._PILOT_REMEASURE_MAX_DRIFT_HZ
                ):
                    old = self._measured_pilot_freq
                    alpha = self._PILOT_REMEASURE_EMA_ALPHA
                    self._measured_pilot_freq = (1.0 - alpha) * old + alpha * new_measure
                    drift = self._measured_pilot_freq - old
                    if abs(drift) > 0.05:
                        logger.info(
                            "RBDS pilot remeasured: %.3f Hz (was %.3f, raw %.3f, drift %+.3f Hz)",
                            self._measured_pilot_freq,
                            old,
                            new_measure,
                            drift,
                        )

        pilot_phases = self._generate_pilot_reference(n, sample_offset)

        # Log pilot reference generation periodically
        if not hasattr(self, '_pilot_log_count'):
            self._pilot_log_count = 0
        self._pilot_log_count += 1
        if self._pilot_log_count % 100 == 1:
            # Check pilot signal strength (for diagnostics only - not used in demod)
            pilot_rms = np.sqrt(np.mean(multiplex ** 2))
            pilot_filtered_sig = np.convolve(multiplex[:min(1000, len(multiplex))], self._pilot_bandpass, mode='same')
            pilot_filtered_rms = np.sqrt(np.mean(pilot_filtered_sig ** 2))
            pilot_hz = self._measured_pilot_freq if self._measured_pilot_freq is not None else 19000.0
            expected_phase = 2.0 * np.pi * pilot_hz * n / self._sample_rate
            logger.info(
                "RBDS Pilot (locked at %.3f Hz): multiplex_rms=%.3f, "
                "filtered_rms=%.3f, samples=%d, expected_phase=%.2f rad",
                pilot_hz, pilot_rms, pilot_filtered_rms, n, expected_phase,
            )

        # Step 2: Bandpass filter to extract 57 kHz RBDS subcarrier (54-60 kHz)
        # CRITICAL: Do this BEFORE decimation that would remove the 57 kHz signal!
        # Use lfilter with persisted state (zi) so the filter's delay line
        # carries over from the previous chunk; np.convolve zeroes it every
        # call, which produced (ntaps-1) samples of transient at the start of
        # every chunk and flooded the bit-sync with garbage.
        if self._rbds_bandpass is not None and sample_rate >= self.RBDS_MIN_SAMPLE_RATE:
            from scipy import signal as scipy_signal
            if self._rbds_bandpass_zi is None or len(self._rbds_bandpass_zi) != len(self._rbds_bandpass) - 1:
                self._rbds_bandpass_zi = np.zeros(len(self._rbds_bandpass) - 1, dtype=x.dtype)
            x, self._rbds_bandpass_zi = scipy_signal.lfilter(
                self._rbds_bandpass, [1.0], x, zi=self._rbds_bandpass_zi
            )

        # Step 3: Frequency shift to baseband using PILOT-DERIVED carrier
        # Generate 57 kHz = pilot × 3 (third harmonic)
        # This ensures our local oscillator is phase-coherent with transmitter!
        n = len(x)
        if len(pilot_phases) == n:
            # Use pilot-derived carrier: 57 kHz = 3 × 19 kHz
            carrier_phases_57k = 3.0 * pilot_phases
            x = x * np.exp(-1j * carrier_phases_57k)
        else:
            # Fallback to fixed oscillator if pilot tracking failed
            logger.warning("RBDS: Pilot tracking failed, using fixed 57 kHz oscillator")
            phase_increment = 2.0 * np.pi * 57000.0 / sample_rate
            phases = self._carrier_phase_57k + phase_increment * np.arange(n, dtype=np.float64)
            x = x * np.exp(-1j * phases)
            self._carrier_phase_57k = (self._carrier_phase_57k + phase_increment * n) % (2.0 * np.pi)

        x = self._apply_interference_notch(x, sample_rate, interferer_offset_hz)

        # Step 3: Lowpass filter (7.5 kHz) to remove mixing artifacts and aliases.
        # After the 57 kHz mix x is complex; lfilter keeps real delay lines per
        # component, so filter the real and imaginary parts separately with
        # their own persisted zi arrays.
        from scipy import signal as scipy_signal
        lp_state_len = len(self._rbds_lowpass) - 1
        if self._rbds_lowpass_zi_real is None or len(self._rbds_lowpass_zi_real) != lp_state_len:
            self._rbds_lowpass_zi_real = np.zeros(lp_state_len, dtype=np.float64)
            self._rbds_lowpass_zi_imag = np.zeros(lp_state_len, dtype=np.float64)
        real_out, self._rbds_lowpass_zi_real = scipy_signal.lfilter(
            self._rbds_lowpass, [1.0], x.real, zi=self._rbds_lowpass_zi_real
        )
        imag_out, self._rbds_lowpass_zi_imag = scipy_signal.lfilter(
            self._rbds_lowpass, [1.0], x.imag, zi=self._rbds_lowpass_zi_imag
        )
        x = real_out + 1j * imag_out

        # Buffer at the high (post-lowpass) sample rate.  Earlier this code
        # decimated and resampled per chunk, then accumulated the resampled
        # output — but `x[::decim]` resets its phase at every chunk boundary
        # and `scipy.signal.resample_poly` is stateless, so each ~8 ms chunk
        # injected a polyphase filter transient into the bit stream.  Across
        # the ~31 chunks that fit in a 250 ms batch that's 31 stitched-together
        # transients feeding M&M, which manifests downstream as the random
        # presync spacings the operator was seeing (expected 26, got 92,
        # expected 104, got 151, …).  Accumulating BEFORE decim+resample
        # keeps the bit clock continuous within a batch — there's exactly
        # one resample transient per batch instead of 31.
        if not hasattr(self, '_rbds_sample_buffer'):
            self._rbds_sample_buffer = np.array([], dtype=np.complex64)

        self._rbds_sample_buffer = np.concatenate([self._rbds_sample_buffer, x])

        # The window thresholds are expressed in samples at the 19 kHz
        # output rate, so scale them up to the current input rate.
        scale = sample_rate / 19000.0
        locked = getattr(self, '_rbds_synced', False)
        window_19k = self.RBDS_SYNCED_WINDOW if locked else self.RBDS_UNSYNCED_WINDOW
        window = int(window_19k * scale)
        if len(self._rbds_sample_buffer) < window:
            return self._decode_rbds_groups()

        # Use buffered samples and reset for next accumulation
        x = self._rbds_sample_buffer
        self._rbds_sample_buffer = np.array([], dtype=np.complex64)

        # Step 4: Decimate to intermediate rate (~25 kHz) to reduce processing load
        # Now safe to decimate since we've already extracted and mixed down the
        # RBDS signal, AND we're operating on a contiguous buffer so x[::decim]
        # has a single, consistent phase for the whole batch.
        decim = max(1, int(sample_rate / self.RBDS_INTERMEDIATE_RATE))
        if decim > 1:
            x = x[::decim]
            sample_rate = int(sample_rate // decim)  # Keep as int

        # Step 5: Resample to exactly 19 kHz (16 samples per symbol at 1187.5
        # baud).  Done once on the entire batch so the polyphase transient
        # only affects the very first few samples, not every chunk boundary.
        if not hasattr(self, '_rate_log_count'):
            self._rate_log_count = 0
        self._rate_log_count += 1
        if self._rate_log_count % 100 == 1:
            logger.debug(
                "RBDS rates: input=%d, post-decim=%d, resampling %d->19000, samples=%d",
                self._sample_rate, sample_rate, sample_rate, len(x)
            )
        x = self._resample(x, sample_rate, 19000)

        # Do NOT reset M&M / Costas state between batches.
        # Unlike an offline recording processed in one pass, this is a continuous
        # stream that feeds 250 ms slices one at a time.  The M&M timing
        # estimator (mu) and the Costas carrier-phase/frequency state are
        # intentionally carried forward so the loops stay locked across batches
        # rather than having to re-converge from scratch every batch.

        if len(x) < 48:  # Need enough samples for processing
            return self._decode_rbds_groups()

        # Step 6: Costas Loop for BPSK carrier phase/frequency correction (FIRST).
        # Running Costas at the full 19 kHz sample rate (16 samples/symbol) gives
        # the loop enough bandwidth (~17 Hz) to acquire the carrier even when the
        # SDR clock has ±100 ppm error (which shifts the 57 kHz subcarrier by
        # ~5.7 Hz).  Running it after M&M at symbol rate — the old order — reduced
        # the effective bandwidth to ~3.5 Hz, which was too narrow to lock reliably.
        # Reference: https://pysdr.org/content/rds.html (Costas before M&M)
        x = self._costas_loop(x)

        # Log Costas frequency offset to check if it's locked
        if hasattr(self, '_costas_log_count'):
            self._costas_log_count += 1
        else:
            self._costas_log_count = 0
        if self._costas_log_count % 50 == 0:
            logger.debug(
                "RBDS Costas: freq=%.3f Hz, phase=%.2f rad",
                self._rbds_costas_freq * 19000.0 / (2 * np.pi),  # Convert to Hz at 19 kHz
                self._rbds_costas_phase
            )

        if len(x) < 2:
            return self._decode_rbds_groups()

        # Step 7: M&M Symbol Timing Recovery (SECOND, after carrier correction).
        # M&M now operates on a signal whose carrier phase has already been
        # corrected by the Costas loop, so timing error estimates are clean.
        n_before = len(x)
        x = self._mm_timing_pysdr(x)
        # Reduced logging: only log M&M timing every 500th call to avoid log flooding
        if not hasattr(self, '_mm_log_count'):
            self._mm_log_count = 0
        self._mm_log_count += 1
        if self._mm_log_count % 500 == 1:
            logger.debug("RBDS M&M: %d samples -> %d symbols (logged every 500 calls)", n_before, len(x))

        if len(x) < 2:
            return self._decode_rbds_groups()

        # Step 8: BPSK demod + differential decode (EN 62106 standard)
        # RBDS differential decoding using python-radio algorithm
        # Reference: https://github.com/ChrisDev8/python-radio/blob/main/decoder.py
        # "Differential decoding, so that it doesn't matter whether our BPSK was 180 degrees rotated"
        # Formula: bits = (bits[1:] - bits[0:-1]) % 2
        
        # BPSK demod: Extract symbols from REAL axis (after Costas phase correction)
        bits_raw = (np.real(x) > 0).astype(np.int8)

        if len(bits_raw) > 0:
            # CRITICAL: Prepend last symbol from previous chunk for continuity
            prev_sym = self._rbds_prev_symbol
            all_symbols = np.concatenate(([prev_sym], bits_raw))

            # Use python-radio's exact differential formula: (bits[1:] - bits[0:-1]) % 2
            # This handles 180° phase ambiguity automatically
            diff = (all_symbols[1:] - all_symbols[:-1]) % 2

            # Save last symbol value for next chunk continuity (0 or 1)
            self._rbds_prev_symbol = int(bits_raw[-1])

            n_bits = len(diff)
            n_ones = int(np.sum(diff))
            # Reduced logging: only log bit extraction every 500th call to avoid log flooding
            if n_bits > 0:
                if not hasattr(self, '_bits_log_count'):
                    self._bits_log_count = 0
                self._bits_log_count += 1
                if self._bits_log_count % 500 == 1:
                    logger.debug(
                        "RBDS bits: %d new bits, %d ones (%.1f%%), buffer=%d (logged every 500 calls)",
                        n_bits, n_ones, 100.0 * n_ones / n_bits, len(self._rbds_bit_buffer)
                    )
            self._rbds_bit_buffer.extend(diff.tolist())

        return self._decode_rbds_groups()

    def _mm_timing_pysdr(self, samples: np.ndarray) -> np.ndarray:
        """M&M symbol timing recovery using python-radio proven implementation.

        This is the EXACT implementation from https://github.com/ChrisDev8/python-radio
        which is known to work correctly for RBDS decoding.
        """
        # Prepend any unconsumed samples from the previous call so that the M&M
        # loop never silently discards the partial symbol at the end of a batch.
        # Without this, the block boundary drifts by ~1 symbol (~16 samples) every
        # 250 ms, causing every block to CRC-fail immediately after sync is acquired.
        if len(self._rbds_mm_leftover) > 0:
            samples = np.concatenate((self._rbds_mm_leftover, samples))

        n = len(samples)
        if n < 32:
            self._rbds_mm_leftover = samples.astype(np.complex64, copy=False)
            return np.array([], dtype=np.complex64)

        # Upsample by 16x for interpolation (python-radio method)
        try:
            from scipy import signal as scipy_signal
            samples_interpolated = scipy_signal.resample_poly(samples, 16, 1)
        except ImportError:
            # Fallback: linear interpolation
            old_len = len(samples)
            new_len = old_len * 16
            old_indices = np.arange(old_len)
            new_indices = np.linspace(0, old_len - 1, new_len)
            real_interp = np.interp(new_indices, old_indices, samples.real)
            imag_interp = np.interp(new_indices, old_indices, samples.imag)
            samples_interpolated = (real_interp + 1j * imag_interp).astype(np.complex64)

        sps = 16  # samples per symbol in interpolated space
        mu = self._rbds_mm_mu if hasattr(self, '_rbds_mm_mu') else 0.01

        # Output should be ~len(samples)/16 symbols (downsampling from 16 sps to 1 sps)
        # Allocate conservatively
        max_out = len(samples) // 16 + 100

        if _NUMBA_AVAILABLE and len(samples_interpolated) > 50:
            # JIT-compiled inner loop: converts ~n/16 Python iterations to
            # one native call, eliminating per-symbol Python overhead.
            interp_r = np.ascontiguousarray(samples_interpolated.real, dtype=np.float64)
            interp_i = np.ascontiguousarray(samples_interpolated.imag, dtype=np.float64)
            out_real, out_imag, i_out, i_in, mu = _mm_timing_loop_numba(
                interp_r, interp_i, mu, max_out
            )
            out = (out_real + 1j * out_imag).astype(np.complex64)
        else:
            out = np.zeros(max_out, dtype=np.complex64)
            out_rail = np.zeros(max_out, dtype=np.complex64)
            i_in = 0  # input sample index (original sample space)
            i_out = 2  # output symbol index (let first two outputs be 0)

            # CRITICAL FIX: Check against interpolated array length, not original length
            while i_out < max_out - 1:
                # Calculate index into interpolated array
                interp_idx = i_in * 16 + int(mu * 16)

                # Boundary check: ensure we don't read past end of interpolated array
                if interp_idx >= len(samples_interpolated) - 1:
                    break

                out[i_out] = samples_interpolated[interp_idx]
                out_rail[i_out] = int(np.real(out[i_out]) > 0) + 1j * int(np.imag(out[i_out]) > 0)
                x = (out_rail[i_out] - out_rail[i_out - 2]) * np.conj(out[i_out - 1])
                y = (out[i_out] - out[i_out - 2]) * np.conj(out_rail[i_out - 1])
                mm_val = np.real(y - x)
                # Bumped from 0.01 to 0.05.  python-radio's reference uses 0.01
                # for offline whole-recording processing where the timing has
                # all the symbols to converge against.  In a streaming pipeline
                # where each batch is ~250 ms (~300 symbols) and we then carry
                # mu forward, 0.01 was too narrow to settle: the user saw
                # continuous "presync spacing mismatch" with random spacings,
                # which is the signature of a slowly-wandering symbol clock.
                # 0.05 still has plenty of margin against oscillation (the
                # standard rule of thumb for Mueller&Müller is gain < ~0.2).
                mu += sps + 0.05 * mm_val
                i_in += int(np.floor(mu))
                mu = mu - np.floor(mu)
                i_out += 1

        # Save unconsumed tail samples so the next call can consume them instead
        # of silently dropping them and drifting the symbol clock.
        self._rbds_mm_leftover = samples[i_in:].astype(np.complex64, copy=False)

        # Save mu state for next call
        self._rbds_mm_mu = mu

        return out[2:i_out]

    def _costas_pysdr(self, samples: np.ndarray) -> np.ndarray:
        """Costas loop for BPSK carrier/phase synchronization.

        Adapted from https://github.com/ChrisDev8/python-radio but uses the
        instance-level loop parameters (alpha / beta) rather than the
        python-radio defaults.  Loop runs at the full 19 kHz rate (before M&M),
        using the PySDR / GNU Radio standard values (alpha=8.7e-3, beta=3.2e-5)
        which give ~17 Hz bandwidth — wide enough to acquire the carrier even
        when an RTL-SDR has ±100 ppm clock error (≈5.7 Hz offset at 57 kHz).
        Loop state is carried forward across batches so it stays locked.
        """
        n = len(samples)
        if n == 0:
            return samples

        # Use the tuned streaming parameters from _init_rbds_state.
        alpha = self._rbds_costas_alpha
        beta = self._rbds_costas_beta

        phase = self._rbds_costas_phase if hasattr(self, '_rbds_costas_phase') else 0.0
        freq = self._rbds_costas_freq if hasattr(self, '_rbds_costas_freq') else 0.0

        out = np.zeros(n, dtype=np.complex64)
        for i in range(n):
            # Adjust the input sample by the inverse of the estimated phase offset
            out[i] = samples[i] * np.exp(-1j * phase)

            # Error formula for 2nd order Costas Loop (for BPSK)
            error = np.real(out[i]) * np.imag(out[i])

            # Advance the loop (recalc phase and freq offset)
            freq += beta * error
            phase += freq + alpha * error

            # Adjust phase so it's always between 0 and 2pi
            while phase >= 2 * np.pi:
                phase -= 2 * np.pi
            while phase < 0:
                phase += 2 * np.pi

        self._rbds_costas_phase = phase
        self._rbds_costas_freq = freq

        return out

    @staticmethod
    def _resample(signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Thin shim around the module-level :func:`resample_to`."""
        return resample_to(signal, from_rate, to_rate)

    def _costas_loop(self, samples: np.ndarray) -> np.ndarray:
        """Costas loop for BPSK frequency sync."""
        n = len(samples)
        if n == 0:
            return samples

        if _NUMBA_AVAILABLE and n > 50:
            samples_f64 = samples.astype(np.complex128)
            out_real, out_imag, phase, freq = _costas_loop_numba(
                samples_f64.real.astype(np.float64),
                samples_f64.imag.astype(np.float64),
                self._rbds_costas_phase,
                self._rbds_costas_freq,
                self._rbds_costas_alpha,
                self._rbds_costas_beta
            )
            self._rbds_costas_phase = phase
            self._rbds_costas_freq = freq
            return out_real + 1j * out_imag
        else:
            # Pure Python fallback - optimized to reduce GIL contention
            # Use math module for scalar trig (10x faster than numpy for scalars)
            out = np.empty(n, dtype=np.complex128)
            phase = self._rbds_costas_phase
            freq = self._rbds_costas_freq
            alpha = self._rbds_costas_alpha
            beta = self._rbds_costas_beta
            two_pi = 2.0 * math.pi

            # Process in batches to yield GIL periodically for audio thread
            batch_size = 256
            samples_real = samples.real
            samples_imag = samples.imag

            for batch_start in range(0, n, batch_size):
                batch_end = min(batch_start + batch_size, n)
                for i in range(batch_start, batch_end):
                    cos_phase = math.cos(phase)
                    sin_phase = math.sin(phase)
                    s_real = samples_real[i]
                    s_imag = samples_imag[i]
                    out_real = s_real * cos_phase + s_imag * sin_phase
                    out_imag = s_imag * cos_phase - s_real * sin_phase
                    out[i] = complex(out_real, out_imag)
                    error = out_real * out_imag
                    freq += beta * error
                    phase += freq + alpha * error
                    if phase >= two_pi or phase < 0:
                        phase = phase % two_pi

            self._rbds_costas_phase = phase
            self._rbds_costas_freq = freq
            return out

    def _mm_clock_recovery(self, samples: np.ndarray) -> List[int]:
        """M&M clock recovery."""
        n = len(samples)
        if n < 32:
            return []

        sps = self._rbds_samples_per_symbol
        bits: List[int] = []
        mu = self._rbds_mm_mu
        out_rail = self._rbds_mm_out_rail
        out = self._rbds_mm_out
        prev_symbol = self._rbds_prev_symbol

        i = 0
        max_symbols = n // sps + 5

        for _ in range(max_symbols):
            if i + sps >= n:
                break

            idx = int(i + mu)
            if idx >= n - 1:
                break

            frac = (i + mu) - idx
            s0_real = samples[idx].real
            s1_real = samples[idx + 1].real
            out_new = s0_real * (1.0 - frac) + s1_real * frac
            out_rail_new = 1.0 if out_new > 0.0 else -1.0
            timing_error = (out_rail * out_new) - (out_rail_new * out)
            out = out_new
            out_rail = out_rail_new

            symbol = 1.0 if out_new >= 0 else -1.0
            # RBDS differential decoding: phase change = 1, no change = 0
            # This matches python-radio: bits = (bits[1:] - bits[0:-1]) % 2
            bit = 1 if symbol != prev_symbol else 0
            prev_symbol = symbol
            bits.append(bit)

            adjustment = 0.02 * timing_error
            adjustment = max(-sps * 0.5, min(sps * 0.5, adjustment))
            mu = mu + sps + adjustment

            while mu >= 1.0:
                mu -= 1.0
                i += 1
            while mu < 0.0:
                mu += 1.0
                i -= 1

            i += sps

        self._rbds_mm_mu = mu
        self._rbds_mm_out_rail = out_rail
        self._rbds_mm_out = out
        self._rbds_prev_symbol = prev_symbol

        return bits

    def _decode_rbds_groups(self) -> Optional[RBDSData]:
        """Decode RBDS groups from bit buffer.

        This uses the EXACT synchronization logic from python-radio:
        https://github.com/ChrisDev8/python-radio/blob/main/decoder.py
        
        Their code is proven to work, so we use it verbatim for sync logic.
        """
        changed = False

        # python-radio constants
        syndrome = [383, 14, 303, 663, 748]
        offset_pos = [0, 1, 2, 3, 2]
        offset_word = [252, 408, 360, 436, 848]

        # Initialize state if not present
        if not hasattr(self, '_rbds_synced'):
            self._rbds_synced = False
            self._rbds_presync = False
            self._rbds_presync_hits = 0
            self._rbds_presync_polarity: Optional[bool] = None
            self._rbds_wrong_blocks_counter = 0
            self._rbds_blocks_counter = 0
            self._rbds_group_good_blocks_counter = 0
            self._rbds_reg = 0
            self._rbds_lastseen_offset_counter = 0
            self._rbds_lastseen_offset = 0
            self._rbds_block_bit_counter = 0
            self._rbds_block_number = 0
            self._rbds_group_assembly_started = False
            self._rbds_bytes_array = bytearray(8)
            self._rbds_global_bit_counter = 0  # CRITICAL: maintain across buffer clears
            self._rbds_inverted_polarity = False
            # Tentative-sync state: when the presync state machine declares a
            # lock we do NOT immediately trust it.  The presync gate accepts a
            # candidate after only 2 spacing-confirmed syndrome hits (~52 bits
            # of evidence), and on a Bernoulli-1/2 stream a syndrome match
            # arrives every ~1024 bits; with the ±4-bit spacing tolerance
            # false locks are statistically inevitable on weak/no signal.
            # Once tentatively-synced we wait until at least
            # _RBDS_TENTATIVE_GOOD_GROUPS fully-decoded (4-block) groups land
            # in the next 50-block sync-quality window before confirming.
            # While tentative we suppress process_group() publishing and the
            # sync_acquired_unix / groups_decoded stat updates so fake-sync
            # events can't inject corrupt metadata into the UI.
            self._rbds_sync_tentative = False
            self._rbds_tentative_good_groups = 0

        # Process all bits in buffer (python-radio style)
        bits = self._rbds_bit_buffer

        # JIT-accelerated presync: scan the entire bit buffer for syndrome
        # matches in one native pass, avoiding per-bit Python overhead on the
        # presync hot path.  _presync_matches maps bit-index → (syndrome_j,
        # polarity) for every bit where a syndrome hit was found.  Set to None
        # when Numba is unavailable or we are already synced (the synced-mode
        # path processes only ~45 blocks/sec so per-bit overhead is negligible).
        _presync_matches: Optional[dict] = None
        if _NUMBA_AVAILABLE and not self._rbds_synced and len(bits) > 0:
            _bits_arr = np.array(bits, dtype=np.int8)
            _mp, _mj, _mpol = _presync_scan_numba(
                _bits_arr, np.int64(self._rbds_reg), _RBDS_SYNDROMES
            )
            _presync_matches = {}
            for _e in range(len(_mp)):
                _presync_matches[int(_mp[_e])] = (int(_mj[_e]), bool(_mpol[_e]))

        for i in range(len(bits)):
            # Use global bit counter for spacing calculations
            global_i = self._rbds_global_bit_counter
            self._rbds_global_bit_counter += 1

            # Shift in next bit (python-radio uses numpy bitwise ops, we use Python ops)
            self._rbds_reg = ((self._rbds_reg << 1) | bits[i]) & 0x3FFFFFF
            
            if not self._rbds_synced:
                # PRESYNC MODE (python-radio logic)
                # Resolve the syndrome match for this bit: look it up in the
                # JIT-precomputed map (fast path, no Python syndrome loops) or
                # compute the two syndromes now (Python fallback / no-Numba).
                if _presync_matches is not None:
                    _match = _presync_matches.get(i)
                    if _match is None:
                        continue  # no syndrome match at this bit: advance to next
                    j, polarity = _match
                else:
                    reg_syndrome = self._calc_syndrome(self._rbds_reg, 26)
                    reg_syndrome_inverted = self._calc_syndrome(self._rbds_reg ^ 0x3FFFFFF, 26)
                    polarity = None
                    j = -1  # -1 is the "no match yet" sentinel; overwritten on first hit
                    for jj in range(5):
                        if reg_syndrome == syndrome[jj]:
                            polarity = False
                            j = jj
                            break
                        elif reg_syndrome_inverted == syndrome[jj]:
                            polarity = True
                            j = jj
                            break
                    if polarity is None:
                        continue  # no syndrome match at this bit: advance to next

                if not self._rbds_presync:
                    # First valid block found
                    self._rbds_lastseen_offset = j
                    self._rbds_lastseen_offset_counter = global_i
                    self._rbds_inverted_polarity = polarity
                    self._rbds_presync_polarity = polarity
                    self._rbds_presync_hits = 0
                    self._rbds_presync = True
                    polarity_text = "inverted" if polarity else "normal"
                    logger.info(
                        "RBDS presync: first block type %d at bit %d (%s polarity)",
                        j,
                        global_i,
                        polarity_text,
                    )
                else:
                    # Second valid block - check spacing
                    if self._rbds_presync_polarity is not None and polarity != self._rbds_presync_polarity:
                        # Mixed polarity during presync usually indicates a random
                        # syndrome collision in noise.  Restart presync from this
                        # block to avoid false "sync then immediate 50/50 CRC fail".
                        self._rbds_lastseen_offset = j
                        self._rbds_lastseen_offset_counter = global_i
                        self._rbds_inverted_polarity = polarity
                        self._rbds_presync_polarity = polarity
                        self._rbds_presync_hits = 0
                        continue  # restart with this block as the new first candidate

                    if offset_pos[self._rbds_lastseen_offset] >= offset_pos[j]:
                        block_distance = offset_pos[j] + 4 - offset_pos[self._rbds_lastseen_offset]
                    else:
                        block_distance = offset_pos[j] - offset_pos[self._rbds_lastseen_offset]

                    expected_spacing = block_distance * 26
                    actual_spacing = global_i - self._rbds_lastseen_offset_counter

                    if (
                        abs(actual_spacing - expected_spacing)
                        > self._rbds_presync_spacing_tolerance_bits
                    ):
                        # Wrong spacing - reset presync and try current block as new first.
                        # Tolerance is ±4 bits (not 0 as in offline python-radio): M&M
                        # symbol timing jitter accumulates ~1 bit per 26-bit block so
                        # over a 78-bit (3-block) span the spacing error reaches ±3-4
                        # bits.  ±2 caused every near-miss to fail (seen in the field
                        # as continuous "expected 78, got 75/82" mismatches with 0
                        # groups decoded).
                        logger.debug("RBDS presync spacing mismatch: expected %s, got %s", expected_spacing, actual_spacing)
                        self._rbds_lastseen_offset = j
                        self._rbds_lastseen_offset_counter = global_i
                        self._rbds_inverted_polarity = polarity
                        self._rbds_presync_polarity = polarity
                        self._rbds_presync_hits = 0
                        # Keep presync=True with new first block
                    else:
                        # Require 3 consecutive correctly spaced presync blocks
                        # (two spacing confirmations) before declaring lock.
                        # This materially reduces false-lock events where random
                        # syndrome hits produce "SYNCED" followed by 50/50 CRC loss.
                        self._rbds_presync_hits += 1
                        self._rbds_lastseen_offset = j
                        self._rbds_lastseen_offset_counter = global_i
                        self._rbds_inverted_polarity = polarity
                        self._rbds_presync_polarity = polarity

                        if self._rbds_presync_hits >= 2:
                            logger.info("RBDS TENTATIVELY SYNCED at bit %d (awaiting group confirmation)", global_i)
                            self._rbds_wrong_blocks_counter = 0
                            self._rbds_blocks_counter = 0
                            self._rbds_block_bit_counter = 0
                            # CRITICAL FIX: Use offset_pos[j] to determine the next expected
                            # block number, not j directly.  For C' (j=4), offset_pos[4]=2
                            # (same slot as C), so the next block is D (3), not B (1).
                            # Using (j+1)%4 gives 1 for j=4 which is wrong and causes
                            # immediate sync loss for stations broadcasting Group 2B.
                            self._rbds_block_number = (offset_pos[j] + 1) % 4
                            self._rbds_group_assembly_started = False
                            # Stale failure streak from the previous lock would
                            # otherwise trip the burst-FEC suppression gate on
                            # the very first blocks of this new lock — silently
                            # disabling the corrector that's most useful right
                            # when we're trying to ratify a tentative sync.
                            self._rbds_consecutive_crc_failures = 0
                            # Update polarity to match the triggering block so synced-mode
                            # CRC checks use the correct inversion flag.
                            self._rbds_inverted_polarity = polarity
                            self._rbds_synced = True
                            # Enter tentative mode: don't publish or set
                            # sync_acquired_unix until the next 50-block
                            # window confirms enough fully-decoded
                            # groups (see _RBDS_TENTATIVE_GOOD_GROUPS).
                            self._rbds_sync_tentative = True
                            self._rbds_tentative_good_groups = 0
                            # Reset per-lock health stats so BLER and FEC
                            # counts reflect the *current* sync window, as
                            # the RBDSDecoderStats docstring promises.  The
                            # prior behaviour silently violated that contract:
                            # blocks_total / blocks_uncorrected accumulated
                            # across every marginal lock since boot, so a
                            # receiver that had bounced sync 78 times showed
                            # 65% BLER even when the live signal was clean.
                            # sync_lost_count is preserved (it's documented
                            # as the one cumulative counter) so the operator-
                            # visible "sync drops since boot" still reflects
                            # lifetime drops on this station.
                            with self._stats_lock:
                                preserved_drops = self._stats.sync_lost_count
                                self._stats = RBDSDecoderStats(
                                    sync_lost_count=preserved_drops,
                                )
            
            else:
                # SYNCED MODE (python-radio logic)
                if self._rbds_block_bit_counter < 25:
                    self._rbds_block_bit_counter += 1
                else:
                    # Complete 26-bit block received - check CRC
                    def _crc_ok_for_block(block_word_value: int, block_number: int) -> bool:
                        dataword_value = (block_word_value >> 10) & 0xFFFF
                        block_calculated_crc_value = self._calc_syndrome(dataword_value, 16)
                        checkword_value = block_word_value & 0x3FF
                        if block_number == 2:
                            # Block C can be C or C' offset word.
                            return (
                                (checkword_value ^ offset_word[2]) == block_calculated_crc_value
                                or (checkword_value ^ offset_word[4]) == block_calculated_crc_value
                            )
                        return (checkword_value ^ offset_word[block_number]) == block_calculated_crc_value

                    def _try_correct_single_bit_error(
                        block_word_value: int,
                        block_number: int,
                    ) -> tuple[bool, int]:
                        """Attempt single-bit RBDS block repair.

                        NRSC-4-B / IEC 62106 uses a (26,16) code with 10 check bits. A
                        one-bit error is correctable if toggling exactly one bit produces
                        a valid CRC+offset check for this expected block slot.
                        """
                        if _crc_ok_for_block(block_word_value, block_number):
                            return True, block_word_value

                        corrected_word: Optional[int] = None
                        for bit_index in range(26):
                            candidate = block_word_value ^ (1 << bit_index)
                            if _crc_ok_for_block(candidate, block_number):
                                # Ambiguous multi-candidate correction can happen in noise;
                                # reject ambiguous cases instead of guessing.
                                if corrected_word is not None:
                                    return False, block_word_value
                                corrected_word = candidate

                        if corrected_word is None:
                            return False, block_word_value
                        return True, corrected_word

                    burst_table = self._burst_correction_table()

                    def _try_correct_burst_error(
                        block_word_value: int,
                        block_number: int,
                    ) -> tuple[bool, int]:
                        """Burst-trapping FEC for the (26,16) RBDS block code.

                        Recovers single bursts of up to 5 contiguous error bits, the
                        common multipath/fade failure mode where 2-5 consecutive bits
                        are corrupted together.  Implemented as a pre-computed
                        syndrome lookup (equivalent to the Meggitt trapping decoder
                        in NRSC-4-B §B.2.4).  Each candidate offset is tried
                        independently and the lowest-weight correction wins.
                        """
                        if block_number == 2:
                            offsets_to_try = (offset_word[2], offset_word[4])
                        else:
                            offsets_to_try = (offset_word[block_number],)

                        best: Optional[Tuple[int, int]] = None  # (corrected_word, weight)
                        for off in offsets_to_try:
                            # XOR offset out of the lower 10 bits to recover the
                            # raw codeword; the syndrome of a clean codeword is 0.
                            codeword = block_word_value ^ off
                            syn = self._calc_syndrome(codeword, 26)
                            if syn == 0:
                                return True, block_word_value
                            mask = burst_table.get(syn)
                            if mask is None:
                                continue
                            corrected = block_word_value ^ mask
                            weight = bin(mask).count('1')
                            if best is None or weight < best[1]:
                                best = (corrected, weight)

                        if best is None:
                            return False, block_word_value
                        return True, best[0]

                    def _repair_block(
                        candidate_word: int, block_number: int
                    ) -> tuple[bool, int, str]:
                        """Two-stage block repair: try strict single-bit first, then
                        burst-of-up-to-5 if that fails.  Single-bit is preferred
                        because it rejects ambiguous multi-candidate fits;
                        burst-trapping then catches the multipath-fade case.
                        Third tuple element labels the path used so the caller
                        can attribute the fix in the FEC stats: 'clean' (no
                        correction needed), 'single', 'burst', 'fail', or
                        'fail-suppressed' (burst-FEC gate active)."""
                        if _crc_ok_for_block(candidate_word, block_number):
                            return True, candidate_word, 'clean'
                        ok, fixed = _try_correct_single_bit_error(
                            candidate_word, block_number
                        )
                        if ok:
                            return True, fixed, 'single'
                        # Suppress burst-FEC during sustained bad streaks: see
                        # _BURST_FEC_SUPPRESS_AFTER for rationale.  The counter
                        # we read here was incremented at the end of the
                        # previous block, so it reflects the *prior* blocks'
                        # state and is not affected by the current attempt.
                        if (
                            self._rbds_consecutive_crc_failures
                            >= self._rbds_burst_fec_suppress_after
                        ):
                            return False, candidate_word, 'fail-suppressed'
                        ok, fixed = _try_correct_burst_error(
                            candidate_word, block_number
                        )
                        if ok:
                            return True, fixed, 'burst'
                        return False, candidate_word, 'fail'

                    good_block = False
                    block_word = self._rbds_reg ^ 0x3FFFFFF if self._rbds_inverted_polarity else self._rbds_reg

                    corrected, corrected_word, repair_path = _repair_block(
                        block_word, self._rbds_block_number
                    )
                    if corrected:
                        block_word = corrected_word
                        good_block = True
                    else:
                        # If current polarity suddenly fails CRC but opposite polarity passes,
                        # recover immediately instead of waiting for a full sync-loss window.
                        alternate_block_word = block_word ^ 0x3FFFFFF
                        corrected_alt, corrected_alt_word, alt_path = _repair_block(
                            alternate_block_word, self._rbds_block_number
                        )
                        if corrected_alt:
                            self._rbds_inverted_polarity = not self._rbds_inverted_polarity
                            block_word = corrected_alt_word
                            repair_path = alt_path
                            good_block = True
                            logger.info(
                                "RBDS polarity flipped while synced; continuing decode (%s polarity)",
                                "inverted" if self._rbds_inverted_polarity else "normal",
                            )
                        else:
                            self._rbds_wrong_blocks_counter += 1

                    # Attribute this block to the FEC counters.  'clean' means
                    # the syndrome was zero before any FEC; the others are
                    # categorised by which corrector won.  These feed the
                    # NRSC-4-B BLER computation surfaced via get_stats().
                    with self._stats_lock:
                        self._stats.blocks_total += 1
                        if repair_path == 'clean':
                            self._stats.blocks_ok += 1
                        elif repair_path == 'single':
                            self._stats.blocks_fec_single += 1
                        elif repair_path == 'burst':
                            self._stats.blocks_fec_burst += 1
                        else:
                            self._stats.blocks_uncorrected += 1

                    dataword = (block_word >> 10) & 0xFFFF
                    if good_block:
                        self._rbds_consecutive_crc_failures = 0
                    else:
                        self._rbds_consecutive_crc_failures += 1
                    
                    # Group assembly (python-radio logic)
                    if self._rbds_block_number == 0 and good_block:
                        self._rbds_group_assembly_started = True
                        self._rbds_group_good_blocks_counter = 0
                        self._rbds_bytes_array = bytearray(8)
                    
                    if self._rbds_group_assembly_started:
                        if not good_block:
                            self._rbds_group_assembly_started = False
                        else:
                            # Store dataword bytes
                            self._rbds_bytes_array[self._rbds_block_number * 2] = (dataword >> 8) & 0xFF
                            self._rbds_bytes_array[self._rbds_block_number * 2 + 1] = dataword & 0xFF
                            self._rbds_group_good_blocks_counter += 1

                            if self._rbds_group_good_blocks_counter == 4:  # RBDS groups have 4 blocks (A,B,C,D)
                                # Complete group received - decode it
                                group_0 = self._rbds_bytes_array[1] | (self._rbds_bytes_array[0] << 8)
                                group_1 = self._rbds_bytes_array[3] | (self._rbds_bytes_array[2] << 8)
                                group_2 = self._rbds_bytes_array[5] | (self._rbds_bytes_array[4] << 8)
                                group_3 = self._rbds_bytes_array[7] | (self._rbds_bytes_array[6] << 8)

                                group_type = (group_1 >> 12) & 0xF
                                program_identification = group_0

                                if self._rbds_sync_tentative:
                                    # Sync not yet confirmed: count this group
                                    # toward the confirmation threshold but do
                                    # NOT publish to the RBDSDecoder (which
                                    # feeds the UI) and do NOT bump the
                                    # groups_decoded stat.  If the lock turns
                                    # out to be false the discarded group is
                                    # exactly the kind of bogus PI/group-type
                                    # we don't want to surface.
                                    self._rbds_tentative_good_groups += 1
                                    logger.debug(
                                        "RBDS tentative group %d/%d: PI=0x%04X type=%d (not published)",
                                        self._rbds_tentative_good_groups,
                                        self._RBDS_TENTATIVE_GOOD_GROUPS,
                                        program_identification,
                                        group_type,
                                    )
                                else:
                                    # Update our RBDSData decoder
                                    self._rbds_decoder.process_group((group_0, group_1, group_2, group_3))
                                    changed = True
                                    with self._stats_lock:
                                        self._stats.groups_decoded += 1

                                    logger.info("RBDS group: PI=0x%04X type=%s", program_identification, group_type)
                    
                    # Reset for next block
                    self._rbds_block_bit_counter = 0
                    self._rbds_block_number = (self._rbds_block_number + 1) % 4
                    self._rbds_blocks_counter += 1
                    
                    # Check sync quality every 50 blocks
                    if self._rbds_blocks_counter == 50:
                        if self._rbds_sync_tentative:
                            # Tentative-sync confirmation window: confirm only
                            # if at least _RBDS_TENTATIVE_GOOD_GROUPS fully-
                            # decoded groups landed in this window.  This
                            # ratifies the presync state machine's lock
                            # against actual valid RBDS frames before we
                            # publish anything to the UI or start the
                            # sync_acquired_unix clock.
                            if self._rbds_tentative_good_groups >= self._RBDS_TENTATIVE_GOOD_GROUPS:
                                logger.info(
                                    "RBDS sync CONFIRMED (%d good groups, %d bad blocks on %d total)",
                                    self._rbds_tentative_good_groups,
                                    self._rbds_wrong_blocks_counter,
                                    50,
                                )
                                self._rbds_sync_tentative = False
                                with self._stats_lock:
                                    self._stats.sync_acquired_unix = time.time()
                            else:
                                # Quality gate failed: drop back to presync
                                # silently.  This was a false lock — never
                                # surfaced to the UI — so we deliberately do
                                # NOT bump sync_lost_count (that counter is
                                # for *real* drops the operator should see).
                                logger.info(
                                    "RBDS tentative sync REJECTED (only %d good groups, %d bad blocks on %d total)",
                                    self._rbds_tentative_good_groups,
                                    self._rbds_wrong_blocks_counter,
                                    50,
                                )
                                self._rbds_synced = False
                                self._rbds_presync = False
                                self._rbds_sync_tentative = False
                            self._rbds_tentative_good_groups = 0
                        elif self._rbds_wrong_blocks_counter > 35:
                            logger.info("RBDS SYNC LOST (%d bad blocks on %d total)", self._rbds_wrong_blocks_counter, self._rbds_blocks_counter)
                            self._rbds_synced = False
                            self._rbds_presync = False
                            with self._stats_lock:
                                self._stats.sync_lost_count += 1
                                self._stats.sync_acquired_unix = None
                        else:
                            logger.info("RBDS sync OK (%d bad blocks on %d total)", self._rbds_wrong_blocks_counter, self._rbds_blocks_counter)
                        self._rbds_blocks_counter = 0
                        self._rbds_wrong_blocks_counter = 0

        # Clear the bit buffer after processing
        self._rbds_bit_buffer.clear()

        if changed:
            return self._rbds_decoder.get_current_data()
        return None

    def _decode_rbds_block(self, bits: List[int]) -> Tuple[Optional[str], int]:
        """Decode a 26-bit RBDS block.

        Uses the standard syndrome-based approach from PySDR and python-radio:
        - Run CRC on all 26 bits
        - Compare result to known syndrome values for each block type
        """
        if len(bits) != 26:
            return None, 0

        # Syndrome values for each block type (from RDS standard)
        # These are what calc_syndrome returns for valid blocks
        syndromes = {
            "A": 383,   # 0x17F - offset 0x0FC
            "B": 14,    # 0x00E - offset 0x198
            "C": 303,   # 0x12F - offset 0x168
            "D": 663,   # 0x297 - offset 0x1B4
            "C'": 748,  # 0x2EC - offset 0x350
        }

        # Convert bits to 26-bit integer (MSB first)
        block = 0
        for b in bits:
            block = (block << 1) | b

        # Extract 16-bit data word
        data = block >> 10

        # Calculate syndrome on full 26-bit block
        syndrome = self._calc_syndrome(block, 26)

        for block_type, expected_syndrome in syndromes.items():
            if syndrome == expected_syndrome:
                if not hasattr(self, '_normal_match_count'):
                    self._normal_match_count = 0
                    self._inverted_match_count = 0
                self._normal_match_count += 1
                return block_type, data

        # Try inverted bits (handles 180° Costas loop phase ambiguity)
        block_inv = 0
        for b in bits:
            block_inv = (block_inv << 1) | (1 - b)
        data_inv = block_inv >> 10
        syndrome_inv = self._calc_syndrome(block_inv, 26)

        for block_type, expected_syndrome in syndromes.items():
            if syndrome_inv == expected_syndrome:
                if not hasattr(self, '_inverted_match_count'):
                    self._inverted_match_count = 0
                    self._normal_match_count = 0
                self._inverted_match_count += 1
                if self._inverted_match_count <= 3 or self._inverted_match_count % 50 == 0:
                    logger.warning(
                        "RBDS: INVERTED bits matched! block=%s data=0x%04X "
                        "(inverted:%d normal:%d)",
                        block_type, data_inv, self._inverted_match_count, self._normal_match_count
                    )
                return block_type, data_inv

        # Debug: log syndrome periodically
        if not hasattr(self, '_syndrome_log_count'):
            self._syndrome_log_count = 0
        self._syndrome_log_count += 1
        if self._syndrome_log_count % 100 == 0:
            logger.debug(
                "RBDS syndrome: normal=%d inverted=%d (expected: A=383 B=14 C=303 D=663 C'=748)",
                syndrome, syndrome_inv
            )

        return None, 0

    def _calc_syndrome(self, x: int, mlen: int) -> int:
        """Calculate syndrome for RDS block validation.

        Dispatches to the JIT-compiled free function when Numba is available;
        falls back to the pure-Python implementation otherwise.

        Uses polynomial g(x) = x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1 = 0x5B9
        (IEC 62106 Annex B).
        """
        if _NUMBA_AVAILABLE:
            return int(_calc_syndrome_numba(x, mlen))
        reg = 0
        plen = 10
        for ii in range(mlen, 0, -1):
            reg = (reg << 1) | ((x >> (ii - 1)) & 0x01)
            if reg & (1 << plen):
                reg = reg ^ 0x5B9
        for ii in range(plen, 0, -1):
            reg = reg << 1
            if reg & (1 << plen):
                reg = reg ^ 0x5B9
        return reg & ((1 << plen) - 1)

    # Class-level cache for the burst-error syndrome table.  The table maps
    # the syndrome of each contiguous burst error (length 1-5) to the
    # corresponding correction mask.  Built once and shared across workers.
    _BURST_CORRECTION_TABLE: Optional[Dict[int, int]] = None
    # Maximum burst length (in bits) we attempt to repair.  NRSC-4-B §B.2.4
    # specifies a Meggitt trapping decoder that handles bursts up to 5 bits;
    # the (26,16) RBDS code's 10 parity bits are exactly enough to cover
    # this range unambiguously.
    _BURST_LIMIT_BITS = 5

    # Burst-FEC gate: after this many consecutive uncorrected blocks, we stop
    # consulting the burst-trapping table for the duration of the bad streak
    # and accept only `clean` or single-bit repairs.  The burst table covers
    # ~75 syndromes (~7% of the 1024-entry syndrome space), so when fed a
    # stream of essentially-random words during fake-sync it produces a
    # steady ~7% rate of false "corrections" that get passed to group
    # assembly as plausible-looking datawords.  This produces visibly
    # corrupt RBDS output (impossible CT timestamps, wrong language codes,
    # AID-on-15B groups, hashed AF lists).  Single-bit FEC is much safer
    # under noise because it requires *exactly one* candidate word to pass
    # CRC and rejects ambiguous cases — false-positive rate is dramatically
    # lower.  The gate self-clears as soon as a clean or single-bit repair
    # lands (i.e. real signal returns), so legitimate burst saves on a
    # healthy channel are unaffected.
    _BURST_FEC_SUPPRESS_AFTER = 2
    _RBDS_INTERFERENCE_GUARD_HZ = 2400.0
    _RBDS_INTERFERENCE_MIN_OFFSET_HZ = 80.0
    _RBDS_INTERFERENCE_NOTCH_Q = 24.0

    # Post-lock quality gate.  After the presync state machine declares a
    # lock we wait through the next 50-block sync-quality window and only
    # *confirm* the lock if at least this many fully-decoded (4-block)
    # groups land in that window.  Until confirmation we suppress
    # process_group() publishing and the sync_acquired_unix /
    # groups_decoded stat updates so a fake-sync event (random syndrome
    # collisions during noise) cannot inject corrupt metadata into the
    # UI.  3-of-(up-to-12.5)-groups is a strong filter against random
    # locks while still being achievable on a healthy channel within ~1.3 s.
    _RBDS_TENTATIVE_GOOD_GROUPS = 3

    @classmethod
    def _burst_correction_table(cls) -> Dict[int, int]:
        """Lazy-built syndrome -> error-mask table for burst-trapping FEC.

        Maps the 10-bit syndrome of every *contiguous* burst error of length
        ≤ _BURST_LIMIT_BITS in a 26-bit block to its correction mask.
        Only solid runs of consecutive bits are considered (e.g. 0b111 at
        some position), never sparse patterns like 0b101.  Including
        non-contiguous patterns inflates the table with entries that match
        random multi-bit noise, causing false-positive "corrections" that
        silently corrupt the decoded data (manifesting as nonsense PI codes
        and call letters).
        Ambiguous syndromes (where two different contiguous masks share a
        syndrome) are dropped so the decoder never guesses.
        """
        if cls._BURST_CORRECTION_TABLE is not None:
            return cls._BURST_CORRECTION_TABLE

        n_bits = 26
        plen = 10
        gen = 0x5B9

        def syndrome(x: int) -> int:
            reg = 0
            for ii in range(n_bits, 0, -1):
                reg = (reg << 1) | ((x >> (ii - 1)) & 0x1)
                if reg & (1 << plen):
                    reg ^= gen
            for _ in range(plen):
                reg <<= 1
                if reg & (1 << plen):
                    reg ^= gen
            return reg & ((1 << plen) - 1)

        candidates: Dict[int, set] = {}
        for start in range(n_bits):
            max_len = min(cls._BURST_LIMIT_BITS, n_bits - start)
            for burst_len in range(1, max_len + 1):
                # Contiguous burst: all bits set from 'start' through
                # 'start + burst_len - 1'.  Non-contiguous patterns
                # (e.g. 0b101) are intentionally excluded to prevent
                # them from matching random noise and corrupting data.
                mask = ((1 << burst_len) - 1) << start
                syn = syndrome(mask)
                if syn == 0:
                    continue
                candidates.setdefault(syn, set()).add(mask)

        table: Dict[int, int] = {}
        for syn, masks in candidates.items():
            sorted_masks = sorted(masks, key=lambda m: bin(m).count('1'))
            if len(sorted_masks) == 1:
                table[syn] = sorted_masks[0]
            elif bin(sorted_masks[0]).count('1') < bin(sorted_masks[1]).count('1'):
                table[syn] = sorted_masks[0]
            # Equal-weight collision: ambiguous, skip.

        cls._BURST_CORRECTION_TABLE = table
        return table


class FMDemodulator:
    """FM demodulator with stereo decoding and RBDS extraction.

    This demodulator uses a multi-stage decimation approach for high sample rate
    SDRs (like Airspy at 2.5 MHz). The signal processing chain is:

    1. IQ samples at SDR rate (e.g., 2.5 MHz)
    2. Phase discriminator to extract FM multiplex signal
    3. Decimate to intermediate rate (e.g., 250 kHz) for efficient filtering
    4. Apply audio lowpass filters at intermediate rate
    5. Stereo decode (if enabled) at intermediate rate
    6. Decimate/resample to final audio rate (e.g., 48 kHz)
    7. Apply de-emphasis filter

    This approach provides much better filter performance than trying to apply
    narrow audio filters directly at MHz sample rates.
    """

    # FM deviation constants for different modulation types
    # These determine the audio gain scaling factor
    FM_DEVIATION_HZ = {
        'WFM': 75000,   # Broadcast FM: ±75 kHz deviation
        'FM': 75000,    # Same as WFM
        'NFM': 5000,    # Narrowband FM: ±5 kHz deviation (NOAA, two-way radio)
    }

    # Default deviation for unknown modulation types (broadcast FM standard)
    DEFAULT_DEVIATION_HZ = 75000

    # Target intermediate sample rate for audio processing
    # 250 kHz is sufficient for FM stereo (needs > 76 kHz for 38 kHz subcarrier)
    # and provides good filter performance with reasonable tap counts
    INTERMEDIATE_SAMPLE_RATE = 250000

    def __init__(self, config: DemodulatorConfig):
        self.config = config

        # Normalize modulation type to uppercase for consistent lookup
        # This prevents issues with case sensitivity (fm vs FM vs Fm)
        self.config.modulation_type = config.modulation_type.upper()

        # Previous complex sample for phase continuity
        self._prev_sample: Optional[np.complex64] = None
        self._sample_index: int = 0

        # Calculate decimation factor for efficient processing
        # We want to get from SDR rate down to ~250 kHz for audio processing
        self._decimation_factor = 1
        self._intermediate_rate = config.sample_rate

        if config.sample_rate > self.INTERMEDIATE_SAMPLE_RATE * 2:
            # Calculate decimation to get close to target intermediate rate
            self._decimation_factor = max(1, int(config.sample_rate / self.INTERMEDIATE_SAMPLE_RATE))
            self._intermediate_rate = config.sample_rate // self._decimation_factor
            logger.info(
                "FM demodulator using %dx decimation: %d Hz -> %d Hz intermediate rate",
                self._decimation_factor, config.sample_rate, self._intermediate_rate
            )

        # Design decimation lowpass filter if needed
        # Cutoff at 80% of new Nyquist to prevent aliasing
        self._decim_filter = None
        if self._decimation_factor > 1:
            decim_cutoff = self._intermediate_rate * 0.4  # 40% of intermediate rate
            # More taps for better stopband rejection at high sample rates
            decim_taps = min(1024, max(256, config.sample_rate // 10000))
            self._decim_filter = self._design_fir_lowpass(decim_cutoff, config.sample_rate, taps=decim_taps)
            logger.debug("Decimation filter: %d taps, cutoff %.1f kHz", decim_taps, decim_cutoff / 1000)

        # Calculate FM audio gain based on modulation type and sample rate
        # The discriminator output is: phase_diff / π, which gives values in [-1, 1]
        # For FM, the actual audio values are much smaller because:
        #   phase_diff_per_sample = 2π × deviation / sample_rate
        # We need to scale up by: sample_rate / (2 × deviation) to get full-scale audio
        deviation_hz = self.FM_DEVIATION_HZ.get(self.config.modulation_type, self.DEFAULT_DEVIATION_HZ)
        # The discriminator already divides by π, so we scale by:
        # sample_rate / (2 × deviation) = the factor to convert frequency deviation to amplitude
        self._audio_gain = config.sample_rate / (2.0 * deviation_hz)

        # Clamp gain to reasonable range to prevent extreme amplification
        # Reduced max gain from 50 to 25 to prevent clipping on strong signals
        self._audio_gain = max(1.0, min(25.0, self._audio_gain))

        # De-emphasis filter state
        self._deemph_alpha = 0.0
        if config.deemphasis_us > 0:
            tau = config.deemphasis_us * 1e-6
            self._deemph_alpha = 1.0 - np.exp(-1.0 / (config.audio_sample_rate * tau))
        self._deemph_state = np.zeros(1, dtype=np.float32)

        # Stereo decoder state
        # Use intermediate rate for stereo processing (more efficient filters)
        self._stereo_enabled = (
            config.stereo_enabled
            and config.modulation_type in {"FM", "WFM"}
            and self._intermediate_rate >= 76000  # Minimum for 38kHz subcarrier
        )

        # Design audio filters for ORIGINAL sample rate since stereo/pilot detection
        # happens BEFORE decimation on the raw multiplex signal
        # CRITICAL FIX: Filters must match the sample rate of the signal they're applied to
        # The multiplex signal is at config.sample_rate, not intermediate_rate
        audio_filter_taps = self._calculate_filter_taps(16000.0, config.sample_rate)
        self._lpr_filter = self._design_fir_lowpass(16000.0, config.sample_rate, taps=audio_filter_taps)
        self._dsb_filter = self._design_fir_lowpass(16000.0, config.sample_rate, taps=audio_filter_taps)
        self._pilot_filter = self._design_fir_bandpass(18500.0, 19500.0, config.sample_rate, taps=audio_filter_taps)

        # Stereo carrier tracking state
        self._pilot_phase = 0.0
        self._pilot_freq = 19000.0  # 19 kHz pilot tone
        self._pilot_pll_bandwidth = 50.0  # Hz - narrow bandwidth for stable lock

        # RBDS processing in separate thread so it never blocks audio
        self._rbds_enabled = config.enable_rbds and config.sample_rate >= 114000
        self._rbds_worker: Optional[RBDSWorker] = None
        self._rbds_intermediate_rate = self._intermediate_rate

        # Early-decimation state (PySDR architecture).  The RBDSWorker's
        # filter chain (54-60 kHz bandpass, 57 kHz mix, 2.4 kHz post-mix
        # lowpass, downstream decim to 25 kHz, then resample to 19 kHz) is
        # sized for ~250 kHz inputs — that's how PySDR's reference RDS
        # tutorial does it (https://pysdr.org/content/rds.html: starts at
        # sample_rate=250e3 and uses a 101-tap firwin lowpass).  Feeding the
        # worker raw SDR rate (e.g. 1 MHz, 2.4 MHz) leaves its 101-tap
        # bandpass with ~40-95 kHz transition vs a 6 kHz target passband —
        # essentially all-pass — and its 501-tap 2.4 kHz lowpass with ~10-25
        # kHz transition, so the 4 kHz post-mix stereo artifact lands in
        # the passband.  We must decimate the multiplex from the *actual,
        # user-configured* SDR rate down to _rbds_intermediate_rate before
        # submitting, with a proper anti-alias filter ahead of the
        # downsampler.  Initialised below only when RBDS is enabled.
        self._rbds_decim: int = 1
        self._rbds_aa_filter: Optional[np.ndarray] = None
        self._rbds_aa_zi: Optional[np.ndarray] = None
        # Sample-offset counter at the *decimated* rate.  The worker's
        # crystal-locked 57 kHz / pilot-locked 19 kHz reference uses
        # sample_offset / self._sample_rate to compute time, so the offset
        # must count samples at the rate the worker actually receives.
        self._rbds_sample_index: int = 0

        if self._rbds_enabled:
            # Pick the largest divisor of config.sample_rate that lands the
            # worker between 130 and ~280 kHz — the band where its filters
            # are correctly proportioned and post-decim Nyquist (>= 65 kHz)
            # safely covers the 57 kHz RBDS subcarrier.  This mirrors the
            # earlier branch that already existed for the audio path but
            # makes it the *actually-applied* rate for the RBDS path too.
            if config.sample_rate > self._intermediate_rate * 2:
                rbds_decim = config.sample_rate // self._intermediate_rate
                while (config.sample_rate // rbds_decim) < 130000 and rbds_decim > 1:
                    rbds_decim -= 1
                self._rbds_intermediate_rate = config.sample_rate // rbds_decim
                self._rbds_decim = rbds_decim
            else:
                # Low-rate SDR (e.g. user already running at 250 kHz):
                # multiplex is already at a reasonable rate, no early
                # decimation needed.  rbds_decim stays at 1.
                self._rbds_intermediate_rate = config.sample_rate
                self._rbds_decim = 1

            # Build the rate-adaptive anti-alias filter when we're going to
            # decimate.  Cutoff must (a) preserve the 57 kHz RBDS subcarrier
            # (whose upper edge is 60 kHz) and (b) put the stopband edge
            # below post-decim Nyquist so nothing folds back into the RBDS
            # band.  Tap count scales with the input rate to hold the
            # transition bandwidth roughly constant — the cap of 1025
            # caps CPU even at Airspy's 10 MHz native rate while keeping
            # the stopband under post-decim Nyquist for any rate the user
            # is realistically going to set.
            if self._rbds_decim > 1:
                post_decim_nyquist = self._rbds_intermediate_rate / 2.0
                rbds_aa_cutoff = min(80_000.0, max(63_000.0, post_decim_nyquist * 0.85))
                # Tap-count heuristic: scale linearly with input rate to
                # hold transition bandwidth roughly constant.  Dividing by
                # 4000 gives ~250 taps at 1 MHz and ~600 taps at 2.4 MHz,
                # which yields a transition bandwidth of ~16 kHz — wide
                # enough that the stopband edge sits comfortably below
                # post-decim Nyquist for every realistic SDR rate.  The
                # `| 1` forces an odd number, required for a Type-I linear-
                # phase symmetric FIR (so group delay is an integer number
                # of samples).  Floor of 127 keeps low-rate users from
                # getting a useless filter; cap of 1025 bounds CPU at
                # Airspy's 10 MHz native rate.
                rbds_aa_taps = max(127, min(1025, (int(config.sample_rate / 4000) | 1)))
                self._rbds_aa_filter = self._design_fir_lowpass(
                    rbds_aa_cutoff, config.sample_rate, taps=rbds_aa_taps
                )
                logger.info(
                    "RBDS anti-alias filter: %d taps, cutoff %.1f kHz @ %d Hz "
                    "→ %d Hz (decim=%d), post-decim Nyquist=%.1f kHz",
                    rbds_aa_taps,
                    rbds_aa_cutoff / 1000.0,
                    config.sample_rate,
                    self._rbds_intermediate_rate,
                    self._rbds_decim,
                    post_decim_nyquist / 1000.0,
                )

            # Create RBDS worker thread - all processing happens there.
            # CRITICAL: pass the *effective* sample rate the worker will
            # receive (post early-decimation), NOT the raw SDR rate.  Its
            # internal filters (bandpass / pilot bandpass / 2.4 kHz post-
            # mix lowpass) are designed against this value.
            self._rbds_worker = RBDSWorker(
                self._rbds_intermediate_rate,
                self._rbds_intermediate_rate,
                rbds_tuning_options={
                    'pilot_snr_threshold': config.rbds_pilot_snr_threshold,
                    'presync_spacing_tolerance_bits': config.rbds_presync_spacing_tolerance_bits,
                    'burst_fec_suppress_after': config.rbds_burst_fec_suppress_after,
                    'interference_rejection_enabled': config.rbds_interference_rejection_enabled,
                    'interference_guard_hz': config.rbds_interference_guard_hz,
                },
            )
            logger.info(
                "RBDS ENABLED: worker at %d Hz (input sample_rate=%d Hz, decim=%d)",
                self._rbds_intermediate_rate,
                config.sample_rate,
                self._rbds_decim,
            )
        else:
            # Log clearly why RBDS is not enabled
            if not config.enable_rbds:
                logger.info(
                    "RBDS DISABLED: enable_rbds=False in receiver config"
                )
            elif config.sample_rate < 114000:
                logger.info(
                    "RBDS DISABLED: sample_rate=%d Hz is below 114 kHz minimum",
                    config.sample_rate
                )
            else:
                logger.info(
                    "RBDS DISABLED: enable_rbds=%s, sample_rate=%d Hz",
                    config.enable_rbds,
                    config.sample_rate
                )


    def _calculate_filter_taps(self, cutoff_hz: float, sample_rate: int, transition_bw_ratio: float = 0.125) -> int:
        """Calculate appropriate number of filter taps for given parameters.

        Args:
            cutoff_hz: Filter cutoff frequency in Hz
            sample_rate: Sample rate in Hz
            transition_bw_ratio: Transition bandwidth as fraction of cutoff (default 12.5%)

        Returns:
            Number of filter taps (odd number for symmetric filter)
        """
        # Transition bandwidth
        transition_bw = cutoff_hz * transition_bw_ratio

        # Kaiser formula approximation: taps ≈ (stopband_attenuation_dB - 8) / (2.285 * transition_bw_normalized)
        # For ~60 dB stopband attenuation:
        # taps ≈ (60 - 8) / (2.285 * (transition_bw / sample_rate)) = 52 / (2.285 * transition_bw / sample_rate)
        taps = int(52.0 * sample_rate / (2.285 * transition_bw))

        # Ensure odd number and reasonable range
        taps = max(65, min(1025, taps | 1))  # Clamp to 65-1025, ensure odd

        return taps

    def process(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Process IQ samples and return audio samples.

        This is the main entry point used by audio processing pipeline.
        Demodulator status (RBDS, stereo pilot) is available via get_last_status().

        Args:
            iq_samples: Complex IQ samples

        Returns:
            Audio samples (float32 numpy array)
        """
        audio, status = self.demodulate(iq_samples)
        self._last_status = status  # Store for get_last_status()
        return audio

    def get_last_status(self) -> Optional[DemodulatorStatus]:
        """Get the most recent demodulator status (stereo pilot, RBDS data)."""
        return getattr(self, '_last_status', None)

    def reset_rbds(self) -> None:
        """Drop all RBDS state (sync, filters, decoded metadata).

        Call this when tuning to a new station.  Without it, the decoder
        keeps showing the previous station's PS/radiotext until the new
        station's first group gets decoded, and the carrier-phase / symbol
        timing state from the old station delays re-locking.
        """
        if self._rbds_worker is not None:
            self._rbds_worker.reset()
        # Also drop the last-status reference to the old station's RBDS
        # data so any downstream consumer that reads get_last_status()
        # before the next demodulate() sees a clean slate.
        last = getattr(self, '_last_status', None)
        if last is not None:
            last.rbds_data = None
            last.rbds_synced = False

    def is_rbds_synced(self) -> bool:
        """True once the RBDS bit-level sync state machine has locked."""
        if self._rbds_worker is None:
            return False
        return self._rbds_worker.is_synced()

    def demodulate(self, iq_samples: np.ndarray) -> Tuple[np.ndarray, Optional[DemodulatorStatus]]:
        """
        Demodulate FM signal from IQ samples.

        Optimized for real-time processing at high IQ sample rates (2.5 MHz).
        Optionally extracts RBDS data and detects stereo pilot tone.

        Args:
            iq_samples: Complex IQ samples

        Returns:
            Tuple of (audio samples, demodulator status with RBDS/stereo info)
        """
        if len(iq_samples) == 0:
            return np.array([], dtype=np.float32), None

        # FAST PATH: Using JIT-compiled functions when available
        iq_array = np.asarray(iq_samples, dtype=np.complex64)

        # Mean IQ magnitude - raw RF signal strength for the RSSI meter.  Done
        # on the input array before phase-continuity prepending so the value
        # reflects the samples that just arrived from the SDR.
        rf_signal_strength = float(np.mean(np.abs(iq_array))) if iq_array.size else 0.0

        # Phase continuity - prepend last sample from previous block
        if self._prev_sample is not None:
            iq_array = np.concatenate(([self._prev_sample], iq_array))
        self._prev_sample = iq_array[-1]

        # Phase discriminator - uses Numba JIT if available (50-100x faster)
        # This is the core FM demodulation algorithm
        # Output is the FM multiplex signal containing L+R, stereo (L-R at 38kHz), and RBDS (at 57kHz)
        multiplex = fm_discriminator(iq_array)

        # Detect stereo pilot tone (19 kHz) and RBDS extraction
        # Must happen BEFORE audio decimation destroys the subcarriers
        rbds_data: Optional[RBDSData] = None
        stereo_pilot_locked = False
        stereo_pilot_strength = 0.0

        # Stereo pilot detection (19 kHz tone indicates stereo broadcast)
        if self._stereo_enabled and self.config.sample_rate >= 38000:
            # Filter for 19 kHz pilot tone
            pilot_filtered = oaconvolve(multiplex, self._pilot_filter, mode="same")

            # Measure pilot strength (RMS of filtered signal)
            pilot_rms = np.sqrt(np.mean(pilot_filtered ** 2))
            stereo_pilot_strength = min(1.0, pilot_rms * 10.0)  # Scale to 0-1 range

            # Pilot is considered "locked" if strength exceeds threshold
            stereo_pilot_locked = stereo_pilot_strength > 0.1  # 10% threshold

            if stereo_pilot_locked:
                logger.debug("Stereo pilot detected: strength=%.2f", stereo_pilot_strength)

        # RBDS extraction in a separate worker thread.  Submit samples
        # (non-blocking) and pick up whatever the worker has decoded since
        # the last call.
        # 24/7 RELIABILITY: Wrap in try-except to ensure RBDS issues never affect audio
        if self._rbds_enabled and self._rbds_worker:
            try:
                # Early-decimate the multiplex from the user-configured SDR
                # rate down to the worker's intermediate rate (PySDR
                # architecture).  When _rbds_decim == 1 (low-rate SDR or
                # already-decimated input) we skip the filter and pass the
                # multiplex through untouched — same as the legacy code
                # path.
                if self._rbds_decim > 1 and self._rbds_aa_filter is not None:
                    from scipy import signal as scipy_signal
                    if self._rbds_aa_zi is None:
                        # Initialize the lfilter delay line so the very
                        # first chunk doesn't ring up from zero.  Using
                        # the steady-state response scaled by the first
                        # input sample matches the convention already
                        # used in _process_rbds for the bandpass/lowpass.
                        self._rbds_aa_zi = scipy_signal.lfilter_zi(
                            self._rbds_aa_filter, 1.0
                        )
                        if multiplex.size:
                            self._rbds_aa_zi = self._rbds_aa_zi * float(multiplex[0])
                    filtered, self._rbds_aa_zi = scipy_signal.lfilter(
                        self._rbds_aa_filter, 1.0, multiplex, zi=self._rbds_aa_zi
                    )
                    # Decimate by integer factor.  Anti-aliasing was just
                    # done above so the [::N] is safe — same pattern PySDR
                    # uses (firwin → np.convolve → x[::10]).
                    rbds_multiplex = filtered[:: self._rbds_decim].astype(np.float32)
                else:
                    rbds_multiplex = multiplex

                # Pass the absolute sample offset *in the worker's domain*
                # so its crystal-locked 57 kHz / pilot-locked 19 kHz
                # reference stays phase-coherent across chunks even when
                # chunks are dropped from the queue (queue overflow
                # discards chunks in the audio thread).  This counter is
                # decoupled from self._sample_index, which counts
                # multiplex samples at the raw SDR rate for any callers
                # that depend on that semantic (e.g. tests).
                self._rbds_worker.submit_samples(rbds_multiplex, self._rbds_sample_index)
                self._rbds_sample_index += len(rbds_multiplex)

                # Get whatever RBDS data is available (may be from previous chunks)
                rbds_data = self._rbds_worker.get_latest_data()
            except Exception as e:
                # Log but don't let RBDS errors affect audio demodulation
                logger.warning("RBDS error (audio unaffected): %s", e)

        # Advance the absolute sample index AFTER submitting to ensure the
        # offset is the position of the FIRST sample in this chunk.
        self._sample_index += len(multiplex)

        # Calculate decimation factor for audio downsampling
        target_rate = self.config.audio_sample_rate
        decim = max(1, self.config.sample_rate // target_rate)

        # Stereo decoding - must happen BEFORE decimation destroys the 38 kHz subcarrier
        # The L-R difference signal is modulated at 38 kHz (double the 19 kHz pilot)
        stereo_audio = None
        if self._stereo_enabled and stereo_pilot_locked and self.config.sample_rate >= 76000:
            # Create sample indices for stereo decoding (carrier generation)
            stereo_sample_indices = np.arange(len(multiplex), dtype=np.float64)
            try:
                stereo_audio = self._decode_stereo(multiplex, stereo_sample_indices)
                if stereo_audio is not None:
                    logger.debug("Stereo decoded: %d samples, shape %s", len(stereo_audio), stereo_audio.shape)
            except Exception as e:
                logger.warning("Stereo decoding error: %s", e, exc_info=True)
                stereo_audio = None
        # CRITICAL FIX: Use proper resampling to exact target rate instead of simple decimation
        # Simple decimation produces wrong sample rate: e.g., 2.5MHz / 52 = 48,077 Hz (not 48,000 Hz)
        # This causes "chipmunk" audio when played back at declared rate
        if stereo_audio is not None:
            # We have stereo audio - decimate and resample both channels
            if decim > 1:
                # Decimate each channel separately
                left = fast_decimate(stereo_audio[:, 0], decim)
                right = fast_decimate(stereo_audio[:, 1], decim)
                intermediate_rate = self.config.sample_rate // decim
                logger.debug(
                    f"FM stereo demod: IQ {self.config.sample_rate}Hz → decim {decim}x → "
                    f"{intermediate_rate}Hz → resample → {target_rate}Hz"
                )
            else:
                left = stereo_audio[:, 0]
                right = stereo_audio[:, 1]
                intermediate_rate = self.config.sample_rate

            # Scale to audio levels
            deviation_hz = self.FM_DEVIATION_HZ.get(self.config.modulation_type, self.DEFAULT_DEVIATION_HZ)
            scale_factor = self.config.sample_rate / (2.0 * deviation_hz * decim)
            left = left * scale_factor
            right = right * scale_factor

            # Resample to exact target rate
            if intermediate_rate != target_rate:
                left = self._resample(left, intermediate_rate, target_rate)
                right = self._resample(right, intermediate_rate, target_rate)

            audio = np.column_stack((left, right))
        else:
            # Mono audio path
            if decim > 1:
                # First decimate to get close to target rate (fast, low quality)
                audio = fast_decimate(multiplex, decim)
                # Calculate actual intermediate rate after decimation
                intermediate_rate = self.config.sample_rate // decim
                logger.debug(
                    f"FM demod: IQ {self.config.sample_rate}Hz → decim {decim}x → "
                    f"{intermediate_rate}Hz → resample → {target_rate}Hz"
                )
            else:
                audio = multiplex
                intermediate_rate = self.config.sample_rate
                logger.debug("FM demod: No decimation needed, %sHz → %sHz", intermediate_rate, target_rate)

            # Scale to audio levels BEFORE resampling (at intermediate rate)
            # For 75 kHz deviation: phase_diff_per_sample = 2π × 75000 / sample_rate
            # We scale by sample_rate / (2 × deviation × decimation_factor) to normalize
            deviation_hz = self.FM_DEVIATION_HZ.get(self.config.modulation_type, self.DEFAULT_DEVIATION_HZ)
            audio = audio * (self.config.sample_rate / (2.0 * deviation_hz * decim))

            # Now resample from intermediate_rate to exact target_rate
            # This ensures audio is at the EXACT sample rate expected by downstream consumers
            if intermediate_rate != target_rate:
                audio = self._resample(audio, intermediate_rate, target_rate)
                logger.debug(
                    f"Resampled {len(audio)} samples from {intermediate_rate}Hz to {target_rate}Hz"
                )

        # Clamp to prevent overflow
        audio = np.clip(audio, -1.5, 1.5)

        # Soft-clip to prevent harsh distortion on overmodulated signals
        # Uses tanh with reduced gain for smoother limiting
        # Scale down before tanh and back up after to preserve dynamics
        audio = np.tanh(audio * 0.7) / 0.7

        # Create demodulator status with stereo pilot and RBDS info
        decoder_stats: Optional[RBDSDecoderStats] = None
        if self._rbds_enabled and self._rbds_worker is not None:
            decoder_stats = self._rbds_worker.get_stats()
        status = DemodulatorStatus(
            rbds_data=rbds_data,
            stereo_pilot_locked=stereo_pilot_locked,
            stereo_pilot_strength=stereo_pilot_strength,
            is_stereo=self._stereo_enabled and stereo_pilot_locked,
            signal_strength=rf_signal_strength,
            rbds_synced=(
                self._rbds_worker.is_synced()
                if self._rbds_enabled and self._rbds_worker is not None
                else False
            ),
            rbds_enabled=self._rbds_enabled,
            rbds_decoder_stats=decoder_stats,
        )

        return audio.astype(np.float32), status

    @staticmethod
    def _resample(signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Thin shim around the module-level :func:`resample_to`."""
        return resample_to(signal, from_rate, to_rate)

    def _apply_deemphasis(self, audio: np.ndarray) -> np.ndarray:
        """Apply de-emphasis filter (single-pole IIR lowpass)."""
        if audio.ndim == 1:
            output = np.zeros_like(audio)
            if self._deemph_state.shape[0] != 1:
                self._deemph_state = np.zeros(1, dtype=np.float32)
            for i in range(len(audio)):
                self._deemph_state[0] = (
                    self._deemph_state[0]
                    + self._deemph_alpha * (audio[i] - self._deemph_state[0])
                )
                output[i] = self._deemph_state[0]
            return output

        channels = audio.shape[1]
        if self._deemph_state.shape[0] != channels:
            self._deemph_state = np.zeros(channels, dtype=np.float32)

        output = np.zeros_like(audio)
        for ch in range(channels):
            state = self._deemph_state[ch]
            for i in range(audio.shape[0]):
                state = state + self._deemph_alpha * (audio[i, ch] - state)
                output[i, ch] = state
            self._deemph_state[ch] = state
        return output

    @staticmethod
    def _design_fir_lowpass(cutoff: float, fs: int, taps: int = 129) -> np.ndarray:
        """Thin shim around the module-level :func:`design_fir_lowpass`."""
        return design_fir_lowpass(cutoff, fs, taps=taps)

    @staticmethod
    def _design_fir_bandpass(low_cut: float, high_cut: float, fs: int, taps: int = 129) -> np.ndarray:
        """Thin shim around the module-level :func:`design_fir_bandpass`."""
        return design_fir_bandpass(low_cut, high_cut, fs, taps=taps)

    def _lpr_filter_signal(self, signal: np.ndarray) -> np.ndarray:
        filtered = oaconvolve(signal, self._lpr_filter, mode="same")
        return filtered

    def _decode_stereo(self, multiplex: np.ndarray, sample_indices: np.ndarray) -> Optional[np.ndarray]:
        """Decode FM stereo from multiplex signal.

        Derives a phase-coherent 38 kHz carrier directly from the recovered
        19 kHz pilot tone by squaring it (cos²(ωt) = ½(1 + cos(2ωt))).  This
        approach is automatically locked to the transmitter's pilot phase and
        frequency, so it tracks both crystal drift and chunk-boundary phase
        without any PLL state.  An earlier implementation generated a free-
        running 38 kHz oscillator that reset to phase 0 on every chunk; with
        the SDR clock differing from the broadcaster's by tens of ppm the L-R
        signal slowly rotated against the carrier, collapsing the stereo image
        toward mono and bleeding L into R.

        Args:
            multiplex: FM multiplex signal (after discriminator)
            sample_indices: Sample indices (unused; kept for backwards-compat)

        Returns:
            Stereo audio as Nx2 array (left, right) or None if stereo cannot
            be decoded for this chunk.
        """
        if not self._stereo_enabled or len(multiplex) == 0:
            return None

        # Extract L+R (mono) using lowpass filter
        lpr = oaconvolve(multiplex, self._lpr_filter, mode="same")

        # Recover the 19 kHz pilot tone via the pre-designed bandpass.
        pilot_filtered = oaconvolve(multiplex, self._pilot_filter, mode="same")

        # Normalize the pilot to ~unit amplitude so the derived 38 kHz carrier
        # has a stable amplitude and the L-R recovery gain doesn't depend on
        # signal strength.  RMS · √2 is the peak amplitude of a sinusoid.
        pilot_rms = float(np.sqrt(np.mean(pilot_filtered ** 2)))
        pilot_peak = pilot_rms * np.sqrt(2.0)
        if pilot_peak < 1e-9:
            # Pilot vanished mid-chunk; let the caller fall back to mono.
            return None
        pilot_unit = pilot_filtered / pilot_peak

        # cos²(ωt) = ½(1 + cos(2ωt)) → 2·cos²(ωt) − 1 = cos(2ωt)
        # This is an exact, phase-coherent 38 kHz reference that tracks the
        # actual pilot frequency (no PLL or oscillator state needed).
        carrier_38k = 2.0 * (pilot_unit * pilot_unit) - 1.0

        # Demodulate L-R: mix with the 38 kHz carrier and lowpass.  The 2× gain
        # compensates for the ½ factor that DSB-SC mixing of unit-amplitude
        # signals introduces (cos(A)·cos(A) = ½(1 + cos(2A))).
        suppressed = 2.0 * multiplex * carrier_38k
        lmr = oaconvolve(suppressed, self._dsb_filter, mode="same")

        # Matrix decode: L = ½((L+R) + (L-R)), R = ½((L+R) - (L-R))
        left = 0.5 * (lpr + lmr)
        right = 0.5 * (lpr - lmr)

        return np.column_stack((left, right))

    def stop(self) -> None:
        """Stop the demodulator and clean up resources."""
        if self._rbds_worker:
            self._rbds_worker.stop()
            self._rbds_worker = None


class AMDemodulator:
    """AM envelope demodulator."""

    def __init__(self, config: DemodulatorConfig):
        self.config = config
        self.dc_offset = 0.0
        self.dc_alpha = 0.001  # DC removal filter coefficient

    def process(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Process IQ samples and return audio samples.
        
        This is the main entry point used by audio processing pipeline.
        
        Args:
            iq_samples: Complex IQ samples
            
        Returns:
            Audio samples (float32 numpy array)
        """
        audio, _ = self.demodulate(iq_samples)
        return audio

    def demodulate(self, iq_samples: np.ndarray) -> Tuple[np.ndarray, Optional[DemodulatorStatus]]:
        """
        Demodulate AM signal from IQ samples using envelope detection.

        Args:
            iq_samples: Complex IQ samples

        Returns:
            Tuple of (audio samples, None) - AM has no stereo/RBDS status
        """
        if len(iq_samples) == 0:
            return np.array([], dtype=np.float32), None

        # Envelope detection - compute magnitude
        audio = np.abs(iq_samples)

        # Remove DC offset (high-pass filter)
        for i in range(len(audio)):
            self.dc_offset = self.dc_offset + self.dc_alpha * (audio[i] - self.dc_offset)
            audio[i] -= self.dc_offset

        # Resample to audio sample rate if needed
        if self.config.sample_rate != self.config.audio_sample_rate:
            audio = self._resample(audio, self.config.sample_rate, self.config.audio_sample_rate)

        # Normalize amplitude
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val

        return audio.astype(np.float32), None

    @staticmethod
    def _resample(signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Thin shim around the module-level :func:`resample_to`."""
        return resample_to(signal, from_rate, to_rate)


# NRSC-4-B Annex D.3: 3-letter US legacy call signs with explicitly
# assigned PI codes. Limited to well-known FM-active stations; anything
# unlisted falls through to the 4-letter algorithmic decode or None.
_NRSC4_THREE_LETTER_CALLSIGNS: Dict[int, str] = {
    0x99A5: "KDKA",
    0x9990: "KYW",
    0x9950: "WBZ",
    0x9952: "WGY",
    0x9953: "WHA",
    0x9955: "WHAS",
    0x9959: "WHO",
    0x9974: "WOC",
    0x9988: "WRR",
    0x9992: "WSB",
    0x9993: "WSM",
    0x9997: "WWJ",
    0x9999: "WWL",
}


def pi_to_call_sign(pi: int) -> Optional[str]:
    """Translate a 16-bit RBDS PI code to US call letters (NRSC-4-B Annex D).

    4-letter call signs are derived algorithmically:
        K-prefix: PI = 0x1000 + 676*(L2) + 26*(L3) + (L4)   → 0x1000..0x54A7
        W-prefix: PI = 0x54A8 + 676*(L2) + 26*(L3) + (L4)   → 0x54A8..0x994F
    where L2/L3/L4 are zero-based alphabetic indices (A=0, ..., Z=25).

    A small set of 3-letter legacy calls have explicit PI assignments
    in Annex D.3 and take precedence over the algorithmic range.

    Returns None if the PI code falls outside the NRSC-4 US allocation
    (e.g. European RDS codes where the high nibble is a country code),
    since those would decode into nonsense call letters.
    """
    if pi in _NRSC4_THREE_LETTER_CALLSIGNS:
        return _NRSC4_THREE_LETTER_CALLSIGNS[pi]

    if 0x1000 <= pi <= 0x994F:
        if pi < 0x54A8:
            prefix = "K"
            charsum = pi - 0x1000
        else:
            prefix = "W"
            charsum = pi - 0x54A8
        l2, rem = divmod(charsum, 676)
        l3, l4 = divmod(rem, 26)
        return prefix + chr(ord("A") + l2) + chr(ord("A") + l3) + chr(ord("A") + l4)

    return None


class RBDSDecoder:
    """
    RBDS/RDS decoder for FM radio.

    Decodes Program Service name, Radio Text, and other metadata from the
    57kHz RBDS subcarrier in FM broadcasts.
    """

    def __init__(self):
        self.pi_code = None
        self.call_sign = None
        self.ps_name = [' '] * 8  # 8 characters
        self.radio_text = [' '] * 64
        # Length of the decoded Radio Text before any 0x0D terminator.
        # The RDS spec says a carriage-return ends the displayed text and
        # anything beyond it is padding that must not be shown.
        self._radio_text_len = 64
        # Index where the most-recent CR landed (0x0D arrived in a previous
        # group at this position).  Tracked so that if a later broadcast of
        # the same segment overwrites that exact index with a non-CR
        # character, the terminator can be released and the visible RT
        # allowed to grow back out.  ``None`` when no CR is in effect.
        self._radio_text_cr_index: Optional[int] = None
        self.pty = None
        self.pty_name = None
        self._pty_name_buf = [' '] * 8
        self._pty_name_ab = 0
        self.tp = None
        self.ta = None
        self.ms = None
        # Decoder Identification: 4 bits accumulated one-per-PS-segment
        self.di_stereo = None
        self.di_artificial_head = None
        self.di_compressed = None
        self.di_dynamic_pty = None
        self.clock_time_utc = None
        self.clock_time_local = None
        self._radio_text_ab = 0
        self._rt_saw_cr_this_group = False
        # Group 0A AF state
        self._af_buffer: List[float] = []
        self._af_method_a_count: Optional[int] = None
        # Method B / LF-MF follow-on indicator (code 250).  Doesn't tell
        # us anything about LF/MF AFs without further decoding, but the
        # presence of the marker is itself useful information.
        self._af_follow_on_indicator: bool = False
        # Method B mode flag and the tuning frequency captured from the
        # regional-variant marker pair (af1 == af2).  Method A and
        # Method B AFs both populate _af_buffer; this just exposes which
        # encoding the station used so receivers can correlate the list
        # against an actual tuning frequency.
        self._af_method_b: bool = False
        self._af_tuning_frequency: Optional[float] = None
        # Slow-labelling raw capture: every Group 1A variant byte we
        # observe, keyed by variant code (0-7).  Specific decoders for
        # variants 0/4/5 still produce semantic fields; this dict gives
        # the UI the raw 16-bit Block-D contents for *all* variants so
        # nothing the station broadcasts is silently dropped.
        self._slow_labelling_raw: Dict[int, int] = {}
        # Group 1A/1B PIN and slow labeling state
        self.pin_day: Optional[int] = None
        self.pin_hour: Optional[int] = None
        self.pin_minute: Optional[int] = None
        self.ecc: Optional[int] = None
        self.language_code: Optional[int] = None
        self.language_name: Optional[str] = None
        self.linkage_set_number: Optional[int] = None
        self.linkage_actuator: Optional[bool] = None
        self.linkage_soft_coupling: Optional[bool] = None
        # Group 1A variant-1: TMC identification provider code (12 bits).
        self.paging_tmc_id: Optional[int] = None
        # Group 1A variant-2: paging operator code (12 bits).
        self.paging_operator_code: Optional[int] = None
        # Group 1A variant-7: EWS slow-labelling channel identifier (12 bits).
        self.ews_channel_identifier: Optional[int] = None
        # Group 3A ODA state
        self._oda_app_map: Dict[int, int] = {}
        self.oda_apps: List[int] = []
        # RT+ (AID 0xCD46) state.  Populated when 3A registers RT+ on a
        # specific group type; the decoder then routes those groups to
        # _handle_rt_plus.
        self._rt_plus_item_running: Optional[bool] = None
        self._rt_plus_item_toggle: Optional[int] = None
        self._rt_plus_tags: Optional[List[dict]] = None
        # Per-AID raw ODA payload buffer.  For every registered AID that
        # we don't have a specific decoder for, we keep the most recent
        # (b_low5, c, d) bytes, a count of received groups, and a unix
        # timestamp.  Lets the UI display "0xC563: 12 groups, last
        # B-low=0x1A C=0x1234 D=0x5678" so unknown ODA traffic isn't
        # silently discarded — useful when stations broadcast custom
        # AIDs (eRT, custom paging, vendor data) we can't yet parse.
        self._oda_payloads: Dict[int, dict] = {}
        # Per-(group_type+version) traffic histogram populated in
        # process_group.  RBDSWorker.get_stats() merges this with its
        # own block-level counters into a single RBDSDecoderStats.
        self._group_type_counts: Dict[str, int] = {}
        # Group 5A/5B TDC state
        self._tdc_channels: Dict[int, List[int]] = {}
        # Group 7A / 13A paging buffers — each capped to the most recent
        # 16 messages.  Format is operator-defined so we only keep raw
        # bytes plus the segmentation hints.
        self._paging_messages: List[dict] = []
        self._enhanced_paging_messages: List[dict] = []
        # Group 6A/6B In-house state
        self.in_house_data: List[int] = []
        # Group 8A TMC state
        self.tmc_present: Optional[bool] = None
        # Group 9A EWS state
        self.ews_channel: Optional[int] = None
        self.ews_message_c: Optional[int] = None
        self.ews_message_d: Optional[int] = None
        # Group 14A/14B EON state
        self._eon_map: Dict[int, dict] = {}
        # Group 15B fast switching state
        self.fast_tp: Optional[bool] = None
        self.fast_ta: Optional[bool] = None
        self.fast_ms: Optional[bool] = None
        self.fast_di_bits: Optional[int] = None
        # Dynamic-PS cycle assembly. Stations that rotate multiple
        # 8-char PS strings send them one after another in complete
        # cycles of 4 segments (addresses 0..3). To avoid displaying
        # Frankenstein blends of two strings, accumulate segments into
        # a staging buffer and only copy to the visible ps_name once a
        # full self-consistent cycle has been observed. If a segment
        # contradicts a previously-seen address in the current cycle,
        # the station has begun a new PS and we discard the stale
        # staging data and start over with the new content.
        self._ps_pending = [' '] * 8
        self._ps_pending_mask = 0
        # Candidate PS (last *fully observed* cycle) and how many times
        # it has repeated. A candidate only promotes to ps_name after
        # being observed twice in a row, which prevents Frankenstein
        # blends (one segment from string A + one from string B
        # interleaving across four unique addresses would otherwise
        # look like a valid cycle).
        self._ps_candidate = None  # type: Optional[str]
        self._ps_candidate_count = 0

    def process_group(self, group_data: Tuple[int, int, int, int]) -> Optional[bool]:
        """
        Process a decoded RBDS group.

        Args:
            group_data: Tuple of four 16-bit RBDS blocks (A, B, C, D)

        Returns:
            True if metadata changed, otherwise False/None
        """
        a, b, c, d = group_data
        changed = False

        group_type = (b >> 12) & 0xF
        version_b = bool((b >> 11) & 0x1)
        logger.debug(
            "RBDS group: A=%04X B=%04X C=%04X D=%04X (type=%d%s)",
            a, b, c, d, group_type, "B" if version_b else "A"
        )

        # Tally this group into the per-type histogram so the UI can show
        # what mix of services this station broadcasts (e.g. "no 2A => no
        # Radio Text" is much clearer than just an empty RT panel).
        gt_key = f"{group_type}{'B' if version_b else 'A'}"
        self._group_type_counts[gt_key] = self._group_type_counts.get(gt_key, 0) + 1

        pi_code = f"{a:04X}"
        if self.pi_code != pi_code:
            self.pi_code = pi_code
            new_call = pi_to_call_sign(a)
            if new_call != self.call_sign:
                self.call_sign = new_call
            changed = True

        pty = (b >> 5) & 0x1F
        if self.pty != pty:
            self.pty = pty
            # A PTY change invalidates any previously-decoded PTYN for the
            # old program type.
            self.pty_name = None
            self._pty_name_buf = [' '] * 8
            changed = True

        tp = bool((b >> 10) & 0x1)
        if self.tp != tp:
            self.tp = tp
            changed = True

        # Bits 4-0 of Block B are group-type-dependent. TA (bit 4) and MS
        # (bit 3) are only defined for Group 0A/0B; in other groups those
        # bits carry unrelated payload (e.g. the RT A/B flag in Group 2,
        # MJD time bits in Group 4A), so extracting them unconditionally
        # would corrupt the flags each time a non-Group-0 group arrived.
        if group_type == 0:
            ta = bool((b >> 4) & 0x1)
            if self.ta != ta:
                self.ta = ta
                changed = True

            ms = bool((b >> 3) & 0x1)
            if self.ms != ms:
                self.ms = ms
                changed = True

            di_bit = bool((b >> 2) & 0x1)
            address = b & 0x3
            if self._update_di(address, di_bit):
                changed = True

            # Group 0A Block C: Alternative Frequencies (Method A).
            # Codes 1-204     -> direct VHF FM frequency 87.6 + 0.1*code MHz
            # Codes 205-223   -> filler / not used
            # Codes 224-249   -> AF list count (224 = "no AF", 225 = 1 AF, ... 249 = 25)
            # Code 250        -> LF/MF follow-on indicator (Method B)
            # Codes 251-255   -> reserved
            # Either byte of Block C may carry a count or follow-on code
            # paired with a direct code; surface both so the UI can mark
            # the AF list "complete" once enough direct codes have arrived.
            if not version_b:
                af1 = (c >> 8) & 0xFF
                af2 = c & 0xFF

                # Method B detection: a pair where both bytes are equal
                # direct codes is the "regional variant exists at this
                # frequency" / tuning-frequency marker (NRSC-4-B Annex C).
                # The presence of this marker tags the station as Method
                # B; the actual AF codes still arrive as direct values in
                # the regular pairs and populate af_list naturally, so we
                # only need to remember the tuning frequency for display.
                if af1 == af2 and 1 <= af1 <= 204:
                    tuning_mhz = round(87.6 + 0.1 * af1, 1)
                    if (not self._af_method_b
                            or self._af_tuning_frequency != tuning_mhz):
                        self._af_method_b = True
                        self._af_tuning_frequency = tuning_mhz
                        changed = True

                new_freqs = []
                for code in (af1, af2):
                    if 1 <= code <= 204:
                        new_freqs.append(round(87.6 + 0.1 * code, 1))
                    elif 224 <= code <= 249:
                        announced = code - 224  # number of AFs the station says follow
                        if self._af_method_a_count != announced:
                            self._af_method_a_count = announced
                            changed = True
                    elif code == 250:
                        if not self._af_follow_on_indicator:
                            self._af_follow_on_indicator = True
                            changed = True
                if new_freqs:
                    prev_len = len(self._af_buffer)
                    for f in new_freqs:
                        if f not in self._af_buffer:
                            self._af_buffer.append(f)
                    if len(self._af_buffer) != prev_len:
                        changed = True

            chars = d
            if self._update_ps_name(address, chars):
                changed = True
        elif group_type == 1 and not version_b:
            pin_day = (c >> 11) & 0x1F
            pin_hour = (c >> 6) & 0x1F
            pin_minute = c & 0x3F
            if pin_day > 0 and (self.pin_day != pin_day or self.pin_hour != pin_hour
                                 or self.pin_minute != pin_minute):
                self.pin_day, self.pin_hour, self.pin_minute = pin_day, pin_hour, pin_minute
                changed = True
            variant = (b >> 2) & 0x7
            if self._apply_group1_variant(variant, d):
                changed = True
        elif group_type == 1 and version_b:
            variant = (b >> 2) & 0x7
            if self._apply_group1_variant(variant, d):
                changed = True
        elif group_type == 2:
            text_segment = b & 0xF
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._radio_text_ab:
                self._radio_text_ab = ab_flag
                self.radio_text = [' '] * 64
                self._radio_text_len = 64
                self._radio_text_cr_index = None
                changed = True
            # Within this single group, any chars arriving after a 0x0D are
            # the padding that fills the final segment. Track it so
            # _update_radio_text can reject those without mistaking them
            # for the station extending its RT in a later broadcast.
            self._rt_saw_cr_this_group = False

            # RDS characters are 8-bit (Annex E of EN 50067 / Annex F of
            # NRSC-4). Masking to 0x7F strips the high bit and silently
            # corrupts anything in the upper half of the RDS character
            # table; use a full byte to stay consistent with PS decoding.
            if not version_b:
                blocks = (c, d)
                for offset, block in enumerate(blocks):
                    chars = [
                        (block >> 8) & 0xFF,
                        block & 0xFF,
                    ]
                    for i, code in enumerate(chars):
                        idx = text_segment * 4 + offset * 2 + i
                        if idx < len(self.radio_text):
                            if self._update_radio_text(idx, code):
                                changed = True
            else:
                chars = [(d >> 8) & 0xFF, d & 0xFF]
                for i, code in enumerate(chars):
                    idx = text_segment * 2 + i
                    if idx < len(self.radio_text):
                        if self._update_radio_text(idx, code):
                            changed = True
        elif group_type == 3 and not version_b:
            oda_group_type = (b >> 1) & 0xF
            oda_version = b & 0x1
            aid = c
            if aid != 0:
                key = (oda_group_type, oda_version)
                if key not in self._oda_app_map or self._oda_app_map[key] != aid:
                    self._oda_app_map[key] = aid
                    if aid not in self.oda_apps:
                        self.oda_apps.append(aid)
                    changed = True
        elif group_type == 4 and not version_b:
            # Group 4A: Clock Time and Date.
            # Block B bits 1-0 + Block C bits 15-1  -> MJD (17 bits)
            # Block C bit 0                         -> hour MSB
            # Block D bits 15-12                    -> hour LSBs (4 bits)
            # Block D bits 11-6                     -> minute (6 bits)
            # Block D bit 5                         -> local offset sign (0=+)
            # Block D bits 4-0                      -> local offset in half-hours
            mjd = ((b & 0x3) << 15) | ((c >> 1) & 0x7FFF)
            hour = ((c & 0x1) << 4) | ((d >> 12) & 0xF)
            minute = (d >> 6) & 0x3F
            offset_sign = -1 if (d >> 5) & 0x1 else 1
            offset_half_hours = d & 0x1F
            if self._update_clock_time(mjd, hour, minute, offset_sign, offset_half_hours):
                changed = True
        elif group_type == 5 and not version_b:
            raw = [(c >> 8) & 0xFF, c & 0xFF, (d >> 8) & 0xFF, d & 0xFF]
            self._accumulate_tdc(b & 0x1F, raw)
            changed = True
        elif group_type == 5 and version_b:
            self._accumulate_tdc(b & 0x1F, [(d >> 8) & 0xFF, d & 0xFF])
            changed = True
        elif group_type == 6 and not version_b:
            raw = [b & 0x1F, c, d]
            self.in_house_data = self.in_house_data[-15:] + raw
            changed = True
        elif group_type == 6 and version_b:
            raw = [b & 0x1F, d]
            self.in_house_data = self.in_house_data[-16:] + raw
            changed = True
        elif group_type == 7 and not version_b:
            # Group 7A: Radio Paging.  NRSC-4-B / IEC 62106 §5 leaves the
            # payload format to the paging operator (different operators
            # use PSWF / PSC / RDS-Paging-1).  We capture the raw bytes
            # plus the segmentation hints from Block B so downstream
            # systems can decode whichever paging dialect their local
            # broadcaster is using; the buffer is capped so a chatty
            # paging stream can't grow unbounded.
            paging_msg = {
                'a_b_flag': bool((b >> 4) & 0x1),
                'paging_segment': b & 0xF,
                'block_c': c,
                'block_d': d,
                'unix_ts': time.time(),
            }
            self._paging_messages.append(paging_msg)
            self._paging_messages = self._paging_messages[-16:]
            changed = True
            logger.debug("RBDS Group 7A (Paging): B=%04X C=%04X D=%04X", b, c, d)
        elif group_type == 13 and not version_b:
            # Group 13A: Enhanced Radio Paging.  Same situation as 7A —
            # the payload format is operator-defined, so we just keep
            # the raw bytes and let an external decoder handle them.
            erp_msg = {
                'block_b_low': b & 0x1F,
                'block_c': c,
                'block_d': d,
                'unix_ts': time.time(),
            }
            self._enhanced_paging_messages.append(erp_msg)
            self._enhanced_paging_messages = self._enhanced_paging_messages[-16:]
            changed = True
            logger.debug("RBDS Group 13A (ERP): B=%04X C=%04X D=%04X", b, c, d)
        elif group_type == 8 and not version_b:
            if not self.tmc_present:
                self.tmc_present = True
                changed = True
            logger.debug("RBDS Group 8A (TMC): B=%04X C=%04X D=%04X", b, c, d)
        elif group_type == 9 and not version_b:
            ews_channel = b & 0x1F
            if (self.ews_channel != ews_channel
                    or self.ews_message_c != c
                    or self.ews_message_d != d):
                self.ews_channel = ews_channel
                self.ews_message_c = c
                self.ews_message_d = d
                changed = True
                logger.info(
                    "RBDS EWS: channel=%d msg_c=0x%04X msg_d=0x%04X",
                    ews_channel, c, d
                )
        elif group_type == 10 and not version_b:
            # Group 10A: Program Type Name (8 chars in two 4-char segments).
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._pty_name_ab:
                self._pty_name_ab = ab_flag
                self._pty_name_buf = [' '] * 8
            segment = b & 0x1
            block_chars = [
                (c >> 8) & 0xFF, c & 0xFF,
                (d >> 8) & 0xFF, d & 0xFF,
            ]
            for i, code in enumerate(block_chars):
                idx = segment * 4 + i
                if idx < len(self._pty_name_buf):
                    char = chr(code) if 32 <= code < 127 else ' '
                    if self._pty_name_buf[idx] != char:
                        self._pty_name_buf[idx] = char
                        name = ''.join(self._pty_name_buf).strip()
                        if self.pty_name != name:
                            self.pty_name = name
                            changed = True
        elif group_type == 10 and version_b:
            segment = b & 0x1
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._pty_name_ab:
                self._pty_name_ab = ab_flag
                self._pty_name_buf = [' '] * 8
            block_chars = [(d >> 8) & 0xFF, d & 0xFF]
            for i, code in enumerate(block_chars):
                idx = segment * 2 + i
                if idx < len(self._pty_name_buf):
                    char = chr(code) if 32 <= code < 127 else ' '
                    if self._pty_name_buf[idx] != char:
                        self._pty_name_buf[idx] = char
                        name = ''.join(self._pty_name_buf).strip()
                        if self.pty_name != name:
                            self.pty_name = name
                            changed = True
        elif group_type == 14 and not version_b:
            variant = b & 0xF
            eon_tp = bool((b >> 4) & 0x1)
            eon_pi = c
            if eon_pi not in self._eon_map:
                self._eon_map[eon_pi] = {
                    'pi': f"{eon_pi:04X}", 'tp': eon_tp, 'ps': ' ' * 8, 'af': []
                }
            eon = self._eon_map[eon_pi]
            eon['tp'] = eon_tp
            if variant <= 3:
                ps_chars = [(d >> 8) & 0xFF, d & 0xFF]
                ps_list = list(eon['ps'])
                for i, code in enumerate(ps_chars):
                    idx = variant * 2 + i
                    if idx < 8:
                        ps_list[idx] = chr(code) if 32 <= code < 127 else ' '
                eon['ps'] = ''.join(ps_list)
            elif variant == 4:
                # Block D in EON variant 4 carries TWO 8-bit AF codes:
                # high byte = mapped frequency for the cross-referenced
                # programme, low byte = matched frequency for the tuned
                # programme.  Earlier code dropped the low byte, halving
                # EON AF coverage; capture both as direct codes 1..204.
                for shift in (8, 0):
                    af_code = (d >> shift) & 0xFF
                    if 1 <= af_code <= 204:
                        af_mhz = round(87.6 + 0.1 * af_code, 1)
                        if af_mhz not in eon['af']:
                            eon['af'].append(af_mhz)
            elif variant == 12:
                eon['linkage'] = d
            elif variant == 13:
                eon['pty'] = (d >> 11) & 0x1F
                eon['ta'] = bool((d >> 0) & 0x1)
            elif variant == 14:
                eon['pin_day'] = (d >> 11) & 0x1F
                eon['pin_hour'] = (d >> 6) & 0x1F
                eon['pin_minute'] = d & 0x3F
            changed = True
        elif group_type == 14 and version_b:
            eon_tp = bool((b >> 4) & 0x1)
            eon_ta = bool((b >> 3) & 0x1)
            eon_pi = c
            if eon_pi not in self._eon_map:
                self._eon_map[eon_pi] = {
                    'pi': f"{eon_pi:04X}", 'tp': eon_tp, 'ta': eon_ta,
                    'ps': ' ' * 8, 'af': []
                }
            self._eon_map[eon_pi]['tp'] = eon_tp
            self._eon_map[eon_pi]['ta'] = eon_ta
            changed = True
        elif group_type == 15 and version_b:
            fast_ta = bool((b >> 4) & 0x1)
            fast_ms = bool((b >> 3) & 0x1)
            fast_di = bool((b >> 2) & 0x1)
            address = b & 0x3
            changed_flags = False
            if self.fast_tp != tp:
                self.fast_tp = tp
                changed_flags = True
            if self.fast_ta != fast_ta:
                self.fast_ta = fast_ta
                changed_flags = True
            if self.fast_ms != fast_ms:
                self.fast_ms = fast_ms
                changed_flags = True
            if changed_flags:
                changed = True
            if self._update_di(address, fast_di):
                changed = True
            if self._update_ps_name(address, d):
                changed = True

        # ODA payload dispatch.  The Group 3A handler (above) records which
        # (group_type, version) slots a station has assigned to ODA AIDs;
        # decode any payload group that matches a known AID.  RT+
        # (0xCD46) gets a real decoder; every other AID has its raw
        # payload captured into _oda_payloads so the UI can show that
        # something is being broadcast on the slot even when we can't
        # interpret it.
        oda_key = (group_type, 1 if version_b else 0)
        oda_aid = self._oda_app_map.get(oda_key)
        if oda_aid is not None:
            if oda_aid == RT_PLUS_AID:
                if self._handle_rt_plus(b, c, d):
                    changed = True
            else:
                # Capture the lower 5 bits of B (the payload nibble — the
                # rest of B is group-type / TP / PTY which we already
                # decoded) plus all of C and D.  Bump count and stamp
                # last-seen so the UI can show traffic activity per AID.
                entry = self._oda_payloads.setdefault(oda_aid, {
                    'aid': oda_aid,
                    'aid_hex': f"0x{oda_aid:04X}",
                    'group': f"{group_type}{'B' if version_b else 'A'}",
                    'count': 0,
                    'last_b_low': 0,
                    'last_c': 0,
                    'last_d': 0,
                    'last_seen_unix': 0.0,
                })
                entry['count'] += 1
                entry['last_b_low'] = b & 0x1F
                entry['last_c'] = c
                entry['last_d'] = d
                entry['last_seen_unix'] = time.time()
                changed = True

        return changed

    def _handle_rt_plus(self, b: int, c: int, d: int) -> bool:
        """Decode an RT+ payload group (AID 0xCD46) per RDS Forum R03/040.1.

        RT+ piggybacks on whatever group type the station registers via 3A
        (most US music stations use 11A).  Each group carries two
        (content_type, start, length) tag pointers into the current Radio
        Text buffer plus item-running / item-toggle bits announcing
        when a new programme item is on air.

        Block layout (16 bits each, MSB first):
            B[4]    : item toggle bit
            B[3]    : item running bit
            B[2:0]  : content type 1 high 3 bits
            C[15:13]: content type 1 low 3 bits  (6-bit total)
            C[12:7] : start marker 1 (0..63)
            C[6:1]  : length marker 1 (length-1, 0..63)
            C[0]    : content type 2 high 1 bit
            D[15:11]: content type 2 low 5 bits  (6-bit total)
            D[10:5] : start marker 2 (0..63)
            D[4:0]  : length marker 2 (length-1, 0..31)

        Returns True if any RT+ field changed.
        """
        item_toggle = (b >> 4) & 0x1
        item_running = bool((b >> 3) & 0x1)
        content_type_1 = ((b & 0x7) << 3) | ((c >> 13) & 0x7)
        start_1 = (c >> 7) & 0x3F
        length_1 = (c >> 1) & 0x3F
        content_type_2 = ((c & 0x1) << 5) | ((d >> 11) & 0x1F)
        start_2 = (d >> 5) & 0x3F
        length_2 = d & 0x1F

        rt_string = ''.join(self.radio_text[:self._radio_text_len])

        new_tags: List[dict] = []
        for ctype, start, length_field in (
            (content_type_1, start_1, length_1),
            (content_type_2, start_2, length_2),
        ):
            # Content type 0 ("DUMMY") signals "no tag in this slot" — used
            # when only one of the two tag pairs is meaningful for the
            # current programme item.  Skip it entirely.
            if ctype == 0:
                continue
            end = start + length_field + 1  # length field is length-minus-1
            if end > len(rt_string) or start >= len(rt_string):
                # Tag points outside the buffered RT.  This usually means
                # we have not yet received all the RT segments the station
                # is referencing; skip and wait for the next RT+ group
                # rather than emit a truncated artist/title.
                continue
            text = rt_string[start:end].strip()
            if not text:
                continue
            new_tags.append({
                'content_type': ctype,
                'content_type_name': RT_PLUS_CONTENT_TYPES.get(
                    ctype, f'TYPE_{ctype}'
                ),
                'text': text,
                'start': start,
                'length': length_field + 1,
            })

        changed = False
        if self._rt_plus_item_running != item_running:
            self._rt_plus_item_running = item_running
            changed = True
        if self._rt_plus_item_toggle != item_toggle:
            # Toggle flip => new programme item.  Replace tags even if
            # decode came back empty so the UI clears the prior song.
            self._rt_plus_item_toggle = item_toggle
            self._rt_plus_tags = new_tags or None
            changed = True
        elif new_tags and new_tags != self._rt_plus_tags:
            # Same item but text refined (RT extended, or station retransmits
            # with corrected content) — promote the newer tag list.
            self._rt_plus_tags = new_tags
            changed = True
        return changed

    def get_current_data(self) -> RBDSData:
        """Get the currently decoded RBDS data."""
        rt_chars = self.radio_text[:self._radio_text_len]

        # Derived PI breakdown — Annex D layout: 4 bits country code,
        # 4 bits area/coverage, 8 bits programme reference.  Surface raw
        # values; the UI is responsible for any region-specific naming.
        pi_country = pi_area = pi_program = None
        if self.pi_code:
            try:
                pi_int = int(self.pi_code, 16)
                pi_country = (pi_int >> 12) & 0xF
                pi_area = (pi_int >> 8) & 0xF
                pi_program = pi_int & 0xFF
            except ValueError:
                pass

        # Reconstruct the ODA assignment table: each entry says which
        # group/version slot a given AID lives on, with the AID rendered
        # in hex for direct comparison against vendor docs.
        oda_assignments: Optional[List[dict]] = None
        if self._oda_app_map:
            oda_assignments = []
            for (gt, ver), aid in sorted(self._oda_app_map.items()):
                entry = {
                    'group': f"{gt}{'B' if ver else 'A'}",
                    'group_type': gt,
                    'version_b': bool(ver),
                    'aid': aid,
                    'aid_hex': f"0x{aid:04X}",
                }
                if aid == RT_PLUS_AID:
                    entry['name'] = 'RT+'
                oda_assignments.append(entry)

        return RBDSData(
            pi_code=self.pi_code,
            pi_country_code=pi_country,
            pi_area_code=pi_area,
            pi_program_ref=pi_program,
            call_sign=self.call_sign,
            ps_name=''.join(self.ps_name).strip(),
            pty_name=self.pty_name,
            radio_text=''.join(rt_chars).strip(),
            radio_text_ab=self._radio_text_ab,
            pty=self.pty,
            tp=self.tp,
            ta=self.ta,
            ms=self.ms,
            di_stereo=self.di_stereo,
            di_artificial_head=self.di_artificial_head,
            di_compressed=self.di_compressed,
            di_dynamic_pty=self.di_dynamic_pty,
            clock_time_utc=self.clock_time_utc,
            clock_time_local=self.clock_time_local,
            af_list=sorted(self._af_buffer) if self._af_buffer else None,
            af_method_a_count=self._af_method_a_count,
            af_follow_on_indicator=(
                True if self._af_follow_on_indicator else None
            ),
            af_method_b=(True if self._af_method_b else None),
            af_tuning_frequency=self._af_tuning_frequency,
            pin_day=self.pin_day,
            pin_hour=self.pin_hour,
            pin_minute=self.pin_minute,
            ecc=self.ecc,
            language_code=self.language_code,
            language_name=self.language_name,
            linkage_set_number=self.linkage_set_number,
            linkage_actuator=self.linkage_actuator,
            linkage_soft_coupling=self.linkage_soft_coupling,
            paging_tmc_id=self.paging_tmc_id,
            paging_operator_code=self.paging_operator_code,
            ews_channel_identifier=self.ews_channel_identifier,
            slow_labelling_raw=(
                dict(self._slow_labelling_raw)
                if self._slow_labelling_raw else None
            ),
            oda_apps=list(self.oda_apps) if self.oda_apps else None,
            oda_assignments=oda_assignments,
            oda_payloads=(
                [dict(v) for v in self._oda_payloads.values()]
                if self._oda_payloads else None
            ),
            paging_messages=(
                [dict(m) for m in self._paging_messages]
                if self._paging_messages else None
            ),
            enhanced_paging_messages=(
                [dict(m) for m in self._enhanced_paging_messages]
                if self._enhanced_paging_messages else None
            ),
            tdc_data=bytes(self._tdc_channels.get(0, [])) if self._tdc_channels else None,
            tdc_channels=(
                {ch: bytes(buf) for ch, buf in self._tdc_channels.items() if buf}
                if self._tdc_channels else None
            ),
            in_house_data=list(self.in_house_data) if self.in_house_data else None,
            tmc_present=self.tmc_present,
            ews_channel=self.ews_channel,
            ews_message_c=self.ews_message_c,
            ews_message_d=self.ews_message_d,
            eon_list=list(self._eon_map.values()) if self._eon_map else None,
            fast_tp=self.fast_tp,
            fast_ta=self.fast_ta,
            fast_ms=self.fast_ms,
            fast_di_bits=None,
            rt_plus_item_running=self._rt_plus_item_running,
            rt_plus_item_toggle=self._rt_plus_item_toggle,
            rt_plus_tags=(
                [dict(t) for t in self._rt_plus_tags]
                if self._rt_plus_tags else None
            ),
        )

    def _apply_group1_variant(self, variant: int, d: int) -> bool:
        """Process a Group 1A/1B slow-labelling variant payload.

        Variants 0/4/5 produce semantic fields (language code, ECC,
        linkage); for completeness every variant — including 1/2/3/6/7
        which the spec leaves loosely defined or assigns to paging /
        TMC ID / EWS slow-labelling pointer — has its raw 16-bit Block-D
        contents captured into _slow_labelling_raw, keyed by variant
        number, so the UI can show "variant N said XXXX" even for codes
        no decoder understands.

        Returns True if any field changed.
        """
        # Always store the raw byte first.  Even when a specific decoder
        # below picks fields out of d we keep the raw word so the UI can
        # show low-level diagnostics next to the interpreted value.
        changed_raw = (
            self._slow_labelling_raw.get(variant) != d
        )
        if changed_raw:
            self._slow_labelling_raw[variant] = d

        changed_decoded = False
        if variant == 0:
            # Per the existing implementation: variant 0 has historically
            # been used for the legacy language code on some installations
            # (RBDS pre-2005 supplements).  Keep the behaviour but only
            # consider it a "language" update when the byte is in range.
            lang = d & 0xFF
            if lang != 0 and self.language_code != lang:
                self.language_code = lang
                self.language_name = RBDS_LANGUAGE_CODES.get(lang)
                changed_decoded = True
        elif variant == 1:
            # Variant 1 is reserved/local in NRSC-4-B; some EU stations
            # use it for "TMC identification" carrying a 12-bit TMC
            # provider code in d[11:0].  Capture it as a structured value.
            tmc_id = d & 0x0FFF
            if self.paging_tmc_id != tmc_id:
                self.paging_tmc_id = tmc_id
                changed_decoded = True
        elif variant == 2:
            # Variant 2: Paging Identification (operator code in d[11:0]
            # plus 4 bits of operator-defined subfield in d[15:12]).
            paging_op = d & 0x0FFF
            if self.paging_operator_code != paging_op:
                self.paging_operator_code = paging_op
                changed_decoded = True
        elif variant == 3:
            # Variant 3: legacy language-code assignment used by some
            # EU broadcasters in place of variant 0.  Treat identically.
            lang = d & 0xFF
            if lang != 0 and self.language_code != lang:
                self.language_code = lang
                self.language_name = RBDS_LANGUAGE_CODES.get(lang)
                changed_decoded = True
        elif variant == 4:
            ecc_val = d & 0xFF
            if ecc_val != 0 and self.ecc != ecc_val:
                self.ecc = ecc_val
                changed_decoded = True
        elif variant == 5:
            lsn = d & 0x0FFF
            la = bool((d >> 15) & 0x1)
            sc = bool((d >> 14) & 0x1)
            if self.linkage_set_number != lsn:
                self.linkage_set_number = lsn
                self.linkage_actuator = la
                self.linkage_soft_coupling = sc
                changed_decoded = True
        elif variant == 6:
            # Variant 6: broadcaster-use 16 bits.  No standard interpretation,
            # but we expose it raw in the slow-labelling table above; nothing
            # extra to compute.
            pass
        elif variant == 7:
            # Variant 7: EWS channel identifier slow-labelling pointer.
            # Carries a 12-bit EWS service identifier in d[11:0] that
            # tells receivers which EWS provider feeds Group 9A.  Useful
            # diagnostic alongside the actual EWS messages.
            ews_id = d & 0x0FFF
            if self.ews_channel_identifier != ews_id:
                self.ews_channel_identifier = ews_id
                changed_decoded = True
        return changed_raw or changed_decoded

    def _accumulate_tdc(self, channel: int, raw: list) -> None:
        """Append TDC bytes to a channel buffer, capped at 256 bytes."""
        if channel not in self._tdc_channels:
            self._tdc_channels[channel] = []
        self._tdc_channels[channel].extend(raw)
        self._tdc_channels[channel] = self._tdc_channels[channel][-256:]

    def _update_ps_name(self, address: int, chars: int) -> bool:
        """Stage PS segments into a pending buffer, display once a full
        4-segment cycle has been observed as self-consistent.

        Stations that broadcast *dynamic PS* rotate through multiple
        8-char strings ("KISS-FM ", station slogan, song title, ...) by
        sending each one as a complete cycle of four segments (address
        0..3). If we committed each segment the moment it arrived, the
        displayed PS would blend bytes from two different strings
        whenever segments from different rotation slots interleaved —
        "93.9 FM " and "Kiss-FM " can end up rendered as "93si-FM ".

        Approach: keep a pending 8-char buffer and a 4-bit 'segments
        seen' mask. When a new segment arrives at an address that was
        already set in the current cycle:
          - If its content matches what we already staged → keep going.
          - Otherwise → the station started broadcasting a new PS;
            discard staging and restart with just this segment.
        When all four segments of a single cycle have been seen
        consistently, copy pending to the visible ps_name.
        """
        idx = address * 2
        chars_pair = [
            chr((chars >> 8) & 0xFF) if 32 <= ((chars >> 8) & 0xFF) < 127 else ' ',
            chr(chars & 0xFF) if 32 <= (chars & 0xFF) < 127 else ' ',
        ]
        bit = 1 << address
        if self._ps_pending_mask & bit:
            # Already staged this segment in the current cycle — is it
            # still the same string?
            if (self._ps_pending[idx] != chars_pair[0] or
                    self._ps_pending[idx + 1] != chars_pair[1]):
                # Station has started broadcasting a different PS.
                # Discard staging and restart with just this segment.
                self._ps_pending = [' '] * 8
                self._ps_pending_mask = 0
        self._ps_pending[idx] = chars_pair[0]
        self._ps_pending[idx + 1] = chars_pair[1]
        self._ps_pending_mask |= bit

        if self._ps_pending_mask != 0xF:
            return False
        # A full cycle has been observed. Don't promote yet — require a
        # second identical cycle to commit, which filters out blended
        # mixes of two different rotation strings (the four segments
        # from A and B can interleave without conflict because each
        # address appears only once per cycle, so "no conflict" alone
        # isn't enough evidence that the 8 chars all came from the
        # same PS string).
        candidate = ''.join(self._ps_pending)
        if candidate == self._ps_candidate:
            self._ps_candidate_count += 1
        else:
            self._ps_candidate = candidate
            self._ps_candidate_count = 1
        # Start a fresh pending cycle for the next 4 segments.
        self._ps_pending = [' '] * 8
        self._ps_pending_mask = 0
        if self._ps_candidate_count < 2:
            return False
        # Two consecutive identical cycles — promote to the visible PS.
        updated = False
        for i, ch in enumerate(candidate):
            if self.ps_name[i] != ch:
                self.ps_name[i] = ch
                updated = True
        return updated

    def _update_radio_text(self, index: int, code: int) -> bool:
        if index >= len(self.radio_text):
            return False
        # RDS spec: 0x0D (carriage return) terminates the Radio Text.
        # Everything that follows 0x0D *within the same group* is padding.
        if code == 0x0D:
            self._rt_saw_cr_this_group = True
            self._radio_text_cr_index = index
            if self._radio_text_len > index:
                self._radio_text_len = index
                return True
            return False
        # Post-CR characters in this same group are padding → drop.
        if self._rt_saw_cr_this_group and index >= self._radio_text_len:
            return False
        # If a *previous* group placed a CR at this exact index and the
        # station is now broadcasting a non-CR byte at the same slot, the
        # CR is no longer in effect — release the terminator so later
        # segments can extend the displayed RT.  Bare padding past the old
        # terminator (a different index) is still rejected below, so a
        # CRC-lucky garbage byte in some unrelated segment can't drag junk
        # into the display.
        if (
            not self._rt_saw_cr_this_group
            and self._radio_text_cr_index is not None
            and index == self._radio_text_cr_index
        ):
            self._radio_text_cr_index = None
            self._radio_text_len = len(self.radio_text)
        char = chr(code) if 32 <= code < 127 else ' '
        # Characters past the current terminator are padding by default.
        # An earlier pass extended the length on any non-space byte, but
        # that let a single CRC-lucky garbage byte drag trailing junk
        # into the displayed RT ("93.9 KISS-FM ... )["). Always drop
        # past-terminator writes — when the station changes RT it should
        # toggle the A/B flag (which clears everything) or re-send a
        # later CR (which moves the terminator accordingly). This is
        # conservative but matches how car receivers behave.
        if index >= self._radio_text_len:
            return False
        if self.radio_text[index] != char:
            self.radio_text[index] = char
            return True
        return False

    def _update_di(self, address: int, di_bit: bool) -> bool:
        """Apply one DI (Decoder Identification) bit. The four bits are
        delivered across the four PS segments (address 0-3) and together
        describe the audio programme properties.

            address 0 -> d3: dynamic PTY indicator
            address 1 -> d2: compressed audio
            address 2 -> d1: artificial head / binaural
            address 3 -> d0: stereo / mono
        """
        attr = {
            0: "di_dynamic_pty",
            1: "di_compressed",
            2: "di_artificial_head",
            3: "di_stereo",
        }.get(address)
        if attr is None:
            return False
        if getattr(self, attr) != di_bit:
            setattr(self, attr, di_bit)
            return True
        return False

    def _update_clock_time(
        self,
        mjd: int,
        hour: int,
        minute: int,
        offset_sign: int,
        offset_half_hours: int,
    ) -> bool:
        """Decode a Group 4A clock-time / date payload into ISO-8601
        UTC and local timestamps. MJD is the Modified Julian Date; hour
        and minute are UTC; offset is the local-time offset in signed
        half-hours. Returns True if either stored timestamp changed."""
        # Reject obviously malformed broadcasts (some stations pad with
        # zeros or never set MJD). MJD 40587 == 1970-01-01.
        if mjd < 40587 or hour > 23 or minute > 59 or offset_half_hours > 47:
            return False
        # MJD -> Gregorian date (Jean Meeus, Astronomical Algorithms ch. 7).
        jd = mjd + 2400001  # integer Julian Day Number at 00:00 UT
        a_ = jd + 32044
        b_ = (4 * a_ + 3) // 146097
        c_ = a_ - (146097 * b_) // 4
        d_ = (4 * c_ + 3) // 1461
        e_ = c_ - (1461 * d_) // 4
        m_ = (5 * e_ + 2) // 153
        day = e_ - (153 * m_ + 2) // 5 + 1
        month = m_ + 3 - 12 * (m_ // 10)
        year = 100 * b_ + d_ - 4800 + m_ // 10
        try:
            utc_dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            return False
        local_dt = utc_dt + timedelta(minutes=30 * offset_sign * offset_half_hours)
        utc_iso = utc_dt.isoformat()
        local_iso = local_dt.replace(tzinfo=None).isoformat()
        changed = False
        if self.clock_time_utc != utc_iso:
            self.clock_time_utc = utc_iso
            changed = True
        if self.clock_time_local != local_iso:
            self.clock_time_local = local_iso
            changed = True
        return changed


def create_demodulator(config: DemodulatorConfig):
    """Factory function to create the appropriate demodulator."""
    # Normalize modulation type to uppercase for consistent comparison
    mod_type = config.modulation_type.upper()

    if mod_type in ('FM', 'WFM', 'NFM'):
        return FMDemodulator(config)
    elif mod_type == 'AM':
        return AMDemodulator(config)
    elif mod_type == 'IQ':
        # No demodulation, return raw IQ
        return None
    else:
        raise ValueError(
            f"Unsupported modulation type: {config.modulation_type}. "
            f"Valid types: FM, WFM, NFM, AM, IQ"
        )
