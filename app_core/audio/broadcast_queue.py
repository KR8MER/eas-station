"""
Broadcast Queue for Audio Distribution

Implements a pub/sub pattern where audio chunks are written once to a shared
buffer and fanned out to multiple independent consumer queues. This allows
EAS monitoring, Icecast streaming, and web streaming to coexist without
competing for audio chunks.

Architecture:
    Audio Source → BroadcastQueue.publish()
                        ↓ (copies to all subscribers)
                   ┌────┴────┬─────────┬─────────┐
                   ↓         ↓         ↓         ↓
              EAS Queue  Icecast  WebStream  Future
"""

import logging
import threading
import queue
from typing import Dict, Optional, Callable
import numpy as np

logger = logging.getLogger(__name__)


class BroadcastQueue:
    """
    Multi-consumer broadcast queue for audio chunks.

    Publishers write once, subscribers each get their own independent
    queue with a copy of the data. This prevents one consumer from
    starving others.
    """

    def __init__(self, name: str = "audio-broadcast", max_queue_size: int = 100):
        """
        Initialize broadcast queue.

        Args:
            name: Identifier for this broadcast queue
            max_queue_size: Maximum chunks per subscriber queue before dropping
        """
        self.name = name
        self.max_queue_size = max_queue_size

        # Subscriber queues: {subscriber_id: queue}
        self._subscribers: Dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

        # Statistics
        self._published_chunks = 0
        self._dropped_chunks = 0

        logger.info(f"Initialized BroadcastQueue '{name}' (max_queue_size={max_queue_size})")

    def subscribe(self, subscriber_id: str) -> queue.Queue:
        """
        Subscribe to receive audio chunks.

        Args:
            subscriber_id: Unique identifier for this subscriber

        Returns:
            Queue instance for this subscriber to read from
        """
        with self._lock:
            if subscriber_id in self._subscribers:
                logger.warning(f"Subscriber '{subscriber_id}' already exists, returning existing queue")
                return self._subscribers[subscriber_id]

            subscriber_queue = queue.Queue(maxsize=self.max_queue_size)
            self._subscribers[subscriber_id] = subscriber_queue

            logger.info(
                f"Subscriber '{subscriber_id}' added to '{self.name}' "
                f"(total subscribers: {len(self._subscribers)})"
            )

            return subscriber_queue

    def unsubscribe(self, subscriber_id: str) -> bool:
        """
        Unsubscribe from receiving audio chunks.

        Args:
            subscriber_id: Subscriber to remove

        Returns:
            True if subscriber was removed, False if not found
        """
        with self._lock:
            if subscriber_id in self._subscribers:
                del self._subscribers[subscriber_id]
                logger.info(
                    f"Subscriber '{subscriber_id}' removed from '{self.name}' "
                    f"(remaining: {len(self._subscribers)})"
                )
                return True
            return False

    def publish(self, chunk: np.ndarray) -> int:
        """
        Publish audio chunk to all subscribers.

        Each subscriber gets an independent copy. If a subscriber's queue
        is full, the chunk is dropped for that subscriber only.

        Args:
            chunk: Audio data as numpy array

        Returns:
            Number of subscribers that successfully received the chunk
        """
        if chunk is None or len(chunk) == 0:
            return 0

        delivered = 0

        with self._lock:
            subscribers = list(self._subscribers.items())

        self._published_chunks += 1

        for subscriber_id, subscriber_queue in subscribers:
            try:
                # Make a copy for each subscriber to prevent sharing issues
                chunk_copy = chunk.copy()
                subscriber_queue.put_nowait(chunk_copy)
                delivered += 1

            except queue.Full:
                # Queue full - drop oldest chunk and try again
                try:
                    subscriber_queue.get_nowait()  # Drop oldest
                    chunk_copy = chunk.copy()
                    subscriber_queue.put_nowait(chunk_copy)
                    delivered += 1
                    self._dropped_chunks += 1
                    logger.debug(
                        f"Subscriber '{subscriber_id}' queue full, dropped oldest chunk "
                        f"(total dropped: {self._dropped_chunks})"
                    )
                except (queue.Empty, queue.Full):
                    logger.warning(f"Failed to deliver chunk to subscriber '{subscriber_id}'")

        return delivered

    def get_stats(self) -> dict:
        """Get broadcast queue statistics."""
        with self._lock:
            return {
                "name": self.name,
                "subscribers": len(self._subscribers),
                "subscriber_ids": list(self._subscribers.keys()),
                "published_chunks": self._published_chunks,
                "dropped_chunks": self._dropped_chunks,
                "max_queue_size": self.max_queue_size,
            }

    def clear_subscriber_queue(self, subscriber_id: str) -> int:
        """
        Clear all pending chunks from a subscriber's queue.

        Args:
            subscriber_id: Subscriber whose queue to clear

        Returns:
            Number of chunks removed
        """
        with self._lock:
            if subscriber_id not in self._subscribers:
                return 0

            subscriber_queue = self._subscribers[subscriber_id]

        cleared = 0
        while True:
            try:
                subscriber_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break

        if cleared > 0:
            logger.info(f"Cleared {cleared} chunks from subscriber '{subscriber_id}'")

        return cleared

    def __repr__(self) -> str:
        return (
            f"<BroadcastQueue '{self.name}' "
            f"subscribers={len(self._subscribers)} "
            f"published={self._published_chunks}>"
        )
