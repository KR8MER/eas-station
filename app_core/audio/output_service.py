"""
Audio Output Service for deterministic EAS alert playback.

This module provides a service component that manages the audio playout queue
and coordinates with hardware (audio output devices, GPIO relays) for reliable
and FCC-compliant alert broadcasting.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

from .playout_queue import AudioPlayoutQueue, PlayoutItem


class PlayoutStatus(Enum):
    """Status of a playout operation."""
    PENDING = 'pending'
    PLAYING = 'playing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    INTERRUPTED = 'interrupted'


@dataclass
class PlayoutEvent:
    """Represents a playout event for logging and tracking."""
    timestamp: datetime
    status: PlayoutStatus
    item: Optional[PlayoutItem] = None
    target: str = 'local_audio'
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize event for storage/logging."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'status': self.status.value,
            'target': self.target,
            'latency_ms': self.latency_ms,
            'error': self.error,
            'item': self.item.to_dict() if self.item else None,
            'metadata': self.metadata,
        }


class AudioOutputService:
    """
    Service component for deterministic audio playout with queue management.

    Features:
    - Manages AudioPlayoutQueue for priority-based playback
    - Handles audio playback via subprocess (aplay, ffplay, etc.)
    - Tracks playout events and timing for compliance reporting
    - Supports GPIO relay control for transmitter activation
    - Handles preemption for high-priority alerts
    - Thread-safe operation with background worker

    Usage:
        service = AudioOutputService(
            queue=audio_queue,
            config=eas_config,
            logger=logger,
            gpio_controller=gpio,
        )

        # Start background playout worker
        service.start()

        # Service will automatically process queue items

        # Stop service
        service.stop()
    """

    def __init__(
        self,
        queue: AudioPlayoutQueue,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
        gpio_controller: Optional[Any] = None,
    ):
        """
        Initialize the audio output service.

        Args:
            queue: AudioPlayoutQueue instance to manage
            config: EAS configuration dictionary
            logger: Logger instance
            gpio_controller: Optional GPIORelayController for transmitter control
        """
        self.queue = queue
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.gpio_controller = gpio_controller

        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._interrupt_event = threading.Event()
        self._current_process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()

        # Event tracking
        self._playout_events: List[PlayoutEvent] = []
        self._event_callbacks: List[Callable[[PlayoutEvent], None]] = []

        # Audio player command from config
        self._audio_cmd = config.get('audio_player_cmd')
        if not self._audio_cmd:
            self.logger.warning('No audio player configured in EAS config')

    def start(self) -> None:
        """Start the background playout worker thread."""
        if self._running:
            self.logger.warning('AudioOutputService already running')
            return

        self._running = True
        self._stop_event.clear()
        self._interrupt_event.clear()

        self._worker_thread = threading.Thread(
            target=self._playout_worker,
            name='AudioOutputWorker',
            daemon=True,
        )
        self._worker_thread.start()

        self.logger.info('AudioOutputService started')

    def stop(self, timeout: float = 10.0) -> None:
        """
        Stop the background playout worker thread.

        Args:
            timeout: Maximum time to wait for worker to stop (seconds)
        """
        if not self._running:
            return

        self.logger.info('Stopping AudioOutputService...')
        self._running = False
        self._stop_event.set()

        # Interrupt any current playback
        self._interrupt_playback()

        # Wait for worker thread to finish
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                self.logger.warning('Worker thread did not stop within timeout')

        self.logger.info('AudioOutputService stopped')

    def register_event_callback(
        self,
        callback: Callable[[PlayoutEvent], None],
    ) -> None:
        """
        Register a callback to be invoked for each playout event.

        Args:
            callback: Function to call with PlayoutEvent
        """
        self._event_callbacks.append(callback)

    def get_recent_events(self, limit: int = 50) -> List[PlayoutEvent]:
        """
        Get recent playout events for monitoring.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of recent PlayoutEvent objects
        """
        return self._playout_events[-limit:]

    def _playout_worker(self) -> None:
        """
        Background worker thread that processes the playout queue.

        This runs continuously, checking for items in the queue and playing
        them in priority order. Handles preemption for high-priority alerts.
        """
        self.logger.info('Playout worker thread started')

        while self._running:
            try:
                # Check if we should interrupt current playback for higher priority
                if self.queue.peek():
                    next_item = self.queue.peek()
                    current = self.queue.current_item

                    if current and self.queue._should_preempt(next_item, current):
                        self.logger.warning(
                            'Higher-priority alert detected, interrupting current playback'
                        )
                        self._interrupt_playback()

                # Get next item from queue
                item = self.queue.dequeue()
                if not item:
                    # Queue is empty, wait a bit before checking again
                    if self._stop_event.wait(timeout=1.0):
                        break
                    continue

                # Log pending event
                self._log_event(PlayoutEvent(
                    timestamp=datetime.now(timezone.utc),
                    status=PlayoutStatus.PENDING,
                    item=item,
                ))

                # Play the alert
                self._play_alert(item)

            except Exception as exc:
                self.logger.exception(f'Error in playout worker: {exc}')
                time.sleep(1.0)

        self.logger.info('Playout worker thread stopped')

    def _play_alert(self, item: PlayoutItem) -> None:
        """
        Play a single alert item with full lifecycle management.

        Args:
            item: PlayoutItem to play
        """
        start_time = time.time()
        start_dt = datetime.now(timezone.utc)
        success = False
        play_success = False
        error_msg: Optional[str] = None

        try:
            # Log playing event
            self._log_event(PlayoutEvent(
                timestamp=start_dt,
                status=PlayoutStatus.PLAYING,
                item=item,
            ))

            # Activate GPIO relay if configured
            gpio_activated = False
            if self.gpio_controller:
                try:
                    self.gpio_controller.activate(self.logger)
                    gpio_activated = True
                except Exception as exc:
                    self.logger.warning(f'GPIO activation failed: {exc}')

            # Play main audio file
            if item.audio_path:
                play_success = self._play_audio_file(item.audio_path)
                if not play_success and not self._interrupt_event.is_set():
                    error_msg = f'Failed to play audio: {item.audio_path}'
            else:
                self.logger.warning('No audio path provided for alert %s', item.alert_id)
                error_msg = 'No audio path provided'

            # Play EOM if present and main playback succeeded
            if play_success and item.eom_path and not self._interrupt_event.is_set():
                self._play_audio_file(item.eom_path)

            # Determine overall success
            # Interrupted alerts should NOT be marked as successful
            if self._interrupt_event.is_set():
                success = False
                if not error_msg:
                    error_msg = 'Playback interrupted by higher-priority alert'
            else:
                success = play_success

            # Deactivate GPIO relay
            if gpio_activated:
                try:
                    self.gpio_controller.deactivate(self.logger)
                except Exception as exc:
                    self.logger.warning(f'GPIO deactivation failed: {exc}')

        except Exception as exc:
            self.logger.exception(f'Error playing alert: {exc}')
            error_msg = str(exc)
            success = False

        finally:
            # Calculate latency
            end_time = time.time()
            elapsed_ms = (end_time - start_time) * 1000.0

            # Determine final status
            if self._interrupt_event.is_set():
                status = PlayoutStatus.INTERRUPTED
                self._interrupt_event.clear()

                # Re-queue interrupted items so they can be played later
                try:
                    requeued_item = self.queue.requeue_interrupted_item(item)
                    self.logger.info(
                        'Re-queued interrupted alert %s (event=%s) as queue_id=%s',
                        item.alert_id,
                        item.event_code,
                        requeued_item.queue_id,
                    )
                except Exception as exc:
                    self.logger.exception(
                        f'Failed to re-queue interrupted alert {item.alert_id}: {exc}'
                    )

            elif success:
                status = PlayoutStatus.COMPLETED
            else:
                status = PlayoutStatus.FAILED

            # Log completion event
            self._log_event(PlayoutEvent(
                timestamp=datetime.now(timezone.utc),
                status=status,
                item=item,
                latency_ms=elapsed_ms,
                error=error_msg,
            ))

            # Mark item as completed in queue (or failed for interrupted items)
            # Interrupted items are NOT marked as completed since they were re-queued
            if status != PlayoutStatus.INTERRUPTED:
                self.queue.mark_completed(
                    item,
                    success=success,
                    error=error_msg,
                )
            else:
                # Clear current item for interrupted alerts
                # (they've been re-queued with a new ID)
                if self.queue._current_item and self.queue._current_item.queue_id == item.queue_id:
                    self.queue._current_item = None

            self.logger.info(
                'Playout %s for alert %s (event=%s) in %.1f ms',
                status.value,
                item.alert_id,
                item.event_code,
                elapsed_ms,
            )

    def _play_audio_file(self, audio_path: str) -> bool:
        """
        Play a single audio file using configured audio player.

        Args:
            audio_path: Path to audio file to play

        Returns:
            True if playback succeeded, False otherwise
        """
        if not self._audio_cmd:
            self.logger.debug('No audio player configured, skipping playback')
            return False

        if not os.path.exists(audio_path):
            self.logger.error(f'Audio file not found: {audio_path}')
            return False

        command = list(self._audio_cmd) + [audio_path]
        self.logger.info('Playing audio: %s', ' '.join(command))

        try:
            with self._process_lock:
                # Start the playback process
                # S603: subprocess call - command is from config, validated by operator
                self._current_process = subprocess.Popen(  # noqa: S603
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Wait for process to complete or be interrupted
            while True:
                if self._stop_event.is_set() or self._interrupt_event.is_set():
                    self._terminate_current_process()
                    return False

                # Check for higher-priority alerts during playback
                # This enables preemption per FCC requirements
                if self.queue.peek() and self.queue.current_item:
                    next_item = self.queue.peek()
                    current = self.queue.current_item
                    if self.queue._should_preempt(next_item, current):
                        self.logger.warning(
                            'Higher-priority alert detected during playback, '
                            'interrupting for %s',
                            next_item.event_code
                        )
                        self._interrupt_event.set()
                        self._terminate_current_process()
                        return False

                # Check if process has finished
                returncode = self._current_process.poll()
                if returncode is not None:
                    break

                # Sleep briefly before checking again
                # Use a short interval to ensure responsive preemption
                time.sleep(0.1)

            with self._process_lock:
                self._current_process = None

            # Check return code
            if returncode == 0:
                return True
            else:
                self.logger.warning(
                    f'Audio player exited with code {returncode} for {audio_path}'
                )
                return False

        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.exception(f'Failed to play audio {audio_path}: {exc}')
            with self._process_lock:
                self._current_process = None
            return False

    def _interrupt_playback(self) -> None:
        """Interrupt currently playing audio."""
        self._interrupt_event.set()
        self._terminate_current_process()

    def _terminate_current_process(self) -> None:
        """Terminate the current playback subprocess if running."""
        with self._process_lock:
            if self._current_process and self._current_process.poll() is None:
                try:
                    self.logger.info('Terminating current audio playback')
                    self._current_process.terminate()

                    # Give it a moment to terminate gracefully
                    try:
                        self._current_process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        # Force kill if it didn't terminate
                        self.logger.warning('Force killing audio playback process')
                        self._current_process.kill()
                        self._current_process.wait()

                except Exception as exc:
                    self.logger.error(f'Error terminating playback: {exc}')

    def _log_event(self, event: PlayoutEvent) -> None:
        """
        Log a playout event and invoke callbacks.

        Args:
            event: PlayoutEvent to log
        """
        self._playout_events.append(event)

        # Keep only last 500 events to prevent unbounded growth
        if len(self._playout_events) > 500:
            self._playout_events = self._playout_events[-500:]

        # Invoke callbacks
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as exc:
                self.logger.exception(f'Error in event callback: {exc}')

    def get_status(self) -> Dict[str, Any]:
        """
        Get current service status for monitoring.

        Returns:
            Dictionary with service state information
        """
        return {
            'running': self._running,
            'has_audio_player': bool(self._audio_cmd),
            'audio_player_cmd': self._audio_cmd,
            'has_gpio': self.gpio_controller is not None,
            'current_playback': self._current_process is not None,
            'queue_status': self.queue.get_status(),
            'recent_events': [e.to_dict() for e in self._playout_events[-10:]],
        }


__all__ = ['AudioOutputService', 'PlayoutEvent', 'PlayoutStatus']
