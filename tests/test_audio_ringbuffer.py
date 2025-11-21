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
Unit tests for AudioRingBuffer

Tests lock-free ring buffer for correctness, thread-safety, and performance.
"""

import pytest
import numpy as np
import threading
import time

from app_core.audio.ringbuffer import AudioRingBuffer, RingBufferStats


class TestAudioRingBuffer:
    """Test suite for AudioRingBuffer."""

    def test_initialization(self):
        """Test ring buffer initialization."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        assert buffer.capacity == 1024  # Power of 2
        assert buffer.mask == 1023
        assert buffer.available_read() == 0
        assert buffer.available_write() == 1023  # capacity - 1 (one slot reserved)

    def test_power_of_2_rounding(self):
        """Test that capacity is rounded up to power of 2."""
        buffer = AudioRingBuffer(capacity_samples=1000, dtype=np.float32)
        assert buffer.capacity == 1024  # Rounded up from 1000

        buffer = AudioRingBuffer(capacity_samples=2048, dtype=np.float32)
        assert buffer.capacity == 2048  # Already power of 2

    def test_simple_write_read(self):
        """Test basic write and read operations."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Write data
        test_data = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        written = buffer.write(test_data, block=False)

        assert written == 5
        assert buffer.available_read() == 5

        # Read data back
        read_data = buffer.read(5, block=False)

        assert read_data is not None
        assert len(read_data) == 5
        assert np.array_equal(read_data, test_data)
        assert buffer.available_read() == 0

    def test_wraparound_write(self):
        """Test write that wraps around buffer end."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Fill most of buffer (leave room for wraparound)
        data1 = np.ones(900, dtype=np.float32)
        buffer.write(data1, block=False)

        # Read some to make space at start
        buffer.read(600, block=False)

        # Write data that will wrap around
        data2 = np.full(700, 2.0, dtype=np.float32)
        written = buffer.write(data2, block=False)

        assert written == 700

        # Read and verify order is correct
        result = buffer.read(1000, block=False)  # 300 from data1 + 700 from data2
        assert result is not None

        expected = np.concatenate([
            np.ones(300, dtype=np.float32),  # Remaining from data1
            np.full(700, 2.0, dtype=np.float32)  # All of data2
        ])
        assert np.array_equal(result, expected)

    def test_wraparound_read(self):
        """Test read that wraps around buffer end."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Write, read, write pattern to position read pointer near end
        buffer.write(np.ones(900, dtype=np.float32), block=False)
        buffer.read(600, block=False)
        buffer.write(np.full(700, 2.0, dtype=np.float32), block=False)

        # Now read more than fits before wraparound
        result = buffer.read(1000, block=False)

        assert result is not None
        assert len(result) == 1000

    def test_overflow_non_blocking(self):
        """Test overflow behavior in non-blocking mode."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Fill buffer to capacity - 1 (one slot always reserved)
        data = np.ones(1023, dtype=np.float32)
        written = buffer.write(data, block=False)
        assert written == 1023

        # Try to write more (should fail)
        overflow_data = np.ones(100, dtype=np.float32)
        written = buffer.write(overflow_data, block=False)
        assert written == 0  # Nothing written

        # Check stats show overrun
        stats = buffer.get_stats()
        assert stats.overruns == 1

    def test_underflow_non_blocking(self):
        """Test underflow behavior in non-blocking mode."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Try to read from empty buffer
        result = buffer.read(10, block=False)
        assert result is None

        # Check stats show underrun
        stats = buffer.get_stats()
        assert stats.underruns == 1

    def test_partial_read(self):
        """Test reading when not enough data available."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Write 5 samples
        buffer.write(np.ones(5, dtype=np.float32), block=False)

        # Try to read 10 samples (only 5 available)
        result = buffer.read(10, block=False)
        assert result is None  # Not enough data

        # Read exactly what's available
        result = buffer.read(5, block=False)
        assert result is not None
        assert len(result) == 5

    def test_stats_tracking(self):
        """Test statistics tracking."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Perform operations
        buffer.write(np.ones(100, dtype=np.float32), block=False)
        buffer.write(np.ones(200, dtype=np.float32), block=False)
        buffer.read(150, block=False)

        stats = buffer.get_stats()

        assert stats.total_written == 300
        assert stats.total_read == 150
        assert stats.current_fill == 150
        assert stats.peak_fill >= 300

    def test_clear(self):
        """Test buffer clear operation."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Write some data
        buffer.write(np.ones(500, dtype=np.float32), block=False)
        assert buffer.available_read() == 500

        # Clear buffer
        buffer.clear()

        assert buffer.available_read() == 0
        assert buffer.available_write() == 1023

    def test_thread_safety_single_producer_single_consumer(self):
        """Test thread safety with one writer and one reader."""
        buffer = AudioRingBuffer(capacity_samples=4096, dtype=np.float32)

        write_count = [0]
        read_count = [0]
        errors = []

        def writer():
            """Writer thread."""
            try:
                for i in range(1000):
                    data = np.full(10, float(i), dtype=np.float32)
                    while buffer.write(data, block=False) == 0:
                        time.sleep(0.001)  # Wait if buffer full
                    write_count[0] += 10
            except Exception as e:
                errors.append(f"Writer error: {e}")

        def reader():
            """Reader thread."""
            try:
                while read_count[0] < 10000:
                    data = buffer.read(10, block=False)
                    if data is not None:
                        read_count[0] += len(data)
                    else:
                        time.sleep(0.001)  # Wait if buffer empty
            except Exception as e:
                errors.append(f"Reader error: {e}")

        # Start threads
        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)

        writer_thread.start()
        reader_thread.start()

        # Wait for completion
        writer_thread.join(timeout=10.0)
        reader_thread.join(timeout=10.0)

        # Check results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert write_count[0] == 10000
        assert read_count[0] == 10000

    def test_dtype_conversion(self):
        """Test automatic dtype conversion."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Write int16 data (should be converted)
        int_data = np.array([100, 200, 300], dtype=np.int16)
        written = buffer.write(int_data, block=False)

        assert written == 3

        # Read back as float32
        result = buffer.read(3, block=False)
        assert result is not None
        assert result.dtype == np.float32

    def test_large_buffer(self):
        """Test with large buffer (10 seconds at 22050 Hz)."""
        buffer = AudioRingBuffer(capacity_samples=220500, dtype=np.float32)

        # Write and read large chunks
        chunk_size = 2205  # 100ms at 22050 Hz

        for i in range(100):
            data = np.full(chunk_size, float(i), dtype=np.float32)
            written = buffer.write(data, block=False)
            assert written == chunk_size

        # Read it all back
        total_read = 0
        while total_read < 220500:
            chunk = buffer.read(chunk_size, block=False)
            if chunk is not None:
                total_read += len(chunk)
            else:
                break

        assert total_read == 220500

    def test_stats_reset(self):
        """Test statistics reset."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Generate some stats
        buffer.write(np.ones(100, dtype=np.float32), block=False)
        buffer.read(50, block=False)
        buffer.write(np.ones(200, dtype=np.float32), block=False)  # Causes overflow
        buffer.read(10, block=False)

        stats = buffer.get_stats()
        assert stats.overruns > 0 or stats.peak_fill > 0

        # Reset stats
        buffer.reset_stats()

        stats = buffer.get_stats()
        assert stats.overruns == 0
        assert stats.peak_fill == 0

    def test_fill_percentage(self):
        """Test fill percentage calculation."""
        buffer = AudioRingBuffer(capacity_samples=1024, dtype=np.float32)

        # Write half capacity
        buffer.write(np.ones(512, dtype=np.float32), block=False)

        stats = buffer.get_stats()
        assert 49.0 < stats.fill_percentage < 51.0  # ~50%

    def test_minimum_size(self):
        """Test minimum buffer size enforcement."""
        with pytest.raises(ValueError, match="at least 1024"):
            AudioRingBuffer(capacity_samples=512, dtype=np.float32)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
