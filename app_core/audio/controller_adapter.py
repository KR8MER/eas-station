"""
Audio Controller Adapter for EAS Monitor

Adapts AudioIngestController to the interface expected by ContinuousEASMonitor.
Bridges the gap between production audio system and EAS monitoring.
"""

import logging
import numpy as np
from typing import Optional
from .ingest import AudioIngestController

logger = logging.getLogger(__name__)


class AudioControllerAdapter:
    """
    Adapter that makes AudioIngestController compatible with EAS Monitor.

    ContinuousEASMonitor expects an object with:
    - read_audio(num_samples) -> Optional[np.ndarray]
    - get_active_source() -> Optional[str]

    AudioIngestController provides:
    - get_audio_chunk(timeout) -> Optional[np.ndarray]
    - get_active_source() -> Optional[str]

    This adapter bridges the difference by buffering chunks and serving
    the requested number of samples.
    """

    def __init__(self, controller: AudioIngestController, sample_rate: int = 22050):
        """
        Initialize adapter.

        Args:
            controller: AudioIngestController instance to adapt
            sample_rate: Expected sample rate (for calculating chunk sizes)
        """
        self.controller = controller
        self.sample_rate = sample_rate
        self._buffer = np.array([], dtype=np.float32)
        self._buffer_lock = __import__('threading').Lock()

    def read_audio(self, num_samples: int) -> Optional[np.ndarray]:
        """
        Read specified number of audio samples.

        Compatible with ContinuousEASMonitor interface.

        Args:
            num_samples: Number of samples to read

        Returns:
            NumPy array of samples, or None if insufficient data
        """
        with self._buffer_lock:
            # Try to fill buffer if we don't have enough samples
            while len(self._buffer) < num_samples:
                chunk = self.controller.get_audio_chunk(timeout=0.1)
                if chunk is None:
                    # No more audio available right now
                    if len(self._buffer) < num_samples:
                        # Not enough data
                        return None
                    break

                # Append chunk to buffer
                self._buffer = np.concatenate([self._buffer, chunk])

                # Limit buffer size to prevent unbounded growth
                # Keep max 5 seconds worth of audio
                max_buffer_samples = self.sample_rate * 5
                if len(self._buffer) > max_buffer_samples:
                    # Trim from front
                    self._buffer = self._buffer[-max_buffer_samples:]

            # Extract requested samples
            if len(self._buffer) >= num_samples:
                samples = self._buffer[:num_samples].copy()
                self._buffer = self._buffer[num_samples:]
                return samples

            return None

    def get_active_source(self) -> Optional[str]:
        """Get name of currently active audio source."""
        return self.controller.get_active_source()

    def __repr__(self) -> str:
        return f"<AudioControllerAdapter wrapping {self.controller}>"
