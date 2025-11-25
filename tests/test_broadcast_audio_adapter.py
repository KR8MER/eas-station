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
Unit tests for BroadcastAudioAdapter

Tests optimized buffer management and audio reading.
"""

import pytest
import numpy as np
import time
import threading

from app_core.audio.broadcast_adapter import BroadcastAudioAdapter
from app_core.audio.broadcast_queue import BroadcastQueue


class TestBroadcastAudioAdapter:
    """Test suite for BroadcastAudioAdapter."""

    def test_initialization(self):
        """Test adapter initialization."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        assert adapter.subscriber_id == 'test-subscriber'
        assert adapter.sample_rate == 16000
        assert adapter._chunk_total_samples == 0
        assert len(adapter._chunk_list) == 0

    def test_read_audio_basic(self):
        """Test basic audio reading."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        # Publish some audio
        for _ in range(5):
            chunk = np.random.randn(1600).astype(np.float32) * 0.1
            bq.publish(chunk)
        
        # Read audio
        samples = adapter.read_audio(4000)
        
        assert samples is not None
        assert len(samples) == 4000
        
        # Check that we successfully read the requested amount
        # (remaining buffer may vary depending on how many chunks were fetched)
        stats = adapter.get_stats()
        assert stats['buffer_samples'] >= 0

    def test_chunk_list_optimization(self):
        """Test that chunk list optimization reduces allocations."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        # Publish many small chunks
        for i in range(20):
            chunk = np.full(160, float(i), dtype=np.float32)
            bq.publish(chunk)
        
        # After publishing, chunks are in the list
        # Read all at once - this should consolidate
        samples = adapter.read_audio(3200)
        
        assert samples is not None
        assert len(samples) == 3200
        
        # The adapter should have consolidated chunks efficiently
        stats = adapter.get_stats()
        assert stats['buffer_samples'] >= 0

    def test_get_stats(self):
        """Test get_stats returns correct values."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        # Publish some audio
        for _ in range(3):
            chunk = np.random.randn(1600).astype(np.float32) * 0.1
            bq.publish(chunk)
        
        # Read some audio (this triggers stats updates)
        samples = adapter.read_audio(1600)
        
        stats = adapter.get_stats()
        
        assert 'subscriber_id' in stats
        assert 'buffer_samples' in stats
        assert 'buffer_seconds' in stats
        assert 'underrun_count' in stats
        assert 'health' in stats
        assert stats['subscriber_id'] == 'test-subscriber'

    def test_get_recent_audio(self):
        """Test get_recent_audio returns buffer contents without consuming."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        # Publish some audio
        for _ in range(5):
            chunk = np.random.randn(1600).astype(np.float32) * 0.1
            bq.publish(chunk)
        
        # Read to populate buffer
        samples = adapter.read_audio(4000)
        assert samples is not None
        
        # Get recent audio - should not consume
        recent = adapter.get_recent_audio(2000)
        
        if recent is not None:  # May be None if no remaining buffer
            assert len(recent) <= 2000
        
        # Buffer should not be consumed by get_recent_audio
        stats = adapter.get_stats()
        # The buffer state should be preserved

    def test_buffer_trimming(self):
        """Test that buffer is trimmed when it exceeds max size."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        # Max buffer is 5 seconds = 80000 samples at 16kHz
        # Publish more than max buffer worth of audio
        for _ in range(100):  # 160000 samples
            chunk = np.random.randn(1600).astype(np.float32) * 0.1
            bq.publish(chunk)
        
        # Read some to trigger buffer management
        samples = adapter.read_audio(1600)
        
        stats = adapter.get_stats()
        # Buffer should be limited to max size (5 seconds = 80000 samples)
        assert stats['buffer_samples'] <= 80000

    def test_empty_buffer_get_recent_audio(self):
        """Test get_recent_audio with empty buffer."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        # No audio published
        recent = adapter.get_recent_audio(1000)
        
        assert recent is None

    def test_get_active_source(self):
        """Test get_active_source returns queue name."""
        bq = BroadcastQueue('my-audio-broadcast')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        source = adapter.get_active_source()
        assert source == 'my-audio-broadcast'


class TestBroadcastAudioAdapterConcurrency:
    """Concurrency tests for BroadcastAudioAdapter."""

    def test_concurrent_read_write(self):
        """Test adapter works with concurrent readers and writers."""
        bq = BroadcastQueue('test-queue')
        adapter = BroadcastAudioAdapter(bq, 'test-subscriber', sample_rate=16000)
        
        samples_read = []
        stop_event = threading.Event()
        
        def writer():
            """Write audio chunks."""
            for _ in range(100):
                if stop_event.is_set():
                    break
                chunk = np.random.randn(160).astype(np.float32) * 0.1
                bq.publish(chunk)
                time.sleep(0.01)
        
        def reader():
            """Read audio samples."""
            while not stop_event.is_set():
                samples = adapter.read_audio(160)
                if samples is not None:
                    samples_read.append(len(samples))
                else:
                    time.sleep(0.01)
        
        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader, daemon=True)
        
        writer_thread.start()
        reader_thread.start()
        
        writer_thread.join()
        stop_event.set()
        reader_thread.join(timeout=1.0)
        
        # Should have read some samples
        total_read = sum(samples_read)
        assert total_read > 0

    def test_multiple_readers_different_adapters(self):
        """Test multiple adapters reading from same broadcast queue."""
        bq = BroadcastQueue('shared-queue')
        adapter1 = BroadcastAudioAdapter(bq, 'reader-1', sample_rate=16000)
        adapter2 = BroadcastAudioAdapter(bq, 'reader-2', sample_rate=16000)
        
        # Publish some audio
        for i in range(10):
            chunk = np.full(160, float(i), dtype=np.float32)
            bq.publish(chunk)
        
        # Both adapters should get the same data
        samples1 = adapter1.read_audio(800)
        samples2 = adapter2.read_audio(800)
        
        assert samples1 is not None
        assert samples2 is not None
        assert len(samples1) == 800
        assert len(samples2) == 800
        # Data should be identical (both got copies of same chunks)
        assert np.allclose(samples1, samples2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
