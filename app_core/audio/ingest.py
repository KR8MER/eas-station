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

"""
Unified Audio Ingest Controller

Provides a centralized interface for managing multiple audio sources
with standardized PCM output, metering, and health monitoring.
"""

import logging
import io
import queue
import threading
import time
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from .broadcast_queue import BroadcastQueue

logger = logging.getLogger(__name__)


class AudioSourceType(Enum):
    """Supported audio source types."""
    SDR = "sdr"
    ALSA = "alsa"
    PULSE = "pulse"
    FILE = "file"
    STREAM = "stream"


class AudioSourceStatus(Enum):
    """Audio source operational status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass
class AudioMetrics:
    """Real-time audio metrics from a source."""
    timestamp: float
    peak_level_db: float
    rms_level_db: float
    sample_rate: int
    channels: int
    frames_captured: int
    silence_detected: bool
    buffer_utilization: float
    metadata: Optional[Dict] = None  # Additional source-specific metadata (e.g., stream URL, codec, bitrate)


@dataclass
class AudioSourceConfig:
    """Configuration for an audio source."""
    source_type: AudioSourceType
    name: str
    enabled: bool = True
    priority: int = 100  # Lower numbers = higher priority
    sample_rate: int = 44100
    channels: int = 1
    buffer_size: int = 4096
    silence_threshold_db: float = -60.0
    silence_duration_seconds: float = 5.0
    # NOTE: `silence_threshold_db`/`silence_duration_seconds` above are
    # UNRELATED to dead-air alarming below: they drive the instantaneous
    # `AudioMetrics.silence_detected` flag, which has no debounce (it flips
    # on every pause between words) and exists only as a statistic for the
    # analytics aggregator.
    #
    # dead_air_* is the debounced alarm policy (tower light / rack buzzer)
    # -- per source, not station-wide. It used to be one shared
    # HardwareSettings row applied identically to every source, which
    # cannot express "alarm on silence for this source, never for that
    # one." That doesn't fit every source: a continuous broadcast monitor
    # going silent is a real fault, but a state-relay or alert-only feed
    # is *supposed* to be silent except when relaying an actual alert, and
    # applying the same policy to both means either constant false alarms
    # or disabling the feature everywhere. See
    # eas_monitoring_service.py::_install_dead_air_criteria() for where
    # this turns into a live app_core.audio.silence.SilenceCriteria.
    dead_air_enabled: bool = False
    dead_air_level_threshold_db: float = -65.0
    dead_air_detect_open_carrier: bool = True
    dead_air_flatness_threshold_pct: int = 25
    dead_air_duration_seconds: float = 20.0
    device_params: Dict = None

    def __post_init__(self):
        if self.device_params is None:
            self.device_params = {}


def _describe_stall(adapter: "AudioSourceAdapter", now: float, last_update: float) -> str:
    """Summarise an adapter's state for stall diagnostics.

    Designed for one-line operator-facing logs.  Pulls the bits most useful
    for triage — uptime, restart count, last error, and adapter-specific
    health signals (ffmpeg process state for streams, capture-handle state
    for SDR sources) — so root cause is visible without flipping debug logs.
    """
    parts: List[str] = []

    uptime = now - adapter._start_time if adapter._start_time else 0.0
    parts.append(f"uptime={uptime:.1f}s")
    parts.append(f"restarts={adapter._restart_count}")

    if last_update and last_update > 0:
        parts.append(f"last_sample_age={now - last_update:.1f}s")
    else:
        parts.append("last_sample_age=never")

    last_err = (adapter._last_error or "").strip()
    if last_err:
        parts.append(f"last_error={last_err[:120]!r}")

    # Stream-source-specific signals — exposed by StreamSourceAdapter only.
    process = getattr(adapter, "_ffmpeg_process", None)
    if process is not None:
        try:
            rc = process.poll()
        except Exception:
            rc = "poll-error"
        if rc is None:
            parts.append(f"ffmpeg_pid={process.pid}(running)")
        else:
            parts.append(f"ffmpeg_pid={process.pid}(exit={rc})")
        attempts = getattr(adapter, "_connection_attempts", None)
        successes = getattr(adapter, "_successful_connections", None)
        if attempts is not None:
            parts.append(f"ffmpeg_connects={successes}/{attempts}")
        url = getattr(adapter, "_resolved_stream_url", None) or getattr(adapter, "_stream_url", None)
        if url:
            parts.append(f"url={url}")

    # SDR-source-specific signals — exposed by RedisSDRSourceAdapter.
    receiver_id = getattr(adapter, "_receiver_id", None)
    if receiver_id:
        parts.append(f"receiver={receiver_id}")
        if getattr(adapter, "_capture_handle", None) is None:
            parts.append("capture_handle=none")

    return ", ".join(parts)


class AudioSourceAdapter(ABC):
    """Abstract base class for audio source adapters."""

    def __init__(self, config: AudioSourceConfig):
        self.config = config
        self.status = AudioSourceStatus.STOPPED
        self.error_message: Optional[str] = None
        self.metrics = AudioMetrics(
            timestamp=0.0,
            peak_level_db=-np.inf,
            rms_level_db=-np.inf,
            sample_rate=config.sample_rate,
            channels=config.channels,
            frames_captured=0,
            silence_detected=False,
            buffer_utilization=0.0,
            metadata={'source_category': config.source_type.value}
        )
        self._stop_event = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        
        # Per-source BroadcastQueue for non-destructive audio distribution
        # This allows multiple consumers (Icecast, web streaming, monitoring) to
        # receive audio from this source independently without competing for chunks.
        # CRITICAL: EAS monitor CANNOT drop packets - larger queue prevents drops during processing spikes
        # 24/7/365 RELIABILITY: Increased buffer to handle network hiccups and temporary slowdowns
        self._source_broadcast = BroadcastQueue(
            name=f"source-{config.name}",
            max_queue_size=10000  # ~853s buffer (14.2 min) at any sample rate
                                  # At 48kHz: 10000 chunks × 4096 samples = 40.96M samples / 48kHz = 853s
                                  # Handles temporary network issues, consumer slowdowns, GC pauses
        )
        
        # Separate 16kHz broadcast queue for EAS monitor
        # ARCHITECTURAL FIX: Resample BEFORE queueing to reduce memory and eliminate conversion bottleneck
        # At 16kHz: same 10000 chunk buffer = ~853s (14.2 min) - resampling preserves duration
        # 24/7/365 RELIABILITY: This buffer must NEVER drop packets for EAS monitoring
        self._eas_broadcast = BroadcastQueue(
            name=f"eas-{config.name}",
            max_queue_size=10000  # ~853s buffer (14.2 min) at 16kHz
                                  # 10000 chunks × 1365 samples (resampled) = 13.65M / 16kHz = 853s
                                  # Ensures EAS monitor never starves even during system load spikes
        )
        
        self._last_metrics_update = 0.0
        self._start_time = 0.0

        # Debounced dead-air monitor. Owns its own thresholds so it can be
        # reconfigured at runtime from the admin UI without restarting the
        # source. `silence_detected` on AudioMetrics stays exactly as it
        # was -- an instantaneous per-chunk flag feeding the analytics
        # rate -- so nothing downstream of it changes behaviour.
        from .silence import SilenceMonitor
        self._silence_monitor = SilenceMonitor(config.name)
        # Optional callback(source_name: str, updates: dict) invoked on each
        # ICY metadata change.  Set by the monitoring service to persist
        # now-playing events to the database.
        self.on_metadata_change = None

        # Monotonically-incrementing injection sequence counter.  The EAS stream
        # injector increments this immediately before publishing EAS chunks so
        # that IcecastStreamer can detect a new injection and flush its local
        # pre-buffer, eliminating the ~7.5 s delay before EAS audio reaches
        # FFmpeg (and therefore Icecast listeners).
        self._eas_inject_seq: int = 0

        # EAS broadcast gate — when set, the capture loop does NOT publish live
        # audio chunks to _source_broadcast.  This prevents live source audio
        # from interleaving with EAS alert audio during an EAS injection, which
        # would produce garbled/mixed audio in the Icecast stream.  The capture
        # loop continues to read audio (keeping the source pipeline alive and
        # the EAS broadcast queue populated) while gated.
        self._eas_injection_active = threading.Event()

        # Pending audio injection inlet — float32 chunks at the source's
        # native sample rate.  The capture loop drains this queue after each
        # real audio read, publishing injected chunks through the EXACT SAME
        # path as live source audio (_source_broadcast + resample → _eas_broadcast).
        # This ensures test signals exercise the full 24/7 pipeline rather than
        # bypassing the capture loop and going straight to the decoder.
        self._inject_pending: queue.Queue = queue.Queue(maxsize=10000)

        # Stateful EAS resampler (see _resample_for_eas / eas_resampler.py).
        # Carries filter history and remainder samples across chunks so the
        # 16 kHz EAS stream has no chunk-boundary discontinuities.  Recreated
        # whenever config.sample_rate changes.
        self._eas_resampler = None
        self._eas_resampler_rate: Optional[int] = None
        # Reconnection support
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._last_error_time = 0.0
        # Activity tracking for capture loop optimization
        self._had_data_activity = False  # Some sources set this when they read data but can't decode yet
        self._restart_lock = threading.Lock()
        self._restart_count = 0
        self._last_restart = 0.0
        self._last_error: Optional[str] = None
        # Circuit breaker: a source that fails to restart repeatedly is
        # quarantined for a cooldown period so the monitor stops hammering it.
        # This prevents one broken stream (bad URL, missing hardware, persistent
        # exception) from monopolizing CPU and log volume, and isolates it from
        # the rest of the audio system.
        self._consecutive_failed_restarts = 0
        self._quarantine_threshold = 3      # failed restarts before quarantine
        self._quarantine_seconds = 60.0      # base cooldown before retrying
        self._quarantined_until = 0.0
        # Quarantine uses exponential backoff.  A source that keeps coming
        # back broken doubles its cooldown each time, so a permanently dead
        # stream settles at one retry every ``_max_quarantine_seconds``
        # instead of hammering the upstream — and flooding the alert log —
        # every ``_quarantine_seconds`` forever.  Cleared by ``note_healthy``.
        self._quarantine_escalations = 0
        self._max_quarantine_seconds = 900.0  # 15 minutes
        # ``start()`` returning True only proves the capture *launched* (the
        # ffmpeg process spawned, the SDR handle opened).  It does not prove
        # audio ever arrives.  Until the health monitor sees a real sample the
        # restart stays provisional, so the circuit-breaker counters must not
        # be cleared.  See ``note_healthy``.
        self._restart_unconfirmed = False

    @abstractmethod
    def _start_capture(self) -> None:
        """Start the audio capture implementation."""
        pass

    @abstractmethod
    def _stop_capture(self) -> None:
        """Stop the audio capture implementation."""
        pass

    @abstractmethod
    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read a chunk of audio data from the source."""
        pass

    def start(self) -> bool:
        """Start audio capture in a separate thread."""
        if self.status == AudioSourceStatus.ERROR:
            # Allow restart from ERROR state: reset to STOPPED first so the
            # stop_event and capture thread are cleaned up before re-launching.
            logger.info(f"Source {self.config.name} is in ERROR state; resetting before restart")
            self._stop_event.set()
            if self._capture_thread and self._capture_thread.is_alive():
                self._capture_thread.join(timeout=3.0)
            try:
                self._stop_capture()
            except Exception:
                pass
            self.status = AudioSourceStatus.STOPPED
            self.error_message = None

        if self.status != AudioSourceStatus.STOPPED:
            logger.warning(f"Source {self.config.name} already running")
            return False

        try:
            self.status = AudioSourceStatus.STARTING
            self._stop_event.clear()
            self._start_capture()

            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                name=f"audio-{self.config.name}",
                daemon=True
            )
            self._capture_thread.start()

            # Wait briefly to ensure startup
            time.sleep(0.1)
            if self.status == AudioSourceStatus.STARTING:
                self.status = AudioSourceStatus.RUNNING

            self._start_time = time.time()
            self._last_metrics_update = time.time()
            self._last_error = None
            logger.info(f"Started audio source: {self.config.name}")
            return True

        except Exception as e:
            self.status = AudioSourceStatus.ERROR
            self.error_message = str(e)
            self._last_error = str(e)
            logger.error(f"Failed to start audio source {self.config.name}: {e}")
            return False

    def stop(self) -> None:
        """Stop audio capture."""
        if self.status == AudioSourceStatus.STOPPED:
            return

        logger.info(f"Stopping audio source: {self.config.name}")
        self.status = AudioSourceStatus.STOPPED
        self.error_message = None  # Clear any error message
        self._stop_event.set()
        self._start_time = 0.0

        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=5.0)
        
        try:
            self._stop_capture()
        except Exception as e:
            logger.error(f"Error stopping capture for {self.config.name}: {e}")

    def get_broadcast_queue(self) -> BroadcastQueue:
        """Get this source's broadcast queue for subscribing to audio.
        
        Creates independent subscriptions that each receive a copy of all
        audio chunks. This allows multiple consumers (Icecast streams,
        web streaming, EAS monitoring) to receive audio without competing.
        
        Returns:
            BroadcastQueue instance for this source
        """
        return self._source_broadcast
    
    def get_eas_broadcast_queue(self) -> BroadcastQueue:
        """
        Get the 16kHz EAS broadcast queue for this source.
        
        ARCHITECTURAL FIX: This queue contains pre-resampled 16kHz audio,
        eliminating the need for EAS monitor to resample and reducing queue memory by 3x.
        
        Returns:
            BroadcastQueue instance with 16kHz audio for EAS monitoring
        """
        return self._eas_broadcast

    def schedule_inject(self, chunk: np.ndarray) -> None:
        """Schedule a float32 audio chunk (at the source's native sample rate)
        for injection into the capture loop's processing path.

        Injected chunks are published to both ``_source_broadcast`` (native
        rate, heard by IcecastStreamer) and ``_eas_broadcast`` (resampled to
        16 kHz by the capture loop, heard by the SAME decoder) — the identical
        path taken by every real audio frame from the live source.

        Because the chunk must pass through the live capture loop thread, this
        method returns immediately; delivery happens on the next loop iteration.
        If the capture loop is stopped or the source is not running, injected
        chunks remain queued but are never processed, which correctly causes a
        test to fail rather than appear to succeed against a dead source.

        Args:
            chunk: Float32 numpy array at ``self.config.sample_rate`` Hz.
        """
        try:
            self._inject_pending.put_nowait(chunk)
        except queue.Full:
            logger.debug(
                "inject_pending queue full for '%s' — dropping chunk",
                self.config.name,
            )

    def _capture_loop(self) -> None:
        """Main capture loop running in separate thread."""
        logger.debug(f"Capture loop started for {self.config.name}")

        # 24/7 RELIABILITY: Track consecutive errors for graceful degradation
        # Don't break on single errors - only stop after persistent failures
        consecutive_errors = 0
        max_consecutive_errors = 50  # Allow up to 50 errors (~5 seconds at 10 errors/sec)
        last_error_log_time = 0.0
        error_log_interval = 1.0  # Rate-limit error logging to 1/second

        while not self._stop_event.is_set():
            try:
                audio_chunk = self._read_audio_chunk()
                if audio_chunk is not None:
                    # Reset error counter on successful read
                    consecutive_errors = 0

                    # Update metrics
                    self._update_metrics(audio_chunk)

                    # Publish to per-source broadcast queue - all subscribers get independent copies
                    # This enables multiple consumers (Icecast, web streaming, controller pump)
                    # to receive audio without competing for chunks.
                    # Gate: skip publishing live audio while an EAS alert is being injected so
                    # that EAS chunks are not interleaved with live source audio in the stream.
                    if not self._eas_injection_active.is_set():
                        self._source_broadcast.publish(audio_chunk)

                    # ARCHITECTURAL FIX: Resample to 16kHz and publish to EAS queue
                    # This eliminates resampling bottleneck and reduces queue memory by 3x
                    #
                    # GATE: When inject_pending has queued test-signal chunks, suppress the
                    # live audio chunk from _eas_broadcast.  Interleaving live source audio
                    # (e.g. music from a radio stream) with the injected FSK tones destroys
                    # the coherent preamble the SAME DLL needs to lock on, causing the EAS
                    # decoder to miss the injected test signal entirely.  This gate does NOT
                    # affect OTA EAS detection: inject_pending is empty during normal 24/7
                    # monitoring, so live audio always reaches the EAS decoder unimpeded.
                    if self._inject_pending.empty():
                        eas_chunk = self._resample_for_eas(audio_chunk)
                        if eas_chunk is not None:
                            self._eas_broadcast.publish(eas_chunk)
                else:
                    # No decoded audio chunk available
                    # Only sleep if source had no data activity (prevents busy loops on truly idle sources)
                    # Stream sources may read HTTP data but not have enough to decode yet - don't sleep in that case
                    if not self._had_data_activity:
                        time.sleep(0.05)  # 50ms sleep to prevent CPU spinning on idle sources

                # Drain any pending injected audio through the same publish path
                # as real source audio.  This ensures test signals exercise the
                # actual capture pipeline (resampling, both broadcast queues) and
                # will NOT fire if the capture loop itself is stopped.
                try:
                    while True:
                        injected = self._inject_pending.get_nowait()
                        self._source_broadcast.publish(injected)
                        eas_injected = self._resample_for_eas(injected)
                        if eas_injected is not None:
                            self._eas_broadcast.publish(eas_injected)
                except queue.Empty:
                    pass

            except Exception as e:
                consecutive_errors += 1
                current_time = time.time()

                # Rate-limit error logging to avoid log spam
                if current_time - last_error_log_time >= error_log_interval:
                    logger.error(
                        f"Error in capture loop for {self.config.name} "
                        f"(consecutive: {consecutive_errors}/{max_consecutive_errors}): {e}",
                        exc_info=(consecutive_errors == 1)  # Full traceback on first error only
                    )
                    last_error_log_time = current_time

                # Only break after too many consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors ({consecutive_errors}) for {self.config.name}, stopping"
                    )
                    self.status = AudioSourceStatus.ERROR
                    self.error_message = str(e)
                    self._last_error = str(e)
                    break

                # Brief sleep before retry to prevent CPU spinning on persistent errors
                time.sleep(0.01)

        logger.debug(f"Capture loop stopped for {self.config.name}")
    
    def _resample_for_eas(self, audio_chunk: np.ndarray) -> Optional[np.ndarray]:
        """
        Resample audio chunk to 16kHz for EAS decoder.

        ARCHITECTURAL FIX: Resample BEFORE queueing to reduce memory and eliminate bottleneck.

        CONTINUITY FIX: Resampling is STATEFUL across chunks.  The previous
        implementation resampled each ~100 ms chunk independently, which
        assumed zeros outside every chunk and stamped a filter-edge transient
        onto every chunk boundary (~10 audible glitches/second on 44.1 kHz
        sources) and, on the integer-decimation path, silently dropped
        ``len % factor`` samples per chunk.  A per-source streaming resampler
        (see app_core/audio/eas_resampler.py) now carries filter history and
        remainder samples across chunks, so the concatenated 16 kHz stream is
        identical to resampling the whole signal at once.

        The resampler is recreated whenever ``config.sample_rate`` changes —
        stream/file sources detect their real rate asynchronously via FFmpeg
        stderr (see StreamSourceAdapter._stderr_pump), and stale state from
        the wrong rate must not leak into the corrected stream.

        Args:
            audio_chunk: Audio at source sample rate (e.g., 48kHz)

        Returns:
            Resampled audio at 16kHz, or None if error / nothing to emit yet
        """
        try:
            # Convert to mono if stereo
            if audio_chunk.ndim == 2:
                audio_chunk = audio_chunk.mean(axis=1)
            elif audio_chunk.ndim > 2:
                audio_chunk = audio_chunk.flatten()

            source_rate = int(self.config.sample_rate)

            # If already at 16kHz, pass through
            if source_rate == 16000:
                return audio_chunk.astype(np.float32)

            if self._eas_resampler is None or self._eas_resampler_rate != source_rate:
                from .eas_resampler import make_eas_resampler
                self._eas_resampler = make_eas_resampler(source_rate, 16000)
                self._eas_resampler_rate = source_rate
                if self._eas_resampler is not None:
                    logger.info(
                        "EAS resampler for '%s': %d Hz → 16000 Hz (%s)",
                        self.config.name,
                        source_rate,
                        type(self._eas_resampler).__name__,
                    )

            if self._eas_resampler is None:
                return audio_chunk.astype(np.float32)

            resampled = self._eas_resampler.process(audio_chunk)
            if resampled is None or len(resampled) == 0:
                # Streaming resampler is still filling its filter context
                # (a few ms at start-of-stream) — nothing to publish yet.
                return None
            return resampled

        except Exception as e:
            logger.error("Error resampling audio for EAS: %s", e)
            return None

    def _update_metrics(self, audio_chunk: np.ndarray) -> None:
        """Update real-time metrics from audio chunk."""
        current_time = time.time()

        # Limit update frequency
        if current_time - self._last_metrics_update < 0.1:
            return

        # Calculate audio levels
        if len(audio_chunk) > 0:
            samples_for_metrics = audio_chunk
            if isinstance(audio_chunk, np.ndarray) and audio_chunk.ndim > 1:
                samples_for_metrics = audio_chunk.mean(axis=1)
            # Peak level in dBFS
            peak = np.max(np.abs(samples_for_metrics))
            peak_db = 20 * np.log10(max(peak, 1e-10))

            # RMS level in dBFS
            rms = np.sqrt(np.mean(samples_for_metrics ** 2))
            rms_db = 20 * np.log10(max(rms, 1e-10))

            # Silence detection
            silence_detected = rms_db < self.config.silence_threshold_db

        else:
            peak_db = rms_db = -np.inf
            silence_detected = True

        # Preserve existing metadata (e.g., RBDS information) across metric updates
        current_metadata = self.metrics.metadata if self.metrics else None
        if current_metadata is None:
            current_metadata = {}
        current_metadata['source_restart_count'] = self._restart_count
        current_metadata['source_last_error'] = self._last_error
        current_metadata['source_start_time'] = self._start_time
        try:
            current_metadata['dead_air'] = self._silence_monitor.snapshot()
        except Exception:
            current_metadata['dead_air'] = None

        # Feed the debounced dead-air monitor. It gets the same samples the
        # levels were measured from, because the spectral axis needs the
        # waveform -- a level alone cannot tell programme audio from the
        # full-scale hiss an SDR emits when its station goes off the air.
        try:
            self._silence_monitor.process(
                samples_for_metrics if len(audio_chunk) > 0 else None,
                rms_db if np.isfinite(rms_db) else -120.0,
            )
        except Exception as exc:
            logger.debug(
                "Dead-air monitor failed for %s: %s", self.config.name, exc
            )

        # Update metrics
        # Use broadcast queue utilization instead of legacy queue for accurate streaming health
        buffer_util = self._source_broadcast.get_average_utilization()
        
        self.metrics = AudioMetrics(
            timestamp=current_time,
            peak_level_db=peak_db,
            rms_level_db=rms_db,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            frames_captured=self.metrics.frames_captured + len(audio_chunk),
            silence_detected=silence_detected,
            buffer_utilization=buffer_util,
            metadata=current_metadata,
        )

        self._last_metrics_update = current_time

    def is_quarantined(self) -> bool:
        """Return True if this source is in restart cooldown after repeated failures."""
        return time.time() < self._quarantined_until

    def quarantine_backoff_seconds(self) -> float:
        """Cooldown the *next* quarantine will use, with exponential backoff.

        Doubles per escalation from ``_quarantine_seconds``, capped at
        ``_max_quarantine_seconds``.  A stream that is simply off the air
        therefore decays to one retry every 15 minutes rather than retrying
        every minute indefinitely.
        """
        return min(
            self._quarantine_seconds * (2 ** self._quarantine_escalations),
            self._max_quarantine_seconds,
        )

    def enter_quarantine(self) -> float:
        """Put the source into cooldown and return the applied duration."""
        cooldown = self.quarantine_backoff_seconds()
        self._quarantined_until = time.time() + cooldown
        self._quarantine_escalations += 1
        return cooldown

    def note_healthy(self) -> None:
        """Confirm the source is genuinely delivering audio.

        This is the *only* place the restart circuit breaker is cleared. The
        health monitor calls it when it observes a metrics update produced by
        a real audio chunk (not the timestamp ``start()`` writes at launch),
        which is the sole evidence that a restart actually worked.
        """
        self._restart_unconfirmed = False
        self._consecutive_failed_restarts = 0
        self._quarantine_escalations = 0
        self._quarantined_until = 0.0

    def restart(
        self,
        reason: str,
        *,
        delay: float = 0.25,
        max_attempts: int = 2,
    ) -> bool:
        """Attempt to restart the adapter when it becomes unhealthy.

        A source that fails to restart ``_quarantine_threshold`` consecutive
        times is placed in quarantine for ``_quarantine_seconds`` so the
        monitor loop stops trying.  This prevents one broken stream from
        consuming CPU, log volume, and lock contention shared with healthy
        sources.
        """

        if not self.config.enabled:
            logger.debug(
                "Skipping restart for %s because the source is disabled",
                self.config.name,
            )
            return False

        if self.is_quarantined():
            remaining = max(0.0, self._quarantined_until - time.time())
            logger.debug(
                "%s: quarantined after %d failed restarts; %.1fs remaining (%s)",
                self.config.name,
                self._consecutive_failed_restarts,
                remaining,
                reason,
            )
            return False

        attempts = max(1, int(max_attempts))
        with self._restart_lock:
            for attempt in range(1, attempts + 1):
                logger.warning(
                    "%s: restarting audio source (%s) [attempt %s/%s]",
                    self.config.name,
                    reason,
                    attempt,
                    attempts,
                )
                try:
                    self.stop()
                except Exception as exc:
                    logger.error(
                        "%s: error during stop() before restart: %s",
                        self.config.name,
                        exc,
                        exc_info=True,
                    )
                if delay > 0:
                    time.sleep(delay)
                try:
                    started = self.start()
                except Exception as exc:
                    logger.error(
                        "%s: unexpected exception during restart: %s",
                        self.config.name,
                        exc,
                        exc_info=True,
                    )
                    started = False
                if started:
                    self._restart_count += 1
                    self._last_restart = time.time()
                    self._last_error = None
                    # NOTE: the circuit-breaker counters
                    # (``_consecutive_failed_restarts``, ``_quarantined_until``,
                    # ``_quarantine_escalations``) are deliberately NOT cleared
                    # here.  ``start()`` only reports that the capture launched;
                    # a dead stream URL or a dead SDR relaunches cleanly every
                    # single time while never delivering a sample.  Clearing the
                    # breaker on launch made it unreachable for exactly that
                    # failure mode, so the monitor escalated to ERROR, waited out
                    # a flat 60s quarantine, restarted, had its quarantine wiped,
                    # and stalled again — forever, at roughly one cycle every
                    # three minutes.  Only ``note_healthy()`` — called by the
                    # health monitor once audio actually flows — clears them.
                    self._restart_unconfirmed = True
                    logger.info(
                        "%s: audio source restarted successfully after %s "
                        "(awaiting audio to confirm recovery)",
                        self.config.name,
                        reason,
                    )
                    return True
                backoff = min(delay * attempt, 2.0)
                if backoff > 0:
                    time.sleep(backoff)

            self._consecutive_failed_restarts += 1
            if self._consecutive_failed_restarts >= self._quarantine_threshold:
                cooldown = self.enter_quarantine()
                logger.error(
                    "%s: quarantining audio source for %.0fs after %d consecutive "
                    "failed restarts (last reason: %s)",
                    self.config.name,
                    cooldown,
                    self._consecutive_failed_restarts,
                    reason,
                )
            else:
                logger.error(
                    "%s: failed to restart audio source after %s attempt(s) (%s)",
                    self.config.name,
                    attempts,
                    reason,
                )
            return False

    def get_waveform_data(self) -> np.ndarray:
        """Waveform visualization is disabled to reduce CPU usage."""
        return np.array([], dtype=np.float32)

    def get_spectrogram_data(self) -> np.ndarray:
        """Spectrogram visualization is disabled to reduce CPU usage."""
        return np.array([], dtype=np.float32)


