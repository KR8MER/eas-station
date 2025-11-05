"""
Unified Audio Ingest Controller

Provides a centralized interface for managing multiple audio sources
with standardized PCM output, metering, and health monitoring.
"""

from __future__ import annotations

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
        self.metrics = AudioMetrics(
            timestamp=0.0,
            peak_level_db=-np.inf,
            rms_level_db=-np.inf,
            sample_rate=config.sample_rate,
            channels=config.channels,
            frames_captured=0,
            silence_detected=False,
            buffer_utilization=0.0
        )
        self._stop_event = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._audio_queue = queue.Queue(maxsize=100)
        self._last_metrics_update = 0.0

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
                
            logger.info(f"Started audio source: {self.config.name}")
            return True
            
        except Exception as e:
            self.status = AudioSourceStatus.ERROR
            logger.error(f"Failed to start audio source {self.config.name}: {e}")
            return False

    def stop(self) -> None:
        """Stop audio capture."""
        if self.status == AudioSourceStatus.STOPPED:
            return

        logger.info(f"Stopping audio source: {self.config.name}")
        self.status = AudioSourceStatus.STOPPED
        self._stop_event.set()
        
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
                            
            except Exception as e:
                logger.error(f"Error in capture loop for {self.config.name}: {e}")
                self.status = AudioSourceStatus.ERROR
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
            # Peak level in dBFS
            peak = np.max(np.abs(audio_chunk))
            peak_db = 20 * np.log10(max(peak, 1e-10))
            
            # RMS level in dBFS  
            rms = np.sqrt(np.mean(audio_chunk ** 2))
            rms_db = 20 * np.log10(max(rms, 1e-10))
            
            # Silence detection
            silence_detected = rms_db < self.config.silence_threshold_db
        else:
            peak_db = rms_db = -np.inf
            silence_detected = True

        # Update metrics
        self.metrics = AudioMetrics(
            timestamp=current_time,
            peak_level_db=peak_db,
            rms_level_db=rms_db,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            frames_captured=self.metrics.frames_captured + len(audio_chunk),
            silence_detected=silence_detected,
            buffer_utilization=self._audio_queue.qsize() / self._audio_queue.maxsize
        )
        
        self._last_metrics_update = current_time


class AudioIngestController:
    """Main controller for managing multiple audio sources."""

    def __init__(self):
        self._sources: Dict[str, AudioSourceAdapter] = {}
        self._active_source: Optional[str] = None
        self._lock = threading.RLock()

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
        """Get audio from the highest priority active source."""
        with self._lock:
            # Find the best active source based on priority
            active_sources = [
                (name, source) for name, source in self._sources.items()
                if source.status == AudioSourceStatus.RUNNING and source.config.enabled
            ]
            
            if not active_sources:
                return None

            # Sort by priority (lower number = higher priority)
            active_sources.sort(key=lambda x: x[1].config.priority)
            best_source_name, best_source = active_sources[0]
            
            # Update active source if changed
            if self._active_source != best_source_name:
                self._active_source = best_source_name
                logger.info(f"Switched to audio source: {best_source_name}")

            return best_source.get_audio_chunk(timeout=timeout)

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

    def cleanup(self) -> None:
        """Cleanup all sources and threads."""
        self.stop_all()
        with self._lock:
            self._sources.clear()
            self._active_source = None