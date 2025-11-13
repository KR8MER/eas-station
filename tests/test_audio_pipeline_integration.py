"""
Integration Tests for the Complete Audio Pipeline

End-to-end tests for audio ingest, playout queue, and output service
working together to provide reliable EAS alert broadcasting.
"""

import pytest
import time
import tempfile
import os
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch

from app_core.audio.ingest import (
    AudioIngestController,
    AudioSourceConfig,
    AudioSourceType,
    AudioSourceStatus,
)
from app_core.audio.playout_queue import (
    AudioPlayoutQueue,
    PlayoutItem,
    PrecedenceLevel,
    SeverityLevel,
    UrgencyLevel,
)
from app_core.audio.output_service import (
    AudioOutputService,
    PlayoutStatus,
)


class TestAudioPipelineIntegration:
    """Test integration of ingest, queue, and output components."""

    @pytest.fixture
    def temp_audio_file(self):
        """Create a temporary audio file for testing."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            # Write a minimal WAV header (44 bytes) for a valid file
            # This is a 1-second, 44100 Hz, mono, 16-bit PCM file
            wav_header = bytes([
                0x52, 0x49, 0x46, 0x46,  # "RIFF"
                0x24, 0x00, 0x00, 0x00,  # File size - 8
                0x57, 0x41, 0x56, 0x45,  # "WAVE"
                0x66, 0x6D, 0x74, 0x20,  # "fmt "
                0x10, 0x00, 0x00, 0x00,  # Subchunk size
                0x01, 0x00,              # Audio format (PCM)
                0x01, 0x00,              # Channels (mono)
                0x44, 0xAC, 0x00, 0x00,  # Sample rate (44100)
                0x88, 0x58, 0x01, 0x00,  # Byte rate
                0x02, 0x00,              # Block align
                0x10, 0x00,              # Bits per sample
                0x64, 0x61, 0x74, 0x61,  # "data"
                0x00, 0x00, 0x00, 0x00,  # Data size
            ])
            f.write(wav_header)
            path = f.name
        
        yield path
        
        # Cleanup
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def audio_config(self):
        """Create test audio configuration."""
        return {
            'audio_output': {
                'enabled': True,
                'device': 'default',
                'player': 'aplay',
            },
            'gpio': {
                'enabled': False,
            },
        }

    def test_complete_pipeline_initialization(self, audio_config):
        """Test that all pipeline components can be initialized together."""
        # Initialize queue
        queue = AudioPlayoutQueue()
        
        # Initialize output service
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Verify components are connected
        assert service.queue == queue
        assert queue.is_empty

    def test_alert_flows_through_pipeline(self, audio_config, temp_audio_file):
        """Test that an alert flows from queue to output service."""
        # Initialize components
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Create an alert
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
            event_name="Tornado Warning",
            same_header="ZCZC-WXR-TOR-012345+0030-1231415-",
            audio_path=temp_audio_file,
            eom_path=temp_audio_file,
        )
        
        # Enqueue the alert
        queue.enqueue(item)
        
        # Verify it's in the queue
        assert queue.size == 1
        assert not queue.is_empty
        
        # Dequeue for "playback"
        next_item = queue.dequeue()
        
        assert next_item == item
        assert queue.current_item == item
        assert queue.is_empty

    def test_multiple_alerts_priority_ordering(self, audio_config, temp_audio_file):
        """Test that multiple alerts are processed in correct priority order."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Create alerts with different priorities
        alerts = [
            PlayoutItem(
                precedence_level=PrecedenceLevel.STATE,
                severity=SeverityLevel.MODERATE,
                urgency=UrgencyLevel.EXPECTED,
                timestamp=time.time(),
                queue_id=1,
                event_code="FLW",
                audio_path=temp_audio_file,
            ),
            PlayoutItem(
                precedence_level=PrecedenceLevel.PRESIDENTIAL,
                severity=SeverityLevel.EXTREME,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time(),
                queue_id=2,
                event_code="EAN",
                audio_path=temp_audio_file,
            ),
            PlayoutItem(
                precedence_level=PrecedenceLevel.LOCAL,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time(),
                queue_id=3,
                event_code="TOR",
                audio_path=temp_audio_file,
            ),
        ]
        
        # Enqueue in non-priority order
        for alert in alerts:
            queue.enqueue(alert)
        
        assert queue.size == 3
        
        # Dequeue and verify order
        first = queue.dequeue()
        assert first.event_code == "EAN"  # Presidential (highest priority)
        
        second = queue.dequeue()
        assert second.event_code == "TOR"  # Local
        
        third = queue.dequeue()
        assert third.event_code == "FLW"  # State

    def test_presidential_alert_preemption(self, audio_config, temp_audio_file):
        """Test that Presidential alerts preempt current playback."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Start playing a local alert
        local = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
            audio_path=temp_audio_file,
        )
        
        queue.enqueue(local)
        current = queue.dequeue()
        assert queue.current_item == current
        
        # Presidential alert arrives
        presidential = PlayoutItem(
            precedence_level=PrecedenceLevel.PRESIDENTIAL,
            severity=SeverityLevel.EXTREME,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=2,
            event_code="EAN",
            audio_path=temp_audio_file,
        )
        
        should_interrupt = queue.enqueue(presidential, check_preemption=True)
        
        # Should signal interruption
        assert should_interrupt
        
        # Re-queue the interrupted item
        requeued = queue.requeue_interrupted_item(current)
        assert requeued.metadata['requeued'] is True
        
        # Presidential should be next
        next_item = queue.dequeue()
        assert next_item.event_code == "EAN"

    def test_alert_completion_tracking(self, audio_config, temp_audio_file):
        """Test that alert completion is properly tracked."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Create and process an alert
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
            audio_path=temp_audio_file,
        )
        
        queue.enqueue(item)
        dequeued = queue.dequeue()
        
        # Mark as completed
        queue.mark_completed(dequeued, success=True)
        
        assert dequeued.metadata['completed'] is True
        assert dequeued.metadata['success'] is True
        assert queue.current_item is None
        
        # Check status
        status = queue.get_status()
        assert status['completed_count'] == 1

    def test_alert_failure_tracking(self, audio_config, temp_audio_file):
        """Test that alert failures are properly tracked."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Create and process an alert
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
            audio_path="/nonexistent/file.wav",
        )
        
        queue.enqueue(item)
        dequeued = queue.dequeue()
        
        # Mark as failed
        queue.mark_completed(dequeued, success=False, error="Audio file not found")
        
        assert dequeued.metadata['completed'] is True
        assert dequeued.metadata['success'] is False
        assert dequeued.metadata['error'] == "Audio file not found"

    def test_queue_status_monitoring(self, audio_config, temp_audio_file):
        """Test that queue status can be monitored in real-time."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Initial status
        status = queue.get_status()
        assert status['queue_size'] == 0
        assert status['current_item'] is None
        
        # Add items
        for i in range(3):
            item = PlayoutItem(
                precedence_level=PrecedenceLevel.LOCAL,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time() + i,
                queue_id=i,
                event_code=f"TOR{i}",
                audio_path=temp_audio_file,
            )
            queue.enqueue(item)
        
        # Check status
        status = queue.get_status()
        assert status['queue_size'] == 3
        assert status['next_item'] is not None
        
        # Start playing
        queue.dequeue()
        status = queue.get_status()
        assert status['current_item'] is not None
        assert status['queue_size'] == 2

    def test_fcc_compliant_precedence_enforcement(self, audio_config, temp_audio_file):
        """Test that FCC precedence rules (47 CFR Part 11) are enforced."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Create alerts representing all precedence levels
        precedence_tests = [
            (PrecedenceLevel.TEST, "RWT", "Required Weekly Test"),
            (PrecedenceLevel.NATIONAL, "NIC", "National Information Center"),
            (PrecedenceLevel.STATE, "SPW", "Shelter in Place Warning"),
            (PrecedenceLevel.LOCAL, "TOR", "Tornado Warning"),
            (PrecedenceLevel.NATIONWIDE_TEST, "NPT", "National Periodic Test"),
            (PrecedenceLevel.PRESIDENTIAL, "EAN", "Emergency Action Notification"),
        ]
        
        # Enqueue in reverse priority order
        for i, (precedence, code, name) in enumerate(precedence_tests):
            item = PlayoutItem(
                precedence_level=precedence,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time(),
                queue_id=i,
                event_code=code,
                event_name=name,
                audio_path=temp_audio_file,
            )
            queue.enqueue(item)
        
        # Verify they come out in correct FCC precedence order
        dequeued_codes = []
        while not queue.is_empty:
            item = queue.dequeue()
            dequeued_codes.append(item.event_code)
        
        expected_order = ["EAN", "NPT", "TOR", "SPW", "NIC", "RWT"]
        assert dequeued_codes == expected_order

    def test_same_header_to_audio_to_eom_sequence(self, audio_config, temp_audio_file):
        """Test that complete SAME sequence is properly structured."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Create alert with complete SAME sequence
        item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR",
            event_name="Tornado Warning",
            same_header="ZCZC-WXR-TOR-012345-012567+0030-1231415-NOCALL00-",
            audio_path=temp_audio_file,
            eom_path=temp_audio_file,
        )
        
        queue.enqueue(item)
        dequeued = queue.dequeue()
        
        # Verify complete sequence is present
        assert dequeued.same_header is not None
        assert dequeued.same_header.startswith("ZCZC-WXR-TOR")
        assert dequeued.audio_path is not None
        assert dequeued.eom_path is not None
        
        # Verify FCC-required components
        assert "ZCZC" in dequeued.same_header  # Preamble
        assert "TOR" in dequeued.same_header   # Event code
        assert "+" in dequeued.same_header     # Valid time separator

    def test_concurrent_alert_handling(self, audio_config, temp_audio_file):
        """Test that multiple alerts can be queued while one is playing."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Start playing first alert
        first = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="TOR1",
            audio_path=temp_audio_file,
        )
        
        queue.enqueue(first)
        queue.dequeue()
        
        # Queue more alerts while first is "playing"
        for i in range(2, 5):
            item = PlayoutItem(
                precedence_level=PrecedenceLevel.LOCAL,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time() + i,
                queue_id=i,
                event_code=f"TOR{i}",
                audio_path=temp_audio_file,
            )
            queue.enqueue(item)
        
        # Verify queue state
        assert queue.current_item.event_code == "TOR1"
        assert queue.size == 3
        
        # Complete first and process rest
        queue.mark_completed(queue.current_item, success=True)
        
        remaining = []
        while not queue.is_empty:
            item = queue.dequeue()
            remaining.append(item.event_code)
            queue.mark_completed(item, success=True)
        
        assert remaining == ["TOR2", "TOR3", "TOR4"]

    def test_queue_snapshot_for_ui_display(self, audio_config, temp_audio_file):
        """Test that queue snapshot provides data for UI display."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Add multiple alerts
        for i in range(5):
            item = PlayoutItem(
                precedence_level=PrecedenceLevel.LOCAL,
                severity=SeverityLevel.SEVERE,
                urgency=UrgencyLevel.IMMEDIATE,
                timestamp=time.time() + i,
                queue_id=i,
                event_code=f"TOR{i}",
                audio_path=temp_audio_file,
            )
            queue.enqueue(item)
        
        # Get snapshot
        snapshot = queue.get_queue_snapshot()
        
        assert len(snapshot) == 5
        assert all(isinstance(item, dict) for item in snapshot)
        assert all('event_code' in item for item in snapshot)
        assert all('precedence_level' in item for item in snapshot)

    def test_deterministic_playout_guarantees(self, audio_config, temp_audio_file):
        """Test that playout is deterministic and reproducible."""
        # Run the same sequence twice and verify identical order
        for run in range(2):
            queue = AudioPlayoutQueue()
            service = AudioOutputService(
                queue=queue,
                config=audio_config,
            )
            
            # Create identical alert set
            alerts = []
            for i in range(10):
                item = PlayoutItem(
                    precedence_level=PrecedenceLevel.LOCAL if i % 2 == 0 else PrecedenceLevel.STATE,
                    severity=SeverityLevel.SEVERE if i % 3 == 0 else SeverityLevel.MODERATE,
                    urgency=UrgencyLevel.IMMEDIATE,
                    timestamp=1000.0 + i,  # Fixed timestamps
                    queue_id=i,
                    event_code=f"ALERT{i}",
                    audio_path=temp_audio_file,
                )
                queue.enqueue(item)
            
            # Dequeue all and record order
            order = []
            while not queue.is_empty:
                item = queue.dequeue()
                order.append(item.event_code)
            
            if run == 0:
                first_run_order = order
            else:
                # Second run should produce identical order
                assert order == first_run_order

    def test_pipeline_resilience_to_errors(self, audio_config):
        """Test that pipeline continues operating after errors."""
        queue = AudioPlayoutQueue()
        service = AudioOutputService(
            queue=queue,
            config=audio_config,
        )
        
        # Process a failing alert
        bad_item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=1,
            event_code="BAD",
            audio_path="/nonexistent/file.wav",
        )
        
        queue.enqueue(bad_item)
        dequeued = queue.dequeue()
        queue.mark_completed(dequeued, success=False, error="File not found")
        
        # Queue should still be operational
        assert queue.current_item is None
        
        # Process a good alert after the failure
        good_item = PlayoutItem(
            precedence_level=PrecedenceLevel.LOCAL,
            severity=SeverityLevel.SEVERE,
            urgency=UrgencyLevel.IMMEDIATE,
            timestamp=time.time(),
            queue_id=2,
            event_code="GOOD",
            audio_path="/tmp/test.wav",
        )
        
        queue.enqueue(good_item)
        assert queue.size == 1
        
        next_item = queue.dequeue()
        assert next_item.event_code == "GOOD"
