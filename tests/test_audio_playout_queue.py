"""
Tests for the Audio Playout Queue

Unit tests for FCC-compliant priority queue, precedence logic,
and alert preemption functionality.
"""

import pytest
import time
from datetime import datetime, timezone
from unittest.mock import Mock

from app_core.audio.playout_queue import (
    AudioPlayoutQueue,
    PlayoutItem,
    PrecedenceLevel,
    SeverityLevel,
    UrgencyLevel,
)


class TestPrecedenceLevel:
    """Test FCC precedence level definitions."""

    def test_precedence_order(self):
        """Test that precedence levels are in correct priority order."""
        assert PrecedenceLevel.PRESIDENTIAL < PrecedenceLevel.NATIONWIDE_TEST
        assert PrecedenceLevel.NATIONWIDE_TEST < PrecedenceLevel.LOCAL
        assert PrecedenceLevel.LOCAL < PrecedenceLevel.STATE
        assert PrecedenceLevel.STATE < PrecedenceLevel.NATIONAL
        assert PrecedenceLevel.NATIONAL < PrecedenceLevel.TEST
        assert PrecedenceLevel.TEST < PrecedenceLevel.UNKNOWN

    def test_presidential_highest_priority(self):
        """Test that Presidential alerts have highest priority."""
        assert PrecedenceLevel.PRESIDENTIAL == 1
        assert PrecedenceLevel.PRESIDENTIAL < PrecedenceLevel.LOCAL
        assert PrecedenceLevel.PRESIDENTIAL < PrecedenceLevel.STATE
        assert PrecedenceLevel.PRESIDENTIAL < PrecedenceLevel.NATIONAL


class TestSeverityLevel:
    """Test CAP severity level definitions."""

    def test_severity_order(self):
        """Test that severity levels are in correct priority order."""
        assert SeverityLevel.EXTREME < SeverityLevel.SEVERE
        assert SeverityLevel.SEVERE < SeverityLevel.MODERATE
        assert SeverityLevel.MODERATE < SeverityLevel.MINOR
        assert SeverityLevel.MINOR < SeverityLevel.UNKNOWN


class TestUrgencyLevel:
    """Test CAP urgency level definitions."""

    def test_urgency_order(self):
        """Test that urgency levels are in correct priority order."""
        assert UrgencyLevel.IMMEDIATE < UrgencyLevel.EXPECTED
        assert UrgencyLevel.EXPECTED < UrgencyLevel.FUTURE
        assert UrgencyLevel.FUTURE < UrgencyLevel.PAST
        assert UrgencyLevel.PAST < UrgencyLevel.UNKNOWN


