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
Robust FFmpeg Audio Source with Watchdog Monitoring

Professional-grade FFmpeg wrapper for 24/7 audio streaming in emergency alert systems.
Includes comprehensive error handling, automatic restart, health monitoring, and failover support.

Key Features:
- Watchdog timer for automatic failure detection
- Exponential backoff retry logic
- Health metrics and alerting
- Clean subprocess management
- Zero audio loss during normal operation
"""

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

import numpy as np

from .ringbuffer import AudioRingBuffer

logger = logging.getLogger(__name__)


class SourceHealth(Enum):
    """Health status of audio source."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # Working but with issues
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class SourceMetrics:
    """Health metrics for monitoring."""
    health: SourceHealth
    uptime_seconds: float
    total_samples_produced: int
    restart_count: int
    consecutive_failures: int
    last_error: Optional[str]
    watchdog_timeouts: int
    samples_per_second: float
    buffer_fill_percent: float


class FFmpegAudioSource:
    """
    Robust FFmpeg-based audio source with comprehensive monitoring.

    Designed for 24/7 operation in mission-critical systems. Automatically
    recovers from failures and provides detailed health metrics.
    """

    def __init__(
        self,
        source_url: str,
        sample_rate: int = 22050,
        buffer_seconds: float = 10.0,
        watchdog_timeout: float = 5.0,
        max_restart_attempts: int = 10,
        health_callback: Optional[Callable[[SourceMetrics], None]] = None
    ):
        """
        Initialize FFmpeg audio source.

        Args:
            source_url: Audio source URL or device
            sample_rate: Target sample rate in Hz
            buffer_seconds: Ring buffer size in seconds
            watchdog_timeout: Seconds without data before restart
            max_restart_attempts: Maximum consecutive restart attempts
            health_callback: Optional callback for health status changes
        """
        self.source_url = source_url
        self.sample_rate = sample_rate
        self.watchdog_timeout = watchdog_timeout
        self.max_restart_attempts = max_restart_attempts
        self.health_callback = health_callback

        # Ring buffer sized for specified duration
        buffer_samples = int(sample_rate * buffer_seconds)
        self.ring_buffer = AudioRingBuffer(buffer_samples, dtype=np.float32)

        # FFmpeg process management
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Health tracking
        self._start_time = 0.0
        self._last_data_time = 0.0
        self._total_samples = 0
        self._restart_count = 0
        self._consecutive_failures = 0
        self._last_error: Optional[str] = None
        self._watchdog_timeouts = 0
        self._health = SourceHealth.STOPPED

        # Retry logic with exponential backoff
        self._retry_delays = [0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
        self._current_retry_index = 0

        logger.info(f"Initialized FFmpegAudioSource: url={source_url}, "
                   f"rate={sample_rate}Hz, buffer={buffer_seconds}s")

    def start(self) -> bool:
        """
        Start the audio source.

        Returns:
            True if started successfully, False otherwise
        """
        if not self._stop_event.is_set():
            logger.warning("FFmpegAudioSource already running")
            return False

        self._stop_event.clear()
        self._start_time = time.time()
        self._health = SourceHealth.HEALTHY

        # Start FFmpeg process
        if not self._start_ffmpeg():
            self._health = SourceHealth.FAILED
            return False

        # Start reader thread
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"ffmpeg-reader-{id(self)}",
            daemon=True
        )
        self._reader_thread.start()

        # Start watchdog thread
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name=f"ffmpeg-watchdog-{id(self)}",
            daemon=True
        )
        self._watchdog_thread.start()

        logger.info(f"Started FFmpegAudioSource: {self.source_url}")
        self._notify_health_change()
        return True

    def stop(self) -> None:
        """Stop the audio source cleanly."""
        logger.info(f"Stopping FFmpegAudioSource: {self.source_url}")
        self._stop_event.set()

        # Stop FFmpeg process
        self._stop_ffmpeg()

        # Wait for threads
        if self._reader_thread:
            self._reader_thread.join(timeout=5.0)
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)

        self._health = SourceHealth.STOPPED
        self._notify_health_change()
        logger.info(f"Stopped FFmpegAudioSource: {self.source_url}")

    def _start_ffmpeg(self) -> bool:
        """
        Start FFmpeg subprocess.

        Returns:
            True if started successfully
        """
        try:
            # FFmpeg command to decode audio to raw PCM
            cmd = [
                'ffmpeg',
                '-re',  # Read input at native frame rate (for streams)
                '-i', self.source_url,
                '-f', 's16le',  # 16-bit PCM little-endian
                '-ar', str(self.sample_rate),
                '-ac', '1',  # Mono
                '-loglevel', 'error',
                '-'  # Output to stdout
            ]

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=8192
            )

            self._last_data_time = time.time()
            logger.info(f"Started FFmpeg process: pid={self._process.pid}")
            return True

        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Failed to start FFmpeg: {e}")
            return False

    def _stop_ffmpeg(self) -> None:
        """Stop FFmpeg subprocess cleanly."""
        if not self._process:
            return

        try:
            # Try graceful termination
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                # Force kill if needed
                logger.warning("FFmpeg didn't terminate gracefully, killing")
                self._process.kill()
                self._process.wait(timeout=1.0)

        except Exception as e:
            logger.error(f"Error stopping FFmpeg: {e}")

        finally:
            self._process = None

    def _reader_loop(self) -> None:
        """Main loop to read PCM data from FFmpeg stdout."""
        logger.debug("FFmpeg reader loop started")
        bytes_per_sample = 2  # 16-bit = 2 bytes
        chunk_samples = int(self.sample_rate * 0.05)  # 50ms chunks
        chunk_bytes = chunk_samples * bytes_per_sample

        while not self._stop_event.is_set():
            if not self._process or self._process.poll() is not None:
                # Process died, attempt restart
                logger.warning("FFmpeg process died, attempting restart")
                self._handle_failure("FFmpeg process terminated unexpectedly")
                if not self._attempt_restart():
                    break
                continue

            try:
                # Read chunk from FFmpeg stdout
                data = self._process.stdout.read(chunk_bytes)

                if not data:
                    # No data means EOF
                    logger.warning("FFmpeg EOF")
                    self._handle_failure("FFmpeg reached EOF")
                    if not self._attempt_restart():
                        break
                    continue

                # Convert PCM to float32 samples
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

                # Write to ring buffer
                written = self.ring_buffer.write(samples, block=False)
                if written == 0:
                    # Buffer overflow - this is critical
                    logger.error("Ring buffer overflow - consumer too slow!")
                    self._health = SourceHealth.DEGRADED

                # Update metrics
                self._last_data_time = time.time()
                self._total_samples += len(samples)
                self._consecutive_failures = 0  # Reset on successful data
                self._current_retry_index = 0  # Reset backoff

                # Update health if we were degraded
                if self._health == SourceHealth.DEGRADED:
                    self._health = SourceHealth.HEALTHY
                    self._notify_health_change()

            except Exception as e:
                logger.error(f"Error reading from FFmpeg: {e}")
                self._handle_failure(str(e))
                if not self._attempt_restart():
                    break

        logger.debug("FFmpeg reader loop stopped")

    def _watchdog_loop(self) -> None:
        """Watchdog timer to detect stalls."""
        logger.debug("FFmpeg watchdog started")

        while not self._stop_event.wait(self.watchdog_timeout / 2):
            time_since_data = time.time() - self._last_data_time

            if time_since_data > self.watchdog_timeout:
                logger.error(f"Watchdog timeout: no data for {time_since_data:.1f}s")
                self._watchdog_timeouts += 1
                self._handle_failure(f"Watchdog timeout ({time_since_data:.1f}s)")

                # Trigger restart
                self._stop_ffmpeg()
                if not self._attempt_restart():
                    break

        logger.debug("FFmpeg watchdog stopped")

    def _handle_failure(self, error_msg: str) -> None:
        """Handle a failure condition."""
        self._last_error = error_msg
        self._consecutive_failures += 1
        self._health = SourceHealth.FAILED if self._consecutive_failures > 3 else SourceHealth.DEGRADED
        self._notify_health_change()

    def _attempt_restart(self) -> bool:
        """
        Attempt to restart FFmpeg with exponential backoff.

        Returns:
            True if restart successful or should keep trying
        """
        if self._stop_event.is_set():
            return False

        if self._consecutive_failures >= self.max_restart_attempts:
            logger.error(f"Max restart attempts ({self.max_restart_attempts}) reached")
            self._health = SourceHealth.FAILED
            self._notify_health_change()
            return False

        # Exponential backoff
        delay_index = min(self._current_retry_index, len(self._retry_delays) - 1)
        delay = self._retry_delays[delay_index]
        self._current_retry_index += 1

        logger.info(f"Restarting FFmpeg in {delay}s (attempt {self._consecutive_failures + 1})")
        self._stop_event.wait(delay)

        if self._stop_event.is_set():
            return False

        # Stop old process
        self._stop_ffmpeg()

        # Start new process
        if self._start_ffmpeg():
            self._restart_count += 1
            logger.info(f"FFmpeg restarted successfully (total restarts: {self._restart_count})")
            return True
        else:
            logger.error("FFmpeg restart failed")
            return True  # Keep trying

    def read_samples(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read audio samples from the ring buffer.

        Args:
            num_samples: Number of samples to read

        Returns:
            NumPy array of samples, or None if insufficient data
        """
        return self.ring_buffer.read(num_samples, block=False)

    def get_metrics(self) -> SourceMetrics:
        """Get current health metrics."""
        uptime = time.time() - self._start_time if self._start_time > 0 else 0
        samples_per_sec = self._total_samples / max(uptime, 0.001)
        buffer_stats = self.ring_buffer.get_stats()

        return SourceMetrics(
            health=self._health,
            uptime_seconds=uptime,
            total_samples_produced=self._total_samples,
            restart_count=self._restart_count,
            consecutive_failures=self._consecutive_failures,
            last_error=self._last_error,
            watchdog_timeouts=self._watchdog_timeouts,
            samples_per_second=samples_per_sec,
            buffer_fill_percent=buffer_stats.fill_percentage
        )

    def _notify_health_change(self) -> None:
        """Notify health callback of status change."""
        if self.health_callback:
            try:
                self.health_callback(self.get_metrics())
            except Exception as e:
                logger.error(f"Error in health callback: {e}")


__all__ = ['FFmpegAudioSource', 'SourceHealth', 'SourceMetrics']
