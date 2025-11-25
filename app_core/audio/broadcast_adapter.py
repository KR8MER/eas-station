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

"""
Broadcast Audio Adapter for EAS Monitor

Subscribes to a BroadcastQueue to receive audio chunks without consuming
from the main streaming pipeline. Each subscriber gets its own independent
copy of audio data.
"""

import logging
import time
import numpy as np
import threading
from typing import Optional
from .broadcast_queue import BroadcastQueue

logger = logging.getLogger(__name__)


class BroadcastAudioAdapter:
    """
    Non-destructive audio tap via broadcast subscription.

    This adapter subscribes to a BroadcastQueue and receives copies of
    audio chunks. It buffers chunks and serves them on-demand via the
    read_audio() interface expected by ContinuousEASMonitor.

    Unlike the AudioControllerAdapter which consumes from a shared queue,
    this adapter has its own dedicated queue fed by broadcast copying.
    """

    def __init__(
        self,
        broadcast_queue: BroadcastQueue,
        subscriber_id: str,
        sample_rate: int = 44100,  # Native sample rate from audio sources
        read_timeout: float = 0.5  # Timeout for queue reads in seconds
    ):
        """
        Initialize broadcast adapter.

        Args:
            broadcast_queue: BroadcastQueue instance to subscribe to
            subscriber_id: Unique ID for this subscription (e.g., "eas-monitor")
            sample_rate: Expected sample rate from audio sources (native stream rate)
            read_timeout: Timeout for queue reads in seconds (default 0.5s).
                         Lower values = more responsive but may cause underruns.
                         Higher values = more resilient to network/system jitter.
        """
        self.broadcast_queue = broadcast_queue
        self.subscriber_id = subscriber_id
        self.sample_rate = sample_rate
        self._read_timeout = max(0.1, float(read_timeout))  # Minimum 100ms

        # Subscribe to broadcast queue
        self._subscriber_queue = broadcast_queue.subscribe(subscriber_id)

        # OPTIMIZATION: Use a list of chunks instead of repeated np.concatenate
        # This avoids O(n) array allocations on every chunk append
        self._chunk_list: list = []
        self._chunk_total_samples: int = 0
        self._buffer_lock = threading.Lock()
        
        # Maximum buffer size (5 seconds of audio)
        self._max_buffer_samples = sample_rate * 5

        # Statistics for monitoring audio continuity
        self._underrun_count = 0
        self._total_reads = 0
        self._last_underrun_log = 0.0
        self._last_audio_time: Optional[float] = None

        logger.info(
            f"BroadcastAudioAdapter '{subscriber_id}' subscribed to '{broadcast_queue.name}' "
            f"(timeout={self._read_timeout}s)"
        )

    def _consolidate_chunks(self) -> np.ndarray:
        """
        Consolidate chunk list into a single contiguous array.
        
        OPTIMIZATION: Only concatenates when needed (when extracting samples),
        instead of on every chunk append. This amortizes the O(n) cost.
        """
        if not self._chunk_list:
            return np.array([], dtype=np.float32)
        if len(self._chunk_list) == 1:
            return self._chunk_list[0]
        result = np.concatenate(self._chunk_list)
        self._chunk_list = [result]
        self._chunk_total_samples = len(result)
        return result

    def _trim_buffer_if_needed(self) -> None:
        """Trim buffer if it exceeds maximum size, keeping recent audio."""
        if self._chunk_total_samples <= self._max_buffer_samples:
            return
        
        # Consolidate and trim
        buffer = self._consolidate_chunks()
        trimmed = buffer[-self._max_buffer_samples:]
        self._chunk_list = [trimmed]
        self._chunk_total_samples = len(trimmed)

    def read_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read specified number of audio samples from broadcast subscription.

        Compatible with ContinuousEASMonitor interface.

        Args:
            num_samples: Number of samples to read

        Returns:
            NumPy array of samples, or None if insufficient data
        """
        with self._buffer_lock:
            self._total_reads += 1

            # Try to fill buffer if we don't have enough samples
            while self._chunk_total_samples < num_samples:
                try:
                    # Use configurable timeout for better adaptability to different environments
                    chunk = self._subscriber_queue.get(timeout=self._read_timeout)

                    # Log successful read for first few to verify subscription works
                    if self._total_reads < 5:
                        logger.info(
                            f"✅ {self.subscriber_id}: Successfully got chunk from queue "
                            f"(size: {len(chunk) if chunk is not None else 0})"
                        )
                except Exception as e:
                    # No more audio available right now
                    if self._chunk_total_samples < num_samples:
                        # Buffer underrun - log warning for monitoring
                        self._underrun_count += 1
                        now = time.time()
                        # Log first 10 underruns immediately to diagnose subscription issues
                        # Then throttle noisy warnings
                        if (
                            self._underrun_count <= 10
                            or self._underrun_count % 50 == 0
                            or (now - self._last_underrun_log) >= 10.0
                        ):
                            # Get queue stats for debugging
                            queue_size = self._subscriber_queue.qsize()
                            logger.warning(
                                f"❌ {self.subscriber_id}: Underrun #{self._underrun_count}! "
                                f"Queue timeout after {self._read_timeout}s, queue_size={queue_size}, "
                                f"buffer={self._chunk_total_samples}/{num_samples} samples, "
                                f"exception={type(e).__name__}"
                            )
                            self._last_underrun_log = now
                        return None
                    break

                if chunk is None:
                    if self._chunk_total_samples < num_samples:
                        self._underrun_count += 1
                        logger.warning(
                            f"{self.subscriber_id}: Received None chunk, "
                            f"insufficient buffer ({self._chunk_total_samples}/{num_samples} samples)"
                        )
                        return None
                    break

                # OPTIMIZATION: Append chunk to list instead of np.concatenate
                # This avoids O(n) array allocation on every chunk
                self._chunk_list.append(chunk)
                self._chunk_total_samples += len(chunk)
                self._last_audio_time = time.time()

                # Trim if buffer is too large
                self._trim_buffer_if_needed()

            # Extract requested samples
            if self._chunk_total_samples >= num_samples:
                # Consolidate chunks only when we need to extract data
                buffer = self._consolidate_chunks()
                samples = buffer[:num_samples].copy()
                
                # Keep remaining samples
                remaining = buffer[num_samples:]
                if len(remaining) > 0:
                    self._chunk_list = [remaining]
                    self._chunk_total_samples = len(remaining)
                else:
                    self._chunk_list = []
                    self._chunk_total_samples = 0
                
                return samples

            # This shouldn't happen due to while loop above, but safety check
            self._underrun_count += 1
            logger.warning(
                f"{self.subscriber_id}: Unexpected buffer state - "
                f"have {self._chunk_total_samples}, need {num_samples}"
            )
            return None

    def get_audio_chunk(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        """
        Get next audio chunk from broadcast subscription.
        
        Compatible with IcecastStreamer interface.
        This pulls a standard chunk size (100ms) with configurable timeout.
        
        Args:
            timeout: Maximum time to wait for audio (seconds)
            
        Returns:
            NumPy array of audio samples, or None if no audio available
        """
        # Standard chunk size: 100ms of audio at current sample rate
        chunk_samples = int(self.sample_rate * 0.1)
        
        with self._buffer_lock:
            self._total_reads += 1
            
            # Try to fill buffer if we don't have enough samples
            while self._chunk_total_samples < chunk_samples:
                try:
                    # Use the caller's timeout (important for Icecast prebuffering)
                    chunk = self._subscriber_queue.get(timeout=timeout)
                except:  # noqa: E722
                    # Queue.Empty or other timeout-related exception
                    # No more audio available right now
                    if self._chunk_total_samples < chunk_samples:
                        # Not enough data - return None
                        return None
                    break
                
                if chunk is None:
                    if self._chunk_total_samples < chunk_samples:
                        return None
                    break

                # OPTIMIZATION: Append chunk to list instead of np.concatenate
                self._chunk_list.append(chunk)
                self._chunk_total_samples += len(chunk)
                self._last_audio_time = time.time()
                
                # Trim if buffer is too large
                self._trim_buffer_if_needed()
            
            # Extract requested samples
            if self._chunk_total_samples >= chunk_samples:
                # Consolidate chunks only when we need to extract data
                buffer = self._consolidate_chunks()
                samples = buffer[:chunk_samples].copy()
                
                # Keep remaining samples
                remaining = buffer[chunk_samples:]
                if len(remaining) > 0:
                    self._chunk_list = [remaining]
                    self._chunk_total_samples = len(remaining)
                else:
                    self._chunk_list = []
                    self._chunk_total_samples = 0
                
                return samples
            
            # Not enough data
            return None
    
    def get_recent_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Get recent audio samples from buffer (for audio archiving).
        
        Compatible with ContinuousEASMonitor interface for saving alert audio.
        
        Note: This returns whatever audio is currently in the buffer, up to
        num_samples. If less audio is available, returns what we have.
        For best results, maintain a larger buffer in real-time operations.
        
        Args:
            num_samples: Number of samples requested
            
        Returns:
            NumPy array of recent audio samples, or None if buffer is empty
        """
        with self._buffer_lock:
            if self._chunk_total_samples == 0:
                logger.warning(
                    f"{self.subscriber_id}: get_recent_audio() called but buffer is empty"
                )
                return None
            
            # Consolidate chunks to access data
            buffer = self._consolidate_chunks()
            
            # Return up to num_samples from the current buffer
            # If we have less than requested, return what we have
            available_samples = min(len(buffer), num_samples)
            
            if available_samples < num_samples:
                logger.debug(
                    f"{self.subscriber_id}: Requested {num_samples} recent samples, "
                    f"only {available_samples} available in buffer"
                )
            
            # Return copy of recent audio without consuming from buffer
            return buffer[:available_samples].copy()

    def get_active_source(self) -> Optional[str]:
        """Get name of currently active audio source."""
        # Broadcast queues don't track source name - return broadcast name
        return self.broadcast_queue.name

    def get_stats(self) -> dict:
        """
        Get adapter statistics for monitoring audio continuity.

        Returns:
            Dictionary with buffer statistics and health metrics
        """
        with self._buffer_lock:
            queue_size = self._subscriber_queue.qsize()
            buffer_samples = self._chunk_total_samples
            buffer_seconds = buffer_samples / self.sample_rate if self.sample_rate > 0 else 0

            # Calculate underrun rate
            underrun_rate = (self._underrun_count / self._total_reads * 100) if self._total_reads > 0 else 0

            return {
                "subscriber_id": self.subscriber_id,
                "queue_size": queue_size,
                "buffer_samples": buffer_samples,
                "buffer_seconds": buffer_seconds,
                "sample_rate": self.sample_rate,
                "total_reads": self._total_reads,
                "underrun_count": self._underrun_count,
                "underrun_rate_percent": underrun_rate,
                "last_audio_time": self._last_audio_time,
                "health": "good" if underrun_rate < 1.0 else "degraded" if underrun_rate < 5.0 else "poor"
            }

    def unsubscribe(self):
        """Unsubscribe from broadcast queue."""
        stats = self.get_stats()
        self.broadcast_queue.unsubscribe(self.subscriber_id)
        logger.info(
            f"BroadcastAudioAdapter '{self.subscriber_id}' unsubscribed - "
            f"Stats: {stats['total_reads']} reads, {stats['underrun_count']} underruns "
            f"({stats['underrun_rate_percent']:.2f}%)"
        )

    def __repr__(self) -> str:
        return (
            f"<BroadcastAudioAdapter '{self.subscriber_id}' "
            f"queue='{self.broadcast_queue.name}'>"
        )
