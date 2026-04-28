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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

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
    pi_code: Optional[str] = None  # Program Identification (raw 16-bit hex)
    call_sign: Optional[str] = None  # Decoded US call letters (e.g. "WXYZ"), if PI is US
    ps_name: Optional[str] = None  # Program Service name (8 chars)
    pty_name: Optional[str] = None  # Program Type Name (PTYN, 8 chars, Group 10A)
    radio_text: Optional[str] = None  # Radio Text (up to 64 chars)
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


class RBDSWorker:
    """Threaded RBDS processor - processes RBDS in background without blocking audio.

    Like SDR++, RBDS runs in its own thread. Audio demodulation drops samples
    into a queue; the worker processes them independently and publishes results.
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

        # Lowpass filter for post-mixing (removes aliases, keeps baseband RBDS at 0-7.5 kHz)
        # Design this at sample_rate since we mix BEFORE lowpass filtering.
        # Bumped to 301 taps from 101: at 256 kHz input the 101-tap version
        # had a ~2.5 kHz transition and a sidelobe shoulder near -40 dB,
        # which let pilot/stereo-subcarrier energy bleed into the post-mix
        # baseband and was the most plausible cause of M&M / Costas failing
        # to settle on a real broadcast.  301 taps cuts the transition to
        # ~800 Hz and lifts the stopband attenuation, at the cost of a few
        # extra ms of per-batch convolution.
        self._rbds_lowpass = self._design_fir_lowpass(7500.0, self._sample_rate, taps=301)

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
        """Design FIR bandpass filter with unity gain at the passband centre.

        The filter is built as the difference of two windowed-sinc lowpass
        prototypes.  Normalising by max(|h|) — the old approach — does NOT
        guarantee passband unity gain because the centre tap of a bandpass
        impulse response is zero; the actual passband gain depends on the
        filter bandwidth and could be many dB away from 0 dB.  Correct
        normalisation evaluates |H(f_centre)| in the frequency domain and
        divides by that value, ensuring |H(f_centre)| = 1.
        """
        fc_low  = low  / sample_rate
        fc_high = high / sample_rate
        n = np.arange(taps, dtype=np.float64)
        mid = (taps - 1) / 2.0
        h_high = np.sinc(2 * fc_high * (n - mid))
        h_low  = np.sinc(2 * fc_low  * (n - mid))
        h = h_high - h_low
        h *= np.blackman(taps)
        # Normalise so |H(f_centre)| = 1
        fc_centre = (fc_low + fc_high) / 2.0
        h_at_centre = float(np.abs(np.sum(h * np.exp(-1j * 2.0 * np.pi * fc_centre * (n - mid)))))
        if h_at_centre > 1e-9:
            h /= h_at_centre
        return h.astype(np.float32)

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
        if n < 32768:
            return None
        # Cap the FFT size for speed.  For typical 250 ms chunks at 250 kHz
        # (62 500 samples) this rounds to 65 536; longer captures get better
        # resolution but we don't need it.
        n_fft = min(1 << int(np.ceil(np.log2(n))), 1 << 18)
        if n_fft > n:
            n_fft = 1 << int(np.floor(np.log2(n)))
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
            a, b, c = float(spectrum[idx - 1]), float(spectrum[idx]), float(spectrum[idx + 1])
            denom = a - 2.0 * b + c
            delta = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
            peak_hz = float(freqs[idx]) + delta * (freqs[1] - freqs[0])
        else:
            peak_hz = float(freqs[idx])
        # Sanity check: the peak amplitude must clearly exceed the surrounding
        # noise floor in the search band, otherwise we're locking onto stereo
        # subcarrier sidebands or noise on a mono station.
        band = spectrum[mask]
        median = float(np.median(band))
        if median > 0 and float(spectrum[idx]) < 4.0 * median:
            return None
        # Reject obvious nonsense (peak more than 200 ppm off nominal would
        # mean a broken SDR; trust the hard-coded 19000 Hz fallback instead).
        if abs(peak_hz - 19000.0) > 4.0:
            return None
        return peak_hz

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
            # This is expected and fine - RBDS is lower priority than audio
            pass

    def get_latest_data(self) -> Optional[RBDSData]:
        """Get the latest RBDS data (thread-safe)."""
        with self._data_lock:
            return self._latest_data

    def is_synced(self) -> bool:
        """Whether the RBDS bit-level sync state machine has locked."""
        return bool(getattr(self, '_rbds_synced', False))

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

                # Yield GIL after processing each sample to let audio thread run
                # Critical when Numba isn't available and RBDS processing is slow
                time.sleep(0)
            except Exception as e:
                logger.warning(f"RBDS processing error: {e}", exc_info=True)

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
        time.sleep(0)  # Yield GIL

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
                ppm = (measured - 19000.0) / 19000.0 * 1e6
                logger.info(
                    "RBDS pilot measured: %.3f Hz (offset %+0.3f Hz, %+.1f ppm SDR clock error). "
                    "57 kHz reference will be %.3f Hz.",
                    measured,
                    measured - 19000.0,
                    ppm,
                    3.0 * measured,
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
            logger.info(f"RBDS Pilot (locked at {pilot_hz:.3f} Hz): multiplex_rms={pilot_rms:.3f}, "
                       f"filtered_rms={pilot_filtered_rms:.3f}, samples={n}, expected_phase={expected_phase:.2f} rad")
        time.sleep(0)  # Yield GIL

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
            time.sleep(0)  # Yield GIL

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
        time.sleep(0)  # Yield GIL

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
        time.sleep(0)  # Yield GIL

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
        time.sleep(0)  # Yield GIL

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
        time.sleep(0)  # Yield GIL

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
        time.sleep(0)  # Yield GIL
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

        # Process all bits in buffer (python-radio style)
        bits = self._rbds_bit_buffer

        for i in range(len(bits)):
            # Use global bit counter for spacing calculations
            global_i = self._rbds_global_bit_counter
            self._rbds_global_bit_counter += 1

            # Shift in next bit (python-radio uses numpy bitwise ops, we use Python ops)
            self._rbds_reg = ((self._rbds_reg << 1) | bits[i]) & 0x3FFFFFF
            
            if not self._rbds_synced:
                # PRESYNC MODE (python-radio logic)
                reg_syndrome = self._calc_syndrome(self._rbds_reg, 26)
                reg_syndrome_inverted = self._calc_syndrome(self._rbds_reg ^ 0x3FFFFFF, 26)
                for j in range(5):
                    polarity: Optional[bool] = None
                    if reg_syndrome == syndrome[j]:
                        polarity = False
                    elif reg_syndrome_inverted == syndrome[j]:
                        polarity = True

                    if polarity is not None:
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
                                break

                            if offset_pos[self._rbds_lastseen_offset] >= offset_pos[j]:
                                block_distance = offset_pos[j] + 4 - offset_pos[self._rbds_lastseen_offset]
                            else:
                                block_distance = offset_pos[j] - offset_pos[self._rbds_lastseen_offset]

                            expected_spacing = block_distance * 26
                            actual_spacing = global_i - self._rbds_lastseen_offset_counter

                            if abs(actual_spacing - expected_spacing) > 4:
                                # Wrong spacing - reset presync and try current block as new first.
                                # Tolerance is ±4 bits (not 0 as in offline python-radio): M&M
                                # symbol timing jitter accumulates ~1 bit per 26-bit block so
                                # over a 78-bit (3-block) span the spacing error reaches ±3-4
                                # bits.  ±2 caused every near-miss to fail (seen in the field
                                # as continuous "expected 78, got 75/82" mismatches with 0
                                # groups decoded).
                                logger.debug(f"RBDS presync spacing mismatch: expected {expected_spacing}, got {actual_spacing}")
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
                                    logger.info(f'RBDS SYNCHRONIZED at bit {global_i}')
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
                                    # Update polarity to match the triggering block so synced-mode
                                    # CRC checks use the correct inversion flag.
                                    self._rbds_inverted_polarity = polarity
                                    self._rbds_synced = True
                        break  # Syndrome found, exit j loop
            
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

                    good_block = False
                    block_word = self._rbds_reg ^ 0x3FFFFFF if self._rbds_inverted_polarity else self._rbds_reg

                    if _crc_ok_for_block(block_word, self._rbds_block_number):
                        good_block = True
                    else:
                        # If current polarity suddenly fails CRC but opposite polarity passes,
                        # recover immediately instead of waiting for a full sync-loss window.
                        alternate_block_word = block_word ^ 0x3FFFFFF
                        if _crc_ok_for_block(alternate_block_word, self._rbds_block_number):
                            self._rbds_inverted_polarity = not self._rbds_inverted_polarity
                            block_word = alternate_block_word
                            good_block = True
                            logger.info(
                                "RBDS polarity flipped while synced; continuing decode (%s polarity)",
                                "inverted" if self._rbds_inverted_polarity else "normal",
                            )
                        else:
                            self._rbds_wrong_blocks_counter += 1

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
                                
                                # Update our RBDSData decoder
                                self._rbds_decoder.process_group((group_0, group_1, group_2, group_3))
                                changed = True
                                
                                logger.info(f"RBDS group: PI=0x{program_identification:04X} type={group_type}")
                    
                    # Reset for next block
                    self._rbds_block_bit_counter = 0
                    self._rbds_block_number = (self._rbds_block_number + 1) % 4
                    self._rbds_blocks_counter += 1
                    
                    # Check sync quality every 50 blocks
                    if self._rbds_blocks_counter == 50:
                        if self._rbds_wrong_blocks_counter > 35:
                            logger.info(f"RBDS SYNC LOST ({self._rbds_wrong_blocks_counter} bad blocks on {self._rbds_blocks_counter} total)")
                            self._rbds_synced = False
                            self._rbds_presync = False
                        else:
                            logger.info(f"RBDS sync OK ({self._rbds_wrong_blocks_counter} bad blocks on {self._rbds_blocks_counter} total)")
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

        This is the standard algorithm from the RDS specification (Annex B).
        Uses polynomial g(x) = x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1 = 0x5B9
        """
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
                # Pass the absolute sample offset so the worker generates the
                # correct crystal-locked 57 kHz carrier phase even when chunks
                # are dropped from the queue (queue overflow discards chunks in
                # the audio thread, so the worker's local counter would lag).
                self._rbds_worker.submit_samples(multiplex, self._sample_index)
                # Get whatever RBDS data is available (may be from previous chunks)
                rbds_data = self._rbds_worker.get_latest_data()
            except Exception as e:
                # Log but don't let RBDS errors affect audio demodulation
                logger.warning(f"RBDS error (audio unaffected): {e}")

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
            is_stereo=self._stereo_enabled and stereo_pilot_locked,
            signal_strength=rf_signal_strength,
            rbds_synced=(
                self._rbds_worker.is_synced()
                if self._rbds_enabled and self._rbds_worker is not None
                else False
            ),
            rbds_enabled=self._rbds_enabled,
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

    def _resample(self, signal: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if from_rate == to_rate:
            return signal

        ratio = to_rate / from_rate
        new_length = int(len(signal) * ratio)
        old_indices = np.arange(len(signal))
        new_indices = np.linspace(0, len(signal) - 1, new_length)

        return np.interp(new_indices, old_indices, signal)


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

            # Bit 2 of Block B carries one of four DI (Decoder
            # Identification) bits, selected by the segment address in
            # bits 1-0. The four bits together describe stereo / binaural
            # / compressed / dynamic-PTY status.
            di_bit = bool((b >> 2) & 0x1)
            address = b & 0x3
            if self._update_di(address, di_bit):
                changed = True

            chars = d
            if self._update_ps_name(address, chars):
                changed = True
        elif group_type == 2:
            text_segment = b & 0xF
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._radio_text_ab:
                self._radio_text_ab = ab_flag
                self.radio_text = [' '] * 64
                self._radio_text_len = 64
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

        return changed

    def get_current_data(self) -> RBDSData:
        """Get the currently decoded RBDS data."""
        rt_chars = self.radio_text[:self._radio_text_len]
        return RBDSData(
            pi_code=self.pi_code,
            call_sign=self.call_sign,
            ps_name=''.join(self.ps_name).strip(),
            pty_name=self.pty_name,
            radio_text=''.join(rt_chars).rstrip(),
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
        )

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
            if self._radio_text_len > index:
                self._radio_text_len = index
                return True
            return False
        # Post-CR characters in this same group are padding → drop.
        if self._rt_saw_cr_this_group and index >= self._radio_text_len:
            return False
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
