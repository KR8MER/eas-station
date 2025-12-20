"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Try to import Numba for JIT compilation of hot DSP functions
# Falls back to pure NumPy if Numba is not available
_NUMBA_AVAILABLE = False
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
def _fast_decimate_numba(samples: np.ndarray, factor: int) -> np.ndarray:
    """JIT-compiled fast decimation by averaging.

    Reduces sample rate by averaging groups of samples. Much faster than
    convolution-based decimation for real-time processing.

    Args:
        samples: Input samples (float32)
        factor: Decimation factor (e.g., 10 means 10:1 reduction)

    Returns:
        Decimated samples (float32)
    """
    n_out = len(samples) // factor
    output = np.empty(n_out, dtype=np.float32)

    for i in prange(n_out):
        acc = np.float32(0.0)
        base = i * factor
        for j in range(factor):
            acc += samples[base + j]
        output[i] = acc / factor

    return output


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
    """Fast decimation - dispatches to JIT or NumPy implementation.

    Args:
        samples: Input samples (float32)
        factor: Decimation factor

    Returns:
        Decimated samples (float32)
    """
    if factor <= 1:
        return samples

    # Truncate to multiple of factor
    n_complete = (len(samples) // factor) * factor
    if n_complete == 0:
        return samples

    samples = samples[:n_complete].astype(np.float32)

    if _NUMBA_AVAILABLE and len(samples) > 100:
        return _fast_decimate_numba(samples, factor)
    else:
        # Pure NumPy using reshape+mean (still fast)
        return samples.reshape(-1, factor).mean(axis=1).astype(np.float32)


@dataclass
class DemodulatorConfig:
    """Configuration for audio demodulator."""
    modulation_type: str  # 'FM', 'WFM', 'NFM', 'AM', 'IQ'
    sample_rate: int  # Input sample rate (Hz)
    audio_sample_rate: int = 44100  # Output audio sample rate (native for streams/outputs)
    stereo_enabled: bool = True  # Enable FM stereo decoding
    deemphasis_us: float = 75.0  # De-emphasis time constant (75μs NA, 50μs EU, 0 to disable)
    enable_rbds: bool = False  # Extract RBDS data from FM multiplex


@dataclass
class RBDSData:
    """Decoded RBDS/RDS data from FM broadcast."""
    pi_code: Optional[str] = None  # Program Identification
    ps_name: Optional[str] = None  # Program Service name (8 chars)
    radio_text: Optional[str] = None  # Radio Text (64 chars)
    pty: Optional[int] = None  # Program Type
    tp: Optional[bool] = None  # Traffic Program flag
    ta: Optional[bool] = None  # Traffic Announcement flag
    ms: Optional[bool] = None  # Music/Speech flag


@dataclass
class DemodulatorStatus:
    """Status information from FM demodulator."""
    rbds_data: Optional[RBDSData] = None  # RBDS data if available
    stereo_pilot_locked: bool = False  # 19 kHz stereo pilot detected
    stereo_pilot_strength: float = 0.0  # Pilot signal strength (0.0 to 1.0)
    is_stereo: bool = False  # Stereo decoding active


class RBDSWorker:
    """Threaded RBDS processor - processes RBDS in background without blocking audio.

    Like SDR++, RBDS runs in its own thread. Audio demodulation drops samples
    into a queue; the worker processes them independently and publishes results.
    This ensures RBDS processing NEVER blocks the audio path.
    """

    def __init__(self, sample_rate: int, intermediate_rate: int):
        """Initialize RBDS worker thread.

        Args:
            sample_rate: Original sample rate before any decimation
            intermediate_rate: Rate after decimation (where RBDS processing happens)
        """
        self._sample_rate = sample_rate
        self._intermediate_rate = intermediate_rate

        # Thread-safe queue for incoming multiplex samples
        # maxsize=5 means we drop old samples if processing is too slow (never block audio)
        self._sample_queue: queue.Queue = queue.Queue(maxsize=5)

        # Thread-safe storage for latest RBDS data
        self._latest_data: Optional[RBDSData] = None
        self._data_lock = threading.Lock()

        # Worker thread
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # RBDS processing state (initialized in _init_rbds_state)
        self._rbds_decoder: Optional['RBDSDecoder'] = None
        self._init_rbds_state()

        # Start worker thread
        self._start()

    def _init_rbds_state(self) -> None:
        """Initialize all RBDS processing state."""
        # RBDSDecoder is defined in this same file (no import needed)
        self._rbds_decoder = RBDSDecoder()

        # Decimation from sample_rate to intermediate_rate
        self._rbds_decim_factor = max(1, self._sample_rate // self._intermediate_rate)
        if self._rbds_decim_factor > 1:
            decim_cutoff = self._intermediate_rate / 2.5
            self._rbds_decim_filter = self._design_fir_lowpass(
                decim_cutoff, self._sample_rate, taps=63
            )
        else:
            self._rbds_decim_filter = None

        # RBDS filter design at intermediate rate
        rbds_filter_taps = min(101, max(31, int(self._intermediate_rate / 3000)))
        self._rbds_bandpass = self._design_fir_bandpass(
            54000.0, 60000.0, self._intermediate_rate, taps=rbds_filter_taps
        )
        self._rbds_lowpass = self._design_fir_lowpass(7500.0, self._intermediate_rate, taps=101)

        # RBDS symbol timing
        self._rbds_symbol_rate = 1187.5
        self._rbds_samples_per_symbol = 16
        self._rbds_target_rate = self._rbds_symbol_rate * self._rbds_samples_per_symbol

        # M&M clock recovery state
        self._rbds_mm_mu = 0.0
        self._rbds_mm_out_rail = 0.0
        self._rbds_mm_out = 0.0
        # State for timing error calculation (need last 2 symbols)
        self._rbds_mm_last_out = [complex(0.0), complex(0.0)]  # Last 2 output values
        self._rbds_mm_last_rail = [complex(1.0), complex(1.0)]  # Last 2 rail values
        self._rbds_mm_i_residual = 0.0  # Residual sample position from previous chunk

        # Costas loop state
        self._rbds_costas_phase = 0.0
        self._rbds_costas_freq = 0.0
        self._rbds_costas_alpha = 0.132
        self._rbds_costas_beta = 0.00932

        # Bit buffer and decoding
        self._rbds_bit_buffer: List[int] = []
        self._rbds_expected_block: Optional[int] = None
        self._rbds_partial_group: List[int] = []
        self._rbds_prev_symbol: float = 1.0
        self._rbds_carrier_phase: float = 0.0
        self._rbds_consecutive_crc_failures: int = 0
        self._rbds_synchronized: bool = False  # Require A→B confirmation before trusting data

        # Sample tracking for phase-continuous 57kHz carrier
        self._sample_index: int = 0
        self._carrier_phase_57k: float = 0.0  # Phase of 57kHz carrier for mixing

    def _design_fir_lowpass(self, cutoff: float, sample_rate: int, taps: int = 101) -> np.ndarray:
        """Design FIR lowpass filter using windowed sinc method."""
        fc = cutoff / sample_rate
        n = np.arange(taps)
        mid = (taps - 1) / 2
        h = np.sinc(2 * fc * (n - mid))
        h *= np.blackman(taps)
        h /= np.sum(h)
        return h.astype(np.float32)

    def _design_fir_bandpass(self, low: float, high: float, sample_rate: int, taps: int = 101) -> np.ndarray:
        """Design FIR bandpass filter."""
        fc_low = low / sample_rate
        fc_high = high / sample_rate
        n = np.arange(taps)
        mid = (taps - 1) / 2
        h_high = np.sinc(2 * fc_high * (n - mid))
        h_low = np.sinc(2 * fc_low * (n - mid))
        h = h_high - h_low
        h *= np.blackman(taps)
        h /= np.sum(np.abs(h))
        return h.astype(np.float32)

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

    def submit_samples(self, multiplex: np.ndarray) -> None:
        """Submit multiplex samples for RBDS processing (non-blocking).

        If the queue is full, samples are dropped. This ensures the audio
        thread is NEVER blocked by RBDS processing.
        """
        try:
            # CRITICAL FIX: Pass reference only - don't copy in audio thread!
            # The multiplex array is read-only for RBDS so sharing is safe.
            # This prevents GIL contention that was causing audio stalling.
            self._sample_queue.put_nowait(multiplex)
        except queue.Full:
            # This is expected and fine - RBDS is lower priority than audio
            pass

    def get_latest_data(self) -> Optional[RBDSData]:
        """Get the latest RBDS data (thread-safe)."""
        with self._data_lock:
            return self._latest_data

    def _worker_loop(self) -> None:
        """Main worker loop - processes RBDS samples from queue."""
        logger.info("RBDS worker thread started")
        samples_processed = 0
        groups_decoded = 0

        while not self._stop_event.is_set():
            try:
                # Wait for samples with timeout (allows checking stop_event)
                multiplex = self._sample_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                samples_processed += 1
                # Process RBDS - this can take as long as needed since we're in our own thread
                rbds_data = self._process_rbds(multiplex)

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

                # Yield GIL after processing each sample to let audio thread run
                # Critical when Numba isn't available and RBDS processing is slow
                time.sleep(0)
            except Exception as e:
                logger.warning(f"RBDS processing error: {e}", exc_info=True)

        logger.info("RBDS worker thread exited (samples=%d, groups=%d)", samples_processed, groups_decoded)

    def _process_rbds(self, multiplex: np.ndarray) -> Optional[RBDSData]:
        """Process multiplex samples to extract RBDS data.

        Based on PySDR's working implementation:
        https://pysdr.org/content/rds.html

        Key insight: M&M timing FIRST, then Costas loop!
        """
        if len(multiplex) == 0:
            return None

        # Step 1: Decimate to intermediate rate
        if self._rbds_decim_filter is not None and self._rbds_decim_factor > 1:
            filtered = np.convolve(multiplex, self._rbds_decim_filter, mode="same")
            x = fast_decimate(filtered.astype(np.float32), self._rbds_decim_factor)
            sample_rate = self._intermediate_rate
        else:
            x = multiplex.astype(np.float32)
            sample_rate = self._sample_rate
        time.sleep(0)  # Yield GIL

        # Step 2: Frequency shift to baseband (-57 kHz) - PHASE CONTINUOUS
        # CRITICAL FIX: Track carrier phase across calls to avoid discontinuities
        n = len(x)
        phase_increment = 2.0 * np.pi * 57000.0 / sample_rate
        phases = self._carrier_phase_57k + phase_increment * np.arange(n, dtype=np.float64)
        x = x * np.exp(-1j * phases)
        # Update phase for next call (wrap to avoid precision loss)
        self._carrier_phase_57k = (self._carrier_phase_57k + phase_increment * n) % (2.0 * np.pi)
        time.sleep(0)  # Yield GIL

        # Step 3: Lowpass filter (7.5 kHz)
        x = np.convolve(x, self._rbds_lowpass, mode='same')
        time.sleep(0)  # Yield GIL

        # Step 4: Decimate by 10 (if sample rate allows)
        decim = max(1, int(sample_rate / 25000))
        if decim > 1:
            x = x[::decim]
            sample_rate = int(sample_rate // decim)  # Keep as int
        time.sleep(0)  # Yield GIL

        # Step 5: Resample to exactly 19 kHz (16 samples per symbol)
        # Log sample rates periodically for debugging
        if not hasattr(self, '_rate_log_count'):
            self._rate_log_count = 0
        self._rate_log_count += 1
        if self._rate_log_count % 100 == 1:
            logger.debug(
                "RBDS rates: input=%d, post-decim=%d, resampling %d->19000, samples=%d",
                self._sample_rate, sample_rate, sample_rate, len(x)
            )
        x = self._resample(x, sample_rate, 19000)
        time.sleep(0)  # Yield GIL

        if len(x) < 48:  # Need enough samples for M&M
            return self._decode_rbds_groups()

        # Step 6: M&M Symbol Timing (FIRST per PySDR!)
        n_before = len(x)
        x = self._mm_timing_pysdr(x)
        time.sleep(0)  # Yield GIL
        logger.debug("RBDS M&M: %d samples -> %d symbols", n_before, len(x))

        if len(x) < 2:
            return self._decode_rbds_groups()

        # Step 7: Costas Loop (SECOND per PySDR!)
        x = self._costas_pysdr(x)
        time.sleep(0)  # Yield GIL

        # Log Costas frequency offset to check if it's locked
        if hasattr(self, '_costas_log_count'):
            self._costas_log_count += 1
        else:
            self._costas_log_count = 0
        if self._costas_log_count % 50 == 0:
            logger.debug(
                "RBDS Costas: freq=%.3f Hz, phase=%.2f rad",
                self._rbds_costas_freq * 1187.5 / (2 * np.pi),  # Convert to Hz
                self._rbds_costas_phase
            )

        # Step 8: BPSK demod + differential decode (EN 62106 standard)
        # Differential: d[i] = d[i-1] XOR a[i], so a[i] = d[i] XOR d[i-1]
        # Per EN 62106: different symbols → bit 1, same symbols → bit 0
        bits_raw = (np.real(x) > 0).astype(np.int8)

        if len(bits_raw) > 0:
            # CRITICAL: Prepend last symbol from previous chunk for continuity
            # Use same comparison (> 0) as bits_raw for consistency
            prev_sym = 1 if self._rbds_prev_symbol > 0 else 0
            all_symbols = np.concatenate(([prev_sym], bits_raw))

            # Per EN 62106: different = 1, same = 0
            diff = (all_symbols[1:] != all_symbols[:-1]).astype(np.int8)

            # Save last SAMPLE value for next chunk continuity
            self._rbds_prev_symbol = float(np.real(x[-1]))

            n_bits = len(diff)
            n_ones = int(np.sum(diff))
            if n_bits > 0:
                logger.debug(
                    "RBDS bits: %d new bits, %d ones (%.1f%%), buffer=%d",
                    n_bits, n_ones, 100.0 * n_ones / n_bits, len(self._rbds_bit_buffer)
                )
            self._rbds_bit_buffer.extend(diff.tolist())

        return self._decode_rbds_groups()

    def _mm_timing_pysdr(self, samples: np.ndarray) -> np.ndarray:
        """M&M symbol timing with proper state continuity across calls.

        Uses linear interpolation and maintains state for continuous processing.
        CRITICAL: Tracks residual position to maintain timing across chunk boundaries.
        """
        n = len(samples)
        if n < 32:
            return samples

        sps = 16  # samples per symbol at 19kHz
        mu = self._rbds_mm_mu

        # Pre-extract real/imag to avoid repeated attribute access
        samples_real = samples.real
        samples_imag = samples.imag

        # Pre-allocate output array (faster than list append)
        max_symbols = n // sps + 10
        out_array = np.empty(max_symbols, dtype=np.complex64)
        n_out = 0

        # Initialize with state from previous call
        prev_out_0, prev_out_1 = self._rbds_mm_last_out
        prev_rail_0, prev_rail_1 = self._rbds_mm_last_rail

        # CRITICAL: Start from residual position from previous chunk
        i_in = self._rbds_mm_i_residual

        while i_in < n - 1 and n_out < max_symbols:
            idx = int(i_in)
            frac = i_in - idx

            if idx + 1 >= n:
                break

            # Linear interpolation
            re = samples_real[idx] + frac * (samples_real[idx + 1] - samples_real[idx])
            im = samples_imag[idx] + frac * (samples_imag[idx + 1] - samples_imag[idx])

            # Hard decision (rail) - use simple comparison
            rail_re = 1.0 if re > 0 else -1.0
            rail_im = 1.0 if im > 0 else -1.0

            # M&M timing error (simplified - avoid complex conjugate overhead)
            # For BPSK, we only care about real part anyway
            mm_val = ((re - prev_out_0.real) * prev_rail_1.real -
                      (rail_re - prev_rail_0.real) * prev_out_1.real)

            # Update timing with clamping
            mu += 0.01 * mm_val
            if mu > 0.5:
                mu = 0.5
            elif mu < -0.5:
                mu = -0.5

            # Store output
            out_sample = complex(re, im)
            out_array[n_out] = out_sample
            n_out += 1

            # Shift history (avoid creating new complex objects)
            prev_out_0 = prev_out_1
            prev_out_1 = out_sample
            prev_rail_0 = prev_rail_1
            prev_rail_1 = complex(rail_re, rail_im)

            # Advance by one symbol period
            i_in += sps + mu

        # Save state for next call
        self._rbds_mm_mu = mu
        self._rbds_mm_last_out = [prev_out_0, prev_out_1]
        self._rbds_mm_last_rail = [prev_rail_0, prev_rail_1]
        # Save residual: how far past the end of this chunk we are
        self._rbds_mm_i_residual = i_in - n if i_in >= n else 0.0

        return out_array[:n_out] if n_out > 0 else np.array([], dtype=np.complex64)

    def _costas_pysdr(self, samples: np.ndarray) -> np.ndarray:
        """Costas loop for BPSK carrier/phase synchronization.

        Uses correct loop parameters derived from loop bandwidth equations.
        alpha and beta are set in _init_rbds_state (0.132 and 0.00932).

        Uses numba JIT when available, otherwise optimized Python with GIL yields.
        """
        n = len(samples)
        if n == 0:
            return samples

        # Use the correctly computed loop parameters from init
        alpha = self._rbds_costas_alpha  # 0.132
        beta = self._rbds_costas_beta    # 0.00932

        # Use JIT-compiled version if numba is available (50-100x faster)
        if _NUMBA_AVAILABLE and n > 50:
            samples_f64 = samples.astype(np.complex128)
            out_real, out_imag, phase, freq = _costas_loop_numba(
                samples_f64.real.astype(np.float64),
                samples_f64.imag.astype(np.float64),
                self._rbds_costas_phase,
                self._rbds_costas_freq,
                alpha,
                beta
            )
            self._rbds_costas_phase = phase
            self._rbds_costas_freq = freq
            return (out_real + 1j * out_imag).astype(np.complex64)

        # Pure Python fallback with GIL yields to prevent audio stalling
        phase = self._rbds_costas_phase
        freq = self._rbds_costas_freq
        two_pi = 6.283185307179586  # Avoid repeated 2*pi calculation

        out = np.empty(n, dtype=np.complex64)
        samples_real = samples.real
        samples_imag = samples.imag

        # Process in batches to yield GIL
        batch_size = 128
        for batch_start in range(0, n, batch_size):
            batch_end = min(batch_start + batch_size, n)
            for i in range(batch_start, batch_end):
                cos_phase = math.cos(phase)
                sin_phase = math.sin(phase)

                s_re = samples_real[i]
                s_im = samples_imag[i]
                out_real = s_re * cos_phase + s_im * sin_phase
                out_imag = s_im * cos_phase - s_re * sin_phase
                out[i] = complex(out_real, out_imag)

                error = out_real * out_imag
                freq += beta * error
                phase += freq + alpha * error

                # Wrap phase
                while phase >= two_pi:
                    phase -= two_pi
                while phase < 0:
                    phase += two_pi

            # Yield GIL between batches
            time.sleep(0)

        self._rbds_costas_phase = phase
        self._rbds_costas_freq = freq
        return out

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Resample signal - handles both real and complex signals."""
        if from_rate == to_rate:
            return signal
        try:
            from scipy import signal as scipy_signal
            import math
            gcd = math.gcd(int(from_rate), int(to_rate))
            up = int(to_rate // gcd)
            down = int(from_rate // gcd)
            return scipy_signal.resample_poly(signal, up, down).astype(signal.dtype)
        except ImportError:
            ratio = to_rate / from_rate
            new_length = int(len(signal) * ratio)
            old_indices = np.arange(len(signal))
            new_indices = np.linspace(0, len(signal) - 1, new_length)
            # CRITICAL FIX: Handle complex signals properly
            if np.iscomplexobj(signal):
                real_resampled = np.interp(new_indices, old_indices, np.real(signal))
                imag_resampled = np.interp(new_indices, old_indices, np.imag(signal))
                return (real_resampled + 1j * imag_resampled).astype(signal.dtype)
            else:
                return np.interp(new_indices, old_indices, signal).astype(signal.dtype)

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

                # Yield GIL between batches to let audio thread run
                time.sleep(0)

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
            # RBDS differential decoding: "1" = same phase, "0" = phase change (EN 62106)
            bit = 1 if symbol == prev_symbol else 0
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
        """Decode RBDS groups from bit buffer."""
        changed = False
        iterations = 0
        max_iterations = 100
        consecutive_failures = 0

        while len(self._rbds_bit_buffer) >= 26 and iterations < max_iterations:
            iterations += 1
            block_bits = self._rbds_bit_buffer[:26]
            block_type, data_word = self._decode_rbds_block(block_bits)

            if block_type is None:
                self._rbds_consecutive_crc_failures += 1
                consecutive_failures += 1

                if self._rbds_consecutive_crc_failures >= 200:
                    self._rbds_bit_buffer.clear()
                    self._rbds_expected_block = None
                    self._rbds_partial_group.clear()
                    self._rbds_consecutive_crc_failures = 0
                    if self._rbds_synchronized:
                        logger.warning("RBDS SYNC LOST - too many CRC failures")
                        self._rbds_synchronized = False
                    break

                if consecutive_failures > 10:
                    del self._rbds_bit_buffer[:4]
                else:
                    del self._rbds_bit_buffer[0]

                # DON'T reset group state on CRC failure - only shift bits and keep looking
                # Group state should only reset when we find a valid block that's out of sequence
                continue

            self._rbds_consecutive_crc_failures = 0
            consecutive_failures = 0
            logger.debug("RBDS block decoded: type=%s, data=0x%04X", block_type, data_word)

            # SYNCHRONIZATION CHECK: Require A→B confirmation to avoid false positives
            # Random bit positions have ~0.5% chance of false positive CRC match
            if not self._rbds_synchronized:
                if block_type == "A" and len(self._rbds_bit_buffer) >= 52:
                    # Found potential A - check if B follows at exactly 26 bits
                    next_block_bits = list(self._rbds_bit_buffer)[26:52]
                    next_type, next_data = self._decode_rbds_block(next_block_bits)
                    if next_type == "B":
                        # Confirmed A→B sequence - we're synchronized!
                        self._rbds_synchronized = True
                        logger.info("RBDS SYNCHRONIZED! A=0x%04X B=0x%04X", data_word, next_data)
                    else:
                        # False positive A, shift by 1 bit and continue searching
                        del self._rbds_bit_buffer[0]
                        continue
                elif block_type != "A":
                    # Not A, not synchronized - keep searching for A
                    del self._rbds_bit_buffer[0]
                    continue
                else:
                    # Found A but not enough bits to verify B yet
                    return None  # Wait for more bits

            if self._rbds_expected_block is None:
                if block_type != "A":
                    logger.debug("RBDS: found %s but need A to start group, discarding", block_type)
                    del self._rbds_bit_buffer[:26]
                    continue
                self._rbds_partial_group = [data_word]
                self._rbds_expected_block = 1
                logger.debug("RBDS: started group with A=0x%04X, expecting B", data_word)
            else:
                expected_types = {1: ["B"], 2: ["C", "C'"], 3: ["D"]}
                expected_names = {1: "B", 2: "C/C'", 3: "D"}
                if block_type not in expected_types.get(self._rbds_expected_block, []):
                    logger.debug(
                        "RBDS: expected %s but got %s, resetting group",
                        expected_names.get(self._rbds_expected_block, "?"), block_type
                    )
                    self._rbds_expected_block = None
                    self._rbds_partial_group.clear()
                    del self._rbds_bit_buffer[:26]
                    continue
                self._rbds_partial_group.append(data_word)
                self._rbds_expected_block += 1
                logger.debug(
                    "RBDS: got %s=0x%04X, group progress: %d/4",
                    block_type, data_word, len(self._rbds_partial_group)
                )

            del self._rbds_bit_buffer[:26]

            if self._rbds_expected_block >= 4:
                group_changed = self._rbds_decoder.process_group(tuple(self._rbds_partial_group))
                changed = group_changed or changed
                self._rbds_partial_group = []
                self._rbds_expected_block = None

        # Enforce buffer limit
        if len(self._rbds_bit_buffer) > 6000:
            del self._rbds_bit_buffer[:len(self._rbds_bit_buffer) - 6000]

        if changed:
            return self._rbds_decoder.get_current_data()
        return None

    def _decode_rbds_block(self, bits: List[int]) -> Tuple[Optional[str], int]:
        """Decode a 26-bit RBDS block."""
        if len(bits) != 26:
            return None, 0

        # CRC check offsets for each block type
        offsets = {
            "A": 0x0FC,
            "B": 0x198,
            "C": 0x168,
            "C'": 0x350,
            "D": 0x1B4,
        }

        # Extract 16-bit data and 10-bit checkword (MSB first)
        data = 0
        for i in range(16):
            data = (data << 1) | bits[i]

        checkword = 0
        for i in range(16, 26):
            checkword = (checkword << 1) | bits[i]

        # Calculate syndrome
        syndrome = self._crc_syndrome(data, checkword)

        for block_type, offset in offsets.items():
            if syndrome == offset:
                # Track normal match count for diagnostics
                if not hasattr(self, '_normal_match_count'):
                    self._normal_match_count = 0
                    self._inverted_match_count = 0
                self._normal_match_count += 1
                return block_type, data

        # DIAGNOSTIC: Try inverted bits (different differential decode convention)
        # This handles 180° Costas loop phase ambiguity where all symbols are inverted
        inverted_bits = [1 - b for b in bits]
        data_inv = 0
        for i in range(16):
            data_inv = (data_inv << 1) | inverted_bits[i]
        checkword_inv = 0
        for i in range(16, 26):
            checkword_inv = (checkword_inv << 1) | inverted_bits[i]
        syndrome_inv = self._crc_syndrome(data_inv, checkword_inv)

        for block_type, offset in offsets.items():
            if syndrome_inv == offset:
                # Track inverted match count for diagnostics
                if not hasattr(self, '_inverted_match_count'):
                    self._inverted_match_count = 0
                    self._normal_match_count = 0
                self._inverted_match_count += 1

                # Only log warning periodically to avoid spam
                if self._inverted_match_count <= 3 or self._inverted_match_count % 50 == 0:
                    logger.warning(
                        "RBDS: INVERTED bits matched! block=%s data=0x%04X "
                        "(inverted:%d normal:%d) - Costas loop may have 180° phase offset",
                        block_type, data_inv, self._inverted_match_count, self._normal_match_count
                    )
                # Return the inverted result - this is valid data from a phase-inverted Costas lock
                return block_type, data_inv

        # Track normal match for diagnostics (happens in the earlier loop)
        if not hasattr(self, '_normal_match_count'):
            self._normal_match_count = 0
            self._inverted_match_count = 0

        # Debug: log syndrome periodically to see what values we're getting
        if hasattr(self, '_syndrome_log_count'):
            self._syndrome_log_count += 1
        else:
            self._syndrome_log_count = 0
        if self._syndrome_log_count % 100 == 0:
            logger.debug(
                "RBDS syndrome: normal=0x%03X inverted=0x%03X (offsets: A=0x0FC B=0x198 C=0x168 D=0x1B4)",
                syndrome, syndrome_inv
            )

        return None, 0

    def _crc_syndrome(self, data: int, checkword: int) -> int:
        """Calculate CRC syndrome for RBDS.

        Uses CRC-10 with polynomial g(x) = x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1
        For LFSR implementation, we use the polynomial WITHOUT the x^10 term: 0x1B9
        (The x^10 term is implicit in the shift operation)
        """
        reg = 0
        for i in range(15, -1, -1):
            bit = (data >> i) & 1
            fb = (reg >> 9) ^ bit
            reg = ((reg << 1) & 0x3FF) ^ (0x1B9 if fb else 0)

        return reg ^ checkword


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

        # RBDS processing in separate thread (like SDR++)
        # This ensures RBDS NEVER blocks audio processing
        self._rbds_enabled = config.enable_rbds and config.sample_rate >= 114000
        self._rbds_worker: Optional[RBDSWorker] = None
        self._rbds_intermediate_rate = self._intermediate_rate

        if self._rbds_enabled:
            # Calculate intermediate rate for RBDS (preserves 57 kHz subcarrier)
            if config.sample_rate > self._intermediate_rate * 2:
                rbds_decim = config.sample_rate // self._intermediate_rate
                while (config.sample_rate // rbds_decim) < 130000 and rbds_decim > 1:
                    rbds_decim -= 1
                self._rbds_intermediate_rate = config.sample_rate // rbds_decim

            # Create RBDS worker thread - all processing happens there
            self._rbds_worker = RBDSWorker(config.sample_rate, self._rbds_intermediate_rate)
            logger.info(
                "RBDS ENABLED: creating worker thread at %d Hz (input sample_rate=%d Hz)",
                self._rbds_intermediate_rate,
                config.sample_rate
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

        # RBDS carrier phase tracking for coherent demodulation
        self._rbds_carrier_phase: float = 0.0

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
            pilot_filtered = np.convolve(multiplex, self._pilot_filter, mode="same")

            # Measure pilot strength (RMS of filtered signal)
            pilot_rms = np.sqrt(np.mean(pilot_filtered ** 2))
            stereo_pilot_strength = min(1.0, pilot_rms * 10.0)  # Scale to 0-1 range

            # Pilot is considered "locked" if strength exceeds threshold
            stereo_pilot_locked = stereo_pilot_strength > 0.1  # 10% threshold

            if stereo_pilot_locked:
                logger.debug(f"Stereo pilot detected: strength={stereo_pilot_strength:.2f}")

        # RBDS extraction in separate thread (like SDR++)
        # Submit samples to worker (non-blocking) and get latest results
        # 24/7 RELIABILITY: Wrap in try-except to ensure RBDS issues never affect audio
        if self._rbds_enabled and self._rbds_worker:
            try:
                # Submit samples for processing - this is instant and never blocks
                self._rbds_worker.submit_samples(multiplex)
                # Get whatever RBDS data is available (may be from previous chunks)
                rbds_data = self._rbds_worker.get_latest_data()
            except Exception as e:
                # Log but don't let RBDS errors affect audio demodulation
                logger.warning(f"RBDS error (audio unaffected): {e}")

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
                    logger.debug(f"Stereo decoded: {len(stereo_audio)} samples, shape {stereo_audio.shape}")
            except Exception as e:
                logger.warning(f"Stereo decoding error: {e}", exc_info=True)
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
                logger.debug(f"FM demod: No decimation needed, {intermediate_rate}Hz → {target_rate}Hz")

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
        status = DemodulatorStatus(
            rbds_data=rbds_data,
            stereo_pilot_locked=stereo_pilot_locked,
            stereo_pilot_strength=stereo_pilot_strength,
            is_stereo=self._stereo_enabled and stereo_pilot_locked
        )

        return audio.astype(np.float32), status

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Resample signal using polyphase filtering (high quality) or linear interpolation (fallback)."""
        if from_rate == to_rate:
            return signal

        # Try using scipy.signal.resample_poly for high-quality resampling
        # This is critical for SDR demodulation to avoid aliasing artifacts
        try:
            from scipy import signal as scipy_signal
            import math
            
            # Calculate integer ratio for polyphase resampling
            gcd = math.gcd(int(from_rate), int(to_rate))
            up = int(to_rate // gcd)
            down = int(from_rate // gcd)
            
            # Use resample_poly which applies an anti-aliasing filter
            if signal.ndim == 1:
                return scipy_signal.resample_poly(signal, up, down).astype(signal.dtype)
            else:
                return scipy_signal.resample_poly(signal, up, down, axis=0).astype(signal.dtype)
        except ImportError:
            # Fallback to linear interpolation if scipy is not available
            pass

        ratio = to_rate / from_rate
        new_length = int(len(signal) * ratio)
        old_indices = np.arange(len(signal))
        new_indices = np.linspace(0, len(signal) - 1, new_length)

        if signal.ndim == 1:
            return np.interp(new_indices, old_indices, signal).astype(signal.dtype)

        channels = []
        for ch in range(signal.shape[1]):
            channel_data = signal[:, ch]
            channels.append(np.interp(new_indices, old_indices, channel_data))
        return np.column_stack(channels).astype(signal.dtype)

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

    def _design_fir_lowpass(self, cutoff: float, fs: int, taps: int = 129) -> np.ndarray:
        """Design a FIR lowpass filter using windowed sinc method.

        Args:
            cutoff: Cutoff frequency in Hz
            fs: Sample rate in Hz
            taps: Number of filter taps (should be odd)

        Returns:
            Filter coefficients as float32 numpy array
        """
        nyquist = fs / 2.0
        norm_cutoff = min(cutoff / nyquist, 0.99)

        # Ensure odd number of taps for symmetric filter
        taps = taps | 1

        indices = np.arange(taps) - (taps - 1) / 2.0

        # Handle center sample to avoid division by zero in sinc
        with np.errstate(divide='ignore', invalid='ignore'):
            sinc = np.sinc(norm_cutoff * indices)

        # Blackman window has better stopband attenuation than Hamming
        window = np.blackman(taps)
        kernel = norm_cutoff * sinc * window

        # Normalize for unity DC gain
        kernel_sum = np.sum(kernel)
        if kernel_sum != 0:
            kernel /= kernel_sum

        return kernel.astype(np.float32)

    def _design_fir_bandpass(self, low_cut: float, high_cut: float, fs: int, taps: int = 129) -> np.ndarray:
        """Design a FIR bandpass filter.

        Args:
            low_cut: Lower cutoff frequency in Hz
            high_cut: Upper cutoff frequency in Hz
            fs: Sample rate in Hz
            taps: Number of filter taps (should be odd)

        Returns:
            Filter coefficients as float32 numpy array
        """
        # Bandpass = lowpass(high) - lowpass(low)
        low = self._design_fir_lowpass(high_cut, fs, taps)
        high = self._design_fir_lowpass(low_cut, fs, taps)
        kernel = low - high
        return kernel.astype(np.float32)

    def _lpr_filter_signal(self, signal: np.ndarray) -> np.ndarray:
        filtered = np.convolve(signal, self._lpr_filter, mode="same")
        return filtered

    def _decode_stereo(self, multiplex: np.ndarray, sample_indices: np.ndarray) -> Optional[np.ndarray]:
        """Decode FM stereo from multiplex signal.

        Uses the 19 kHz pilot tone to generate a coherent 38 kHz carrier for
        demodulating the L-R stereo difference signal.

        Args:
            multiplex: FM multiplex signal (after discriminator)
            sample_indices: Sample indices at intermediate rate

        Returns:
            Stereo audio as Nx2 array (left, right) or None if stereo disabled
        """
        if not self._stereo_enabled or len(multiplex) == 0:
            return None

        # Extract L+R (mono) using lowpass filter
        lpr = np.convolve(multiplex, self._lpr_filter, mode="same")

        # Generate 38 kHz carrier using time at ORIGINAL sample rate
        # CRITICAL FIX: The multiplex signal is at original SDR rate, not intermediate rate
        # The carrier must be coherent with the 19 kHz pilot (doubled)
        time = sample_indices / float(self.config.sample_rate)

        # Try to extract pilot tone and lock to it for better carrier coherence
        # For now, use a synthetic carrier (can be improved with PLL later)
        pilot_filtered = np.convolve(multiplex, self._pilot_filter, mode="same")

        # Generate 38 kHz carrier from pilot (pilot is at 19 kHz)
        # Use analytical signal approach: pilot × 2 for phase doubling
        carrier = 2.0 * np.cos(2.0 * np.pi * 38000.0 * time)

        # Demodulate L-R signal by mixing with 38 kHz carrier
        suppressed = multiplex * carrier
        lmr = np.convolve(suppressed, self._dsb_filter, mode="same")

        # Matrix decode: L = (L+R) + (L-R), R = (L+R) - (L-R)
        # Scale by 0.5 to normalize
        left = 0.5 * (lpr + lmr)
        right = 0.5 * (lpr - lmr)

        stereo = np.column_stack((left, right))
        return stereo

    def _extract_rbds(self, multiplex: np.ndarray, sample_indices: np.ndarray) -> Optional[RBDSData]:
        if not self._rbds_enabled or len(multiplex) == 0:
            logger.debug(f"RBDS extraction skipped: enabled={self._rbds_enabled}, multiplex_len={len(multiplex)}")
            return None

        # Step 1: Decimate to intermediate rate for practical filter design
        # High sample rates (2.5 MHz) require too many taps for narrow 54-60 kHz bandpass
        if self._rbds_decim_filter is not None and self._rbds_decim_factor > 1:
            # Apply anti-aliasing filter and decimate
            filtered = np.convolve(multiplex, self._rbds_decim_filter, mode="same")
            rbds_signal = fast_decimate(filtered.astype(np.float32), self._rbds_decim_factor)
            rbds_rate = self._rbds_intermediate_rate
        else:
            rbds_signal = multiplex
            rbds_rate = self.config.sample_rate

        # Step 2: Bandpass filter for 54-60 kHz RBDS subcarrier (now at practical rate)
        rbds_band = np.convolve(rbds_signal, self._rbds_bandpass, mode="same")

        # CRITICAL FIX: Check signal quality before extracting symbols
        # If signal is too weak, don't add garbage to the bit buffer
        rbds_rms = np.sqrt(np.mean(rbds_band ** 2))

        # Adaptive threshold based on multiplex signal level
        multiplex_rms = np.sqrt(np.mean(multiplex ** 2))
        # RBDS is typically -20dB to -25dB below the main audio, so ~1/10 to 1/20 of the level
        # Use a threshold relative to the multiplex signal
        signal_threshold = multiplex_rms * 0.01  # RBDS should be at least 1% of multiplex RMS

        if rbds_rms < signal_threshold:
            # Signal too weak - likely no RBDS on this station
            # Don't extract symbols (would just be noise)
            logger.debug(f"RBDS signal too weak: {rbds_rms:.6f} < threshold {signal_threshold:.6f}")
            return self._decode_rbds_groups()  # Still process existing buffer

        if rbds_rms > 0.001:  # Log if there's measurable signal
            logger.debug(f"RBDS band signal RMS: {rbds_rms:.6f} at {rbds_rate}Hz")

        # Step 3: Mix down to baseband using 57 kHz carrier with PHASE CONTINUITY
        # CRITICAL FIX: Use the ACTUAL sample rate (rbds_rate) for time calculation,
        # not config.sample_rate which may be before decimation!
        num_samples = len(rbds_band)
        time = np.arange(num_samples, dtype=np.float64) / float(rbds_rate)
        carrier_phase = 2.0 * np.pi * 57000.0 * time + self._rbds_carrier_phase
        baseband = rbds_band * np.exp(-1j * carrier_phase)

        # Update carrier phase for next chunk (maintain continuity)
        self._rbds_carrier_phase = (self._rbds_carrier_phase + 2.0 * np.pi * 57000.0 * num_samples / rbds_rate) % (2.0 * np.pi)

        # Step 4: Lowpass filter baseband (matched filter + anti-alias)
        baseband_filtered = np.convolve(baseband, self._rbds_lowpass, mode="same")

        # Step 5: Resample to 19 kHz (16 samples per symbol) for robust clock recovery
        resampled = self._resample(
            baseband_filtered,
            rbds_rate,
            int(self._rbds_target_rate),
        )

        if len(resampled) < self._rbds_samples_per_symbol * 2:
            return self._decode_rbds_groups()

        # Step 6: Costas loop for fine frequency synchronization (BPSK)
        # This corrects any residual frequency offset from the 57 kHz mixing
        synced = self._rbds_costas_loop(resampled)

        # Step 7: Mueller and Muller clock recovery
        # Extracts symbols at optimal timing points
        bits = self._rbds_mm_clock_recovery(synced)

        if bits:
            self._rbds_bit_buffer.extend(bits)
            # Periodically log bit buffer status at INFO level for visibility
            if len(self._rbds_bit_buffer) % 520 == 0:  # ~20 blocks worth
                logger.info(f"RBDS processing: {len(self._rbds_bit_buffer)} bits in buffer, {len(bits)} new bits")

        return self._decode_rbds_groups()

    def _decode_rbds_groups(self) -> Optional[RBDSData]:
        """Decode RBDS groups from bit buffer with bounded execution time.

        CRITICAL FIX: This method now has multiple safeguards to prevent blocking:
        1. Maximum iterations per call (prevents infinite loops on garbage data)
        2. Buffer size limit (prevents unbounded memory growth)
        3. Consecutive failure detection (clears buffer when no RBDS signal)
        4. Aggressive garbage cleanup (removes multiple bits on repeated failures)
        """
        changed = False
        blocks_checked = 0
        blocks_valid = 0
        iterations = 0
        consecutive_failures_this_call = 0

        # CRITICAL FIX: Limit iterations to prevent blocking audio thread
        while len(self._rbds_bit_buffer) >= 26 and iterations < self._rbds_max_decode_iterations:
            iterations += 1
            block_bits = self._rbds_bit_buffer[:26]
            block_type, data_word = self._decode_rbds_block(block_bits)
            blocks_checked += 1

            if block_type is None:
                # CRC failed - no valid block at this position
                self._rbds_consecutive_crc_failures += 1
                consecutive_failures_this_call += 1

                # CRITICAL FIX: If too many consecutive failures, likely no RBDS signal
                # Clear buffer aggressively to prevent CPU waste
                if self._rbds_consecutive_crc_failures >= self._rbds_max_consecutive_failures:
                    logger.debug(
                        f"RBDS: {self._rbds_consecutive_crc_failures} consecutive CRC failures, "
                        f"clearing buffer ({len(self._rbds_bit_buffer)} bits) - station may not have RBDS"
                    )
                    self._rbds_bit_buffer.clear()
                    self._rbds_expected_block = None
                    self._rbds_partial_group.clear()
                    self._rbds_consecutive_crc_failures = 0
                    break

                # CRITICAL FIX: If many failures in this call, skip multiple bits
                # This speeds up scanning through garbage data
                if consecutive_failures_this_call > 10:
                    # Skip 4 bits at a time after many failures (faster scanning)
                    skip_count = min(4, len(self._rbds_bit_buffer))
                    del self._rbds_bit_buffer[:skip_count]
                else:
                    # Normal case: shift by 1 bit to search for sync
                    del self._rbds_bit_buffer[0]

                self._rbds_expected_block = None
                self._rbds_partial_group.clear()
                continue

            # Valid block found - reset failure counter
            blocks_valid += 1
            self._rbds_consecutive_crc_failures = 0
            consecutive_failures_this_call = 0
            logger.debug(f"RBDS block detected: type={block_type}, data=0x{data_word:04X}")

            if self._rbds_expected_block is None:
                if block_type != "A":
                    # Valid block but not A - consume it to maintain sync
                    del self._rbds_bit_buffer[:26]
                    continue
                self._rbds_partial_group = [data_word]
                self._rbds_expected_block = 1
                del self._rbds_bit_buffer[:26]
                continue

            sequence = ["A", "B", "C", "D"]
            expected = sequence[self._rbds_expected_block]
            if expected == "C" and block_type == "C":
                pass
            elif block_type == "A":
                # New group starting - use this A block to start fresh
                del self._rbds_bit_buffer[:26]
                self._rbds_partial_group = [data_word]
                self._rbds_expected_block = 1
                continue
            elif expected != block_type:
                # Valid block but wrong type - consume it to maintain sync
                self._rbds_expected_block = None
                self._rbds_partial_group.clear()
                del self._rbds_bit_buffer[:26]
                continue

            self._rbds_partial_group.append(data_word)
            self._rbds_expected_block += 1
            del self._rbds_bit_buffer[:26]

            if self._rbds_expected_block >= 4:
                logger.info(f"RBDS complete group decoded: {[hex(w) for w in self._rbds_partial_group]}")
                group_changed = self._rbds_decoder.process_group(tuple(self._rbds_partial_group))
                changed = group_changed or changed
                self._rbds_partial_group = []
                self._rbds_expected_block = None

        # CRITICAL FIX: Enforce buffer size limit to prevent unbounded growth
        if len(self._rbds_bit_buffer) > self._rbds_bit_buffer_max_size:
            excess = len(self._rbds_bit_buffer) - self._rbds_bit_buffer_max_size
            del self._rbds_bit_buffer[:excess]
            logger.debug(f"RBDS: Trimmed {excess} old bits from buffer (limit: {self._rbds_bit_buffer_max_size})")

        # Log summary of block decoding attempts (rate-limited)
        if blocks_checked > 50:
            success_rate = (100 * blocks_valid / blocks_checked) if blocks_checked > 0 else 0
            logger.debug(
                f"RBDS decode: {blocks_valid}/{blocks_checked} valid ({success_rate:.1f}%), "
                f"buffer: {len(self._rbds_bit_buffer)} bits, iterations: {iterations}"
            )

        if changed:
            return self._rbds_decoder.get_current_data()
        return None

    def _rbds_costas_loop(self, samples: np.ndarray) -> np.ndarray:
        """Apply Costas loop for BPSK frequency synchronization.

        Uses JIT-compiled function when Numba is available for ~50-100x speedup.
        This was the main bottleneck causing audio stalling.

        Args:
            samples: Complex baseband samples after filtering

        Returns:
            Frequency-synchronized complex samples
        """
        n = len(samples)
        if n == 0:
            return samples

        if _NUMBA_AVAILABLE and n > 50:
            # Use JIT-compiled version (50-100x faster)
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
            # Pure Python fallback (slow but always works)
            out = np.empty(n, dtype=np.complex128)
            phase = self._rbds_costas_phase
            freq = self._rbds_costas_freq
            alpha = self._rbds_costas_alpha
            beta = self._rbds_costas_beta
            two_pi = 2.0 * np.pi

            for i in range(n):
                cos_phase = np.cos(phase)
                sin_phase = np.sin(phase)
                s = samples[i]
                out[i] = complex(s.real * cos_phase + s.imag * sin_phase,
                                s.imag * cos_phase - s.real * sin_phase)
                error = out[i].real * out[i].imag
                freq += beta * error
                phase += freq + alpha * error
                if phase >= two_pi or phase < 0:
                    phase = phase % two_pi

            self._rbds_costas_phase = phase
            self._rbds_costas_freq = freq
            return out

    def _rbds_mm_clock_recovery(self, samples: np.ndarray) -> List[int]:
        """Mueller and Muller clock recovery for RBDS symbol timing.

        PERFORMANCE FIX: Simplified implementation using linear interpolation only.
        Filter creation moved to __init__ to avoid repeated allocation.

        Args:
            samples: Frequency-synchronized complex samples from Costas loop

        Returns:
            List of decoded bits (differentially decoded)
        """
        n = len(samples)
        if n < 32:  # Need at least 2 symbols worth
            return []

        sps = self._rbds_samples_per_symbol  # 16

        bits: List[int] = []

        # Local variables for speed
        mu = self._rbds_mm_mu
        out_rail = self._rbds_mm_out_rail
        out = self._rbds_mm_out
        prev_symbol = self._rbds_prev_symbol

        i = 0
        max_symbols = n // sps + 5

        for _ in range(max_symbols):
            if i + sps >= n:
                break

            # Linear interpolation at position i + mu
            idx = int(i + mu)
            if idx >= n - 1:
                break

            frac = (i + mu) - idx
            # Get real part directly for BPSK
            s0_real = samples[idx].real
            s1_real = samples[idx + 1].real
            out_new = s0_real * (1.0 - frac) + s1_real * frac

            # Rail quantization
            out_rail_new = 1.0 if out_new > 0.0 else -1.0

            # M&M timing error
            timing_error = (out_rail * out_new) - (out_rail_new * out)

            # Update state
            out = out_new
            out_rail = out_rail_new

            # Differential BPSK decode inline (avoid function call overhead)
            # RBDS: "1" = same phase, "0" = phase change (EN 62106)
            symbol = 1.0 if out_new >= 0 else -1.0
            bit = 1 if symbol == prev_symbol else 0
            prev_symbol = symbol
            bits.append(bit)

            # Update timing with clamped adjustment
            adjustment = 0.02 * timing_error
            if adjustment > sps * 0.5:
                adjustment = sps * 0.5
            elif adjustment < -sps * 0.5:
                adjustment = -sps * 0.5

            mu = mu + sps + adjustment

            # Keep mu in [0, 1) range
            while mu >= 1.0:
                mu -= 1.0
                i += 1
            while mu < 0.0:
                mu += 1.0
                i -= 1

            i += sps

        # Save state
        self._rbds_mm_mu = mu
        self._rbds_mm_out_rail = out_rail
        self._rbds_mm_out = out
        self._rbds_prev_symbol = prev_symbol

        return bits

    def _rbds_symbol_to_bit(self, sample: float) -> int:
        """Decode a differentially-encoded RBDS symbol into a data bit."""

        symbol = 1.0 if sample >= 0 else -1.0
        previous = self._rbds_prev_symbol
        self._rbds_prev_symbol = symbol

        if previous is None:
            return 0

        # Differential BPSK: bit=0 when polarity stays the same, 1 when it flips
        return 0 if symbol == previous else 1

    def _decode_rbds_block(self, bits: List[int]) -> Tuple[Optional[str], Optional[int]]:
        value = 0
        for bit in bits:
            value = (value << 1) | int(bit)

        data_word = value >> 10
        check_word = value & 0x3FF

        remainder = self._rbds_crc(data_word << 10)
        syndrome = remainder ^ check_word

        offset_map = {
            0x0FC: "A",
            0x198: "B",
            0x168: "C",
            0x350: "C",
            0x1B4: "D",
        }
        block_type = offset_map.get(syndrome)
        if block_type is None:
            return None, None
        return block_type, data_word

    def _rbds_crc(self, value: int) -> int:
        polynomial = 0b11101101001
        for bit in range(value.bit_length() - 1, 9, -1):
            if value & (1 << bit):
                value ^= polynomial << (bit - 10)
        return value & 0x3FF


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

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if from_rate == to_rate:
            return signal

        ratio = to_rate / from_rate
        new_length = int(len(signal) * ratio)
        old_indices = np.arange(len(signal))
        new_indices = np.linspace(0, len(signal) - 1, new_length)

        return np.interp(new_indices, old_indices, signal)


class RBDSDecoder:
    """
    RBDS/RDS decoder for FM radio.

    Decodes Program Service name, Radio Text, and other metadata from the
    57kHz RBDS subcarrier in FM broadcasts.
    """

    def __init__(self):
        self.pi_code = None
        self.ps_name = [' '] * 8  # 8 characters
        self.radio_text = [' '] * 64  # 64 characters
        self.pty = None
        self.tp = None
        self.ta = None
        self.ms = None
        self._radio_text_ab = 0
        # Track which PS segments (0-3) have been received to avoid reporting partial data
        self._ps_segments_received = set()

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

        # Log raw block values for debugging - helps diagnose data extraction issues
        group_type = (b >> 12) & 0xF
        version_b = bool((b >> 11) & 0x1)
        logger.debug(
            "RBDS group: A=%04X B=%04X C=%04X D=%04X (type=%d%s)",
            a, b, c, d, group_type, "B" if version_b else "A"
        )

        pi_code = f"{a:04X}"
        if self.pi_code != pi_code:
            self.pi_code = pi_code
            changed = True

        pty = (b >> 5) & 0x1F
        if self.pty != pty:
            self.pty = pty
            changed = True

        tp = bool((b >> 10) & 0x1)
        if self.tp != tp:
            self.tp = tp
            changed = True

        ta = bool((b >> 4) & 0x1)
        if self.ta != ta:
            self.ta = ta
            changed = True

        ms = bool((b >> 3) & 0x1)
        if self.ms != ms:
            self.ms = ms
            changed = True

        group_type = (b >> 12) & 0xF
        version_b = bool((b >> 11) & 0x1)

        if group_type == 0:
            address = b & 0x3
            chars = d
            changed = self._update_ps_name(address, chars) or changed
        elif group_type == 2:
            text_segment = b & 0xF
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._radio_text_ab:
                self._radio_text_ab = ab_flag
                self.radio_text = [' '] * 64
                changed = True

            if not version_b:
                blocks = (c, d)
                for offset, block in enumerate(blocks):
                    chars = [
                        (block >> 8) & 0x7F,
                        block & 0x7F,
                    ]
                    for i, code in enumerate(chars):
                        idx = text_segment * 4 + offset * 2 + i
                        if idx < len(self.radio_text):
                            if self._update_radio_text(idx, code):
                                changed = True
            else:
                chars = [(d >> 8) & 0x7F, d & 0x7F]
                for i, code in enumerate(chars):
                    idx = text_segment * 2 + i
                    if idx < len(self.radio_text):
                        if self._update_radio_text(idx, code):
                            changed = True

        return changed

    def get_current_data(self) -> RBDSData:
        """Get the currently decoded RBDS data."""
        return RBDSData(
            pi_code=self.pi_code,
            ps_name=''.join(self.ps_name).strip(),
            radio_text=''.join(self.radio_text).strip(),
            pty=self.pty,
            tp=self.tp,
            ta=self.ta,
            ms=self.ms
        )

    def _update_ps_name(self, address: int, chars: int) -> bool:
        idx = address * 2
        updated = False
        for offset in range(2):
            char_code = (chars >> (8 * (1 - offset))) & 0xFF
            if 32 <= char_code < 127:
                char = chr(char_code)
            else:
                char = ' '
            pos = idx + offset
            if pos < len(self.ps_name) and self.ps_name[pos] != char:
                logger.debug(
                    "RBDS PS: pos=%d char='%s' (0x%02X) from D=0x%04X addr=%d",
                    pos, char, char_code, chars, address
                )
                self.ps_name[pos] = char
                updated = True
        
        # Track that this segment was received
        self._ps_segments_received.add(address)
        
        # Only report as updated if all 4 segments (0-3) have been received at least once
        # This prevents reporting partial/garbage PS names like "0io" before full name arrives
        if len(self._ps_segments_received) < 4:
            logger.debug(
                "RBDS PS: segment %d received, waiting for all 4 segments (have %d/4)",
                address, len(self._ps_segments_received)
            )
            return False  # Don't report as changed until all segments received
        
        return updated

    def _update_radio_text(self, index: int, code: int) -> bool:
        if index >= len(self.radio_text):
            return False
        char = chr(code) if 32 <= code < 127 else ' '
        if self.radio_text[index] != char:
            self.radio_text[index] = char
            return True
        return False


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
