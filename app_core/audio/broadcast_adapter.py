"""
Broadcast Audio Adapter for EAS Monitor

Subscribes to a BroadcastQueue to receive audio chunks without consuming
from the main streaming pipeline. Each subscriber gets its own independent
copy of audio data.
"""

import logging
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
        sample_rate: int = 22050
    ):
        """
        Initialize broadcast adapter.

        Args:
            broadcast_queue: BroadcastQueue instance to subscribe to
            subscriber_id: Unique ID for this subscription (e.g., "eas-monitor")
            sample_rate: Expected sample rate for calculations
        """
        self.broadcast_queue = broadcast_queue
        self.subscriber_id = subscriber_id
        self.sample_rate = sample_rate

        # Subscribe to broadcast queue
        self._subscriber_queue = broadcast_queue.subscribe(subscriber_id)

        # Local buffer for read_audio()
        self._buffer = np.array([], dtype=np.float32)
        self._buffer_lock = threading.Lock()

        logger.info(
            f"BroadcastAudioAdapter '{subscriber_id}' subscribed to '{broadcast_queue.name}'"
        )

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
            # Try to fill buffer if we don't have enough samples
            while len(self._buffer) < num_samples:
                try:
                    chunk = self._subscriber_queue.get(timeout=0.1)
                except Exception:
                    # No more audio available right now
                    if len(self._buffer) < num_samples:
                        return None
                    break

                if chunk is None:
                    if len(self._buffer) < num_samples:
                        return None
                    break

                # Append chunk to buffer
                self._buffer = np.concatenate([self._buffer, chunk])

                # Limit buffer size to prevent unbounded growth
                # Keep max 5 seconds worth of audio
                max_buffer_samples = self.sample_rate * 5
                if len(self._buffer) > max_buffer_samples:
                    # Trim from front (drop oldest audio)
                    self._buffer = self._buffer[-max_buffer_samples:]

            # Extract requested samples
            if len(self._buffer) >= num_samples:
                samples = self._buffer[:num_samples].copy()
                self._buffer = self._buffer[num_samples:]
                return samples

            return None

    def get_active_source(self) -> Optional[str]:
        """Get name of currently active audio source."""
        # Broadcast queues don't track source name - return broadcast name
        return self.broadcast_queue.name

    def unsubscribe(self):
        """Unsubscribe from broadcast queue."""
        self.broadcast_queue.unsubscribe(self.subscriber_id)
        logger.info(f"BroadcastAudioAdapter '{self.subscriber_id}' unsubscribed")

    def __repr__(self) -> str:
        return (
            f"<BroadcastAudioAdapter '{self.subscriber_id}' "
            f"queue='{self.broadcast_queue.name}'>"
        )
