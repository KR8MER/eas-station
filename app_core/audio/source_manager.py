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
Audio Source Manager with Automatic Failover

Manages multiple audio sources with priority-based selection and automatic
failover for mission-critical 24/7 operation. Ensures continuous audio
availability for emergency alert monitoring.

Key Features:
- Priority-based source selection
- Automatic failover on source failure
- Silence detection with configurable thresholds
- Health monitoring for all sources
- Seamless audio handoff between sources
- Integration with EAS decoder
"""

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Callable

import numpy as np

from .ffmpeg_source import FFmpegAudioSource, SourceHealth, SourceMetrics
from .ringbuffer import AudioRingBuffer

logger = logging.getLogger(__name__)


class FailoverReason(Enum):
    """Reason for source failover."""
    SOURCE_FAILED = "source_failed"
    SILENCE_DETECTED = "silence_detected"
    MANUAL = "manual"
    PRIORITY_CHANGE = "priority_change"


@dataclass
class AudioSourceConfig:
    """Configuration for an audio source."""
    name: str
    source_url: str
    priority: int  # Lower number = higher priority
    enabled: bool = True
    sample_rate: int = 22050
    silence_threshold_db: float = -50.0
    silence_duration_seconds: float = 10.0


@dataclass
class FailoverEvent:
    """Record of a failover event."""
    timestamp: float
    reason: FailoverReason
    from_source: Optional[str]
    to_source: str
    description: str


class AudioSourceManager:
    """
    Manages multiple audio sources with automatic failover.

    This is the main interface for the EAS system to receive audio.
    Ensures continuous audio availability by automatically switching
    between sources based on health and priority.
    """

    def __init__(
        self,
        sample_rate: int = 22050,
        master_buffer_seconds: float = 5.0,
        failover_callback: Optional[Callable[[FailoverEvent], None]] = None
    ):
        """
        Initialize source manager.

        Args:
            sample_rate: Global sample rate for all sources
            master_buffer_seconds: Size of master output buffer
            failover_callback: Optional callback for failover events
        """
        self.sample_rate = sample_rate
        self.failover_callback = failover_callback

        # Master output buffer (feeds EAS decoder)
        buffer_samples = int(sample_rate * master_buffer_seconds)
        self.master_buffer = AudioRingBuffer(buffer_samples, dtype=np.float32)

        # Source management
        self._sources: Dict[str, FFmpegAudioSource] = {}
        self._source_configs: Dict[str, AudioSourceConfig] = {}
        self._active_source: Optional[str] = None

        # Monitoring threads
        self._monitor_thread: Optional[threading.Thread] = None
        self._mixer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Failover history
        self._failover_history: List[FailoverEvent] = []
        self._max_history = 100

        # Silence detection
        self._silence_start_times: Dict[str, Optional[float]] = {}

        logger.info(f"Initialized AudioSourceManager: rate={sample_rate}Hz, "
                   f"buffer={master_buffer_seconds}s")

    def add_source(self, config: AudioSourceConfig) -> bool:
        """
        Add an audio source to the manager.

        Args:
            config: Source configuration

        Returns:
            True if added successfully
        """
        if config.name in self._sources:
            logger.warning(f"Source {config.name} already exists")
            return False

        try:
            # Create FFmpeg source
            source = FFmpegAudioSource(
                source_url=config.source_url,
                sample_rate=config.sample_rate,
                buffer_seconds=10.0,
                watchdog_timeout=5.0,
                health_callback=lambda metrics: self._on_source_health_change(config.name, metrics)
            )

            self._sources[config.name] = source
            self._source_configs[config.name] = config
            self._silence_start_times[config.name] = None

            logger.info(f"Added source: {config.name} (priority={config.priority})")
            return True

        except Exception as e:
            logger.error(f"Failed to add source {config.name}: {e}")
            return False

    def start(self) -> bool:
        """
        Start the source manager and all enabled sources.

        Returns:
            True if started successfully
        """
        if not self._stop_event.is_set():
            logger.warning("AudioSourceManager already running")
            return False

        self._stop_event.clear()

        # Start all enabled sources
        started_count = 0
        for name, config in self._source_configs.items():
            if config.enabled:
                source = self._sources[name]
                if source.start():
                    started_count += 1
                    logger.info(f"Started source: {name}")
                else:
                    logger.error(f"Failed to start source: {name}")

        if started_count == 0:
            logger.error("No sources started successfully")
            return False

        # Select initial active source
        self._select_best_source(reason=FailoverReason.MANUAL)

        # Start monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="source-monitor",
            daemon=True
        )
        self._monitor_thread.start()

        # Start mixer thread
        self._mixer_thread = threading.Thread(
            target=self._mixer_loop,
            name="audio-mixer",
            daemon=True
        )
        self._mixer_thread.start()

        logger.info(f"AudioSourceManager started with {started_count} sources")
        return True

    def stop(self) -> None:
        """Stop the source manager and all sources."""
        logger.info("Stopping AudioSourceManager")
        self._stop_event.set()

        # Stop all sources
        for name, source in self._sources.items():
            try:
                source.stop()
                logger.info(f"Stopped source: {name}")
            except Exception as e:
                logger.error(f"Error stopping source {name}: {e}")

        # Wait for threads
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        if self._mixer_thread:
            self._mixer_thread.join(timeout=5.0)

        logger.info("AudioSourceManager stopped")

    def _monitor_loop(self) -> None:
        """Monitor source health and trigger failover if needed."""
        logger.debug("Source monitor loop started")

        while not self._stop_event.wait(1.0):
            try:
                # Check if active source is still healthy
                if self._active_source:
                    source = self._sources[self._active_source]
                    metrics = source.get_metrics()

                    # Check if source failed
                    if metrics.health == SourceHealth.FAILED:
                        logger.warning(f"Active source {self._active_source} failed")
                        self._select_best_source(reason=FailoverReason.SOURCE_FAILED)
                        continue

                    # Check for silence
                    config = self._source_configs[self._active_source]
                    if self._check_silence(self._active_source, config):
                        logger.warning(f"Silence detected on {self._active_source}")
                        self._select_best_source(reason=FailoverReason.SILENCE_DETECTED)
                        continue

                # Check if a higher priority source became available
                self._check_priority_failover()

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

        logger.debug("Source monitor loop stopped")

    def _mixer_loop(self) -> None:
        """Mix active source audio into master buffer."""
        logger.debug("Audio mixer loop started")
        chunk_samples = int(self.sample_rate * 0.05)  # 50ms chunks

        while not self._stop_event.is_set():
            if not self._active_source:
                # No active source, sleep
                time.sleep(0.1)
                continue

            try:
                source = self._sources[self._active_source]
                samples = source.read_samples(chunk_samples)

                if samples is not None:
                    # Write to master buffer
                    written = self.master_buffer.write(samples, block=False)
                    if written == 0:
                        logger.warning("Master buffer overflow - decoder too slow!")
                else:
                    # No data available, yield briefly
                    time.sleep(0.001)

            except Exception as e:
                logger.error(f"Error in mixer loop: {e}")
                time.sleep(0.1)

        logger.debug("Audio mixer loop stopped")

    def _select_best_source(self, reason: FailoverReason) -> None:
        """
        Select the best available source based on priority and health.

        Args:
            reason: Reason for source selection
        """
        old_source = self._active_source

        # Get all healthy sources sorted by priority
        healthy_sources = []
        for name, config in self._source_configs.items():
            if not config.enabled:
                continue

            source = self._sources[name]
            metrics = source.get_metrics()

            if metrics.health in [SourceHealth.HEALTHY, SourceHealth.DEGRADED]:
                healthy_sources.append((config.priority, name))

        if not healthy_sources:
            logger.error("No healthy sources available!")
            self._active_source = None
            return

        # Sort by priority (lower number = higher priority)
        healthy_sources.sort()
        new_source = healthy_sources[0][1]

        if new_source != old_source:
            self._active_source = new_source

            # Record failover event
            event = FailoverEvent(
                timestamp=time.time(),
                reason=reason,
                from_source=old_source,
                to_source=new_source,
                description=f"Switched from {old_source or 'none'} to {new_source}"
            )
            self._failover_history.append(event)
            if len(self._failover_history) > self._max_history:
                self._failover_history.pop(0)

            logger.info(f"Failover: {old_source or 'none'} -> {new_source} ({reason.value})")

            # Notify callback
            if self.failover_callback:
                try:
                    self.failover_callback(event)
                except Exception as e:
                    logger.error(f"Error in failover callback: {e}")

    def _check_silence(self, source_name: str, config: AudioSourceConfig) -> bool:
        """
        Check if source has been silent for too long.

        Args:
            source_name: Name of source to check
            config: Source configuration

        Returns:
            True if silence threshold exceeded
        """
        source = self._sources[source_name]

        # Read some samples to check level
        test_samples = source.read_samples(int(self.sample_rate * 0.1))
        if test_samples is None:
            return False  # No data yet

        # Calculate RMS level
        rms = np.sqrt(np.mean(test_samples ** 2))
        rms_db = 20 * np.log10(max(rms, 1e-10))

        if rms_db < config.silence_threshold_db:
            # Silent
            if self._silence_start_times[source_name] is None:
                self._silence_start_times[source_name] = time.time()

            silence_duration = time.time() - self._silence_start_times[source_name]
            if silence_duration > config.silence_duration_seconds:
                return True
        else:
            # Not silent, reset timer
            self._silence_start_times[source_name] = None

        return False

    def _check_priority_failover(self) -> None:
        """Check if a higher priority source is now available."""
        if not self._active_source:
            return

        active_config = self._source_configs[self._active_source]

        # Check if any higher priority source is healthy
        for name, config in self._source_configs.items():
            if config.priority < active_config.priority and config.enabled:
                source = self._sources[name]
                metrics = source.get_metrics()

                if metrics.health == SourceHealth.HEALTHY:
                    logger.info(f"Higher priority source {name} available")
                    self._select_best_source(reason=FailoverReason.PRIORITY_CHANGE)
                    return

    def _on_source_health_change(self, source_name: str, metrics: SourceMetrics) -> None:
        """Callback when source health changes."""
        logger.info(f"Source {source_name} health: {metrics.health.value}")

        # If active source degraded or failed, trigger failover
        if source_name == self._active_source:
            if metrics.health in [SourceHealth.DEGRADED, SourceHealth.FAILED]:
                self._select_best_source(reason=FailoverReason.SOURCE_FAILED)

    def read_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read audio from master buffer (interface for EAS decoder).

        Args:
            num_samples: Number of samples to read

        Returns:
            NumPy array of samples, or None if insufficient data
        """
        return self.master_buffer.read(num_samples, block=False)

    def get_active_source(self) -> Optional[str]:
        """Get name of currently active source."""
        return self._active_source

    def get_source_metrics(self, source_name: str) -> Optional[SourceMetrics]:
        """Get metrics for a specific source."""
        source = self._sources.get(source_name)
        return source.get_metrics() if source else None

    def get_all_metrics(self) -> Dict[str, SourceMetrics]:
        """Get metrics for all sources."""
        return {name: source.get_metrics() for name, source in self._sources.items()}

    def get_failover_history(self) -> List[FailoverEvent]:
        """Get recent failover events."""
        return self._failover_history.copy()


__all__ = ['AudioSourceManager', 'AudioSourceConfig', 'FailoverEvent', 'FailoverReason']
