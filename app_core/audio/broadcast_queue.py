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
import time
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
    
    IMPORTANT: Dropped chunks are EXPECTED behavior when subscribers cannot keep up.
    
    The broadcast queue implements a circular buffer pattern where slow consumers
    automatically drop their oldest chunks to make room for new ones. This prevents
    one slow consumer (e.g., a network streaming client) from blocking or slowing
    down the entire audio pipeline.
    
    High drop counts typically indicate:
    1. A subscriber is not reading fast enough (normal for cold-start or reconnecting clients)
    2. Network streaming clients disconnecting/reconnecting frequently
    3. The queue size (max_queue_size) may need adjustment for your use case
    
    This is by design and ensures real-time audio processing continues uninterrupted.
    The "total dropped" counter is cumulative since service start and will naturally
    grow over time, especially with network streaming subscribers.
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
        # Rate-limited drop logging: dropped audio is the root cause of
        # "stuttering" complaints, so drops must be visible in the system
        # logs at WARNING — but at most once per subscriber per interval so
        # a chronically slow consumer can't flood the journal.
        self._drop_log_interval_seconds = 30.0
        self._last_drop_log: Dict[str, float] = {}
        self._drops_since_log: Dict[str, int] = {}

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

        n_subs = len(subscribers)
        for idx, (subscriber_id, subscriber_queue) in enumerate(subscribers):
            # The last subscriber receives the original array — no copy needed.
            # All earlier subscribers get independent copies so they cannot
            # interfere with each other or with the capture loop.
            chunk_to_put = chunk if idx == n_subs - 1 else chunk.copy()
            try:
                subscriber_queue.put_nowait(chunk_to_put)
                delivered += 1

            except queue.Full:
                # Queue full - drop oldest chunk and try again
                try:
                    subscriber_queue.get_nowait()  # Drop oldest
                    subscriber_queue.put_nowait(chunk_to_put)
                    delivered += 1
                    self._dropped_chunks += 1
                    # Dropped chunks = missing audio = audible stutter for
                    # this subscriber.  Log at WARNING (rate-limited per
                    # subscriber) so operators can see exactly which consumer
                    # is falling behind instead of the drop being silent.
                    self._drops_since_log[subscriber_id] = (
                        self._drops_since_log.get(subscriber_id, 0) + 1
                    )
                    now = time.monotonic()
                    last = self._last_drop_log.get(subscriber_id, 0.0)
                    if now - last >= self._drop_log_interval_seconds:
                        logger.warning(
                            "Audio chunks dropped for subscriber '%s' on '%s': "
                            "%d in the last %.0fs (total dropped: %d). This "
                            "subscriber is consuming slower than real time — "
                            "its audio will stutter.",
                            subscriber_id,
                            self.name,
                            self._drops_since_log.get(subscriber_id, 0),
                            (now - last) if last > 0 else self._drop_log_interval_seconds,
                            self._dropped_chunks,
                        )
                        self._last_drop_log[subscriber_id] = now
                        self._drops_since_log[subscriber_id] = 0
                except (queue.Empty, queue.Full):
                    logger.warning(f"Failed to deliver chunk to subscriber '{subscriber_id}'")

        return delivered

    def get_average_utilization(self) -> float:
        """
        Get average queue utilization across all subscribers.
        
        Returns:
            Float between 0.0 and 1.0 representing average utilization.
            Returns 0.0 if no subscribers or max_queue_size is 0.
        """
        with self._lock:
            if not self._subscribers or self.max_queue_size <= 0:
                return 0.0

            total_utilization = 0.0
            for subscriber_queue in self._subscribers.values():
                # Calculate utilization for this subscriber's queue
                utilization = subscriber_queue.qsize() / self.max_queue_size
                total_utilization += utilization

            subscriber_count = len(self._subscribers)
            return total_utilization / subscriber_count if subscriber_count > 0 else 0.0
    
    def get_stats(self) -> dict:
        """Get broadcast queue statistics."""
        with self._lock:
            # Calculate average utilization inline to avoid lock re-entry
            if not self._subscribers or self.max_queue_size <= 0:
                avg_utilization = 0.0
            else:
                total_utilization = 0.0
                for subscriber_queue in self._subscribers.values():
                    utilization = subscriber_queue.qsize() / self.max_queue_size
                    total_utilization += utilization
                subscriber_count = len(self._subscribers)
                avg_utilization = total_utilization / subscriber_count if subscriber_count > 0 else 0.0

            return {
                "name": self.name,
                "subscribers": len(self._subscribers),
                "subscriber_ids": list(self._subscribers.keys()),
                "published_chunks": self._published_chunks,
                "dropped_chunks": self._dropped_chunks,
                "max_queue_size": self.max_queue_size,
                "average_utilization": avg_utilization,
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
