from __future__ import annotations
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

"""Thread-safe ring buffer for SDR sample streaming.

This module provides a lock-free ring buffer implementation optimized for
the producer-consumer pattern used in reliable SDR operation. The design
is inspired by dump1090 and other robust SDR applications that achieve
months of uninterrupted operation.

Key design principles:
1. Single producer (USB reader thread) - writes samples from SDR
2. Single consumer (processing thread) - reads samples for processing
3. Lock-free operation - no mutexes in the hot path
4. Memory barriers via atomic operations for visibility
5. Pre-allocated numpy arrays for zero-copy operation

The ring buffer provides:
- Jitter absorption: Smooths out USB latency spikes
- Backpressure handling: Producer can detect when consumer is too slow
- Overflow detection: Logs when samples are dropped
- Health metrics: Buffer fill level, overflow count, etc.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RingBufferStats:
    """Health statistics for ring buffer monitoring."""
    
    size: int = 0
    fill_level: int = 0
    fill_percentage: float = 0.0
    total_samples_written: int = 0
    total_samples_read: int = 0
    overflow_count: int = 0
    underflow_count: int = 0
    last_write_time: float = 0.0
    last_read_time: float = 0.0
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "size": self.size,
            "fill_level": self.fill_level,
            "fill_percentage": round(self.fill_percentage, 2),
            "total_samples_written": self.total_samples_written,
            "total_samples_read": self.total_samples_read,
            "overflow_count": self.overflow_count,
            "underflow_count": self.underflow_count,
            "uptime_seconds": round(time.time() - self.created_at, 1),
        }


class SDRRingBuffer:
    """Thread-safe ring buffer for IQ samples from SDR devices.
    
    This implementation uses a single-producer single-consumer (SPSC) design
    that is lock-free in the hot path. The producer (USB reader thread) only
    writes to write_pos, and the consumer (processing thread) only writes to
    read_pos. This eliminates lock contention and ensures reliable operation.
    
    Memory ordering is guaranteed by Python's GIL for simple integer operations,
    but we use explicit memory barriers via threading primitives for the
    data available signaling.
    
    Args:
        size: Number of complex64 samples to hold (should be ~1 second of data)
        numpy_module: The numpy module to use for array allocation
        identifier: Optional identifier for logging
    """
    
    # Minimum buffer size (256KB of samples = ~0.1s at 2.5 MHz)
    MIN_SIZE = 262144

    # Maximum buffer size (8MB of samples = ~3.2s at 2.5 MHz)
    # Larger buffer provides more headroom for processing latency spikes
    MAX_SIZE = 8388608
    
    def __init__(
        self,
        size: int,
        numpy_module,
        identifier: str = "unknown",
    ) -> None:
        self._numpy = numpy_module
        self._identifier = identifier
        
        # Clamp size to valid range
        self._size = max(self.MIN_SIZE, min(size, self.MAX_SIZE))
        if size != self._size:
            logger.warning(
                "Ring buffer size for %s clamped from %d to %d",
                identifier, size, self._size
            )
        
        # Pre-allocate buffer
        self._buffer = numpy_module.zeros(self._size, dtype=numpy_module.complex64)
        
        # Position tracking (only one thread writes each)
        self._write_pos = 0  # Written by producer only
        self._read_pos = 0   # Written by consumer only
        
        # Statistics
        self._stats = RingBufferStats(size=self._size)
        self._stats_lock = threading.Lock()
        
        # Signaling for data availability
        self._data_available = threading.Event()
        
        # Overflow tracking with exponential backoff logging
        self._overflow_logged = False
        self._last_overflow_time = 0.0
        self._overflow_log_interval = 5.0  # Start at 5 seconds
        self._max_overflow_log_interval = 300.0  # Max 5 minutes between overflow logs
        
        logger.info(
            "Created ring buffer for %s: %d samples (%.1f MB, %.2fs at 2.5MHz)",
            identifier,
            self._size,
            self._size * 8 / 1024 / 1024,  # complex64 = 8 bytes
            self._size / 2_500_000
        )
    
    @property
    def size(self) -> int:
        """Total buffer capacity in samples."""
        return self._size
    
    @property
    def fill_level(self) -> int:
        """Current number of samples available for reading."""
        # Calculate fill level from positions
        write_pos = self._write_pos
        read_pos = self._read_pos
        
        if write_pos >= read_pos:
            return write_pos - read_pos
        else:
            return self._size - read_pos + write_pos
    
    @property
    def free_space(self) -> int:
        """Number of samples that can be written without overflow."""
        return self._size - self.fill_level - 1  # -1 to distinguish full from empty
    
    def write(self, samples: "np.ndarray") -> int:
        """Write samples to the ring buffer.
        
        This method is called by the USB reader thread only. It writes as many
        samples as possible without blocking. If the buffer is full, samples
        are dropped and an overflow is recorded.
        
        Args:
            samples: Complex64 numpy array of IQ samples
            
        Returns:
            Number of samples actually written (may be less than input if overflow)
        """
        num_samples = len(samples)
        if num_samples == 0:
            return 0
        
        available_space = self.free_space
        
        # Handle overflow
        if num_samples > available_space:
            samples_to_write = available_space
            dropped = num_samples - available_space
            
            with self._stats_lock:
                self._stats.overflow_count += 1
            
            # Rate-limit overflow logging with exponential backoff
            # Start at 5s, double each time up to 5 minutes max
            now = time.time()
            if not self._overflow_logged or now - self._last_overflow_time >= self._overflow_log_interval:
                logger.warning(
                    "Ring buffer overflow for %s: dropped %d samples (buffer full, "
                    "processing may be too slow). Next log in %.0fs.",
                    self._identifier, dropped, self._overflow_log_interval
                )
                self._overflow_logged = True
                self._last_overflow_time = now
                # Exponential backoff: 5s -> 10s -> 20s -> 40s -> 80s -> 160s -> 300s (max)
                self._overflow_log_interval = min(
                    self._overflow_log_interval * 2,
                    self._max_overflow_log_interval
                )
        else:
            samples_to_write = num_samples
        
        if samples_to_write == 0:
            return 0
        
        # Write to ring buffer (handle wrap-around)
        write_pos = self._write_pos
        write_end = write_pos + samples_to_write
        
        if write_end <= self._size:
            # Simple case: no wrap-around
            self._buffer[write_pos:write_end] = samples[:samples_to_write]
        else:
            # Wrap-around case
            first_chunk = self._size - write_pos
            self._buffer[write_pos:] = samples[:first_chunk]
            self._buffer[:samples_to_write - first_chunk] = samples[first_chunk:samples_to_write]
        
        # Update write position (atomic for single writer)
        self._write_pos = write_end % self._size
        
        # Update statistics
        with self._stats_lock:
            self._stats.total_samples_written += samples_to_write
            self._stats.last_write_time = time.time()
        
        # Signal that data is available
        self._data_available.set()
        
        return samples_to_write
    
    def read(self, num_samples: int, timeout: float = 0.5) -> Optional["np.ndarray"]:
        """Read samples from the ring buffer.

        This method is called by the processing thread only. It reads up to
        num_samples from the buffer, waiting if necessary for data to become
        available.

        For real-time SDR streaming, the timeout should be long enough to handle
        USB bus contention and system load spikes. 500ms is a reasonable default
        that provides headroom while still detecting actual hardware failures.

        Args:
            num_samples: Maximum number of samples to read
            timeout: Maximum time to wait for data (seconds). Default 500ms.

        Returns:
            Complex64 numpy array of samples, or None if timeout/no data
        """
        # Wait for data if buffer is empty
        # 24/7 RELIABILITY: Use short wait loop instead of single long wait to avoid
        # race condition where producer sets event between fill_level check and clear()
        available = self.fill_level

        if available == 0:
            # Buffer completely empty - wait for producer to signal data
            deadline = time.time() + timeout
            while available == 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    # Timeout with no data - this is a significant event for real-time audio
                    with self._stats_lock:
                        self._stats.underflow_count += 1
                        underflow_count = self._stats.underflow_count

                    # Log underflow warnings (rate-limited by caller)
                    if underflow_count == 1 or underflow_count % 100 == 0:
                        logger.warning(
                            "Ring buffer underflow for %s after %.1fs timeout (total: %d). "
                            "USB/SDR may not be keeping up.",
                            self._identifier, timeout, underflow_count
                        )
                    return None

                self._data_available.clear()
                # Re-check after clear to catch race with producer
                available = self.fill_level
                if available > 0:
                    break

                # Wait with short intervals for responsive shutdown
                wait_time = min(remaining, 0.05)  # 50ms max per wait (was 10ms)
                self._data_available.wait(timeout=wait_time)
                available = self.fill_level

        # Have data - read what's available (may be less than requested, that's OK)
        if available == 0:
            return None
        
        to_read = min(num_samples, available)
        read_pos = self._read_pos
        read_end = read_pos + to_read
        
        if read_end <= self._size:
            # Simple case: no wrap-around
            result = self._buffer[read_pos:read_end].copy()
        else:
            # Wrap-around case
            first_chunk = self._size - read_pos
            result = self._numpy.concatenate([
                self._buffer[read_pos:],
                self._buffer[:to_read - first_chunk]
            ])
        
        # Update read position (atomic for single writer)
        self._read_pos = read_end % self._size
        
        # Update statistics
        with self._stats_lock:
            self._stats.total_samples_read += to_read
            self._stats.last_read_time = time.time()
        
        return result
    
    def get_stats(self) -> RingBufferStats:
        """Get current buffer statistics."""
        with self._stats_lock:
            stats = RingBufferStats(
                size=self._size,
                fill_level=self.fill_level,
                fill_percentage=self.fill_level / self._size * 100 if self._size > 0 else 0,
                total_samples_written=self._stats.total_samples_written,
                total_samples_read=self._stats.total_samples_read,
                overflow_count=self._stats.overflow_count,
                underflow_count=self._stats.underflow_count,
                last_write_time=self._stats.last_write_time,
                last_read_time=self._stats.last_read_time,
                created_at=self._stats.created_at,
            )
        return stats
    
    def reset(self) -> None:
        """Reset the buffer to empty state.
        
        This should only be called when both producer and consumer are stopped.
        """
        self._write_pos = 0
        self._read_pos = 0
        self._data_available.clear()
        self._overflow_logged = False
        
        with self._stats_lock:
            self._stats = RingBufferStats(size=self._size, created_at=time.time())
        
        logger.info("Ring buffer reset for %s", self._identifier)
    
    def signal_shutdown(self) -> None:
        """Signal consumer thread to wake up for shutdown."""
        self._data_available.set()


def calculate_buffer_size(sample_rate: int, buffer_time_seconds: float = 1.0) -> int:
    """Calculate optimal ring buffer size based on sample rate.
    
    Args:
        sample_rate: SDR sample rate in Hz
        buffer_time_seconds: Desired buffer duration (default 1 second)
        
    Returns:
        Buffer size in samples, clamped to valid range
    """
    size = int(sample_rate * buffer_time_seconds)
    return max(SDRRingBuffer.MIN_SIZE, min(size, SDRRingBuffer.MAX_SIZE))
