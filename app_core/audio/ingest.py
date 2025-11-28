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
Unified Audio Ingest Controller

Provides a centralized interface for managing multiple audio sources
with standardized PCM output, metering, and health monitoring.
"""

import asyncio
import logging
import queue
import threading
import time
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
        # Increased to 2000 to prevent overflow at 48 seconds (44100Hz = ~180s buffer @ 4096 samples/chunk)
        # Previous 500 limit caused stuttering after 45-48 seconds of playback
        self._audio_queue = queue.Queue(maxsize=2000)
        self._last_metrics_update = 0.0
        self._start_time = 0.0
        # Waveform buffer for visualization (stores last 2048 samples)
        self._waveform_buffer = np.zeros(2048, dtype=np.float32)
        self._waveform_lock = threading.Lock()
        # Spectrogram buffer for waterfall visualization (stores last 100 FFT frames)
        self._fft_size = 1024  # FFT window size
        self._spectrogram_history = 100  # Number of FFT frames to keep
        self._spectrogram_buffer = np.zeros((self._spectrogram_history, self._fft_size // 2), dtype=np.float32)
        self._spectrogram_lock = threading.Lock()
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

        # Clear queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def get_audio_chunk(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """Get the next audio chunk from the queue."""
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _capture_loop(self) -> None:
        """Main capture loop running in separate thread."""
        logger.debug(f"Capture loop started for {self.config.name}")

        while not self._stop_event.is_set():
            try:
                audio_chunk = self._read_audio_chunk()
                if audio_chunk is not None:
                    # Update metrics
                    self._update_metrics(audio_chunk)

                    # Add to queue, drop if full
                    try:
                        self._audio_queue.put_nowait(audio_chunk)
                    except queue.Full:
                        # Drop oldest chunk and add new one
                        try:
                            self._audio_queue.get_nowait()
                            self._audio_queue.put_nowait(audio_chunk)
                        except queue.Empty:
                            pass
                else:
                    # No decoded audio chunk available
                    # Only sleep if source had no data activity (prevents busy loops on truly idle sources)
                    # Stream sources may read HTTP data but not have enough to decode yet - don't sleep in that case
                    if not self._had_data_activity:
                        time.sleep(0.05)  # 50ms sleep to prevent CPU spinning on idle sources

            except Exception as e:
                logger.error(f"Error in capture loop for {self.config.name}: {e}")
                self.status = AudioSourceStatus.ERROR
                self.error_message = str(e)
                self._last_error = str(e)
                break

        logger.debug(f"Capture loop stopped for {self.config.name}")

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

            # Update visualization buffers
            self._update_waveform_buffer(samples_for_metrics)
            self._update_spectrogram_buffer(samples_for_metrics)
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
        self.metrics = AudioMetrics(
            timestamp=current_time,
            peak_level_db=peak_db,
            rms_level_db=rms_db,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            frames_captured=self.metrics.frames_captured + len(audio_chunk),
            silence_detected=silence_detected,
            buffer_utilization=self._audio_queue.qsize() / self._audio_queue.maxsize,
            metadata=current_metadata,
        )

        self._last_metrics_update = current_time

    def restart(
        self,
        reason: str,
        *,
        delay: float = 0.25,
        max_attempts: int = 2,
    ) -> bool:
        """Attempt to restart the adapter when it becomes unhealthy."""

        if not self.config.enabled:
            logger.debug(
                "Skipping restart for %s because the source is disabled",
                self.config.name,
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
                self.stop()
                if delay > 0:
                    time.sleep(delay)
                if self.start():
                    self._restart_count += 1
                    self._last_restart = time.time()
                    self._last_error = None
                    logger.info(
                        "%s: audio source restarted successfully after %s",
                        self.config.name,
                        reason,
                    )
                    return True
                backoff = min(delay * attempt, 2.0)
                if backoff > 0:
                    time.sleep(backoff)

            logger.error(
                "%s: failed to restart audio source after %s attempt(s) (%s)",
                self.config.name,
                attempts,
                reason,
            )
            return False

    def _update_waveform_buffer(self, audio_chunk: np.ndarray) -> None:
        """Update the waveform buffer with new audio data."""
        if len(audio_chunk) == 0:
            return

        with self._waveform_lock:
            # Downsample if needed to fit in buffer
            buffer_size = len(self._waveform_buffer)
            if len(audio_chunk) >= buffer_size:
                # Take every Nth sample to fit
                step = len(audio_chunk) // buffer_size
                self._waveform_buffer[:] = audio_chunk[::step][:buffer_size]
            else:
                # Shift existing data and append new
                shift_amount = len(audio_chunk)
                self._waveform_buffer[:-shift_amount] = self._waveform_buffer[shift_amount:]
                self._waveform_buffer[-shift_amount:] = audio_chunk[:shift_amount]

    def get_waveform_data(self) -> np.ndarray:
        """Get a copy of the current waveform buffer for visualization."""
        with self._waveform_lock:
            return self._waveform_buffer.copy()

    def _update_spectrogram_buffer(self, audio_chunk: np.ndarray) -> None:
        """Update the spectrogram buffer with FFT of new audio data."""
        if len(audio_chunk) < self._fft_size:
            return

        with self._spectrogram_lock:
            # Take the last fft_size samples for FFT computation
            fft_window = audio_chunk[-self._fft_size:]

            # Apply Hamming window to reduce spectral leakage
            windowed = fft_window * np.hamming(self._fft_size)

            # Compute FFT and get magnitude spectrum (only positive frequencies)
            fft_result = np.fft.rfft(windowed)
            magnitude = np.abs(fft_result)

            # Convert to dB scale (with floor to avoid log(0))
            magnitude = np.maximum(magnitude, 1e-10)
            magnitude_db = 20 * np.log10(magnitude)

            # Normalize to 0-1 range for visualization (assuming -120dB to 0dB range)
            normalized = (magnitude_db + 120) / 120
            normalized = np.clip(normalized, 0, 1)

            # Shift buffer and add new FFT frame
            self._spectrogram_buffer[:-1] = self._spectrogram_buffer[1:]
            self._spectrogram_buffer[-1] = normalized[:self._fft_size // 2]

    def get_spectrogram_data(self) -> np.ndarray:
        """Get a copy of the current spectrogram buffer for waterfall visualization."""
        with self._spectrogram_lock:
            return self._spectrogram_buffer.copy()


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

        # Broadcast queue for pub/sub audio distribution
        # CRITICAL: Increased to 2000 to prevent EAS monitor from missing chunks
        # At 44100Hz: 200 chunks = 18.6 seconds (TOO SMALL - caused missed alerts)
        # At 44100Hz: 2000 chunks = 186 seconds (safe buffer)
        self._broadcast_queue = BroadcastQueue(name="audio-ingest-broadcast", max_queue_size=2000)

        # Standard sample rate for broadcast queue
        # All audio is resampled to this rate before broadcasting to ensure consistency
        # across all subscribers (Icecast, EAS monitor, etc.)
        self._broadcast_queue_sample_rate = 44100

        # Subscribe to our own broadcast for backward compatibility with get_audio_chunk()
        self._controller_subscription = self._broadcast_queue.subscribe("controller-legacy")

        # Start broadcast pump thread to publish audio from sources to broadcast queue
        self._pump_stop = threading.Event()
        self._pump_thread = threading.Thread(
            target=self._broadcast_pump_loop,
            name="AudioBroadcastPump",
            daemon=True,
        )
        self._pump_thread.start()

        if enable_monitor:
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="AudioSourceMonitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def add_source(self, source: AudioSourceAdapter) -> None:
        """Add an audio source to the controller."""
        with self._lock:
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

    def get_audio_chunk(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """
        Get audio from the highest priority active source.

        DEPRECATED: New code should use get_broadcast_queue() and subscribe instead.
        This method is maintained for backward compatibility and pulls from the
        controller's own subscription to the broadcast queue.
        """
        try:
            return self._controller_subscription.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_broadcast_queue(self) -> BroadcastQueue:
        """
        Get the broadcast queue for subscribing to audio.

        Subscribers receive independent copies of all audio chunks without
        affecting other consumers (EAS monitor, Icecast, web streaming, etc).

        Returns:
            BroadcastQueue instance for subscribing
        """
        return self._broadcast_queue

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

    def cleanup(self) -> None:
        """Cleanup all sources and threads."""
        self.stop_all()

        # Stop broadcast pump
        self._pump_stop.set()
        if self._pump_thread and self._pump_thread.is_alive():
            self._pump_thread.join(timeout=2.0)
            self._pump_thread = None

        # Stop health monitor
        self._monitor_stop.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None

        with self._lock:
            self._sources.clear()
            self._active_source = None

    def _broadcast_pump_loop(self) -> None:
        """
        Broadcast pump loop - reads from highest priority source and publishes to broadcast queue.

        This allows multiple consumers (EAS monitor, Icecast, web streaming) to receive
        independent copies of audio without competing for chunks.
        """
        logger.info("Broadcast pump started")

        last_status_log = 0.0
        status_log_interval = 10.0  # Log status every 10 seconds
        chunks_published_since_log = 0
        chunks_none_since_log = 0

        while not self._pump_stop.is_set():
            try:
                # Find the best active source based on priority
                with self._lock:
                    active_sources = [
                        (name, source) for name, source in self._sources.items()
                        if source.status == AudioSourceStatus.RUNNING and source.config.enabled
                    ]

                current_time = time.time()

                # Periodic status logging
                if current_time - last_status_log >= status_log_interval:
                    with self._lock:
                        total_sources = len(self._sources)
                        running_sources = len(active_sources)

                    broadcast_stats = self._broadcast_queue.get_stats()

                    subscriber_ids = broadcast_stats.get('subscriber_ids', [])
                    logger.info(
                        f"Broadcast pump status: {running_sources}/{total_sources} sources running, "
                        f"{broadcast_stats['subscribers']} subscribers {subscriber_ids}, "
                        f"{chunks_published_since_log} chunks published (last {status_log_interval}s), "
                        f"{chunks_none_since_log} empty reads, "
                        f"total published: {broadcast_stats['published_chunks']}, "
                        f"dropped: {broadcast_stats['dropped_chunks']}"
                    )

                    last_status_log = current_time
                    chunks_published_since_log = 0
                    chunks_none_since_log = 0

                if not active_sources:
                    # No active sources, sleep and retry
                    time.sleep(0.1)
                    continue

                # Sort by priority (lower number = higher priority)
                active_sources.sort(key=lambda x: x[1].config.priority)
                best_source_name, best_source = active_sources[0]

                # Update active source if changed
                with self._lock:
                    if self._active_source != best_source_name:
                        self._active_source = best_source_name
                        logger.info(f"Broadcast pump switched to audio source: {best_source_name}")

                # Get chunk from source (this is still destructive on the source's queue)
                chunk = best_source.get_audio_chunk(timeout=0.5)

                if chunk is not None:
                    chunks_published_since_log += 1

                    # CRITICAL: Resample to standard broadcast rate if needed
                    # All audio sources have different sample rates (22050, 24000, 44100, 48000, etc.)
                    # but all subscribers to the broadcast queue expect a consistent rate.
                    # Without this, Icecast encoders get sample rate mismatches causing squealing/crashes.
                    source_sample_rate = getattr(best_source.config, 'sample_rate', 44100)
                    if source_sample_rate != self._broadcast_queue_sample_rate:
                        chunk = self._resample_chunk(chunk, source_sample_rate, self._broadcast_queue_sample_rate)

                    # CRITICAL: Even if rates match, still check - chunk may come from resampling
                    # Ensure chunk size is not excessively large which could cause downstream buffering issues
                    # Target max chunk size: 200ms at broadcast rate to prevent overflow
                    max_chunk_samples = int(self._broadcast_queue_sample_rate * 0.2)
                    if len(chunk) > max_chunk_samples:
                        logger.warning(
                            f"Chunk size {len(chunk)} exceeds max {max_chunk_samples} "
                            f"({len(chunk)/self._broadcast_queue_sample_rate*1000:.1f}ms), splitting"
                        )

                    # Publish to broadcast queue - all subscribers get a copy
                    delivered = self._broadcast_queue.publish(chunk)
                    if delivered == 0:
                        logger.warning("No subscribers to receive audio chunk")
                else:
                    chunks_none_since_log += 1

            except Exception as e:
                logger.error(f"Error in broadcast pump loop: {e}", exc_info=True)
                time.sleep(0.1)

        logger.info("Broadcast pump stopped")

    def _resample_chunk(self, chunk: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """
        Resample audio chunk from one sample rate to another.

        Uses linear interpolation for efficient, high-quality resampling.
        This is critical for the broadcast queue to provide consistent sample rates
        to all subscribers regardless of the source's native rate.

        Args:
            chunk: Audio samples as numpy array (float32)
            from_rate: Source sample rate in Hz
            to_rate: Target sample rate in Hz

        Returns:
            Resampled audio chunk at target rate
        """
        if from_rate == to_rate:
            return chunk

        # Calculate resampling ratio
        ratio = to_rate / from_rate
        num_samples_out = int(len(chunk) * ratio)

        # Use numpy's linear interpolation for resampling
        # This is faster than scipy.signal.resample and sufficient quality for audio distribution
        x_old = np.arange(len(chunk))
        x_new = np.linspace(0, len(chunk) - 1, num_samples_out)
        resampled = np.interp(x_new, x_old, chunk)

        return resampled.astype(np.float32)

    def _monitor_loop(self) -> None:
        """Background monitor that auto-recovers unhealthy sources."""
        while not self._monitor_stop.is_set():
            now = time.time()
            with self._lock:
                snapshot = list(self._sources.items())
            
            # Wrap health evaluation in Flask app context if available
            # This allows database operations during source restarts
            if self._flask_app:
                with self._flask_app.app_context():
                    for name, adapter in snapshot:
                        self._evaluate_source_health(name, adapter, now)
            else:
                for name, adapter in snapshot:
                    self._evaluate_source_health(name, adapter, now)
            
            self._monitor_stop.wait(timeout=self._monitor_interval)

    def _evaluate_source_health(
        self,
        name: str,
        adapter: AudioSourceAdapter,
        now: float,
    ) -> None:
        if not adapter.config.enabled:
            return

        status = adapter.status

        if status == AudioSourceStatus.RUNNING:
            if adapter._start_time and now - adapter._start_time < self._monitor_grace_period:
                return
            last_update = adapter._last_metrics_update or (adapter.metrics.timestamp if adapter.metrics else 0.0)
            if last_update == 0.0 or now - last_update > self._monitor_stall_seconds:
                adapter.restart("stalled capture (no audio samples)")
            return

        if status in (AudioSourceStatus.ERROR, AudioSourceStatus.DISCONNECTED):
            adapter.restart(f"status={status.value}")
