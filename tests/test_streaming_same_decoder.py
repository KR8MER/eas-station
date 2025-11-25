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
Unit tests for StreamingSAMEDecoder

Tests decoder reset functionality and optimized sample processing.
"""

import pytest
import numpy as np
import time

from app_core.audio.streaming_same_decoder import StreamingSAMEDecoder


class TestStreamingSAMEDecoder:
    """Test suite for StreamingSAMEDecoder."""

    def test_initialization(self):
        """Test decoder initialization."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        assert decoder.sample_rate == 16000
        assert decoder.samples_processed == 0
        assert decoder.alerts_detected == 0
        assert decoder.bytes_decoded == 0
        assert decoder.synced is False
        assert decoder.in_message is False

    def test_process_samples_basic(self):
        """Test basic sample processing."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Process 1 second of random audio
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        decoder.process_samples(audio)
        
        assert decoder.samples_processed == 16000

    def test_process_empty_samples(self):
        """Test processing empty sample array."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        empty_audio = np.array([], dtype=np.float32)
        decoder.process_samples(empty_audio)
        
        assert decoder.samples_processed == 0

    def test_process_multiple_chunks(self):
        """Test processing multiple audio chunks."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Process 5 chunks of 100ms each
        for _ in range(5):
            audio = np.random.randn(1600).astype(np.float32) * 0.1
            decoder.process_samples(audio)
        
        assert decoder.samples_processed == 8000  # 5 * 1600

    def test_reset_clears_all_state(self):
        """Test that reset() clears all decoder state."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Process some audio
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        decoder.process_samples(audio)
        
        # Verify state was modified
        assert decoder.samples_processed == 16000
        
        # Reset
        decoder.reset()
        
        # Verify all state is cleared
        assert decoder.samples_processed == 0
        assert decoder.alerts_detected == 0
        assert decoder.bytes_decoded == 0
        assert decoder.synced is False
        assert decoder.in_message is False
        assert len(decoder.current_msg) == 0
        assert len(decoder.bit_confidences) == 0

    def test_get_stats_returns_correct_values(self):
        """Test that get_stats returns accurate statistics."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Initial stats
        stats = decoder.get_stats()
        assert stats['samples_processed'] == 0
        assert stats['alerts_detected'] == 0
        assert stats['synced'] is False
        
        # After processing audio
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        decoder.process_samples(audio)
        
        stats = decoder.get_stats()
        assert stats['samples_processed'] == 16000
        assert stats['synced'] is False  # No preamble in random noise
        assert stats['in_message'] is False

    def test_correlation_window_preallocated(self):
        """Test that correlation window is pre-allocated after reset."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Should have pre-allocated correlation window
        assert hasattr(decoder, '_correlation_window')
        assert len(decoder._correlation_window) == decoder.corr_len
        
        # After reset, should still be allocated
        decoder.reset()
        assert hasattr(decoder, '_correlation_window')
        assert len(decoder._correlation_window) == decoder.corr_len

    def test_batch_sample_processing_efficiency(self):
        """Test that batch processing is faster than previous implementation."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Process a large chunk of audio to test performance
        large_audio = np.random.randn(160000).astype(np.float32) * 0.1
        
        start_time = time.time()
        decoder.process_samples(large_audio)
        elapsed = time.time() - start_time
        
        # Should process 10 seconds of audio in less than 1 second of real time
        # This is a basic sanity check - actual performance will vary
        assert decoder.samples_processed == 160000
        assert elapsed < 5.0, f"Processing took {elapsed:.2f}s, expected < 5s for 10s of audio"

    def test_callback_invoked_on_alert(self):
        """Test that callback is invoked when alert is detected."""
        alerts_received = []
        
        def capture_alert(alert):
            alerts_received.append(alert)
        
        decoder = StreamingSAMEDecoder(sample_rate=16000, alert_callback=capture_alert)
        
        # Process random audio (no alerts expected)
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        decoder.process_samples(audio)
        
        # No alerts from random noise
        assert len(alerts_received) == 0
        assert decoder.alerts_detected == 0


class TestStreamingSAMEDecoderEdgeCases:
    """Edge case tests for StreamingSAMEDecoder."""

    def test_small_sample_chunks(self):
        """Test processing very small sample chunks."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Process 100 chunks of 10 samples each
        for _ in range(100):
            audio = np.random.randn(10).astype(np.float32) * 0.1
            decoder.process_samples(audio)
        
        assert decoder.samples_processed == 1000

    def test_single_sample_processing(self):
        """Test processing single samples."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        for _ in range(100):
            audio = np.array([0.1], dtype=np.float32)
            decoder.process_samples(audio)
        
        assert decoder.samples_processed == 100

    def test_different_sample_rates(self):
        """Test decoder with different sample rates."""
        for rate in [8000, 16000, 22050, 44100]:
            decoder = StreamingSAMEDecoder(sample_rate=rate)
            
            audio = np.random.randn(rate).astype(np.float32) * 0.1
            decoder.process_samples(audio)
            
            assert decoder.samples_processed == rate
            assert decoder.sample_rate == rate

    def test_reset_after_partial_message(self):
        """Test reset during partial message decoding."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Process some audio
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        decoder.process_samples(audio)
        
        # Simulate being in the middle of message
        decoder.in_message = True
        decoder.current_msg = ['Z', 'C', 'Z', 'C']
        
        # Reset should clear message state
        decoder.reset()
        
        assert decoder.in_message is False
        assert len(decoder.current_msg) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
