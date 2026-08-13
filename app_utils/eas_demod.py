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

SAMEDemodulatorCore — the single FSK/DLL SAME demodulation engine.

Previously the project maintained two independent implementations of the same
core algorithm:

  - app_utils/eas_decode.py  (_correlate_and_decode_with_dll)
  - app_core/audio/streaming_same_decoder.py  (_process_dll_and_bits)

This module replaces both with one implementation.  The file-based decoder
and the real-time streaming decoder both compose SAMEDemodulatorCore; all DSP
constants, DLL state machine logic, bandpass filtering, and ENDEC hardware
fingerprinting now live here exactly once.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional Numba JIT acceleration for the per-sample DLL state machine.
#
# The inner DLL loop is the dominant cost of SAME demodulation: at every input
# sample it updates a shift register, integrator, and DLL phase accumulator,
# but only emits a "bit complete" event roughly once per ``corr_len`` samples
# (every 30-77 samples at 16-44 kHz).  Doing that loop in Python imposes ~100x
# overhead on what is otherwise trivial integer math.  Compiling it with Numba
# yields a 10-50x speed-up on real workloads with bit-exact output.
#
# Mirrors the pattern in app_core/radio/demodulation.py: free function with
# numpy array arguments, ``@jit(nopython=True, fastmath=True)``, and a no-op
# decorator fallback when Numba is unavailable.
#
# Deliberately NOT ``cache=True``: this module is imported by up to half a
# dozen independent OS processes (web workers, poller, EAS/SDR/audio
# services), several of which can start within the same second on a service
# restart or reboot. Numba's on-disk cache (a shared .nbi/.nbc pair next to
# this file) isn't safe against that many processes racing to compile and
# write it on first import — one such race corrupted the cache with
# "cannot cache function '_dll_drain_bits_numba': no locator available",
# which made `from app import ...` fail in the poller, which fell back to
# its stale duplicate CAPAlert model and silently broke CAP alert ingestion
# for hours. JIT compilation still happens per-process (a few tens of ms,
# once, at import time); it's just never persisted to a shared file.
# ---------------------------------------------------------------------------

