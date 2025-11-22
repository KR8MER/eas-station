"""
Tests for BroadcastAudioAdapter missing methods fix.

Verifies that get_audio_chunk() and get_recent_audio() methods
work correctly for EAS monitor and Icecast integration.
"""

import unittest
import numpy as np
from unittest.mock import Mock, MagicMock
from queue import Queue


class TestBroadcastAudioAdapterMethods(unittest.TestCase):
    """Test the new methods added to BroadcastAudioAdapter."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Import here to avoid module loading issues
        from app_core.audio.broadcast_adapter import BroadcastAudioAdapter
        from app_core.audio.broadcast_queue import BroadcastQueue
        
        # Create a mock broadcast queue
        self.broadcast_queue = Mock(spec=BroadcastQueue)
        self.broadcast_queue.name = "test-broadcast"
        
        # Create a subscriber queue for the adapter
        self.subscriber_queue = Queue()
        self.broadcast_queue.subscribe = Mock(return_value=self.subscriber_queue)
        self.broadcast_queue.unsubscribe = Mock()
        
        # Create the adapter
        self.adapter = BroadcastAudioAdapter(
            broadcast_queue=self.broadcast_queue,
            subscriber_id="test-subscriber",
            sample_rate=22050
        )
    
    def test_get_audio_chunk_exists(self):
        """Test that get_audio_chunk method exists."""
        self.assertTrue(hasattr(self.adapter, 'get_audio_chunk'))
        self.assertTrue(callable(self.adapter.get_audio_chunk))
    
    def test_get_recent_audio_exists(self):
        """Test that get_recent_audio method exists."""
        self.assertTrue(hasattr(self.adapter, 'get_recent_audio'))
        self.assertTrue(callable(self.adapter.get_recent_audio))
    
    def test_get_audio_chunk_returns_chunk(self):
        """Test that get_audio_chunk returns audio data."""
        # Put some audio in the queue
        test_audio = np.random.randn(2205).astype(np.float32)  # 100ms at 22050 Hz
        self.subscriber_queue.put(test_audio)
        
        # Call get_audio_chunk
        result = self.adapter.get_audio_chunk(timeout=0.5)
        
        # Should return audio
        self.assertIsNotNone(result)
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(len(result), 2205)  # 100ms at 22050 Hz
    
    def test_get_audio_chunk_returns_none_when_empty(self):
        """Test that get_audio_chunk returns None when no audio available."""
        # Don't put any audio in queue
        result = self.adapter.get_audio_chunk(timeout=0.1)
        
        # Should return None
        self.assertIsNone(result)
    
    def test_get_recent_audio_returns_buffer_contents(self):
        """Test that get_recent_audio returns buffered audio."""
        # Put some audio in the queue and let adapter buffer it
        test_audio = np.random.randn(4410).astype(np.float32)  # 200ms
        self.subscriber_queue.put(test_audio)
        
        # Read some audio to populate internal buffer
        self.adapter.read_audio(2205)  # Read 100ms, leaving 100ms in buffer
        
        # Now get recent audio
        result = self.adapter.get_recent_audio(2205)
        
        # Should return audio from buffer
        self.assertIsNotNone(result)
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(len(result), 2205)
    
    def test_get_recent_audio_returns_none_when_empty(self):
        """Test that get_recent_audio returns None when buffer is empty."""
        # Don't put any audio in buffer
        result = self.adapter.get_recent_audio(2205)
        
        # Should return None
        self.assertIsNone(result)
    
    def test_get_recent_audio_returns_partial_when_insufficient(self):
        """Test that get_recent_audio returns partial data when buffer has less than requested."""
        # Put small amount of audio in buffer
        test_audio = np.random.randn(1000).astype(np.float32)
        self.subscriber_queue.put(test_audio)
        
        # Read to populate buffer
        self.adapter.read_audio(500)  # Read 500, leaving 500 in buffer
        
        # Request more than available
        result = self.adapter.get_recent_audio(2205)
        
        # Should return what's available (500 samples)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 500)


if __name__ == '__main__':
    unittest.main()