class TestPlayoutItem:
    """Test PlayoutItem creation and parsing."""

    def test_minimal_creation(self):
        """Test creating a minimal PlayoutItem."""
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
        )

        assert item.precedence_level == PrecedenceLevel.LOCAL
        assert item.severity == SeverityLevel.SEVERE
        assert item.urgency == UrgencyLevel.IMMEDIATE
        assert item.queue_id == 1

    def test_full_creation(self):
        """Test creating a full PlayoutItem with all fields."""
        timestamp = time.time()
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.STATE,
            severity=SeverityLevel.EXTREME,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=timestamp,
            queue_id=42,
            alert_id=100,
            eas_message_id=200,
            event_code="TOR",
            event_name="Tornado Warning",
            same_header="ZCZC-WXR-TOR-012345-012567+0030-1231415-NOCALL00-",
            audio_path="/tmp/tornado.wav",
            eom_path="/tmp/eom.wav",
            metadata={"test": "data"},
        )

        assert item.queue_id == 42
        assert item.alert_id == 100
        assert item.eas_message_id == 200
        assert item.event_code == "TOR"
        assert item.event_name == "Tornado Warning"
        assert item.same_header.startswith("ZCZC-WXR-TOR")
        assert item.audio_path == "/tmp/tornado.wav"
        assert item.eom_path == "/tmp/eom.wav"
        assert item.metadata["test"] == "data"

    def test_parse_severity_valid(self):
        """Test parsing valid severity strings."""
        assert PlayoutItem._parse_severity("Extreme") == SeverityLevel.EXTREME
        assert PlayoutItem._parse_severity("SEVERE") == SeverityLevel.SEVERE
        assert PlayoutItem._parse_severity("moderate") == SeverityLevel.MODERATE
        assert PlayoutItem._parse_severity("Minor") == SeverityLevel.MINOR

    def test_parse_severity_invalid(self):
        """Test parsing invalid severity strings."""
        assert PlayoutItem._parse_severity("Invalid") == SeverityLevel.UNKNOWN
        assert PlayoutItem._parse_severity(None) == SeverityLevel.UNKNOWN
        assert PlayoutItem._parse_severity("") == SeverityLevel.UNKNOWN

    def test_parse_urgency_valid(self):
        """Test parsing valid urgency strings."""
        assert PlayoutItem._parse_urgency("Immediate") == UrgencyLevel.IMMEDIATE
        assert PlayoutItem._parse_urgency("EXPECTED") == UrgencyLevel.EXPECTED
        assert PlayoutItem._parse_urgency("future") == UrgencyLevel.FUTURE
        assert PlayoutItem._parse_urgency("Past") == UrgencyLevel.PAST

    def test_parse_urgency_invalid(self):
        """Test parsing invalid urgency strings."""
        assert PlayoutItem._parse_urgency("Invalid") == UrgencyLevel.UNKNOWN
        assert PlayoutItem._parse_urgency(None) == UrgencyLevel.UNKNOWN
        assert PlayoutItem._parse_urgency("") == UrgencyLevel.UNKNOWN

    def test_determine_precedence_presidential(self):
        """Test precedence determination for Presidential alerts."""
        precedence = PlayoutItem._determine_precedence("EAN", "Public", "Alert")
        assert precedence == PrecedenceLevel.PRESIDENTIAL

    def test_determine_precedence_nationwide_test(self):
        """Test precedence determination for Nationwide Test."""
        precedence = PlayoutItem._determine_precedence("NPT", "Public", "Test")
        assert precedence == PrecedenceLevel.NATIONWIDE_TEST

    def test_determine_precedence_required_tests(self):
        """Test precedence determination for Required Tests."""
        assert PlayoutItem._determine_precedence("RMT", "Public", "Alert") == PrecedenceLevel.TEST
        assert PlayoutItem._determine_precedence("RWT", "Public", "Alert") == PrecedenceLevel.TEST

    def test_determine_precedence_test_message_type(self):
        """Test that Test message type results in TEST precedence."""
        precedence = PlayoutItem._determine_precedence("TOR", "Public", "Test")
        assert precedence == PrecedenceLevel.TEST

    def test_determine_precedence_local(self):
        """Test precedence determination for local alerts."""
        precedence = PlayoutItem._determine_precedence("TOR", "Public", "Alert")
        assert precedence == PrecedenceLevel.LOCAL

    def test_determine_precedence_state(self):
        """Test precedence determination for state alerts."""
        # State-level events
        assert PlayoutItem._determine_precedence("SPW", "Public", "Alert") == PrecedenceLevel.STATE
        assert PlayoutItem._determine_precedence("EVI", "Public", "Alert") == PrecedenceLevel.STATE

    def test_determine_precedence_national(self):
        """Test precedence determination for national alerts."""
        # National-level events
        assert PlayoutItem._determine_precedence("NIC", "Public", "Alert") == PrecedenceLevel.NATIONAL
        assert PlayoutItem._determine_precedence("ADR", "Public", "Alert") == PrecedenceLevel.NATIONAL

    def test_determine_precedence_unknown(self):
        """Test precedence determination for unknown/invalid inputs."""
        assert PlayoutItem._determine_precedence(None, "Public", "Alert") == PrecedenceLevel.UNKNOWN
        assert PlayoutItem._determine_precedence("", "Public", "Alert") == PrecedenceLevel.UNKNOWN
        assert PlayoutItem._determine_precedence("TOR", None, "Alert") == PrecedenceLevel.UNKNOWN
        assert PlayoutItem._determine_precedence("TOR", "", "Alert") == PrecedenceLevel.UNKNOWN

    def test_to_dict(self):
        """Test serialization to dictionary."""
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            alert_id=100,
            event_code="TOR",
        )

        result = item.to_dict()

        assert result["queue_id"] == 1
        assert result["alert_id"] == 100
        assert result["event_code"] == "TOR"
        assert result["precedence_level"] == PrecedenceLevel.LOCAL
        assert result["severity"] == SeverityLevel.SEVERE
        assert result["urgency"] == UrgencyLevel.IMMEDIATE


