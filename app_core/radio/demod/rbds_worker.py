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

"""Threaded RBDS processor.

``RBDSWorker`` pulls the 57 kHz subcarrier out of the FM multiplex on a
background thread so RBDS decoding never blocks the audio path.
"""

import logging
import math
import queue
import threading
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from app_core.radio.demod.kernels import (
    _NUMBA_AVAILABLE,
    _RBDS_SYNDROMES,
    _calc_syndrome_numba,
    _costas_loop_numba,
    _mm_timing_loop_numba,
    _presync_scan_numba,
)
from app_core.radio.demod.dsp import (
    design_fir_bandpass,
    design_fir_lowpass,
    resample_to,
)
from app_core.radio.demod.types import (
    RBDSData,
    RBDSDecoderStats,
)
from app_core.radio.demod.rbds_decoder import RBDSDecoder

logger = logging.getLogger(__name__)

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
    ):
        """Initialize RBDS worker thread.

        Args:
            sample_rate: Original sample rate before any decimation
            intermediate_rate: Rate after decimation (where RBDS processing happens)
        """
        self._sample_rate = sample_rate
        self._intermediate_rate = intermediate_rate

        # Thread-safe queue for incoming multiplex samples.  put_nowait keeps
        # the audio thread non-blocking; depth determines how long a worker
        # stall can last before chunks are dropped.  Sized to absorb the
        # synced-mode batch burst (1 s of samples is DSP'd in one go after
        # each window fills) plus scheduler contention from the other
        # pipelines sharing a small SBC (MP3 encode, SAME decoders, web UI).
        # The old maxsize=5 covered only tens of milliseconds, so every batch
        # spike overflowed; a dropped chunk is much worse than the ~few MB of
        # buffering this costs because it tears the Costas/M&M phase
        # continuity and forces a full resync (observed in the field as
        # periodic garbage stretches and a climbing chunks-dropped counter).
        # In steady state the queue stays near-empty, so depth adds no
        # decode latency.
        self._sample_queue: queue.Queue = queue.Queue(maxsize=64)

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

        # Lowpass (matched) filter for post-mixing: removes everything outside
        # the RBDS baseband.  Designed and applied at the POST-DECIMATION rate
        # (~25 kHz), not the full multiplex rate.
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
        # Why post-decimation: the previous design ran this filter at the full
        # multiplex rate, which forced 501 taps (transition width scales with
        # fs/N) and cost ~250M MAC/s on real+imag — the single largest CPU
        # consumer in the worker and the cause of chunk drops on Pi-class
        # hosts.  Decimating first is safe because the 54-60 kHz bandpass has
        # already confined the spectrum: after the 57 kHz mix the only content
        # is the RBDS baseband at DC and its negative-frequency image, which
        # folds to ≥8 kHz under ::decim — outside this filter's passband.
        # 75 taps at 25 kHz gives a Blackman transition of ~5.5*fs/N ≈
        # 1.8 kHz (vs ~2.7 kHz for the 501-tap/250 kHz original), putting
        # the 4 kHz stereo artifact at -83 dB — far past the -40 dB
        # requirement — at ~1/70 the MAC cost.  Of the 51/75/101-tap
        # candidates, 75 also gave the lowest BLER under noise in
        # end-to-end simulation (sharper cuts more noise, but much sharper
        # starts clipping signal energy).
        decim = max(1, int(self._sample_rate / self.RBDS_INTERMEDIATE_RATE))
        self._rbds_post_decim_rate = (
            int(self._sample_rate // decim) if decim > 1 else self._sample_rate
        )
        self._rbds_lowpass = self._design_fir_lowpass(
            2400.0, self._rbds_post_decim_rate, taps=75
        )

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
        # Overshoot: when i_in advances past the end of a batch the next batch must
        # skip that many positions before extracting a new symbol.  Without this
        # correction the first symbol of every batch re-samples within the last
        # symbol of the previous batch, inserting a spurious extra bit into the
        # differential bitstream (always decoded as 0).  That extra bit accumulates
        # to a 1-bit block-boundary slip every 2 batches, causing 100% BLER on
        # every other batch indefinitely.
        self._rbds_mm_overshoot: int = 0

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

        # High-rate RBDS sample accumulation before decimate+resample.
        # Keep chunks in a list and concatenate once per window; repeatedly
        # np.concatenate()'ing a growing array per incoming chunk is O(n²) in
        # copy volume and can make the worker fall behind at high chunk rates.
        self._rbds_sample_buffer_chunks: List[np.ndarray] = []
        self._rbds_sample_buffer_samples: int = 0

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
        if median > 0 and float(spectrum[idx]) < self._PILOT_SNR_THRESHOLD * median:
            return None
        # Reject obvious nonsense.  At ±4 Hz (~210 ppm at 19 kHz) we're well
        # past anything an even loosely-calibrated SDR produces (typical
        # 25-100 ppm), so anything further out signals broken hardware or a
        # mis-detection — fall back to the 19 000.0 Hz nominal instead.
        if abs(peak_hz - 19000.0) > self._MAX_PILOT_DEVIATION_HZ:
            return None
        return peak_hz

    def _detect_off_frequency_interferer_hz(self, multiplex: np.ndarray) -> Optional[float]:
        """Return baseband offset (Hz) of a strong 55–59 kHz spur vs pilot×3.

        Self-gated: returns None unless a peak in the 55–59 kHz band
        passes the pilot-grade SNR test AND lands inside the guard band
        offset from the expected ``3 × pilot`` frequency.  No external
        configuration; the decoder auto-engages the notch only when a
        real spur is observed.
        """
        if (
            self._measured_pilot_freq is None
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
        if median <= 0.0 or peak_amp < self._PILOT_SNR_THRESHOLD * median:
            return None
        peak_hz = float(freqs[idx])
        expected_hz = 3.0 * float(self._measured_pilot_freq)
        offset_hz = peak_hz - expected_hz
        abs_offset = abs(offset_hz)
        if (
            abs_offset < self._RBDS_INTERFERENCE_MIN_OFFSET_HZ
            or abs_offset > self._RBDS_INTERFERENCE_GUARD_HZ
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
        # ``zi_real``/``zi_imag`` get reset to None whenever ``offset_hz`` was
        # None on the previous call (see the early-return branch above), so
        # they must be re-checked here even when the ``b``/``a``/freq cache
        # is still valid.  Without this check we would feed ``zi=None`` into
        # ``scipy.signal.lfilter`` — which silently returns ``y`` only (not a
        # ``(y, zf)`` tuple) — and the unpacking on the next line would
        # explode with ``ValueError: too many values to unpack (expected 2)``.
        # The exception is swallowed by the worker's try/except so the RBDS
        # pipeline keeps "running" but the notch is silently disabled every
        # time the detector toggles None→value→None→value, which is exactly
        # what happens with marginal off-frequency spurs (the very case the
        # notch exists to handle).
        if (
            self._rbds_interference_notch_b is None
            or self._rbds_interference_notch_a is None
            or self._rbds_interference_notch_freq_hz is None
            or self._rbds_interference_notch_zi_real is None
            or self._rbds_interference_notch_zi_imag is None
            or abs(self._rbds_interference_notch_freq_hz - notch_hz) > 10.0
        ):
            w0 = notch_hz / nyq
            b, a = scipy_signal.iirnotch(w0, self._RBDS_INTERFERENCE_NOTCH_Q)
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
                blocks_bit_slips=self._stats.blocks_bit_slips,
                groups_decoded=self._stats.groups_decoded,
                sync_acquired_unix=self._stats.sync_acquired_unix,
                sync_lost_count=self._stats.sync_lost_count,
                chunks_dropped=self._chunks_dropped,
                group_type_counts={},
            )
        # Group histogram and field-churn counters live on the
        # RBDSDecoder; pull copies here so the snapshot is internally
        # consistent.
        if self._rbds_decoder is not None:
            snap.group_type_counts = dict(
                getattr(self._rbds_decoder, '_group_type_counts', {}) or {}
            )
            snap.pi_change_count = getattr(self._rbds_decoder, 'pi_change_count', 0)
            snap.pty_change_count = getattr(self._rbds_decoder, 'pty_change_count', 0)
            snap.ta_toggle_count = getattr(self._rbds_decoder, 'ta_toggle_count', 0)
            snap.glitches_rejected = getattr(self._rbds_decoder, 'glitches_rejected', 0)
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
            '_rbds_reg_wide',
            '_rbds_slip_retry_pending',
            '_rbds_slip_saved_word',
            '_rbds_sync_tentative',
            '_rbds_tentative_good_groups',
            '_rbds_sample_buffer',
            '_rbds_sample_buffer_chunks',
            '_rbds_sample_buffer_samples',
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

        # Remember the most recent interferer detection for the batch-stage
        # notch below: the notch runs at the decimated rate (where it costs
        # ~decim× less), so it consumes the latest per-chunk verdict instead
        # of being applied chunk-by-chunk at the full rate.
        self._rbds_interferer_offset_hz = interferer_offset_hz

        # Buffer the post-mix complex baseband at the full sample rate.
        # Earlier this code decimated and resampled per chunk, then
        # accumulated the resampled output — but `x[::decim]` resets its
        # phase at every chunk boundary and `scipy.signal.resample_poly` is
        # stateless, so each ~8 ms chunk injected a polyphase filter
        # transient into the bit stream.  Across the ~31 chunks that fit in
        # a 250 ms batch that's 31 stitched-together transients feeding M&M,
        # which manifests downstream as the random presync spacings the
        # operator was seeing (expected 26, got 92, expected 104, got 151,
        # …).  Accumulating BEFORE decim+resample keeps the bit clock
        # continuous within a batch — there's exactly one resample transient
        # per batch instead of 31.  complex64 halves the buffer footprint
        # and downstream memory traffic with no fidelity cost at this SNR.
        if not hasattr(self, '_rbds_sample_buffer_chunks'):
            self._rbds_sample_buffer_chunks = []
            self._rbds_sample_buffer_samples = 0

        self._rbds_sample_buffer_chunks.append(x.astype(np.complex64))
        self._rbds_sample_buffer_samples += len(x)

        # The window thresholds are expressed in samples at the 19 kHz
        # output rate, so scale them up to the current input rate.
        scale = sample_rate / 19000.0
        locked = getattr(self, '_rbds_synced', False)
        window_19k = self.RBDS_SYNCED_WINDOW if locked else self.RBDS_UNSYNCED_WINDOW
        window = int(window_19k * scale)
        if self._rbds_sample_buffer_samples < window:
            return self._decode_rbds_groups()

        # Use buffered samples and reset for next accumulation.
        if len(self._rbds_sample_buffer_chunks) == 1:
            x = self._rbds_sample_buffer_chunks[0]
        else:
            x = np.concatenate(self._rbds_sample_buffer_chunks)
        self._rbds_sample_buffer_chunks = []
        self._rbds_sample_buffer_samples = 0

        # Step 4: Decimate to intermediate rate (~25 kHz) to reduce processing load.
        # Safe without a dedicated anti-alias filter: the 54-60 kHz bandpass
        # already confined the spectrum, so after the 57 kHz mix the only
        # content is the RBDS baseband at DC and its negative-frequency image,
        # which folds to ≥8 kHz under ::decim — into the stopband of the
        # matched filter applied right below.  Any sub-decim tail is carried
        # into the next batch so the decimation phase (and therefore the
        # matched filter's delay-line state) is continuous across batches.
        decim = max(1, int(sample_rate / self.RBDS_INTERMEDIATE_RATE))
        if decim > 1:
            usable = len(x) - (len(x) % decim)
            if usable < len(x):
                self._rbds_sample_buffer_chunks = [x[usable:]]
                self._rbds_sample_buffer_samples = len(x) - usable
                x = x[:usable]
            x = x[::decim]
            sample_rate = int(sample_rate // decim)

        # Off-frequency spur notch, applied at the decimated rate using the
        # most recent per-chunk detection.
        x = self._apply_interference_notch(
            x, sample_rate, getattr(self, '_rbds_interferer_offset_hz', None)
        )

        # Matched filter: sharp 2.4 kHz lowpass at the decimated rate (see
        # _init_rbds_state for the design rationale — this used to be a
        # 501-tap filter at the full multiplex rate and dominated worker
        # CPU).  x is complex; lfilter keeps real delay lines per component,
        # so filter the real and imaginary parts separately with their own
        # persisted zi arrays.  State carries across batches, which the
        # tail-carry decimation above makes phase-correct.
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
        x = real_out + 1j * imag_out  # Keep as int

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

        # Upsample by 16x for interpolation (python-radio method).
        # The full combined array (leftover + new batch) is upsampled in one call
        # so the polyphase filter has complete history at the boundary.
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

        # Apply timing-overshoot correction from the previous batch.
        #
        # At 19 000 Hz with sps=16 each batch yields 19 000 / 16 = 1187.5 symbols.
        # The M&M loop advances i_in by exactly sps after each extracted symbol, so
        # after 1188 symbols it leaves i_in = 1188 × 16 = 19 008 — eight samples
        # past the end of the 19 000-sample batch.  The leftover is then empty
        # (samples[19008:] = []), and the next call restarts at i_in = 0.
        #
        # Those eight "virtual" positions belong to the same rectangular-pulse
        # symbol that was extracted last in the previous batch.  Re-sampling them
        # at i_in = 0 of the new batch yields an identical symbol value, which
        # differential-decodes to a spurious 0-bit.  The extra bit accumulates to
        # a 1-bit block-boundary slip every two batches, causing every block in
        # every other batch to fail its CRC check (100% BLER on alternating
        # one-second windows in the field).
        #
        # Fix: skip the first `overshoot × sps` interpolated positions so the M&M
        # starts at the true next-symbol boundary.  The upsampling was done on the
        # full array, so no filter-transient is introduced at the skip point.
        overshoot_skip: int = self._rbds_mm_overshoot
        if overshoot_skip > 0:
            skip_interp = overshoot_skip * sps
            if skip_interp < len(samples_interpolated):
                samples_interpolated = samples_interpolated[skip_interp:]
            else:
                # Pathological: the entire batch is consumed by the overshoot.
                # Carry forward the remaining overshoot and return no symbols.
                self._rbds_mm_overshoot = overshoot_skip - len(samples_interpolated) // sps
                self._rbds_mm_leftover = np.array([], dtype=np.complex64)
                return np.array([], dtype=np.complex64)
        self._rbds_mm_overshoot = 0

        # Allocate output buffer.  The M&M extracts at most
        # len(samples_interpolated) // sps symbols; the + 3 accounts for the
        # two history slots (i_out starts at 2) plus one rounding margin.
        max_out = len(samples_interpolated) // sps + 3

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
            i_in = 0  # input sample index (relative to samples_interpolated after skip)
            i_out = 2  # output symbol index (let first two outputs be 0)

            # Check against interpolated array length, not original length.
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

        # Compute the consumed position in the original `samples` array.
        # Note: `i_in` is in ORIGINAL-sample space (the M&M loop advances it by
        # ~sps original samples per symbol, not by 1 interpolated sample).
        # `overshoot_skip` is also in original-sample space (symbols × sps).
        # Their sum gives the total number of original samples consumed.
        actual_i_in = i_in + overshoot_skip
        if actual_i_in <= len(samples):
            # Normal: save remaining unprocessed samples for the next call.
            self._rbds_mm_leftover = samples[actual_i_in:].astype(np.complex64, copy=False)
            # overshoot is already 0 (set above)
        else:
            # M&M advanced past the end again; record the overshoot so the
            # next call can skip the corresponding positions.
            self._rbds_mm_leftover = np.array([], dtype=np.complex64)
            self._rbds_mm_overshoot = actual_i_in - len(samples)

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
            # Clock-slip recovery state (synced mode only).  _rbds_reg_wide is
            # a 27-bit shadow of _rbds_reg so the "-1 bit" hypothesis (block
            # boundary was one bit earlier) can be tested after the newest bit
            # has already shifted in; _rbds_slip_retry_pending defers the
            # verdict on a failed block by one bit to test the "+1 bit"
            # hypothesis (boundary is one bit later).  See the slip-recovery
            # comments in the synced-mode block handler.
            self._rbds_reg_wide = 0
            self._rbds_slip_retry_pending = False
            # Polarity-adjusted word from the expected block boundary, kept
            # across the one-bit deferral so the FEC fallback can repair the
            # original (unshifted) word if the +1 hypothesis fails.
            self._rbds_slip_saved_word = 0
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
                        > self._RBDS_PRESYNC_SPACING_TOLERANCE_BITS
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
                            # Clear the stale failure streak from the previous
                            # lock so the slip-recovery and (post-confirmation)
                            # burst-FEC gates start this lock from a clean
                            # slate rather than inheriting the old lock's bad
                            # streak.  (Burst-FEC itself stays suppressed for
                            # the whole tentative phase regardless — see
                            # _repair_block.)
                            self._rbds_consecutive_crc_failures = 0
                            # Seed the slip-recovery shadow register from the
                            # presync register so the very first synced block
                            # can already test the -1-bit hypothesis, and make
                            # sure no stale deferred retry survives from a
                            # previous lock.
                            self._rbds_reg_wide = self._rbds_reg
                            self._rbds_slip_retry_pending = False
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
                # Shadow register for slip recovery: one bit wider than
                # _rbds_reg so the 26-bit window ending one bit *earlier*
                # is still recoverable after the newest bit shifts in.
                # Updated only while synced to keep the presync hot path
                # untouched; seeded from _rbds_reg at sync acquisition.
                self._rbds_reg_wide = ((self._rbds_reg_wide << 1) | bits[i]) & 0x7FFFFFF
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
                        # Suppress burst-FEC during sustained bad streaks and
                        # while sync is still tentative: see
                        # _BURST_FEC_SUPPRESS_AFTER for the streak rationale.
                        # While tentative we are trying to *validate* the lock
                        # — every accepted block feeds the confirmation count
                        # and the first published groups — so only clean and
                        # single-bit repairs (whose false-positive rate is far
                        # lower) may contribute; otherwise burst false-fixes
                        # on a marginal channel ratify the lock with junk and
                        # publish it.  The streak counter we read here was
                        # incremented at the end of the previous block, so it
                        # reflects the *prior* blocks' state and is not
                        # affected by the current attempt.
                        if (
                            self._rbds_consecutive_crc_failures
                            >= self._BURST_FEC_SUPPRESS_AFTER
                            or self._rbds_sync_tentative
                        ):
                            return False, candidate_word, 'fail-suppressed'
                        ok, fixed = _try_correct_burst_error(
                            candidate_word, block_number
                        )
                        if ok:
                            return True, fixed, 'burst'
                        return False, candidate_word, 'fail'

                    # Block decision with clock-slip recovery.  A single M&M
                    # symbol-timing slip shifts the 26-bit block grid by one
                    # bit and, without recovery, every subsequent block fails
                    # CRC until the 50-block window drops sync — a ~1 s outage
                    # plus full reacquisition for a one-bit problem.  When the
                    # block fails the clean CRC check we therefore test the
                    # two ±1-bit grid hypotheses BEFORE attempting FEC:
                    # a slipped word is a shifted codeword, which lands within
                    # 1 bit of some *other* valid codeword often enough that
                    # the single-bit corrector will occasionally "repair" it
                    # into a wrong-but-valid dataword.  Slip hypotheses are
                    # accepted only on a *clean* CRC pass (never via FEC):
                    # a false realignment corrupts every following block,
                    # which is worse than one lost block.
                    #
                    # Decision order per block:
                    #   1. clean CRC at the expected boundary       → good
                    #   2. clean CRC one bit earlier (-1, via the
                    #      shadow register)                         → realign
                    #   3. defer one bit; clean CRC one bit later
                    #      (+1)                                     → realign
                    #   4. FEC + polarity recovery on the word from
                    #      the original boundary                    → repair
                    # Steps 3 and 4 happen on the deferred retry pass; stats,
                    # group assembly and sync-quality bookkeeping run exactly
                    # once per block, on whichever pass reaches a verdict.
                    good_block = False
                    slip_recovered = False
                    # Value _rbds_block_bit_counter is reset to after this
                    # block; 1 when one bit of the next block (or of the
                    # restored grid) has already been consumed.
                    next_block_bit_counter = 0
                    retry_pass = self._rbds_slip_retry_pending
                    self._rbds_slip_retry_pending = False
                    block_word = self._rbds_reg ^ 0x3FFFFFF if self._rbds_inverted_polarity else self._rbds_reg

                    # Set when no clean/slip verdict was reached and the FEC
                    # fallback below must decide; fec_word is the word the
                    # fallback repairs (the original-boundary word when a
                    # deferral consumed an extra bit).
                    needs_fec = False
                    fec_word = block_word

                    if not retry_pass:
                        if _crc_ok_for_block(block_word, self._rbds_block_number):
                            good_block = True
                            repair_path = 'clean'
                        elif (
                            self._rbds_consecutive_crc_failures
                            < self._BURST_FEC_SUPPRESS_AFTER
                        ):
                            # Slip hypotheses are only tested while the recent
                            # streak is healthy: a real M&M slip is an isolated
                            # event on an otherwise-decoding channel.  During a
                            # sustained garbage stretch (dropped chunks, deep
                            # fades) a "clean" match at ±1 bit is a CRC
                            # coincidence, and realigning onto it keeps a dead
                            # sync alive — bridging right through data that
                            # should fail out to presync as it used to.
                            #
                            # Early hypothesis (-1): the true boundary was one
                            # bit ago; the shadow register still holds that
                            # 26-bit window.
                            early_word = (self._rbds_reg_wide >> 1) & 0x3FFFFFF
                            if self._rbds_inverted_polarity:
                                early_word ^= 0x3FFFFFF
                            if _crc_ok_for_block(early_word, self._rbds_block_number):
                                block_word = early_word
                                good_block = True
                                slip_recovered = True
                                repair_path = 'clean'
                                # The newest bit already belongs to the next
                                # block on the realigned grid.
                                next_block_bit_counter = 1
                                logger.info(
                                    "RBDS bit slip (-1) recovered at block %d; grid realigned in place",
                                    self._rbds_block_number,
                                )
                            else:
                                # Late hypothesis (+1) needs one more bit:
                                # save the word from the expected boundary for
                                # the FEC fallback and re-enter block
                                # processing on the next bit.
                                self._rbds_slip_saved_word = block_word
                                self._rbds_slip_retry_pending = True
                                self._rbds_block_bit_counter = 25
                                continue
                        else:
                            # Bad streak: skip slip testing and decide now.
                            needs_fec = True
                    elif _crc_ok_for_block(block_word, self._rbds_block_number):
                        # Late-slip (+1) confirmed: a clean block sits one bit
                        # past the expected boundary.  Keep the shifted grid.
                        good_block = True
                        slip_recovered = True
                        repair_path = 'clean'
                        logger.info(
                            "RBDS bit slip (+1) recovered at block %d; grid realigned in place",
                            self._rbds_block_number,
                        )
                    else:
                        # No slip: fall back to FEC on the word captured at
                        # the original boundary, then restore the original
                        # grid (the deferral consumed one extra bit).
                        needs_fec = True
                        fec_word = self._rbds_slip_saved_word
                        next_block_bit_counter = 1

                    if needs_fec:
                        corrected, corrected_word, repair_path = _repair_block(
                            fec_word, self._rbds_block_number
                        )
                        if corrected:
                            block_word = corrected_word
                            good_block = True
                        else:
                            # If current polarity suddenly fails CRC but opposite polarity passes,
                            # recover immediately instead of waiting for a full sync-loss window.
                            alternate_block_word = fec_word ^ 0x3FFFFFF
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
                        if slip_recovered:
                            self._stats.blocks_bit_slips += 1
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
                                    self._rbds_tentative_good_groups += 1
                                    # +1: the block that completed this group
                                    # has not been added to the window counter
                                    # yet (that happens below).
                                    blocks_so_far = self._rbds_blocks_counter + 1
                                    window_is_clean = (
                                        self._rbds_wrong_blocks_counter * 5
                                        <= blocks_so_far
                                    )
                                    if (
                                        self._rbds_tentative_good_groups
                                        >= self._RBDS_TENTATIVE_GOOD_GROUPS
                                        and window_is_clean
                                    ):
                                        # Confirm the lock the moment the Nth
                                        # fully-decoded group completes instead
                                        # of waiting for the 50-block window
                                        # boundary — but only when the window
                                        # so far is clean (≤20% uncorrected).
                                        # On a healthy channel this saves up to
                                        # ~0.8 s of first-data latency; on a
                                        # marginal channel the carrier/timing
                                        # loops are often still settling right
                                        # after lock, and publishing that shaky
                                        # period is how FEC false-fixes reach
                                        # the UI — those locks wait for the
                                        # full 50-block verdict below.  The
                                        # confirming group itself is published:
                                        # it passed the same CRC gauntlet as
                                        # everything that will follow it.
                                        logger.info(
                                            "RBDS sync CONFIRMED (%d good groups after %d blocks)",
                                            self._rbds_tentative_good_groups,
                                            self._rbds_blocks_counter + 1,
                                        )
                                        self._rbds_sync_tentative = False
                                        with self._stats_lock:
                                            self._stats.sync_acquired_unix = time.time()
                                        self._rbds_decoder.process_group(
                                            (group_0, group_1, group_2, group_3)
                                        )
                                        changed = True
                                        with self._stats_lock:
                                            self._stats.groups_decoded += 1
                                    else:
                                        # Below the confirmation threshold:
                                        # count the group but do NOT publish to
                                        # the RBDSDecoder (which feeds the UI)
                                        # and do NOT bump groups_decoded.  If
                                        # the lock turns out to be false this
                                        # is exactly the kind of bogus
                                        # PI/group-type we don't want to
                                        # surface.
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
                    
                    # Reset for next block.  next_block_bit_counter is 1 when
                    # slip recovery already consumed one bit of the next block
                    # (or of the restored grid after a failed retry), 0 otherwise.
                    self._rbds_block_bit_counter = next_block_bit_counter
                    self._rbds_block_number = (self._rbds_block_number + 1) % 4
                    self._rbds_blocks_counter += 1
                    
                    # Check sync quality every 50 blocks
                    if self._rbds_blocks_counter == 50:
                        if self._rbds_sync_tentative:
                            # Locks on clean channels confirm inline the moment
                            # the Nth good group completes (see group assembly
                            # above).  Reaching the window boundary still
                            # tentative therefore means the channel is dirty:
                            # confirm here only if enough fully-decoded groups
                            # landed in the window (the original 50-block
                            # quality gate), otherwise reject.
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

