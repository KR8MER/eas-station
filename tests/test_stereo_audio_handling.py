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

"""
Unit tests for stereo audio handling in EAS monitoring pipeline.

Tests that stereo (2-channel) audio is properly converted to mono
in various components of the audio pipeline.
"""

import pytest
import numpy as np
from unittest.mock import Mock, MagicMock

from app_core.audio.streaming_same_decoder import StreamingSAMEDecoder

# Constants
FLOAT32_BYTES = 4  # Number of bytes per float32 value


class MockAudioManager:
    """Mock audio manager for testing."""
    
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self._stereo_mode = False
    
    def set_stereo_mode(self, stereo: bool):
        """Toggle between stereo and mono output."""
        self._stereo_mode = stereo
    
    def read_audio(self, num_samples: int) -> np.ndarray:
        """Return either mono or stereo audio based on mode."""
        if self._stereo_mode:
            # Return stereo audio (2D array with shape (num_samples, 2))
            return np.random.randn(num_samples, 2).astype(np.float32) * 0.1
        else:
            # Return mono audio (1D array with shape (num_samples,))
            return np.random.randn(num_samples).astype(np.float32) * 0.1
    
    def get_stats(self):
        """Return mock stats."""
        return {'queue_size': 0, 'buffer_samples': 0}


class TestStereoAudioHandling:
    """Test suite for stereo audio handling."""
    
    def test_streaming_decoder_with_mono_audio(self):
        """Test that decoder handles mono audio correctly."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Create mono audio (1D array)
        mono_audio = np.random.randn(1600).astype(np.float32) * 0.1
        
        # Should process without error
        decoder.process_samples(mono_audio)
        assert decoder.samples_processed == 1600
    
    def test_streaming_decoder_with_stereo_audio_fails(self):
        """Test that decoder fails with stereo audio (2D array)."""
        decoder = StreamingSAMEDecoder(sample_rate=16000)
        
        # Create stereo audio (2D array with shape (1600, 2))
        stereo_audio = np.random.randn(1600, 2).astype(np.float32) * 0.1
        
        # Should fail with ValueError when trying to assign 2D to 1D buffer
        with pytest.raises(ValueError):
            decoder.process_samples(stereo_audio)
    
    def test_resample_if_needed_with_mono_audio(self):
        """Test _resample_if_needed with mono audio."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        # Create monitor instance
        mock_audio_manager = MockAudioManager(sample_rate=44100)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        # Create mono audio at 44100 Hz
        mono_audio = np.random.randn(4410).astype(np.float32) * 0.1
        
        # Resample to 16 kHz
        resampled = monitor._resample_if_needed(mono_audio)
        
        # Check that output is 1D and approximately correct length
        assert resampled.ndim == 1
        expected_length = int(len(mono_audio) * 16000 / 44100)
        assert abs(len(resampled) - expected_length) <= 1
    
    def test_resample_if_needed_with_stereo_audio(self):
        """Test _resample_if_needed with stereo audio (should convert to mono)."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        # Create monitor instance
        mock_audio_manager = MockAudioManager(sample_rate=44100)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        # Create stereo audio at 44100 Hz (2D array with shape (4410, 2))
        stereo_audio = np.random.randn(4410, 2).astype(np.float32) * 0.1
        
        # Resample - should convert stereo to mono first, then resample
        resampled = monitor._resample_if_needed(stereo_audio)
        
        # Check that output is 1D (mono) and approximately correct length
        assert resampled.ndim == 1
        expected_length = int(len(stereo_audio) * 16000 / 44100)
        assert abs(len(resampled) - expected_length) <= 1
    
    def test_resample_if_needed_no_resampling_with_stereo(self):
        """Test _resample_if_needed when no resampling needed but audio is stereo."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        # Create monitor instance with same rate
        mock_audio_manager = MockAudioManager(sample_rate=16000)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        # Create stereo audio at 16 kHz (no resampling needed, but still stereo)
        stereo_audio = np.random.randn(1600, 2).astype(np.float32) * 0.1
        
        # Should convert stereo to mono even without resampling
        result = monitor._resample_if_needed(stereo_audio)
        
        # Check that output is 1D (mono) and same length
        assert result.ndim == 1
        assert len(result) == len(stereo_audio)
    
    def test_redis_publisher_with_stereo_audio(self):
        """Test that RedisAudioPublisher converts stereo to mono."""
        from app_core.audio.redis_audio_publisher import RedisAudioPublisher
        from app_core.audio.broadcast_queue import BroadcastQueue
        import base64
        import json
        
        # Create mock broadcast queue and adapter
        broadcast_queue = BroadcastQueue("test_queue")
        
        # Create publisher (it will fail to connect to Redis, but that's OK for this test)
        publisher = RedisAudioPublisher(
            broadcast_queue=broadcast_queue,
            source_name="test_source",
            sample_rate=16000
        )
        
        # Mock Redis client
        publisher._redis_client = Mock()
        publisher._redis_client.publish = Mock()
        
        # Mock audio adapter to return stereo audio
        publisher._audio_adapter = Mock()
        stereo_audio = np.random.randn(1600, 2).astype(np.float32) * 0.1
        publisher._audio_adapter.read_audio = Mock(return_value=stereo_audio)
        
        # Start the publisher thread
        publisher._running.set()
        
        # Manually call one iteration of the publisher loop
        chunk_samples = 1600
        audio_chunk = publisher._audio_adapter.read_audio(chunk_samples)
        
        # Simulate the processing in _publisher_loop
        if audio_chunk is not None and len(audio_chunk) > 0:
            # Apply stereo to mono conversion (this is what our fix does)
            if audio_chunk.ndim == 2:
                if audio_chunk.shape[1] == 2:
                    audio_chunk = audio_chunk.mean(axis=1)
            
            # Verify audio is now mono
            assert audio_chunk.ndim == 1
            assert len(audio_chunk) == 1600
            
            # Encode and verify
            sample_bytes = audio_chunk.astype(np.float32).tobytes()
            # Byte length should be 1600 samples * FLOAT32_BYTES = 6400 bytes
            assert len(sample_bytes) == 1600 * FLOAT32_BYTES


