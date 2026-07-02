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
from typing import Dict, List, Optional, Union

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

    # SDR-source-specific signals — exposed by SDRSourceAdapter.
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
        self._quarantine_seconds = 60.0      # cooldown before retrying
        self._quarantined_until = 0.0

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
                    self._consecutive_failed_restarts = 0
                    self._quarantined_until = 0.0
                    logger.info(
                        "%s: audio source restarted successfully after %s",
                        self.config.name,
                        reason,
                    )
                    return True
                backoff = min(delay * attempt, 2.0)
                if backoff > 0:
                    time.sleep(backoff)

            self._consecutive_failed_restarts += 1
            if self._consecutive_failed_restarts >= self._quarantine_threshold:
                self._quarantined_until = time.time() + self._quarantine_seconds
                logger.error(
                    "%s: quarantining audio source for %.0fs after %d consecutive "
                    "failed restarts (last reason: %s)",
                    self.config.name,
                    self._quarantine_seconds,
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
        # Headers injected via inject_eas_test_signal() — decoded alerts whose
        # raw_header matches an entry here are known-synthetic and get confidence=1.0.
        self._synthetic_headers: set = set()
        self._synthetic_headers_lock = threading.Lock()

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

    def remove_source(self, name: str) -> None:
        """Remove an audio source from the controller."""
        with self._lock:
            if name in self._sources:
                source = self._sources[name]
                source.stop()
                del self._sources[name]
                if self._active_source == name:
                    self._active_source = None
                logger.info(f"Removed audio source: {name}")

    def start_source(self, name: str) -> bool:
        """Start a specific audio source."""
        with self._lock:
            if name not in self._sources:
                logger.error(f"Audio source not found: {name}")
                return False

            return self._sources[name].start()

    def stop_source(self, name: str) -> None:
        """Stop a specific audio source."""
        with self._lock:
            if name in self._sources:
                self._sources[name].stop()

    def start_all(self) -> None:
        """Start all enabled audio sources."""
        with self._lock:
            for source in self._sources.values():
                if source.config.enabled:
                    source.start()

    def stop_all(self) -> None:
        """Stop all audio sources."""
        with self._lock:
            for source in self._sources.values():
                source.stop()

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
            return

        # Quarantined sources are skipped to break the restart-storm cycle
        # that otherwise has the monitor flooding logs and CPU on a stream
        # that simply cannot be brought up right now.
        if adapter.is_quarantined():
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
                self._fire_source_alert(adapter.config.name, "stall", "stalled capture (no audio samples)")

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
                    try:
                        adapter.stop()
                    except Exception as exc:
                        logger.error("%s: error stopping stalled source: %s", name, exc, exc_info=True)
                    adapter.status = AudioSourceStatus.ERROR
                    adapter.error_message = f"no audio samples after {stalls} restarts ({diagnostics})"
                    adapter._last_error = adapter.error_message
                    adapter._quarantined_until = time.time() + adapter._quarantine_seconds
                    self._fire_source_alert(
                        adapter.config.name,
                        "error",
                        adapter.error_message,
                    )
                    self._consecutive_stalls[name] = 0
                else:
                    adapter.restart("stalled capture (no audio samples)")
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
            return

        if status in (AudioSourceStatus.ERROR, AudioSourceStatus.DISCONNECTED):
            self._fire_source_alert(adapter.config.name, status.value, adapter.error_message or f"source in {status.value} state")
            adapter.restart(f"status={status.value}")

    def _fire_source_alert(self, source_name: str, event_type: str, message: str) -> None:
        """Invoke the registered source alert callback (non-blocking, best-effort)."""
        if self._source_alert_callback is None:
            return
        try:
            self._source_alert_callback(source_name, event_type, message)
        except Exception as exc:
            logger.error("Error in source alert callback for %s: %s", source_name, exc)