class AudioIngestController:
    """Main controller for managing multiple audio sources."""

    # Relative severity of the source-alert states, used to decide whether a
    # repeat alert is worth emitting.  A failing source oscillates between
    # these as it is restarted, so only an *escalation* breaks the dedup.
    _ALERT_SEVERITY = {
        "stall": 1,
        "disconnected": 2,
        "error": 3,
    }

    def __init__(
        self,
        *,
        enable_monitor: bool = True,
        monitor_interval: float = 1.0,
        stall_seconds: float = 5.0,
        flask_app=None,
    ) -> None:
        self._sources: Dict[str, AudioSourceAdapter] = {}
        self._active_source: Optional[str] = None
        self._lock = threading.RLock()
        self._monitor_enabled = enable_monitor
        self._monitor_interval = max(0.5, float(monitor_interval))
        self._monitor_stall_seconds = max(1.0, float(stall_seconds))
        self._monitor_grace_period = 5.0
        self._monitor_stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._flask_app = flask_app  # Store Flask app for app context in background threads
        self._metadata_change_callback = None  # Applied to every source (current and future)
        self._source_alert_callback = None  # Optional: called on source events (restart/error/stop)
        # Tracks how many times in a row a source has stalled without producing a
        # single fresh sample between restarts.  ``adapter.restart()`` only counts
        # a restart as failed when ``start()`` raises or returns False, so a stream
        # whose ffmpeg launches fine but never delivers audio (dead URL, dead SDR)
        # would otherwise cycle forever.  When this counter exceeds
        # ``_stall_quarantine_threshold`` the monitor escalates the source to
        # ERROR and lets the adapter's own quarantine timer back off the loop.
        self._consecutive_stalls: Dict[str, int] = {}
        self._stall_quarantine_threshold = 3
        # Last (state, message) reported per source, with its timestamp, so a
        # source stuck in ERROR does not emit an identical alert row on every
        # retry cycle.  Cleared as soon as the source is healthy again.
        self._alerted_states: Dict[str, Tuple[str, float]] = {}
        self._alert_renotify_seconds = 900.0  # re-surface a stuck source every 15 min
        # Headers injected via inject_eas_test_signal() — decoded alerts whose
        # raw_header matches an entry here are known-synthetic and get confidence=1.0.
        self._synthetic_headers: set = set()
        self._synthetic_headers_lock = threading.Lock()
        # Per-source recovery threads.  Restarting a stalled source involves
        # blocking work (capture-thread joins, process termination, URL
        # resolution, network connections) that can take tens of seconds.
        # Running it inline in the shared health-monitor thread let ONE
        # stalled capture delay stall detection and recovery for every other
        # source.  Each recovery therefore runs in its own daemon thread,
        # with at most one in flight per source.
        self._recovery_threads: Dict[str, threading.Thread] = {}
        self._recovery_lock = threading.Lock()

        if enable_monitor:
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="AudioSourceMonitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def set_metadata_change_callback(self, callback) -> None:
        """Store a metadata-change callback and apply it to all current and future sources."""
        self._metadata_change_callback = callback
        with self._lock:
            for adapter in self._sources.values():
                adapter.on_metadata_change = callback

    def set_source_alert_callback(self, callback) -> None:
        """Register a callback invoked when a source event occurs (stall/error/disconnected).

        The callback receives ``(source_name: str, event_type: str, message: str)``
        and is called from within a Flask app context when one is available.
        """
        self._source_alert_callback = callback

    def add_source(self, source: AudioSourceAdapter) -> None:
        """Add an audio source to the controller."""
        with self._lock:
            if self._metadata_change_callback is not None:
                source.on_metadata_change = self._metadata_change_callback
            self._sources[source.config.name] = source
            logger.info(f"Added audio source: {source.config.name}")

    # NOTE on locking: ``self._lock`` guards ONLY the source registry.
    # ``adapter.start()`` / ``adapter.stop()`` perform blocking work (thread
    # joins, process termination, URL resolution, network connections) that
    # can take tens of seconds — holding the registry lock across those calls
    # froze every other consumer of the controller (metrics publishing,
    # status queries, EAS-monitor source discovery, Redis command handling)
    # whenever a single stalled capture was being stopped or restarted.

    def remove_source(self, name: str) -> None:
        """Remove an audio source from the controller."""
        with self._lock:
            source = self._sources.pop(name, None)
            if self._active_source == name:
                self._active_source = None
        if source is not None:
            source.stop()
            logger.info(f"Removed audio source: {name}")

    def update_source(self, name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a live config update to a running source.

        This is the separated-architecture counterpart of the field-by-field
        application ``webapp/admin/audio_ingest/routes_sources_write.py``'s
        PATCH route already does for integrated mode -- reached here over
        Redis via ``redis_commands.py``'s ``source_update`` command instead
        of a direct in-process attribute set, so a change made through the
        webapp takes effect on the audio-service's running adapter without a
        restart.
        """
        adapter = self.get_source(name)
        if adapter is None:
            return {'success': False, 'message': f'Source {name} not found'}

        cfg = adapter.config
        dead_air_changed = False

        if 'enabled' in updates:
            cfg.enabled = bool(updates['enabled'])
        if 'priority' in updates:
            cfg.priority = int(updates['priority'])
        if 'silence_threshold_db' in updates:
            cfg.silence_threshold_db = float(updates['silence_threshold_db'])
        if 'silence_duration_seconds' in updates:
            cfg.silence_duration_seconds = float(updates['silence_duration_seconds'])
        if 'dead_air_enabled' in updates:
            cfg.dead_air_enabled = bool(updates['dead_air_enabled'])
            dead_air_changed = True
        if 'dead_air_level_threshold_db' in updates:
            cfg.dead_air_level_threshold_db = float(updates['dead_air_level_threshold_db'])
            dead_air_changed = True
        if 'dead_air_detect_open_carrier' in updates:
            cfg.dead_air_detect_open_carrier = bool(updates['dead_air_detect_open_carrier'])
            dead_air_changed = True
        if 'dead_air_flatness_threshold_pct' in updates:
            cfg.dead_air_flatness_threshold_pct = int(updates['dead_air_flatness_threshold_pct'])
            dead_air_changed = True
        if 'dead_air_duration_seconds' in updates:
            cfg.dead_air_duration_seconds = float(updates['dead_air_duration_seconds'])
            dead_air_changed = True
        if 'device_params' in updates and isinstance(updates['device_params'], dict):
            if cfg.device_params is None:
                cfg.device_params = {}
            cfg.device_params.update(updates['device_params'])

        if dead_air_changed:
            monitor = getattr(adapter, '_silence_monitor', None)
            if monitor is not None:
                from app_core.audio.silence import criteria_from_source_config
                monitor.update_criteria(criteria_from_source_config(cfg))

        logger.info(f"Updated audio source {name} via update_source ({sorted(updates.keys())})")
        return {'success': True, 'message': f'Updated source {name}'}

    def start_source(self, name: str) -> bool:
        """Start a specific audio source (blocking work runs outside the lock)."""
        with self._lock:
            adapter = self._sources.get(name)
        if adapter is None:
            logger.error(f"Audio source not found: {name}")
            return False
        return adapter.start()

    def stop_source(self, name: str) -> None:
        """Stop a specific audio source (blocking work runs outside the lock)."""
        with self._lock:
            adapter = self._sources.get(name)
        if adapter is not None:
            adapter.stop()

    def start_all(self) -> None:
        """Start all enabled audio sources."""
        with self._lock:
            sources = list(self._sources.values())
        for source in sources:
            if source.config.enabled:
                source.start()

    def stop_all(self) -> None:
        """Stop all audio sources."""
        with self._lock:
            sources = list(self._sources.values())
        for source in sources:
            source.stop()

    def recovery_in_flight(self, name: str) -> bool:
        """True when a background recovery thread is currently running for a source."""
        with self._recovery_lock:
            thread = self._recovery_threads.get(name)
            return bool(thread and thread.is_alive())

    def spawn_recovery(self, name: str, action, reason: str) -> bool:
        """Run a blocking recovery action for one source in a dedicated thread.

        ``action`` is a zero-argument callable (typically wrapping
        ``adapter.restart(...)`` or a stop/start sequence).  At most one
        recovery per source is in flight at a time: returns True when a new
        recovery thread was started, False when one is already running.

        This is what keeps a stalled capture isolated: the blocking stop/
        start work happens here, off the shared health-monitor thread and
        off the metrics loop, so other sources keep decoding and the service
        keeps publishing metrics no matter how long one recovery takes.
        """
        with self._recovery_lock:
            existing = self._recovery_threads.get(name)
            if existing and existing.is_alive():
                logger.debug(
                    "%s: recovery already in flight — skipping duplicate (%s)",
                    name,
                    reason,
                )
                return False

            def _run() -> None:
                try:
                    if self._flask_app is not None:
                        with self._flask_app.app_context():
                            action()
                    else:
                        action()
                except Exception as exc:
                    logger.error(
                        "%s: recovery (%s) raised: %s", name, reason, exc, exc_info=True
                    )
                finally:
                    with self._recovery_lock:
                        self._recovery_threads.pop(name, None)

            thread = threading.Thread(
                target=_run,
                name=f"audio-recovery-{name}",
                daemon=True,
            )
            self._recovery_threads[name] = thread
            thread.start()
            return True

    def get_active_sample_rate(self) -> Optional[int]:
        """Return the current active source sample rate (or first configured rate)."""
        with self._lock:
            active = self._active_source
            if active and active in self._sources:
                metrics = self._sources[active].metrics
                if metrics and metrics.sample_rate:
                    return int(metrics.sample_rate)

            # Fall back to the first configured source's sample rate if active is unknown
            for adapter in self._sources.values():
                if adapter.config.sample_rate:
                    return int(adapter.config.sample_rate)

        return None

    def get_source_metrics(self, name: str) -> Optional[AudioMetrics]:
        """Get metrics for a specific source."""
        with self._lock:
            if name in self._sources:
                return self._sources[name].metrics
            return None

    def get_all_metrics(self) -> Dict[str, AudioMetrics]:
        """Get metrics for all sources."""
        with self._lock:
            return {name: source.metrics for name, source in self._sources.items()}

    def get_source_status(self, name: str) -> Optional[AudioSourceStatus]:
        """Get status for a specific source."""
        with self._lock:
            if name in self._sources:
                return self._sources[name].status
            return None

    def get_all_status(self) -> Dict[str, AudioSourceStatus]:
        """Get status for all sources."""
        with self._lock:
            return {name: source.status for name, source in self._sources.items()}

    def get_active_source(self) -> Optional[str]:
        """Get the currently active source name."""
        with self._lock:
            return self._active_source

    def list_sources(self) -> List[str]:
        """List all configured source names."""
        with self._lock:
            return list(self._sources.keys())

    def get_source(self, name: str) -> Optional[AudioSourceAdapter]:
        """Get a specific audio source adapter by name.
        
        Args:
            name: Source name to retrieve
            
        Returns:
            AudioSourceAdapter if found, None otherwise
        """
        with self._lock:
            return self._sources.get(name)

    def get_all_sources(self) -> Dict[str, AudioSourceAdapter]:
        """Get all audio source adapters.
        
        Returns:
            Dictionary mapping source names to AudioSourceAdapter instances
        """
        with self._lock:
            return dict(self._sources)  # Return a copy to prevent external modification

    def ensure_source_running(
        self,
        name: str,
        *,
        reason: str = "on-demand",
        timeout: float = 5.0,
    ) -> bool:
        """Ensure the specified source is running, restarting if required."""

        with self._lock:
            adapter = self._sources.get(name)

        if adapter is None or not adapter.config.enabled:
            return False

        if adapter.status == AudioSourceStatus.RUNNING:
            return True

        logger.warning(
            "Attempting to recover audio source %s due to %s (status=%s)",
            name,
            reason,
            adapter.status.value,
        )
        adapter.restart(f"{reason}")
        deadline = time.time() + max(1.0, timeout)
        while time.time() < deadline:
            if adapter.status == AudioSourceStatus.RUNNING:
                return True
            time.sleep(0.1)

        return adapter.status == AudioSourceStatus.RUNNING

    def inject_eas_test_signal(self, source_name: Optional[str] = None) -> Optional[str]:
        """Inject a SAME Required Weekly Test (RWT) signal through the live capture pipeline.

        Generates a standards-compliant SAME header + EOM burst at 16 kHz,
        resamples it to the source's native sample rate, then schedules it via
        ``schedule_inject()`` so the capture loop processes it identically to
        real source audio: publishing to ``_source_broadcast`` (Icecast hears
        it) and resampling to ``_eas_broadcast`` (SAME decoder hears it).

        This is the correct end-to-end test of the 24/7 pipeline:

        * If the capture loop is stopped or the source is disconnected, the
          injected chunks are never drained and the decoder never fires —
          correctly indicating a pipeline failure.
        * The re-broadcast audio from the alert is also injected into Icecast
          via ``inject_eas_audio()`` so listeners on the mount point hear it.

        Args:
            source_name: Name of the audio source to inject into.  If *None*,
                the first running source is used.

        Returns:
            The name of the source that received the signal, or *None* if no
            running source could be found.
        """
        import math
        from datetime import datetime, timezone

        from app_utils.eas_fsk import (
            SAME_BAUD,
            SAME_MARK_FREQ,
            SAME_SPACE_FREQ,
            encode_same_bits,
            generate_fsk_samples,
        )

        sample_rate = 16000
        amplitude = 0.7 * 32767

        # Build a minimal RWT SAME header for the current UTC time.
        now = datetime.now(timezone.utc)
        julian_day = now.timetuple().tm_yday
        timestamp = f"{julian_day:03d}{now:%H%M}"
        header = f"ZCZC-EAS-RWT-000000+0015-{timestamp}-EASTEST-"

        # Register this header as synthetic so the monitor can report confidence=1.0.
        with self._synthetic_headers_lock:
            self._synthetic_headers.add(header)

        # Encode header bits and render FSK samples once; reuse for all 3 bursts.
        same_bits = encode_same_bits(header, include_preamble=True)
        header_samples = generate_fsk_samples(
            same_bits,
            sample_rate=sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )

        silence = [0] * sample_rate  # 1-second inter-burst silence

        # FCC §11.31: transmit header 3 times with 1 s silence between bursts.
        all_samples: List[int] = []
        for i in range(3):
            all_samples.extend(header_samples)
            if i < 2:
                all_samples.extend(silence)

        all_samples.extend(silence)  # Post-header pause before EOM

        # EOM (NNNN) × 3 with 1-second silence between bursts.
        eom_bits = encode_same_bits("NNNN", include_preamble=True, include_cr=False)
        eom_samples = generate_fsk_samples(
            eom_bits,
            sample_rate=sample_rate,
            bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ,
            space_freq=SAME_SPACE_FREQ,
            amplitude=amplitude,
        )
        for i in range(3):
            all_samples.extend(eom_samples)
            if i < 2:
                all_samples.extend(silence)

        # Convert int16 range to float32 normalised [-1.0, 1.0] — the format
        # used by the EAS broadcast queues and UnifiedEASMonitorService.
        audio_np = np.array(all_samples, dtype=np.float32) / 32767.0

        # Locate the target source.
        with self._lock:
            sources_snapshot = dict(self._sources)

        target_adapter = None
        if source_name:
            adapter = sources_snapshot.get(source_name)
            if adapter and adapter.status == AudioSourceStatus.RUNNING:
                target_adapter = adapter
        else:
            for adapter in sources_snapshot.values():
                if adapter.status == AudioSourceStatus.RUNNING:
                    target_adapter = adapter
                    break

        if target_adapter is None:
            logger.warning("inject_eas_test_signal: no running audio source found")
            return None

        # Resample the 16 kHz test signal to the source's native sample rate so
        # that injected chunks travel through schedule_inject() → _capture_loop
        # → _source_broadcast (Icecast hears it) + _resample_for_eas() →
        # _eas_broadcast (SAME decoder hears it).
        #
        # This is the ONLY correct end-to-end test path: if the capture loop is
        # dead or the source is not producing audio, the injected chunks will
        # never be delivered and the test will correctly fail — unlike the old
        # approach of writing directly to _eas_broadcast, which fired the
        # decoder regardless of capture-pipeline health.
        native_rate = getattr(target_adapter.config, 'sample_rate', 44100) or 44100

        if native_rate != sample_rate:
            src_len = len(audio_np)
            dst_len = max(1, int(src_len * native_rate / sample_rate))
            src_idx = np.linspace(0, src_len - 1, dst_len)
            audio_native = np.interp(src_idx, np.arange(src_len), audio_np).astype(np.float32)
        else:
            audio_native = audio_np

        chunk_size = max(1, int(native_rate * 0.085))  # ~85 ms per chunk at native rate
        scheduled = 0
        for start in range(0, len(audio_native), chunk_size):
            chunk = audio_native[start:start + chunk_size]
            if len(chunk) > 0:
                target_adapter.schedule_inject(chunk)
                scheduled += 1

        logger.info(
            "Scheduled EAS test signal (%d samples @ %d Hz → %d native chunks) "
            "via capture-loop injection inlet for source '%s'",
            len(audio_np),
            sample_rate,
            scheduled,
            target_adapter.config.name,
        )

        # Do NOT call inject_eas_audio() here with the raw FSK tones.
        # The correct store-and-forward path is:
        #   schedule_inject() → capture loop → SAME decoder → _on_eom_received()
        #   → auto_forward_ota_alert() → EASBroadcaster.handle_alert()
        #   → inject_eas_audio(full_broadcast_wav)
        #
        # Calling inject_eas_audio() here with the raw FSK+EOM burst causes
        # Icecast listeners to hear the raw preamble tones immediately (before
        # the decoder even fires), followed by the EOM, and then the full
        # regenerated broadcast 1-2 minutes later — which is exactly backwards.
        # The EASBroadcaster already calls inject_eas_audio() with the complete
        # broadcast sequence (SAME headers + attention tone + narration + EOM)
        # once the EOM is received and the alert has been processed.

        return target_adapter.config.name

    def cleanup(self) -> None:
        """Cleanup all sources and threads."""
        self.stop_all()

        # Stop health monitor
        self._monitor_stop.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None

        with self._lock:
            self._sources.clear()
            self._active_source = None

    def _monitor_loop(self) -> None:
        """Background monitor that auto-recovers unhealthy sources.

        The outer try/except is the firewall that prevents one source's bug
        (DB error, exception in restart, AttributeError on a partially-
        initialized adapter, etc.) from killing the monitor thread for the
        entire audio system.  Each source is evaluated in isolation; a failure
        in one cannot affect the others or stop future monitoring iterations.
        """
        while not self._monitor_stop.is_set():
            try:
                now = time.time()
                with self._lock:
                    snapshot = list(self._sources.items())

                for name, adapter in snapshot:
                    try:
                        if self._flask_app:
                            with self._flask_app.app_context():
                                self._evaluate_source_health(name, adapter, now)
                        else:
                            self._evaluate_source_health(name, adapter, now)
                    except Exception as exc:
                        # Isolate per-source failures so they cannot take down
                        # other healthy sources or the monitor itself.
                        logger.error(
                            "Error evaluating health of source %s: %s",
                            name,
                            exc,
                            exc_info=True,
                        )
            except Exception as exc:
                # Last-line-of-defense for anything unexpected (e.g. lock
                # acquisition failure, snapshot iteration issue).  Logged and
                # swallowed so the monitor stays alive.
                logger.error("Unexpected error in audio monitor loop: %s", exc, exc_info=True)

            self._monitor_stop.wait(timeout=self._monitor_interval)

    def _evaluate_source_health(
        self,
        name: str,
        adapter: AudioSourceAdapter,
        now: float,
    ) -> None:
        if not adapter.config.enabled:
            self._consecutive_stalls.pop(name, None)
            # Drop the dedup record too, so re-enabling a source reports its
            # next failure immediately rather than being suppressed as a
            # "repeat" of whatever state it was in when it was switched off.
            self._alerted_states.pop(name, None)
            return

        # Quarantined sources are skipped to break the restart-storm cycle
        # that otherwise has the monitor flooding logs and CPU on a stream
        # that simply cannot be brought up right now.
        if adapter.is_quarantined():
            return

        # A background recovery (restart or escalation) is already running
        # for this source.  Skip evaluation so the stall counter doesn't
        # double-fire against a source that is mid-restart.
        if self.recovery_in_flight(name):
            return

        status = adapter.status

        if status == AudioSourceStatus.RUNNING:
            if adapter._start_time and now - adapter._start_time < self._monitor_grace_period:
                return
            last_update = adapter._last_metrics_update or (adapter.metrics.timestamp if adapter.metrics else 0.0)
            if last_update == 0.0 or now - last_update > self._monitor_stall_seconds:
                stalls = self._consecutive_stalls.get(name, 0) + 1
                self._consecutive_stalls[name] = stalls
                diagnostics = _describe_stall(adapter, now, last_update)
                logger.warning(
                    "%s: stalled capture detected (no audio samples for %.1fs, "
                    "consecutive=%d/%d) — %s",
                    name,
                    now - last_update if last_update else -1.0,
                    stalls,
                    self._stall_quarantine_threshold,
                    diagnostics,
                )
                if self._should_alert_state(name, "stall", now):
                    self._fire_source_alert(
                        adapter.config.name,
                        "stall",
                        "stalled capture (no audio samples)",
                    )

                if stalls >= self._stall_quarantine_threshold:
                    # adapter.restart() keeps succeeding because ``start()`` only
                    # checks process/handle creation, not whether samples ever
                    # arrive.  Force ERROR + quarantine here so the monitor
                    # stops cycling and operators get a visible failure state
                    # in the UI instead of an endless WARNING stream.
                    logger.error(
                        "%s: escalating to ERROR after %d consecutive stalls — %s",
                        name,
                        stalls,
                        diagnostics,
                    )

                    def _escalate(adapter=adapter, name=name, stalls=stalls, diagnostics=diagnostics):
                        try:
                            adapter.stop()
                        except Exception as exc:
                            logger.error("%s: error stopping stalled source: %s", name, exc, exc_info=True)
                        adapter.status = AudioSourceStatus.ERROR
                        adapter.error_message = f"no audio samples after {stalls} restarts ({diagnostics})"
                        adapter._last_error = adapter.error_message
                        # Exponential backoff: each escalation doubles the
                        # cooldown, so a source that is simply off the air
                        # stops being retried every minute forever.
                        cooldown = adapter.enter_quarantine()
                        logger.error(
                            "%s: quarantined for %.0fs after stall escalation "
                            "(escalation #%d)",
                            name,
                            cooldown,
                            adapter._quarantine_escalations,
                        )
                        if self._should_alert_state(name, "error", time.time()):
                            self._fire_source_alert(
                                adapter.config.name,
                                "error",
                                adapter.error_message,
                            )

                    self.spawn_recovery(name, _escalate, "stall escalation")
                    self._consecutive_stalls[name] = 0
                else:
                    # Blocking stop/start runs in a per-source recovery thread
                    # so one stalled capture cannot delay stall detection or
                    # recovery for any other source.
                    self.spawn_recovery(
                        name,
                        lambda adapter=adapter: adapter.restart("stalled capture (no audio samples)"),
                        "stalled capture",
                    )
            else:
                # Only treat the tick as "healthy" — and reset the stall
                # counter — when ``_last_metrics_update`` reflects an actual
                # audio chunk, not the timestamp ``start()`` writes at launch.
                # Without this guard the counter would clear on every cycle
                # immediately after ``adapter.restart()``, since the restart
                # itself bumps ``_last_metrics_update`` to "now" even when no
                # samples ever flowed — turning the escalation into a no-op
                # on streams that always stall.
                started_at = adapter._start_time or 0.0
                if last_update > started_at + self._monitor_grace_period:
                    self._consecutive_stalls.pop(name, None)
                    # Audio is genuinely flowing, so this is the one moment a
                    # restart can be called confirmed.  Clearing the breaker
                    # here — rather than in restart() on a successful launch —
                    # is what stops a permanently dead stream from resetting
                    # its own quarantine every cycle.
                    if adapter._restart_unconfirmed or adapter._quarantine_escalations:
                        logger.info(
                            "%s: audio confirmed flowing — clearing restart "
                            "circuit breaker",
                            name,
                        )
                    adapter.note_healthy()
                    self._alerted_states.pop(name, None)
            return

        if status in (AudioSourceStatus.ERROR, AudioSourceStatus.DISCONNECTED):
            # Fire once per distinct failure state rather than on every retry
            # cycle.  A source parked in ERROR was previously logging a fresh
            # alert row each time its quarantine lapsed, which is what filled
            # the Audio Alerts log with the same two sources for hours.
            message = adapter.error_message or f"source in {status.value} state"
            if self._should_alert_state(name, status.value, now):
                self._fire_source_alert(adapter.config.name, status.value, message)
            self.spawn_recovery(
                name,
                lambda adapter=adapter, status=status: adapter.restart(f"status={status.value}"),
                f"status={status.value}",
            )

    def _should_alert_state(self, name: str, state: str, now: float) -> bool:
        """Rate-limit repeated alerts for a source stuck failing.

        An alert fires when any of these hold:

        * nothing has been reported for this source since it was last healthy;
        * the failure has escalated in severity (a source that was merely
          stalling is now in ERROR);
        * ``_alert_renotify_seconds`` has elapsed, so a long outage is
          re-surfaced periodically rather than going silent forever.

        Severity ranking matters because a broken source *cycles*: it stalls,
        escalates to ERROR, gets restarted out of quarantine, stalls again.
        Keying on state equality alone would let that alternation fire a fresh
        pair of alerts on every cycle — which is precisely the flood this
        method exists to stop.

        Keying on state rather than message is also deliberate: the escalation
        message embeds ``_describe_stall`` diagnostics (uptime, restart count,
        last-sample age) that differ on every cycle, so a message-based
        signature would dedup nothing.  The message still reaches the callback;
        it just does not participate in the signature.
        """
        rank = self._ALERT_SEVERITY.get(state, 0)
        previous = self._alerted_states.get(name)
        if previous is not None:
            prev_state, reported_at = previous
            prev_rank = self._ALERT_SEVERITY.get(prev_state, 0)
            if (
                rank <= prev_rank
                and now - reported_at < self._alert_renotify_seconds
            ):
                return False
        self._alerted_states[name] = (state, now)
        return True

    def _fire_source_alert(self, source_name: str, event_type: str, message: str) -> None:
        """Invoke the registered source alert callback (non-blocking, best-effort)."""
        if self._source_alert_callback is None:
            return
        try:
            self._source_alert_callback(source_name, event_type, message)
        except Exception as exc:
            logger.error("Error in source alert callback for %s: %s", source_name, exc)

