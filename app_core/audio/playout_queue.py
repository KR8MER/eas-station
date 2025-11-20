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
Audio Playout Queue with FCC-compliant precedence logic per 47 CFR Part 11.

This module implements a priority queue for EAS alert playback that enforces
the FCC-mandated precedence order:
1. Presidential/National Emergency (EAN) - Absolute priority
2. Local alerts
3. State/Regional alerts
4. National non-Presidential alerts

Within each precedence level, alerts are prioritized by:
- Severity (Extreme > Severe > Moderate > Minor > Unknown)
- Urgency (Immediate > Expected > Future > Past > Unknown)
- Timestamp (older alerts first)
"""

from __future__ import annotations

import heapq
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple


class PrecedenceLevel(IntEnum):
    """
    FCC-mandated EAS alert precedence levels per 47 CFR § 11.31.

    Lower numeric values = higher priority (for use with heapq min-heap).
    """
    PRESIDENTIAL = 1       # EAN - Presidential National Emergency
    NATIONWIDE_TEST = 2    # NPT - Nationwide Test
    LOCAL = 3              # Local alerts
    STATE = 4              # State/regional alerts
    NATIONAL = 5           # National non-Presidential alerts
    TEST = 6               # Required Monthly/Weekly Tests (RMT, RWT)
    UNKNOWN = 99           # Unknown/unclassified alerts


class SeverityLevel(IntEnum):
    """CAP severity levels in priority order."""
    EXTREME = 1
    SEVERE = 2
    MODERATE = 3
    MINOR = 4
    UNKNOWN = 5


class UrgencyLevel(IntEnum):
    """CAP urgency levels in priority order."""
    IMMEDIATE = 1
    EXPECTED = 2
    FUTURE = 3
    PAST = 4
    UNKNOWN = 5


@dataclass(order=True)
class PlayoutItem:
    """
    A prioritized queue item representing an EAS alert ready for playout.

    Items are automatically ordered by priority tuple:
    (precedence_level, severity, urgency, timestamp, queue_id)
    """

    # Priority fields (used for sorting)
    precedence_level: int = field(compare=True)
    severity: int = field(compare=True)
    urgency: int = field(compare=True)
    timestamp: float = field(compare=True)
    queue_id: int = field(compare=True)

    # Payload fields (not used for sorting)
    alert_id: Optional[int] = field(compare=False, default=None)
    eas_message_id: Optional[int] = field(compare=False, default=None)
    event_code: Optional[str] = field(compare=False, default=None)
    event_name: Optional[str] = field(compare=False, default=None)
    same_header: Optional[str] = field(compare=False, default=None)
    audio_path: Optional[str] = field(compare=False, default=None)
    eom_path: Optional[str] = field(compare=False, default=None)
    metadata: Dict[str, Any] = field(compare=False, default_factory=dict)

    @staticmethod
    def _parse_severity(severity: Optional[str]) -> int:
        """Convert CAP severity string to numeric priority level."""
        if not severity:
            return SeverityLevel.UNKNOWN

        severity_upper = severity.upper()
        mapping = {
            'EXTREME': SeverityLevel.EXTREME,
            'SEVERE': SeverityLevel.SEVERE,
            'MODERATE': SeverityLevel.MODERATE,
            'MINOR': SeverityLevel.MINOR,
        }
        return mapping.get(severity_upper, SeverityLevel.UNKNOWN)

    @staticmethod
    def _parse_urgency(urgency: Optional[str]) -> int:
        """Convert CAP urgency string to numeric priority level."""
        if not urgency:
            return UrgencyLevel.UNKNOWN

        urgency_upper = urgency.upper()
        mapping = {
            'IMMEDIATE': UrgencyLevel.IMMEDIATE,
            'EXPECTED': UrgencyLevel.EXPECTED,
            'FUTURE': UrgencyLevel.FUTURE,
            'PAST': UrgencyLevel.PAST,
        }
        return mapping.get(urgency_upper, UrgencyLevel.UNKNOWN)

    @staticmethod
    def _determine_precedence(
        event_code: Optional[str],
        scope: Optional[str],
        message_type: Optional[str],
    ) -> int:
        """
        Determine FCC precedence level per 47 CFR § 11.31.

        Args:
            event_code: Three-letter EAS event code (e.g., 'EAN', 'NPT', 'TOR')
            scope: CAP scope field ('Public', 'Restricted', 'Private')
            message_type: CAP message_type ('Alert', 'Update', 'Cancel', 'Test')

        Returns:
            PrecedenceLevel enum value
        """
        if not event_code:
            return PrecedenceLevel.UNKNOWN

        event_upper = event_code.upper()

        # Presidential National Emergency - absolute priority
        if event_upper == 'EAN':
            return PrecedenceLevel.PRESIDENTIAL

        # Nationwide tests - high priority
        if event_upper == 'NPT':
            return PrecedenceLevel.NATIONWIDE_TEST

        # Required tests - lower priority
        if event_upper in ('RMT', 'RWT'):
            return PrecedenceLevel.TEST

        # Test messages go to test priority
        msg_type_upper = (message_type or '').upper()
        if msg_type_upper == 'TEST':
            return PrecedenceLevel.TEST

        # Scope-based precedence for operational alerts
        # Note: CAP doesn't have explicit "local/state/national" field,
        # so we infer from scope and context. This may need customization
        # based on your specific CAP source configuration.
        scope_upper = (scope or '').upper()

        # For now, treat all public operational alerts as LOCAL precedence
        # unless they have specific national event codes
        if scope_upper == 'PUBLIC':
            # National-level events (this list can be expanded)
            national_events = {'EAN', 'NPT', 'NIC', 'ADR', 'AVW', 'AVA'}
            if event_upper in national_events:
                return PrecedenceLevel.NATIONAL

            # State-level events (this list can be expanded)
            state_events = {'SPW', 'EVI', 'CEM', 'DMO'}
            if event_upper in state_events:
                return PrecedenceLevel.STATE

            # Default to LOCAL for public alerts
            return PrecedenceLevel.LOCAL

        return PrecedenceLevel.UNKNOWN

    @classmethod
    def from_alert(
        cls,
        alert: Any,
        eas_message: Any,
        broadcast_result: Dict[str, Any],
        queue_id: int,
    ) -> PlayoutItem:
        """
        Create a PlayoutItem from a CAPAlert, EASMessage, and broadcast result.

        Args:
            alert: CAPAlert database model instance
            eas_message: EASMessage database model instance
            broadcast_result: Result dict from EASBroadcaster.handle_alert()
            queue_id: Unique sequential ID for this queue item

        Returns:
            Configured PlayoutItem ready for queue insertion
        """
        event_code = broadcast_result.get('event_code')
        severity_str = getattr(alert, 'severity', None)
        urgency_str = getattr(alert, 'urgency', None)
        scope = getattr(alert, 'scope', None)
        message_type = getattr(alert, 'message_type', None)

        precedence = cls._determine_precedence(event_code, scope, message_type)
        severity = cls._parse_severity(severity_str)
        urgency = cls._parse_urgency(urgency_str)

        # Use alert sent time, or current time if not available
        sent_dt = getattr(alert, 'sent', None)
        if sent_dt and isinstance(sent_dt, datetime):
            timestamp = sent_dt.timestamp()
        else:
            timestamp = datetime.now(timezone.utc).timestamp()

        return cls(
            precedence_level=precedence,
            severity=severity,
            urgency=urgency,
            timestamp=timestamp,
            queue_id=queue_id,
            alert_id=getattr(alert, 'id', None),
            eas_message_id=getattr(eas_message, 'id', None),
            event_code=event_code,
            event_name=getattr(alert, 'event', None),
            same_header=broadcast_result.get('same_header'),
            audio_path=broadcast_result.get('audio_path'),
            eom_path=broadcast_result.get('eom_path'),
            metadata={
                'identifier': getattr(alert, 'identifier', None),
                'status': getattr(alert, 'status', None),
                'message_type': message_type,
                'scope': scope,
                'severity': severity_str,
                'urgency': urgency_str,
                'certainty': getattr(alert, 'certainty', None),
                'location_codes': broadcast_result.get('location_codes', []),
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize PlayoutItem to a dictionary for logging/storage."""
        return {
            'queue_id': self.queue_id,
            'alert_id': self.alert_id,
            'eas_message_id': self.eas_message_id,
            'event_code': self.event_code,
            'event_name': self.event_name,
            'same_header': self.same_header,
            'audio_path': self.audio_path,
            'eom_path': self.eom_path,
            'precedence_level': self.precedence_level,
            'severity': self.severity,
            'urgency': self.urgency,
            'timestamp': self.timestamp,
            'metadata': self.metadata,
        }