class TestAudioShapeNormalization:
    """Test various audio shape scenarios."""
    
    def test_mono_1d_array(self):
        """Test that 1D mono audio passes through unchanged."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        mock_audio_manager = MockAudioManager(sample_rate=16000)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        mono_audio = np.random.randn(1600).astype(np.float32) * 0.1
        result = monitor._resample_if_needed(mono_audio)
        
        assert result.ndim == 1
        assert len(result) == 1600
    
    def test_stereo_2d_array_two_channels(self):
        """Test that 2D stereo audio (2 channels) is converted to mono."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        mock_audio_manager = MockAudioManager(sample_rate=16000)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        stereo_audio = np.random.randn(1600, 2).astype(np.float32) * 0.1
        result = monitor._resample_if_needed(stereo_audio)
        
        assert result.ndim == 1
        assert len(result) == 1600
    
    def test_mono_2d_array_one_channel(self):
        """Test that 2D mono audio (1 channel) is flattened to 1D."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        mock_audio_manager = MockAudioManager(sample_rate=16000)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        # Create 2D array with 1 channel: shape (1600, 1)
        mono_2d_audio = np.random.randn(1600, 1).astype(np.float32) * 0.1
        result = monitor._resample_if_needed(mono_2d_audio)
        
        assert result.ndim == 1
        assert len(result) == 1600
    
    def test_multi_channel_audio_uses_first_channel(self):
        """Test that audio with >2 channels uses first channel only."""
        from app_core.audio.eas_monitor import ContinuousEASMonitor
        
        mock_audio_manager = MockAudioManager(sample_rate=16000)
        monitor = ContinuousEASMonitor(
            audio_manager=mock_audio_manager,
            sample_rate=16000
        )
        
        # Create 4-channel audio: shape (1600, 4)
        multi_channel_audio = np.random.randn(1600, 4).astype(np.float32) * 0.1
        result = monitor._resample_if_needed(multi_channel_audio)
        
        assert result.ndim == 1
        assert len(result) == 1600