class TestAudioPlayoutQueue:
    """Test AudioPlayoutQueue functionality."""

    def test_initialization(self):
        """Test queue initialization."""
        logger = Mock()
        queue = AudioPlayoutQueue(logger)

        assert queue.is_empty
        assert queue.size == 0
        assert queue.current_item is None

    def test_enqueue_single_item(self):
        """Test enqueueing a single item."""
        queue = AudioPlayoutQueue()
        
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )

        should_interrupt = queue.enqueue(item)

        assert not should_interrupt  # No current item to interrupt
        assert queue.size == 1
        assert not queue.is_empty

    def test_dequeue_single_item(self):
        """Test dequeueing a single item."""
        queue = AudioPlayoutQueue()
        
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )

        queue.enqueue(item)
        dequeued = queue.dequeue()

        assert dequeued == item
        assert queue.current_item == item
        assert queue.is_empty

    def test_dequeue_empty_queue(self):
        """Test dequeueing from an empty queue."""
        queue = AudioPlayoutQueue()
        
        dequeued = queue.dequeue()

        assert dequeued is None

    def test_peek(self):
        """Test peeking at the next item without removing it."""
        queue = AudioPlayoutQueue()
        
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )

        queue.enqueue(item)
        peeked = queue.peek()

        assert peeked == item
        assert queue.size == 1  # Item still in queue

    def test_priority_ordering_by_precedence(self):
        """Test that items are ordered by precedence level."""
        queue = AudioPlayoutQueue()
        
        # Add items in non-priority order
        local = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )
        
        presidential = PlayoutItem(
            precedence_level=PrecedenceLevel.PRESIDENTIAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=2,
            event_code="EAN",
        )
        
        state = PlayoutItem(
            precedence_level=PrecedenceLevel.STATE,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=3,
            event_code="SPW",
        )

        queue.enqueue(local)
        queue.enqueue(presidential)
        queue.enqueue(state)

        # Presidential should come first
        first = queue.dequeue()
        assert first.event_code == "EAN"

        # Local should come second (higher priority than state)
        second = queue.dequeue()
        assert second.event_code == "TOR"

        # State should come last
        third = queue.dequeue()
        assert third.event_code == "SPW"

    def test_priority_ordering_by_severity(self):
        """Test that items with same precedence are ordered by severity."""
        queue = AudioPlayoutQueue()
        
        timestamp = time.time()
        
        moderate = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.MODERATE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=timestamp,
            queue_id=1,
            event_code="FLW",
        )
        
        extreme = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.EXTREME,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=timestamp,
            queue_id=2,
            event_code="TOR",
        )

        queue.enqueue(moderate)
        queue.enqueue(extreme)

        # Extreme severity should come first
        first = queue.dequeue()
        assert first.event_code == "TOR"

        second = queue.dequeue()
        assert second.event_code == "FLW"

    def test_priority_ordering_by_urgency(self):
        """Test that items with same precedence and severity are ordered by urgency."""
        queue = AudioPlayoutQueue()
        
        timestamp = time.time()
        
        expected = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.EXPECTED,
            timestamp=timestamp,
            queue_id=1,
            event_code="SVR",
        )
        
        immediate = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=timestamp,
            queue_id=2,
            event_code="TOR",
        )

        queue.enqueue(expected)
        queue.enqueue(immediate)

        # Immediate urgency should come first
        first = queue.dequeue()
        assert first.event_code == "TOR"

        second = queue.dequeue()
        assert second.event_code == "SVR"

    def test_priority_ordering_by_timestamp(self):
        """Test that items with same priority are ordered by timestamp (older first)."""
        queue = AudioPlayoutQueue()
        
        newer = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time() + 10,
            queue_id=1,
            event_code="TOR2",
        )
        
        older = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=2,
            event_code="TOR1",
        )

        queue.enqueue(newer)
        queue.enqueue(older)

        # Older timestamp should come first
        first = queue.dequeue()
        assert first.event_code == "TOR1"

        second = queue.dequeue()
        assert second.event_code == "TOR2"

    def test_preemption_presidential(self):
        """Test that Presidential alerts preempt any current playback."""
        queue = AudioPlayoutQueue()
        
        # Simulate current item playing
        current = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )
        queue.enqueue(current)
        queue.dequeue()  # Start "playing" the tornado warning

        # Presidential alert arrives
        presidential = PlayoutItem(
            precedence_level=PrecedenceLevel.PRESIDENTIAL,
            severity=SeverityLevel.EXTREME,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=2,
            event_code="EAN",
        )

        should_interrupt = queue.enqueue(presidential, check_preemption=True)

        assert should_interrupt  # Presidential must preempt

    def test_preemption_higher_priority(self):
        """Test that higher-priority alerts preempt lower-priority ones."""
        queue = AudioPlayoutQueue()
        
        # Simulate current item playing (moderate severity)
        current = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.MODERATE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="FLW",
        )
        queue.enqueue(current)
        queue.dequeue()

        # Extreme severity alert arrives
        extreme = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.EXTREME,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=2,
            event_code="TOR",
        )

        should_interrupt = queue.enqueue(extreme, check_preemption=True)

        assert should_interrupt  # Higher severity should preempt

    def test_no_preemption_same_priority(self):
        """Test that same-priority alerts do not preempt."""
        queue = AudioPlayoutQueue()
        
        # Simulate current item playing
        current = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR1",
        )
        queue.enqueue(current)
        queue.dequeue()

        # Another alert with same priority
        similar = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time() + 1,
            queue_id=2,
            event_code="TOR2",
        )

        should_interrupt = queue.enqueue(similar, check_preemption=True)

        assert not should_interrupt  # Same priority should not preempt

    def test_mark_completed(self):
        """Test marking an item as completed."""
        queue = AudioPlayoutQueue()
        
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )

        queue.enqueue(item)
        dequeued = queue.dequeue()
        queue.mark_completed(dequeued, success=True)

        assert queue.current_item is None
        assert dequeued.metadata["completed"] is True
        assert dequeued.metadata["success"] is True

    def test_mark_completed_with_error(self):
        """Test marking an item as completed with error."""
        queue = AudioPlayoutQueue()
        
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )

        queue.enqueue(item)
        dequeued = queue.dequeue()
        queue.mark_completed(dequeued, success=False, error="Playback failed")

        assert dequeued.metadata["completed"] is True
        assert dequeued.metadata["success"] is False
        assert dequeued.metadata["error"] == "Playback failed"

    def test_requeue_interrupted_item(self):
        """Test re-queueing an interrupted item."""
        queue = AudioPlayoutQueue()
        
        # Use queue's next_queue_id to create original item so they differ
        original_queue_id = queue.get_next_queue_id()
        original = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=original_queue_id,
            event_code="TOR",
        )

        requeued = queue.requeue_interrupted_item(original)

        assert requeued.queue_id != original.queue_id
        assert requeued.queue_id == original_queue_id + 1  # Should get next sequential ID
        assert requeued.event_code == original.event_code
        assert requeued.metadata["requeued"] is True
        assert requeued.metadata["original_queue_id"] == original.queue_id
        assert queue.size == 1

    def test_get_next_queue_id(self):
        """Test sequential queue ID generation."""
        queue = AudioPlayoutQueue()
        
        id1 = queue.get_next_queue_id()
        id2 = queue.get_next_queue_id()
        id3 = queue.get_next_queue_id()

        assert id2 == id1 + 1
        assert id3 == id2 + 1

    def test_clear_queue(self):
        """Test clearing all items from queue."""
        queue = AudioPlayoutQueue()
        
        for i in range(5):
            item = PlayoutItem(
                precedence_level=PrecedenceLevel.LOCAL,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time(),
                queue_id=i,
                event_code=f"TOR{i}",
            )
            queue.enqueue(item)

        assert queue.size == 5

        cleared = queue.clear()

        assert cleared == 5
        assert queue.is_empty

    def test_get_status(self):
        """Test getting queue status."""
        queue = AudioPlayoutQueue()
        
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
        )

        queue.enqueue(item)
        status = queue.get_status()

        assert status["queue_size"] == 1
        assert status["next_item"] is not None
        assert status["current_item"] is None

        queue.dequeue()
        status = queue.get_status()

        assert status["current_item"] is not None
        assert status["current_item"]["event_code"] == "TOR"

    def test_get_queue_snapshot(self):
        """Test getting a snapshot of queued items."""
        queue = AudioPlayoutQueue()
        
        # Add multiple items
        for i in range(3):
            item = PlayoutItem(
                precedence_level=PrecedenceLevel.LOCAL,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time() + i,
                queue_id=i,
                event_code=f"TOR{i}",
            )
            queue.enqueue(item)

        snapshot = queue.get_queue_snapshot()

        assert len(snapshot) == 3
        assert all(isinstance(item, dict) for item in snapshot)
        # Should be in priority order (sorted)
        assert snapshot[0]["event_code"] == "TOR0"  # Oldest timestamp

    def test_thread_safety(self):
        """Test that queue operations are thread-safe."""
        import threading
        
        queue = AudioPlayoutQueue()
        errors = []

        def enqueue_items():
            try:
                for i in range(100):
                    item = PlayoutItem(
                        precedence_level=PrecedenceLevel.LOCAL,
                        severity=SeverityLevel.SEVERE,
                        urgency=UrgencyLevel.IMMEDIATE,
                        timestamp=time.time(),
                        queue_id=i,
                        event_code=f"TOR{i}",
                    )
                    queue.enqueue(item)
            except Exception as e:
                errors.append(e)

        # Start multiple threads enqueueing items
        threads = [threading.Thread(target=enqueue_items) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0  # No threading errors
        assert queue.size == 500  # All items enqueued
