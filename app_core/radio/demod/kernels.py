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

"""Numba-JIT DSP kernels for the FM/RBDS hot path.

Every function here is compiled with ``@jit(nopython=True)`` when Numba is
available and falls back to the pure-Python definition otherwise. They are the
lowest layer of the demodulator and import nothing from the rest of the
package.
"""

import logging
from typing import Tuple

import numpy as np


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
def _fm_discriminator_declick_numba(
    iq_real: np.ndarray,
    iq_imag: np.ndarray,
    mag_threshold_sq: float,
    prev_phase: float,
) -> Tuple[np.ndarray, np.int64, np.float32]:
    """JIT-compiled FM phase discriminator with magnitude-aware click suppression.

    On weak/multipath signals the envelope |z[n]·z*[n-1]| collapses toward
    zero during deep fades; in that regime atan2 returns essentially
    uniformly-distributed phase noise that, spectrally, is a flat impulse
    floor obliterating the 19 kHz pilot and 57 kHz RBDS subcarriers. The
    classical FM "click" suppressor — used in narrowband FM voice receivers
    since the 1960s — detects those fades by their magnitude collapse and
    replaces the corrupted phase output with the previous sample's value.

    Why magnitude squared: |z[n]·z*[n-1]| = |z[n]|·|z[n-1]|.  We compare its
    square against a caller-supplied threshold so the inner loop avoids a
    sqrt per sample.  The threshold is the **chunk RMS power squared**
    scaled by the user-configurable fraction; this makes the suppressor
    self-adjusting to AGC gain (a strong station and a weak one produce
    the same fraction of clicks before/after the change, just at different
    absolute magnitudes).

    Args:
        iq_real: Real component of IQ samples (float32)
        iq_imag: Imaginary component of IQ samples (float32)
        mag_threshold_sq: Suppress samples where |z[n]|^2·|z[n-1]|^2 falls
            below this value.  Caller computes it as
            (suppression_fraction * mean(|z|^2))^2 over the chunk.
        prev_phase: Phase output from the last sample of the previous chunk
            (or 0.0 for the first call); used as the forward-fill seed so a
            click at sample 0 doesn't leak into the next chunk.

    Returns:
        Tuple of:
            audio: Audio samples as phase differences (float32)
            click_count: Number of samples replaced by forward-fill (int64)
            last_phase: Phase of the last *good* (non-suppressed) sample,
                for use as prev_phase on the next chunk
    """
    n = len(iq_real) - 1
    audio = np.empty(n, dtype=np.float32)
    click_count = np.int64(0)
    last_good = np.float32(prev_phase)

    for i in range(n):
        r0, i0 = iq_real[i], iq_imag[i]
        r1, i1 = iq_real[i + 1], iq_imag[i + 1]

        # mag_sq_product = |z[n]|^2 * |z[n-1]|^2 == (r0^2+i0^2)*(r1^2+i1^2)
        # which equals (real_part^2 + imag_part^2) because
        # |z1·z0*|^2 = |z1|^2·|z0|^2.  We get it for free from the parts
        # we already need for atan2.
        real_part = r1 * r0 + i1 * i0
        imag_part = i1 * r0 - r1 * i0
        mag_sq = real_part * real_part + imag_part * imag_part

        if mag_sq < mag_threshold_sq:
            # Click: envelope collapsed.  Hold the previous good phase
            # rather than feeding atan2's random output into the
            # discriminator chain.
            audio[i] = last_good
            click_count += 1
        else:
            phase = np.arctan2(imag_part, real_part)
            audio[i] = phase
            last_good = phase

    return audio, click_count, last_good



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