try:
    from numba import jit as _numba_jit
    _NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without numba
    _NUMBA_AVAILABLE = False

    def _numba_jit(*args, **kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func
        return decorator


@_numba_jit(nopython=True, fastmath=True)
def _dll_drain_bits_numba(
    correlations: np.ndarray,      # float32[N]
    total_powers: np.ndarray,      # float32[N]
    state: np.ndarray,             # int64[4]: dcd_shreg, dcd_integrator, sphase, lasts
    sphaseinc: int,
    integrator_max: int,
    out_indices: np.ndarray,       # int32[M] - sample index where each bit completed
    out_lasts: np.ndarray,         # int32[M] - lasts register snapshot at that bit
    out_confidences: np.ndarray,   # float32[M]
) -> int:
    """Run the per-sample SAME DLL state machine; emit one record per bit.

    This is the JIT-compiled counterpart to the inner Python loop that
    previously called ``_process_dll_and_bits`` once per audio sample.  All
    samples that don't complete a bit are processed in tight integer/float
    arithmetic; only at bit boundaries (``sphase`` overflow) is an entry
    written to the output arrays for the Python caller to handle.

    State semantics are bit-exact with the original implementation:

    * ``dcd_shreg``   - 32-bit transition shift register.
    * ``dcd_integrator`` - signed counter clamped to ``+/-integrator_max``.
    * ``sphase``      - 16.16 fixed-point phase accumulator (overflow == bit).
    * ``lasts``       - 8-bit byte assembly register; one new bit shifted in
                        from the MSB at each bit boundary.

    The DLL gain (0.4) is applied as a float multiply followed by ``int()``
    truncation, matching ``int(self.sphase * self.DLL_GAIN)`` in the original
    Python code.  The 8192-sample clamp matches the original.

    Returns:
        The number of bits emitted.  ``out_*`` arrays are populated up to
        that index.  The final DLL state is written back into ``state``.
    """
    dcd_shreg = state[0]
    dcd_integrator = state[1]
    sphase = state[2]
    lasts = state[3]

    n = correlations.shape[0]
    emitted = 0

    for i in range(n):
        c = correlations[i]
        tp = total_powers[i]

        # 32-bit transition shift register
        dcd_shreg = (dcd_shreg << 1) & 0xFFFFFFFF
        if c > 0.0:
            dcd_shreg |= 1

        # Integrator with hysteresis clamp
        if c > 0.0:
            if dcd_integrator < integrator_max:
                dcd_integrator += 1
        elif c < 0.0:
            if dcd_integrator > -integrator_max:
                dcd_integrator -= 1

        # DLL phase adjustment on detected bit transition
        if ((dcd_shreg ^ (dcd_shreg >> 1)) & 1) != 0:
            if sphase < 0x8000:
                if sphase > sphaseinc // 2:
                    adj = int(sphase * 0.4)
                    if adj > 8192:
                        adj = 8192
                    sphase -= adj
            else:
                if sphase < 0x10000 - sphaseinc // 2:
                    adj = int((0x10000 - sphase) * 0.4)
                    if adj > 8192:
                        adj = 8192
                    sphase += adj

        sphase += sphaseinc

        # End of bit period?
        if sphase >= 0x10000:
            sphase &= 0xFFFF
            lasts = (lasts >> 1) & 0x7F
            if dcd_integrator >= 0:
                lasts |= 0x80

            if tp > 0.0:
                conf = c if c >= 0.0 else -c
                conf = conf / tp
                if conf > 1.0:
                    conf = 1.0
            else:
                conf = 0.0

            out_indices[emitted] = i
            out_lasts[emitted] = lasts
            out_confidences[emitted] = conf
            emitted += 1

    state[0] = dcd_shreg
    state[1] = dcd_integrator
    state[2] = sphase
    state[3] = lasts
    return emitted

# ---------------------------------------------------------------------------
# ENDEC hardware type constants
# ---------------------------------------------------------------------------

ENDEC_MODE_UNKNOWN = "UNKNOWN"
ENDEC_MODE_DEFAULT = "DEFAULT"          # DASDEC / generic
ENDEC_MODE_NWS = "NWS"                  # NWS Legacy / EAS.js
ENDEC_MODE_NWS_CRS = "NWS_CRS"         # NWS Console Replacement System 1998-2016
ENDEC_MODE_NWS_BMH = "NWS_BMH"         # NWS Broadcast Message Handler 2016+
ENDEC_MODE_SAGE_3644 = "SAGE_DIGITAL_3644"
ENDEC_MODE_SAGE_1822 = "SAGE_ANALOG_1822"
ENDEC_MODE_TRILITHIC = "TRILITHIC"      # Trilithic EASyPLUS (~868 ms inter-burst gap)
ENDEC_MODE_EAS_STATION = "EAS_STATION"  # KR8MER EAS Station (3 × 0xA9 trill fingerprint)

# Inter-burst gap windows (ms) for mode fingerprinting
_ENDEC_GAP_TRILITHIC = (820, 920)   # 868 ms nominal
_ENDEC_GAP_STANDARD = (900, 1100)   # 1000 ms nominal (DASDEC, SAGE, NWS)


# ---------------------------------------------------------------------------
# Shared DSP utilities
# ---------------------------------------------------------------------------

def apply_bandpass_filter(samples: Sequence[float], sample_rate: int) -> List[float]:
    """Apply a 4th-order Butterworth bandpass filter (1200–2500 Hz).

    Isolates the SAME FSK signal and rejects out-of-band noise before
    demodulation.  Matches the SoftwareBandpass(1822.9 Hz, Q=3) used by
    EAS-Tools decoder-bundle.js.  Returns the original samples unchanged if
    scipy is unavailable.
    """
    try:
        from scipy.signal import butter, sosfilt
        nyq = sample_rate / 2.0
        low = 1200.0 / nyq
        high = min(2500.0, nyq * 0.95) / nyq
        if not (0 < low < high < 1.0):
            return list(samples)
        sos = butter(4, [low, high], btype="bandpass", output="sos")
        filtered = sosfilt(sos, np.asarray(samples, dtype=np.float64))
        return filtered.tolist()
    except Exception:
        return list(samples)


def compute_burst_timing_gaps_ms(
    burst_sample_ranges: List[Tuple[int, int]], sample_rate: int
) -> List[float]:
    """Return inter-burst gap durations (ms) from a list of (start, end) sample pairs.

    The gap is measured from the END of burst N to the START of burst N+1,
    which matches the inter-burst silence durations published in ENDEC hardware
    profiles (e.g. 1000 ms for DASDEC, 868 ms for Trilithic EASyPLUS).
    """
    gaps: List[float] = []
    for i in range(1, len(burst_sample_ranges)):
        gap_samples = burst_sample_ranges[i][0] - burst_sample_ranges[i - 1][1]
        if gap_samples >= 0:
            gaps.append(gap_samples / float(sample_rate) * 1000.0)
    return gaps


def detect_endec_mode(
    messages: List[str],
    burst_timing_gaps_ms: List[float],
    terminator_runs: Optional[List[Tuple[int, int]]] = None,
    leading_null_detected: bool = False,
) -> str:
    """Fingerprint the originating ENDEC hardware from transmission characteristics.

    Uses a voting system matching EAS-Tools (wagwan-piffting-blud/EAS-Tools
    decoder-bundle.js), combining three evidence sources:

    1. **Terminator byte signatures** — different ENDECs append specific bytes
       after each SAME burst:
       - NWS Legacy/EAS.js:          2 × 0x00 per burst
       - NWS CRS (1998-2016):        3 × 0x00 per burst (on EOM, prefix+suffix)
       - NWS BMH (2016+):            3 × 0x00 per burst
       - SAGE ANALOG 1822:           1 × 0xFF per burst
       - SAGE DIGITAL 3644:          3 × 0xFF per burst  (+ leading 0x00 on 1st burst)
       - DEFAULT/DASDEC, TRILITHIC:  no terminator bytes
       - KR8MER EAS Station:         3 × 0xA9 per burst

    2. **Leading 0x00 before preamble** — SAGE DIGITAL 3644 prepends one 0x00
       byte before the 16-byte preamble on the first burst.

    3. **Inter-burst gap timing** — Trilithic EASyPLUS uses ~868 ms gaps
       (760–930 ms window) instead of the standard ~1000 ms.

    Args:
        messages:             Decoded SAME message strings (must be non-empty).
        burst_timing_gaps_ms: List of inter-burst silence durations in ms.
        terminator_runs:      List of (byte_value, run_length) tuples collected
                              from bytes that immediately follow each burst.
        leading_null_detected: True when a 0x00 byte was observed immediately
                               before the preamble run of any burst.

    Returns:
        One of the ENDEC_MODE_* constants.
    """
    if not messages:
        return ENDEC_MODE_UNKNOWN

    # EAS_STATION listed first so that on a vote tie it wins over the
    # ENDECs whose terminator bytes (0x00 / 0xFF) overlap with the FSK
    # silence floor.  max(...) returns the first key reaching the max.
    votes: dict = {
        ENDEC_MODE_EAS_STATION:  0.0,
        ENDEC_MODE_DEFAULT:      0.0,
        ENDEC_MODE_NWS:          0.0,
        ENDEC_MODE_NWS_CRS:      0.0,
        ENDEC_MODE_NWS_BMH:      0.0,
        ENDEC_MODE_SAGE_3644:    0.0,
        ENDEC_MODE_SAGE_1822:    0.0,
        ENDEC_MODE_TRILITHIC:    0.0,
    }

    # 1. Terminator byte votes — primary ENDEC discriminator.
    # Collapse repeated per-burst entries to the MAX run length seen for
    # each byte value, so a single noise-corrupted run cannot dominate
    # the vote and so legitimate fingerprints aren't double-counted
    # across all three SAME bursts.  KR8MER's 3 × 0xA9 trill is a hard
    # signature — when it appears with a clean run length, it wins
    # outright (no other ENDEC emits 0xA9 bytes).
    if terminator_runs:
        max_run_per_byte: Dict[int, int] = {}
        for byte_val, run_length in terminator_runs:
            if run_length > max_run_per_byte.get(byte_val, 0):
                max_run_per_byte[byte_val] = run_length

        if max_run_per_byte.get(0xA9, 0) >= 3:
            # KR8MER EAS Station fingerprint is deliberate and unambiguous;
            # short-circuit the vote so 0x00/0xFF silence-floor evidence
            # captured on neighbouring bursts can't override it.
            return ENDEC_MODE_EAS_STATION

        for byte_val, run_length in max_run_per_byte.items():
            if byte_val == 0x00:
                # Null-byte terminator → NWS variants.
                # Vote strength is proportional to run length, and the specific
                # NWS sub-variant is chosen by run length:
                #   1 byte  → weak NWS signal
                #   2 bytes → NWS Legacy / EAS.js profile
                #   3+bytes → NWS BMH (2016+) or CRS (1998-2016)
                if run_length >= 3:
                    votes[ENDEC_MODE_NWS_BMH] += 4.0
                    votes[ENDEC_MODE_NWS_CRS] += 2.0
                    votes[ENDEC_MODE_NWS] += 0.5
                elif run_length == 2:
                    votes[ENDEC_MODE_NWS] += 4.0
                    votes[ENDEC_MODE_NWS_BMH] += 0.5
                else:
                    votes[ENDEC_MODE_NWS] += 0.5
            elif byte_val == 0xFF:
                # FF-byte terminator → SAGE variants
                if run_length >= 3:
                    votes[ENDEC_MODE_SAGE_3644] += 4.0
                    votes[ENDEC_MODE_SAGE_1822] += 0.5
                elif run_length == 1:
                    votes[ENDEC_MODE_SAGE_1822] += 4.0
                    votes[ENDEC_MODE_SAGE_3644] += 0.5
                else:
                    votes[ENDEC_MODE_SAGE_1822] += 1.5
                    votes[ENDEC_MODE_SAGE_3644] += 1.5
            elif byte_val == 0xA9:
                # 0xA9 terminator → KR8MER EAS Station.
                # Not used by any known ENDEC; EAS-Tools ignores it entirely.
                if run_length >= 3:
                    votes[ENDEC_MODE_EAS_STATION] += 4.0
                else:
                    votes[ENDEC_MODE_EAS_STATION] += run_length * 1.0

    # 2. Leading null byte (SAGE DIGITAL 3644 specific signature)
    if leading_null_detected:
        votes[ENDEC_MODE_SAGE_3644] += 5.5

    # 3. Gap timing votes
    if burst_timing_gaps_ms:
        avg_gap = sum(burst_timing_gaps_ms) / len(burst_timing_gaps_ms)
        if 760 <= avg_gap <= 930:
            votes[ENDEC_MODE_TRILITHIC] += 5.0
        elif 1080 <= avg_gap <= 1160:
            votes[ENDEC_MODE_TRILITHIC] += 3.0   # Trilithic after-gap window
        elif 930 <= avg_gap < 1050:
            votes[ENDEC_MODE_DEFAULT] += 2.0

    # Return the highest-voted mode (ties broken by dict insertion order)
    best_mode = max(votes, key=votes.get)
    if votes[best_mode] > 0:
        return best_mode

    return ENDEC_MODE_UNKNOWN


# ---------------------------------------------------------------------------
# SAMEDemodulatorCore
# ---------------------------------------------------------------------------

class SAMEDemodulatorCore:
    """
    Stateful FSK/DLL SAME demodulator — the single shared implementation.

    Handles the complete signal path from raw PCM samples to decoded SAME
    message text:

      PCM samples → bandpass filter → sliding-window I/Q correlation →
      DLL timing recovery → bit assembly → 8N1 framing → SAME message

    Designed for both batch (file) and streaming (real-time) use:

    * **Streaming**: create one instance; call process_samples() with each
      audio chunk.  All state persists between calls.
    * **Batch / file**: create one instance; feed the entire sample array in
      one process_samples() call; read results from .messages.

    Args:
        sample_rate:       Audio sample rate in Hz.
        message_callback:  Optional callable invoked for each complete decoded
                           message with signature
                           ``(msg_text: str, confidence: float,
                              burst_sample_ranges: List[Tuple[int,int]])``.
        apply_bandpass:    When True (default) the core applies an IIR
                           bandpass filter to each chunk before demodulation.
                           Set False when the caller has already filtered the
                           samples (avoids double-filtering).
    """

    # DLL constants — identical values used by both the old file decoder and
    # the old streaming decoder; consolidated here.
    PREAMBLE_BYTE = 0xAB
    DLL_GAIN = 0.4
    INTEGRATOR_MAX = 12
    MAX_MSG_LEN = 268

    def __init__(
        self,
        sample_rate: int,
        message_callback: Optional[Callable[[str, float, List[Tuple[int, int]]], None]] = None,
        apply_bandpass: bool = True,
    ) -> None:
        self.sample_rate = sample_rate
        self.baud_rate = float(SAME_BAUD)
        self.corr_len = int(sample_rate / self.baud_rate)
        self.message_callback = message_callback
        self._apply_bandpass_flag = apply_bandpass

        # Correlation tables (numpy float32 for BLAS)
        t = np.arange(self.corr_len, dtype=np.float64)
        mark_phase = 2.0 * np.pi * SAME_MARK_FREQ / sample_rate * t
        space_phase = 2.0 * np.pi * SAME_SPACE_FREQ / sample_rate * t
        self._mark_i = np.cos(mark_phase).astype(np.float32)
        self._mark_q = np.sin(mark_phase).astype(np.float32)
        self._space_i = np.cos(space_phase).astype(np.float32)
        self._space_q = np.sin(space_phase).astype(np.float32)

        # Bandpass filter coefficients (computed once; never reset)
        self._bandpass_sos: Optional[np.ndarray] = None
        self._bandpass_available = False
        if apply_bandpass:
            self._init_bandpass()

        # All mutable decoder state lives in reset()
        self._bandpass_zi: Optional[np.ndarray] = None
        self.reset()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_bandpass(self) -> None:
        try:
            from scipy.signal import butter
            nyq = self.sample_rate / 2.0
            low = 1200.0 / nyq
            high = min(2500.0, nyq * 0.95) / nyq
            if 0 < low < high < 1.0:
                # Keep SOS coefficients in float32 so sosfilt can run on the
                # incoming float32 audio without per-chunk up/down-casts.
                self._bandpass_sos = butter(
                    4, [low, high], btype="bandpass", output="sos"
                ).astype(np.float32)
                self._bandpass_available = True
                logger.debug(
                    "SAMEDemodulatorCore bandpass filter: 1200–2500 Hz, 4th-order "
                    "Butterworth @ %d Hz", self.sample_rate
                )
        except Exception as exc:
            logger.debug("Bandpass filter unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all DLL, message-assembly, filter, and accumulator state."""
        # DLL state.  The JIT helper consumes/produces these via a small int64
        # array; the scalar attributes are kept in sync after each chunk for
        # any external readers that inspect them.
        self.dcd_shreg: int = 0
        self.dcd_integrator: int = 0
        self.sphase: int = 1
        self.sphaseinc: int = int(0x10000 * self.baud_rate / self.sample_rate)
        self.lasts: int = 0
        self.byte_counter: int = 0
        self.synced: bool = False
        self._dll_state = np.array(
            [self.dcd_shreg, self.dcd_integrator, self.sphase, self.lasts],
            dtype=np.int64,
        )

        # Message assembly
        self.current_msg: List[str] = []
        self.in_message: bool = False
        self.bit_confidences: List[float] = []

        # Accumulators (cleared on full reset)
        self.messages: List[str] = []
        self.burst_sample_ranges: List[Tuple[int, int]] = []
        self._all_bit_confidences: List[float] = []
        self.bytes_decoded: int = 0
        self.samples_processed: int = 0

        # Burst timing / ENDEC
        self._burst_start_sample: Optional[int] = None
        self._burst_sample_history: List[Tuple[int, int]] = []
        self.endec_mode: str = ENDEC_MODE_UNKNOWN
        self.burst_timing_gaps_ms: List[float] = []

        # Terminator byte tracking (EAS-Tools-style ENDEC fingerprinting)
        # After each message completes, the decoder stays in "post-message mode"
        # briefly to capture the null/FF bytes that different ENDECs append after
        # each burst before the inter-burst silence.
        self._post_message_mode: bool = False   # capturing bytes after message end
        self._terminator_byte: Optional[int] = None   # current terminator value (0x00 or 0xFF)
        self._terminator_run: int = 0                  # consecutive count of that byte
        self._all_terminator_runs: List[Tuple[int, int]] = []  # (byte_val, run_len) per burst
        self._leading_null_detected: bool = False  # 0x00 seen just before preamble
        self._prev_decoded_byte: Optional[int] = None  # last successfully decoded byte
        # Cap captured terminator bytes per burst.  Real ENDECs append 1-3
        # terminator bytes after each SAME burst; anything longer is the FSK
        # noise floor (inter-burst silence decoded as all-mark 0xFF bytes,
        # or sustained DC as 0x00) and must not pollute the fingerprint.
        self._post_message_bytes_captured: int = 0
        self._MAX_TERMINATOR_BYTES_PER_BURST = 8

        # Absolute sample position of the bit currently being processed.
        # Updated by process_samples() before each _handle_bit_event() call so
        # that burst_sample_ranges reflect the actual position of each burst
        # in the audio (not the end-of-chunk position, which broke gap timing
        # on batch decodes where the whole file arrives in a single chunk).
        self._current_sample_position: int = 0

        # Prefix buffer for cross-chunk continuity (streaming use)
        self._prefix = np.zeros(self.corr_len - 1, dtype=np.float32)
        self._warmup_remaining: int = self.corr_len

        # Reset bandpass filter initial conditions
        if self._bandpass_available and self._bandpass_sos is not None:
            self._bandpass_zi = np.zeros(
                (self._bandpass_sos.shape[0], 2), dtype=np.float32
            )

    def process_samples(self, samples: np.ndarray) -> None:
        """Process audio samples through the full demodulation pipeline.

        Maintains all state between calls — safe to call repeatedly with
        streaming audio chunks of any size (including single samples).

        Args:
            samples: Audio samples as a numpy array, normalised to [-1, 1].
                     Will be cast to float32 if needed.
        """
        if len(samples) == 0:
            return

        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        self.samples_processed += len(samples)

        # Bandpass filter (stateful — zi persists across calls)
        if self._bandpass_available and self._bandpass_sos is not None:
            try:
                from scipy.signal import sosfilt
                samples, self._bandpass_zi = sosfilt(
                    self._bandpass_sos,
                    samples,
                    zi=self._bandpass_zi,
                )
            except Exception:
                pass  # continue with unfiltered samples

        num_samples = len(samples)

        # Warmup: need corr_len samples before the first correlation window
        if self._warmup_remaining > 0:
            if num_samples < self._warmup_remaining:
                self._warmup_remaining -= num_samples
                prefix_len = self.corr_len - 1
                if num_samples >= prefix_len:
                    self._prefix[:] = samples[-prefix_len:]
                else:
                    self._prefix = np.roll(self._prefix, -num_samples)
                    self._prefix[-num_samples:] = samples
                return
            else:
                warmup_count = self._warmup_remaining
                self._warmup_remaining = 0
                prefix_len = self.corr_len - 1
                if warmup_count >= prefix_len:
                    self._prefix[:] = samples[warmup_count - prefix_len:warmup_count]
                else:
                    shift = prefix_len - warmup_count
                    self._prefix[:shift] = self._prefix[warmup_count:]
                    self._prefix[shift:] = samples[:warmup_count]
                samples = samples[warmup_count:]
                num_samples = len(samples)
                if num_samples == 0:
                    return

        # Build contiguous linear buffer (prefix + new samples)
        prefix_len = self.corr_len - 1
        linear = np.empty(prefix_len + num_samples, dtype=np.float32)
        linear[:prefix_len] = self._prefix
        linear[prefix_len:] = samples
        self._prefix[:] = linear[-(self.corr_len - 1):]

        # BLAS-accelerated batch correlation:
        # sliding_window_view gives (num_samples, corr_len) with zero copies;
        # 4 matrix multiplies replace 4*N individual np.dot calls.
        windows = np.lib.stride_tricks.sliding_window_view(linear, self.corr_len)
        mark_i_all = windows @ self._mark_i    # (num_samples,)
        mark_q_all = windows @ self._mark_q
        space_i_all = windows @ self._space_i
        space_q_all = windows @ self._space_q

        mark_power = mark_i_all * mark_i_all + mark_q_all * mark_q_all
        space_power = space_i_all * space_i_all + space_q_all * space_q_all
        correlations = (mark_power - space_power).astype(np.float32, copy=False)
        total_powers = (mark_power + space_power).astype(np.float32, copy=False)

        # Drain bit events from the DLL state machine.  The JIT helper handles
        # the per-sample inner loop in compiled code; Python only sees one
        # record per completed bit (~1 entry per corr_len samples).
        if num_samples > 0:
            out_indices = np.empty(num_samples, dtype=np.int32)
            out_lasts = np.empty(num_samples, dtype=np.int32)
            out_confidences = np.empty(num_samples, dtype=np.float32)
            emitted = _dll_drain_bits_numba(
                correlations,
                total_powers,
                self._dll_state,
                self.sphaseinc,
                self.INTEGRATOR_MAX,
                out_indices,
                out_lasts,
                out_confidences,
            )
            # Sync back the post-drain DLL state for any external readers.
            self.dcd_shreg = int(self._dll_state[0])
            self.dcd_integrator = int(self._dll_state[1])
            self.sphase = int(self._dll_state[2])
            self.lasts = int(self._dll_state[3])

            # Chunk-relative sample indices in out_indices[] become absolute
            # positions by adding the chunk start.  samples_processed already
            # advanced to end-of-chunk above (line 520) so subtract num_samples.
            chunk_start_sample = self.samples_processed - num_samples
            for k in range(emitted):
                self._current_sample_position = chunk_start_sample + int(out_indices[k])
                self._handle_bit_event(
                    int(out_lasts[k]),
                    float(out_confidences[k]),
                )

    # ------------------------------------------------------------------
    # Properties derived from accumulated state
    # ------------------------------------------------------------------

    @property
    def average_confidence(self) -> float:
        """Mean bit confidence across all decoded bits since last reset."""
        if self._all_bit_confidences:
            return sum(self._all_bit_confidences) / len(self._all_bit_confidences)
        return 0.0

    # ------------------------------------------------------------------
    # Internal DLL state machine
    # ------------------------------------------------------------------

    def _handle_bit_event(self, lasts_byte: int, confidence: float) -> None:
        """Process one completed bit emitted by the JIT DLL helper.

        Runs the byte-assembly / preamble-sync / post-message-terminator
        logic that used to live in ``_process_dll_and_bits``.  All per-sample
        DLL math (shift register, integrator, phase accumulator) has been
        moved into ``_dll_drain_bits_numba``; this method only sees bit
        boundaries and is therefore called ~1/30th as often as the old
        per-sample loop.

        Args:
            lasts_byte: 8-bit ``lasts`` shift register snapshot at the moment
                        this bit completed (already shifted; new bit in MSB).
            confidence: Bit confidence in [0, 1] (|correlation| / total_power).
        """
        # Mirror the old self.lasts so external callers continue to observe
        # the byte register at bit boundaries.
        self.lasts = lasts_byte

        # Bit confidence (gated by sync state, matching the original)
        if self.synced or self.in_message:
            self.bit_confidences.append(confidence)
            self._all_bit_confidences.append(confidence)

        # Preamble sync detection (bit-level shift-register match)
        if (lasts_byte & 0xFF) == self.PREAMBLE_BYTE and not self.in_message:
            # Check whether the byte decoded just before this preamble run was 0x00
            # (SAGE DIGITAL 3644 prepends one 0x00 byte on the first burst)
            if self._prev_decoded_byte == 0x00 and not self.synced:
                self._leading_null_detected = True
            # Flush any open post-message terminator run
            if self._post_message_mode:
                self._flush_terminator_run()
                self._post_message_mode = False
                self._post_message_bytes_captured = 0
                self._update_endec_from_evidence()
            self.synced = True
            self.byte_counter = 0
            # Reset per-burst confidence window.  After a burst completes,
            # synced stays True through the inter-burst silence, causing
            # ~520 zero-confidence samples (~1 s x 520.83 baud) to
            # accumulate before the next preamble arrives.  Clearing here
            # ensures each burst's confidence is measured only against its
            # own preamble + message bits - not the silence that preceded it.
            self.bit_confidences = []
        elif self.synced:
            self.byte_counter += 1
            if self.byte_counter == 8:
                byte_val = lasts_byte & 0xFF
                self.bytes_decoded += 1
                self._prev_decoded_byte = byte_val

                if self._post_message_mode:
                    # Post-message mode: capture terminator bytes that follow
                    # a completed SAME message.  Different ENDECs append 0x00
                    # or 0xFF bytes here before the inter-burst silence.
                    # Skip carriage-return (0x0D / 13) and line-feed (0x0A / 10):
                    # FCC Section 11.31 encoding appends a trailing \r after the header,
                    # which must be ignored here to avoid prematurely exiting
                    # post-message capture before ENDEC terminator bytes arrive.
                    if byte_val in (0x00, 0xFF, 0xA9):
                        if self._terminator_byte is None:
                            self._terminator_byte = byte_val
                            self._terminator_run = 1
                        elif self._terminator_byte == byte_val:
                            self._terminator_run += 1
                        else:
                            # Different terminator type - flush previous run
                            self._flush_terminator_run()
                            self._terminator_byte = byte_val
                            self._terminator_run = 1
                        self._post_message_bytes_captured += 1

                        # KR8MER EAS Station fingerprint is a precise 3 × 0xA9
                        # trill.  Once it's captured, lock it in immediately —
                        # any further 0xFF accumulated during inter-burst
                        # silence (the FSK demod outputs mark bits when the
                        # signal goes quiet) would corrupt the fingerprint
                        # vote with bogus SAGE_DIGITAL_3644 evidence.
                        eas_station_locked = (
                            self._terminator_byte == 0xA9
                            and self._terminator_run >= 3
                        )

                        # Real ENDEC terminator runs are 1-3 bytes.  Anything
                        # longer is signal noise — cap at MAX_TERMINATOR_BYTES
                        # so a long silence cannot accumulate hundreds of
                        # 0xFF/0x00 bytes into a single huge run.
                        if (
                            eas_station_locked
                            or self._terminator_run >= self._MAX_TERMINATOR_BYTES_PER_BURST
                            or self._post_message_bytes_captured >= self._MAX_TERMINATOR_BYTES_PER_BURST
                        ):
                            self._flush_terminator_run()
                            self._post_message_mode = False
                            self._post_message_bytes_captured = 0
                            self._update_endec_from_evidence()
                    elif byte_val in (10, 13):
                        pass  # Skip CR/LF - part of FCC Section 11.31 header encoding
                    else:
                        # Non-terminator byte ends post-message capture
                        self._flush_terminator_run()
                        self._post_message_mode = False
                        self._post_message_bytes_captured = 0
                        self._update_endec_from_evidence()
                        if byte_val != self.PREAMBLE_BYTE:
                            self.synced = False
                    self.byte_counter = 0
                    return

                if 32 <= byte_val <= 126 or byte_val in (10, 13):
                    char = chr(byte_val)
                    if not self.in_message and char in ("Z", "N"):
                        # 'Z' -> start of a ZCZC header burst.
                        # 'N' -> start of an NNNN EOM burst (never starts with 'Z').
                        # Both begin with their own preamble so synced=True here
                        # means we just came off a valid 0xAB preamble run.
                        self.in_message = True
                        self._burst_start_sample = self._current_sample_position
                        self.current_msg = [char]
                    elif self.in_message:
                        self.current_msg.append(char)
                        msg_text = "".join(self.current_msg)
                        if self._is_message_complete(msg_text, char):
                            self._on_message_complete(msg_text)
                            # Enter post-message mode instead of full reset so
                            # the DLL continues decoding terminator bytes.
                            self.current_msg = []
                            self.in_message = False
                            self.bit_confidences = []
                            self._burst_start_sample = None
                            self._post_message_mode = True
                            self._post_message_bytes_captured = 0
                            # Keep self.synced = True for terminator capture
                        elif len(self.current_msg) > self.MAX_MSG_LEN:
                            self._reset_message_state()
                else:
                    self.synced = False
                    if self.in_message:
                        self._reset_message_state()
                self.byte_counter = 0

    def _is_message_complete(self, msg_text: str, last_char: str) -> bool:
        # NNNN EOM: complete as soon as we have the 4-character string "NNNN".
        # Some ENDECs append \r or \n; the existing CR/LF check below catches
        # those.  This check handles transmitters that send exactly "NNNN" with
        # no terminator (the 4th 'N' is the last printable byte in the burst).
        if last_char == "N" and len(self.current_msg) >= 4 and msg_text[:4] == "NNNN":
            return True
        if last_char in ("\r", "\n"):
            return "ZCZC" in msg_text or "NNNN" in msg_text
        if last_char == "-" and len(self.current_msg) > 40:
            dash_count = msg_text.count("-")
            if "+" in msg_text:
                try:
                    pre_exp, _ = msg_text.split("+", 1)
                    loc_segs = pre_exp.split("-")[3:]
                    loc_count = sum(
                        1 for s in loc_segs if len(s.strip()) == 6 and s.strip().isdigit()
                    )
                    min_dashes = 6 if loc_count <= 0 else 6 + max(loc_count - 1, 0)
                    if dash_count >= min_dashes:
                        return "ZCZC" in msg_text or "NNNN" in msg_text
                except (ValueError, IndexError):
                    pass
        return False

    def _on_message_complete(self, msg_text: str) -> None:
        msg_text = msg_text.strip()
        # Trim to last dash for ZCZC messages
        if "ZCZC" in msg_text and "-" in msg_text:
            msg_text = msg_text[: msg_text.rfind("-") + 1]

        # Record burst timing
        if self._burst_start_sample is not None:
            burst_end_sample = self._current_sample_position
            self.burst_sample_ranges.append(
                (self._burst_start_sample, burst_end_sample)
            )
            self._burst_sample_history.append(
                (self._burst_start_sample, burst_end_sample)
            )
            self._burst_start_sample = None
            if len(self._burst_sample_history) > 4:
                self._burst_sample_history = self._burst_sample_history[-4:]
            self.burst_timing_gaps_ms = compute_burst_timing_gaps_ms(
                self._burst_sample_history, self.sample_rate
            )

        confidence = (
            sum(self.bit_confidences) / len(self.bit_confidences)
            if self.bit_confidences
            else 0.0
        )
        self.messages.append(msg_text)

        if self.message_callback:
            self.message_callback(msg_text, confidence, list(self.burst_sample_ranges))

    def _flush_terminator_run(self) -> None:
        """Append the current terminator byte run to the accumulated list."""
        if self._terminator_byte is not None and self._terminator_run > 0:
            self._all_terminator_runs.append((self._terminator_byte, self._terminator_run))
        self._terminator_byte = None
        self._terminator_run = 0

    def _update_endec_from_evidence(self) -> None:
        """Recompute endec_mode from all gathered evidence (timing + terminator bytes)."""
        self.endec_mode = detect_endec_mode(
            self.messages,
            self.burst_timing_gaps_ms,
            self._all_terminator_runs,
            self._leading_null_detected,
        )

    def _reset_message_state(self) -> None:
        self.current_msg = []
        self.in_message = False
        self.synced = False
        self.bit_confidences = []
        self._burst_start_sample = None
        self._post_message_mode = False


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "SAMEDemodulatorCore",
    "apply_bandpass_filter",
    "compute_burst_timing_gaps_ms",
    "detect_endec_mode",
    "ENDEC_MODE_UNKNOWN",
    "ENDEC_MODE_DEFAULT",
    "ENDEC_MODE_NWS",
    "ENDEC_MODE_NWS_CRS",
    "ENDEC_MODE_NWS_BMH",
    "ENDEC_MODE_SAGE_3644",
    "ENDEC_MODE_SAGE_1822",
    "ENDEC_MODE_TRILITHIC",
]
