"""Edge-case coverage for BroadcastQueue and the Icecast subscription path.

These fill gaps the original ingest tests left open: what happens when a
subscriber queue overflows, whether slow consumers can affect fast ones,
chunk isolation between subscribers, and the Icecast streamer's
subscription read/unsubscribe behavior now that the legacy direct-access
fallback has been removed.
"""

import numpy as np
import pytest

from app_core.audio.broadcast_queue import BroadcastQueue
from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer


def _chunk(value: float, n: int = 8) -> np.ndarray:
    return np.full(n, value, dtype=np.float32)


class TestBroadcastQueueOverflow:
    def test_full_queue_drops_oldest_keeps_newest(self):
        bq = BroadcastQueue(name="t", max_queue_size=3)
        sub = bq.subscribe("slow")

        for i in range(5):
            bq.publish(_chunk(float(i)))

        received = [sub.get_nowait()[0] for _ in range(3)]
        assert received == [2.0, 3.0, 4.0], "oldest chunks should be dropped first"
        assert sub.empty()

        stats = bq.get_stats()
        assert stats["published_chunks"] == 5
        assert stats["dropped_chunks"] == 2

    def test_slow_subscriber_does_not_starve_fast_one(self):
        bq = BroadcastQueue(name="t", max_queue_size=2)
        slow = bq.subscribe("slow")
        fast = bq.subscribe("fast")

        seen = []
        for i in range(6):
            bq.publish(_chunk(float(i)))
            seen.append(fast.get_nowait()[0])

        # The fast consumer saw every chunk despite the slow one overflowing.
        assert seen == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        assert slow.qsize() == 2

    def test_publish_returns_delivered_count(self):
        bq = BroadcastQueue(name="t", max_queue_size=4)
        bq.subscribe("a")
        bq.subscribe("b")
        assert bq.publish(_chunk(1.0)) == 2

    def test_publish_empty_or_none_is_noop(self):
        bq = BroadcastQueue(name="t", max_queue_size=4)
        bq.subscribe("a")
        assert bq.publish(None) == 0
        assert bq.publish(np.array([], dtype=np.float32)) == 0
        assert bq.get_stats()["published_chunks"] == 0

    def test_subscribers_get_isolated_copies(self):
        bq = BroadcastQueue(name="t", max_queue_size=4)
        a = bq.subscribe("a")
        b = bq.subscribe("b")

        bq.publish(_chunk(7.0))
        chunk_a = a.get_nowait()
        chunk_b = b.get_nowait()

        chunk_a[:] = -1.0  # mutating one subscriber's view ...
        assert np.all(chunk_b == 7.0), "... must not affect another subscriber"

    def test_unsubscribe_stops_delivery(self):
        bq = BroadcastQueue(name="t", max_queue_size=4)
        bq.subscribe("a")
        assert bq.unsubscribe("a") is True
        assert bq.unsubscribe("a") is False
        assert bq.publish(_chunk(1.0)) == 0


class FakeSource:
    """Minimal audio source exposing the broadcast-queue contract."""

    def __init__(self):
        self.broadcast = BroadcastQueue(name="fake-source", max_queue_size=8)

    def get_broadcast_queue(self) -> BroadcastQueue:
        return self.broadcast


def _streamer(source) -> IcecastStreamer:
    config = IcecastConfig(
        server="127.0.0.1",
        port=8000,
        password="x",
        mount="test.mp3",
        name="Test",
        description="Test stream",
    )
    return IcecastStreamer(config, source)


class TestIcecastSubscriptionPath:
    def test_read_before_subscription_returns_none(self):
        streamer = _streamer(FakeSource())
        assert streamer._get_audio_from_subscription(timeout=0.01) is None

    def test_subscription_receives_published_audio(self):
        source = FakeSource()
        streamer = _streamer(source)
        streamer._audio_queue = source.get_broadcast_queue().subscribe(
            streamer._subscriber_id
        )

        source.get_broadcast_queue().publish(_chunk(3.0))
        chunk = streamer._get_audio_from_subscription(timeout=0.5)
        assert chunk is not None and chunk[0] == 3.0

        # Empty queue times out to None instead of raising.
        assert streamer._get_audio_from_subscription(timeout=0.01) is None

    def test_stop_unsubscribes_from_source(self):
        source = FakeSource()
        streamer = _streamer(source)
        streamer._audio_queue = source.get_broadcast_queue().subscribe(
            streamer._subscriber_id
        )
        assert source.get_broadcast_queue().get_stats()["subscribers"] == 1

        streamer.stop()

        assert streamer._audio_queue is None
        assert source.get_broadcast_queue().get_stats()["subscribers"] == 0