class AudioPlayoutQueue:
    """
    Thread-safe priority queue for EAS alert playback with FCC precedence enforcement.

    Features:
    - FCC-compliant precedence per 47 CFR § 11.31
    - Automatic priority sorting by (precedence, severity, urgency, timestamp)
    - Preemption support for high-priority alerts (e.g., EAN)
    - Thread-safe operations with locking
    - Playback state tracking (queued, playing, completed)

    Usage:
        queue = AudioPlayoutQueue(logger)

        # Enqueue an alert
        item = PlayoutItem.from_alert(alert, eas_message, result, queue_id)
        should_interrupt = queue.enqueue(item)

        if should_interrupt:
            # Stop current playback and start new high-priority alert
            pass

        # Get next item to play
        next_item = queue.dequeue()
        if next_item:
            # Play the audio
            pass
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the audio playout queue.

        Args:
            logger: Logger instance for queue operations
        """
        self.logger = logger or logging.getLogger(__name__)
        self._queue: List[PlayoutItem] = []
        self._current_item: Optional[PlayoutItem] = None
        self._completed_items: List[PlayoutItem] = []
        self._next_queue_id = 1
        self._lock = threading.RLock()

    def enqueue(
        self,
        item: PlayoutItem,
        *,
        check_preemption: bool = True,
    ) -> bool:
        """
        Add an alert to the playout queue with automatic priority sorting.

        Args:
            item: PlayoutItem to add to the queue
            check_preemption: If True, check if this item should preempt current playback

        Returns:
            True if the item should interrupt current playback, False otherwise
        """
        with self._lock:
            heapq.heappush(self._queue, item)

            self.logger.info(
                'Enqueued alert %s (event=%s, precedence=%s) with queue_id=%s',
                item.alert_id,
                item.event_code,
                PrecedenceLevel(item.precedence_level).name,
                item.queue_id,
            )

            # Check if this item should preempt currently playing item
            if check_preemption and self._current_item:
                return self._should_preempt(item, self._current_item)

            return False

    def dequeue(self) -> Optional[PlayoutItem]:
        """
        Remove and return the highest-priority item from the queue.

        Returns:
            Next PlayoutItem to play, or None if queue is empty
        """
        with self._lock:
            if not self._queue:
                return None

            item = heapq.heappop(self._queue)
            self._current_item = item

            self.logger.info(
                'Dequeued alert %s (event=%s, precedence=%s) for playback',
                item.alert_id,
                item.event_code,
                PrecedenceLevel(item.precedence_level).name,
            )

            return item

    def peek(self) -> Optional[PlayoutItem]:
        """
        Return the highest-priority item without removing it.

        Returns:
            Next PlayoutItem that would be dequeued, or None if queue is empty
        """
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0]

    def mark_completed(
        self,
        item: PlayoutItem,
        *,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """
        Mark an item as completed after playback.

        Args:
            item: The PlayoutItem that finished playing
            success: Whether playback completed successfully
            error: Optional error message if playback failed
        """
        with self._lock:
            if self._current_item and self._current_item.queue_id == item.queue_id:
                self._current_item = None

            # Add completion metadata
            item.metadata['completed'] = True
            item.metadata['success'] = success
            if error:
                item.metadata['error'] = error
            item.metadata['completed_at'] = datetime.now(timezone.utc).isoformat()

            self._completed_items.append(item)

            # Keep only last 100 completed items to prevent unbounded growth
            if len(self._completed_items) > 100:
                self._completed_items = self._completed_items[-100:]

            status = 'successfully' if success else 'with error'
            self.logger.info(
                'Marked alert %s (event=%s) as completed %s',
                item.alert_id,
                item.event_code,
                status,
            )

    def get_next_queue_id(self) -> int:
        """Get the next sequential queue ID for item creation."""
        with self._lock:
            queue_id = self._next_queue_id
            self._next_queue_id += 1
            return queue_id

    def requeue_interrupted_item(self, item: PlayoutItem) -> PlayoutItem:
        """
        Re-queue an interrupted item with a fresh queue ID.

        When a lower-priority alert is preempted by a higher-priority alert,
        it should be re-queued so it can be played after the interruption.

        Args:
            item: The PlayoutItem that was interrupted

        Returns:
            New PlayoutItem with fresh queue ID, ready for re-queuing
        """
        with self._lock:
            # Create a new item with the same priority but fresh queue ID
            new_queue_id = self.get_next_queue_id()

            new_item = PlayoutItem(
                precedence_level=item.precedence_level,
                severity=item.severity,
                urgency=item.urgency,
                timestamp=item.timestamp,  # Keep original timestamp
                queue_id=new_queue_id,
                alert_id=item.alert_id,
                eas_message_id=item.eas_message_id,
                event_code=item.event_code,
                event_name=item.event_name,
                same_header=item.same_header,
                audio_path=item.audio_path,
                eom_path=item.eom_path,
                metadata=dict(item.metadata),  # Copy metadata
            )

            # Add metadata about the interruption
            new_item.metadata['requeued'] = True
            new_item.metadata['original_queue_id'] = item.queue_id
            new_item.metadata['requeue_reason'] = 'Interrupted by higher-priority alert'
            new_item.metadata['requeued_at'] = datetime.now(timezone.utc).isoformat()

            # Enqueue the new item
            heapq.heappush(self._queue, new_item)

            self.logger.info(
                'Re-queued interrupted alert %s (event=%s) with new queue_id=%s',
                new_item.alert_id,
                new_item.event_code,
                new_queue_id,
            )

            return new_item

    def _should_preempt(
        self,
        new_item: PlayoutItem,
        current_item: PlayoutItem,
    ) -> bool:
        """
        Determine if a new item should preempt the currently playing item.

        Per 47 CFR § 11.31, Presidential (EAN) alerts MUST preempt all others.
        Other high-priority alerts may also preempt based on precedence.

        Args:
            new_item: Newly enqueued item
            current_item: Currently playing item

        Returns:
            True if new_item should interrupt current_item playback
        """
        # Presidential alerts (EAN) always preempt
        if new_item.precedence_level == PrecedenceLevel.PRESIDENTIAL:
            self.logger.warning(
                'Presidential alert (EAN) must preempt current playback'
            )
            return True

        # Check if new item has higher priority than current
        # (lower numeric values = higher priority)
        new_priority = (
            new_item.precedence_level,
            new_item.severity,
            new_item.urgency,
        )
        current_priority = (
            current_item.precedence_level,
            current_item.severity,
            current_item.urgency,
        )

        if new_priority < current_priority:
            self.logger.warning(
                'High-priority alert %s (precedence=%s) should preempt current alert %s',
                new_item.event_code,
                PrecedenceLevel(new_item.precedence_level).name,
                current_item.event_code,
            )
            return True

        return False

    def clear(self) -> int:
        """
        Clear all pending items from the queue.

        Returns:
            Number of items removed from the queue
        """
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self.logger.warning('Cleared %s items from playout queue', count)
            return count

    def get_status(self) -> Dict[str, Any]:
        """
        Get current queue status for monitoring/debugging.

        Returns:
            Dictionary with queue state information
        """
        with self._lock:
            return {
                'queue_size': len(self._queue),
                'current_item': self._current_item.to_dict() if self._current_item else None,
                'next_item': self.peek().to_dict() if self._queue else None,
                'completed_count': len(self._completed_items),
                'recent_completed': [
                    item.to_dict() for item in self._completed_items[-5:]
                ],
            }

    def get_queue_snapshot(self) -> List[Dict[str, Any]]:
        """
        Get a snapshot of all queued items for display/debugging.

        Returns:
            List of serialized PlayoutItem dictionaries in priority order
        """
        with self._lock:
            # Return a copy of the queue in sorted order
            sorted_queue = sorted(self._queue)
            return [item.to_dict() for item in sorted_queue]

    @property
    def current_item(self) -> Optional[PlayoutItem]:
        """Get the currently playing item (read-only)."""
        with self._lock:
            return self._current_item

    @property
    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        with self._lock:
            return len(self._queue) == 0

    @property
    def size(self) -> int:
        """Get the number of items in the queue."""
        with self._lock:
            return len(self._queue)
