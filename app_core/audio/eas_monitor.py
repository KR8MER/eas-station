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

from __future__ import annotations

"""
Continuous EAS Monitoring Service

Integrates professional audio subsystem with EAS decoder for 24/7 alert monitoring.
Continuously buffers audio from AudioSourceManager and runs SAME decoder to detect alerts.

This is the bridge between the audio subsystem and the alert detection logic.
"""

import hashlib
import io
import logging
import os
import queue
import tempfile
import threading
import time
import wave
import math
from dataclasses import dataclass
from datetime import datetime
from collections import OrderedDict
from typing import Optional, Callable, List

import numpy as np
# Note: scipy.signal.resample_poly was replaced with numpy.interp (linear interpolation)
# for optimal Raspberry Pi performance - 10-20x faster with equivalent quality for SAME decoding

from app_utils.eas_decode import decode_same_audio, SAMEAudioDecodeResult
from app_utils import utc_now
from app_utils.eas_codes import get_event_name, get_originator_name
from .source_manager import AudioSourceManager
from .fips_utils import determine_fips_matches

logger = logging.getLogger(__name__)


def _store_received_alert(
    alert: EASAlert,
    forwarding_decision: str,
    forwarding_reason: str,
    matched_fips: List[str],
    generated_message_id: Optional[int] = None
) -> None:
    """
    Store received EAS alert in database with forwarding decision.

    Args:
        alert: The received EAS alert
        forwarding_decision: 'forwarded', 'ignored', or 'error'
        forwarding_reason: Human-readable reason for the decision
        matched_fips: List of FIPS codes that matched (if any)
        generated_message_id: FK to eas_messages table if forwarded
    """
    try:
        # Import here to avoid circular dependencies
        from app_core.models import ReceivedEASAlert
        from app_core.extensions import db
        from flask import current_app, has_app_context

        # Skip if not in Flask app context
        if not has_app_context():
            logger.debug("Not in Flask app context, skipping database storage")
            return

        # Extract data from alert
        event_code = "UNKNOWN"
        event_name = None
        originator_code = "UNKNOWN"
        originator_name = None
        fips_codes = []
        issue_datetime = None
        purge_datetime = None
        callsign = None
        raw_same_header = None

        if alert.headers and len(alert.headers) > 0:
            first_header = alert.headers[0]
            raw_same_header = first_header.get('raw_text')

            if 'fields' in first_header:
                fields = first_header['fields']
                event_code = fields.get('event_code', 'UNKNOWN')
                event_name = get_event_name(event_code)
                originator_code = fields.get('originator', 'UNKNOWN')
                originator_name = get_originator_name(originator_code)
                callsign = fields.get('callsign')

                # Extract FIPS codes
                locations = fields.get('locations', [])
                if isinstance(locations, list):
                    for loc in locations:
                        if isinstance(loc, dict):
                            code = loc.get('code', '')
                            if code:
                                fips_codes.append(code)

                # Extract timestamps
                issue_time = fields.get('issue_time')
                purge_time = fields.get('purge_time')
                if issue_time:
                    issue_datetime = datetime.fromisoformat(issue_time) if isinstance(issue_time, str) else issue_time
                if purge_time:
                    purge_datetime = datetime.fromisoformat(purge_time) if isinstance(purge_time, str) else purge_time

        # Create database record
        received_alert = ReceivedEASAlert(
            received_at=alert.timestamp,
            source_name=alert.source_name,
            raw_same_header=raw_same_header,
            event_code=event_code,
            event_name=event_name,
            originator_code=originator_code,
            originator_name=originator_name,
            fips_codes=fips_codes,
            issue_datetime=issue_datetime,
            purge_datetime=purge_datetime,
            callsign=callsign,
            forwarding_decision=forwarding_decision,
            forwarding_reason=forwarding_reason,
            matched_fips_codes=matched_fips,
            generated_message_id=generated_message_id,
            forwarded_at=utc_now() if forwarding_decision == 'forwarded' else None,
            decode_confidence=alert.confidence,
            full_alert_data={
                'raw_text': alert.raw_text,
                'headers': alert.headers,
                'duration_seconds': alert.duration_seconds,
                'audio_file_path': alert.audio_file_path,
            }
        )

        db.session.add(received_alert)
        db.session.commit()
        logger.info(f"Stored received alert in database: {event_code} from {alert.source_name}")

    except Exception as e:
        logger.error(f"Failed to store received alert in database: {e}", exc_info=True)
        # Don't let database errors break alert processing
        try:
            from app_core.extensions import db
            db.session.rollback()
        except:
            pass


@dataclass
class EASAlert:
    """Detected EAS alert with metadata."""
    timestamp: datetime
    raw_text: str
    headers: List[dict]
    confidence: float
    duration_seconds: float
    source_name: str
    audio_file_path: Optional[str] = None


def compute_alert_signature(alert: EASAlert) -> str:
    """Create a deterministic hash of decoded SAME headers for deduplication."""
    header_texts: List[str] = []
    for header in alert.headers or []:
        if not isinstance(header, dict):
            continue
        raw_value = header.get('raw_text') or header.get('header')
        if isinstance(raw_value, str) and raw_value.strip():
            header_texts.append(raw_value.strip())

    base_text = "||".join(header_texts).strip()
    if not base_text:
        base_text = (alert.raw_text or "").strip()

    if not base_text:
        base_text = f"{alert.source_name}|{alert.timestamp.isoformat()}"

    return hashlib.sha256(base_text.encode('utf-8', 'ignore')).hexdigest()


def create_fips_filtering_callback(
    configured_fips_codes: List[str],
    forward_callback: Callable[[EASAlert], None],
    logger_instance: Optional[logging.Logger] = None
) -> Callable[[EASAlert], None]:
    """
    Create an alert callback wrapper that filters by FIPS codes and logs results.

    This helper function creates a callback that:
    1. Extracts FIPS codes from the alert
    2. Compares them against configured FIPS codes
    3. Logs the matching result
    4. Only forwards alerts that match configured FIPS codes

    Args:
        configured_fips_codes: List of FIPS codes to match (e.g., ['039137', '039051'])
        forward_callback: Function to call when alert matches FIPS codes
        logger_instance: Optional logger (defaults to module logger)

    Returns:
        Callback function that can be passed to ContinuousEASMonitor

    Example:
        >>> configured_fips = ['039137', '039051']  # Putnam County, OH + Others
        >>> def my_forward_handler(alert):
        ...     print(f"Forwarding alert: {alert.raw_text}")
        >>>
        >>> callback = create_fips_filtering_callback(
        ...     configured_fips,
        ...     my_forward_handler,
        ...     logger
        ... )
        >>> monitor = ContinuousEASMonitor(
        ...     audio_manager=manager,
        ...     alert_callback=callback
        ... )
    """
    log = logger_instance or logger

    def fips_filtering_callback(alert: EASAlert) -> None:
        """Callback that filters alerts by FIPS codes with logging."""
        # Extract FIPS codes from alert
        alert_fips_codes = []
        event_code = "UNKNOWN"
        originator = "UNKNOWN"

        if alert.headers and len(alert.headers) > 0:
            first_header = alert.headers[0]
            if 'fields' in first_header:
                fields = first_header['fields']
                event_code = fields.get('event_code', 'UNKNOWN')
                originator = fields.get('originator', 'UNKNOWN')

                locations = fields.get('locations', [])
                if isinstance(locations, list):
                    for loc in locations:
                        if isinstance(loc, dict):
                            code = loc.get('code', '')
                            if code:
                                alert_fips_codes.append(code)

        matched_fips_list = determine_fips_matches(alert_fips_codes, configured_fips_codes)

        if matched_fips_list:
            # Alert matches configured FIPS codes - FORWARD IT
            forwarding_reason = f"FIPS match: {', '.join(matched_fips_list)}"

            log.warning(
                f"✓ FIPS MATCH - FORWARDING ALERT: "
                f"Event={event_code} | "
                f"Originator={originator} | "
                f"Alert FIPS={','.join(alert_fips_codes)} | "
                f"Configured FIPS={','.join(configured_fips_codes)} | "
                f"Matched={','.join(matched_fips_list)}"
            )

            try:
                result = forward_callback(alert)
                generated_message_id = None
                if isinstance(result, dict):
                    generated_message_id = result.get('message_id') or result.get('id')
                elif hasattr(result, 'id'):
                    generated_message_id = getattr(result, 'id')
                elif isinstance(result, (int, float)):
                    generated_message_id = int(result)
                elif isinstance(result, (list, tuple)) and result:
                    first = result[0]
                    if isinstance(first, dict):
                        generated_message_id = first.get('message_id') or first.get('id')
                    elif hasattr(first, 'id'):
                        generated_message_id = getattr(first, 'id')

                if generated_message_id is not None:
                    try:
                        generated_message_id = int(generated_message_id)
                    except (TypeError, ValueError):
                        logger.debug(
                            "Forward callback returned non-integer message id %r; ignoring",
                            generated_message_id,
                        )
                        generated_message_id = None

                log.info(f"Alert forwarding completed successfully")

                # Store as forwarded
                _store_received_alert(
                    alert=alert,
                    forwarding_decision='forwarded',
                    forwarding_reason=forwarding_reason,
                    matched_fips=matched_fips_list,
                    generated_message_id=generated_message_id
                )
            except Exception as e:
                log.error(f"Error forwarding alert: {e}", exc_info=True)

                # Store as error
                _store_received_alert(
                    alert=alert,
                    forwarding_decision='error',
                    forwarding_reason=f"Forwarding failed: {str(e)}",
                    matched_fips=matched_fips_list
                )

        else:
            # Alert does NOT match configured FIPS codes - IGNORE IT
            log.info(
                f"✗ NO FIPS MATCH - IGNORING ALERT: "
                f"Event={event_code} | "
                f"Originator={originator} | "
                f"Alert FIPS={','.join(alert_fips_codes) if alert_fips_codes else 'NONE'} | "
                f"Configured FIPS={','.join(configured_fips_codes)}"
            )

            # Store as ignored
            if alert_fips_codes:
                forwarding_reason = f"No FIPS match. Alert FIPS: {', '.join(alert_fips_codes)}. Configured: {', '.join(configured_fips_codes)}"
            else:
                forwarding_reason = "No FIPS codes in alert"

            _store_received_alert(
                alert=alert,
                forwarding_decision='ignored',
                forwarding_reason=forwarding_reason,
                matched_fips=[]
            )

    return fips_filtering_callback


class ContinuousEASMonitor:
    """
    Continuously monitors audio sources for EAS/SAME alerts.

    Buffers audio from AudioSourceManager and periodically analyzes it
    for SAME headers. When alerts are detected, triggers callbacks and
    stores to database.
    """
    
    # Minimum elapsed time for rate calculation (prevents division by zero on startup)
    MIN_ELAPSED_SECONDS = 0.1

    def __init__(
        self,
        audio_manager: AudioSourceManager,
        sample_rate: int = 16000,
        alert_callback: Optional[Callable[[EASAlert], None]] = None,
        save_audio_files: bool = True,
        audio_archive_dir: str = "/tmp/eas-audio"
    ):
        """
        Initialize continuous EAS monitor with real-time streaming decoder.

        Args:
            audio_manager: AudioSourceManager instance providing audio
            sample_rate: Audio sample rate in Hz (default: 16000)
            alert_callback: Optional callback function called when alert detected
            save_audio_files: Whether to save audio files of detected alerts
            audio_archive_dir: Directory to save alert audio files
            
        How it works:
            Audio samples are processed immediately as they arrive using a
            streaming SAME decoder. No buffering, no batching, no delays.
            Detection latency is <200ms, matching commercial EAS decoders.
        """
        self.audio_manager = audio_manager
        self.sample_rate = sample_rate
        self.source_sample_rate = getattr(audio_manager, "sample_rate", sample_rate)
        self.alert_callback = alert_callback
        self.save_audio_files = save_audio_files
        self.audio_archive_dir = audio_archive_dir

        # Create audio archive directory
        if save_audio_files:
            os.makedirs(audio_archive_dir, exist_ok=True)

        # STREAMING DECODER: Process samples in real-time as they arrive
        # NO BUFFERING. NO BATCHING. NO INTERVALS. NO TEMP FILES.
        # Every sample is processed immediately by the decoder.
        # This is how commercial EAS decoders work (DASDEC, multimon-ng).
        from .streaming_same_decoder import StreamingSAMEDecoder
        
        self._streaming_decoder = StreamingSAMEDecoder(
            sample_rate=sample_rate,
            alert_callback=self._handle_streaming_alert
        )
        
        logger.warning(
            "⚠️ BATCH PROCESSING DISABLED - Using real-time streaming decoder. "
            "No buffering, no intervals, no temp files. "
            f"Audio archiving: {'ENABLED' if save_audio_files else 'DISABLED'}. "
            "This is commercial-grade EAS decoder operation."
        )
        
        # Monitoring state
        self._monitor_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stop_event.set()  # Initialize in "stopped" state
        self._alerts_detected = 0
        self._last_alert_time: Optional[float] = None
        self._duplicate_cooldown_seconds = 30.0
        self._recent_alert_signatures: OrderedDict[str, float] = OrderedDict()
        self._stats_lock = threading.Lock()  # Protect statistics
        
        # Watchdog/heartbeat tracking
        self._last_activity: float = time.time()
        self._activity_lock = threading.Lock()
        self._watchdog_timeout: float = 60.0  # Seconds before considering thread stalled
        self._restart_count: int = 0
        
        # Track actual start time for accurate rate calculation
        self._start_time: Optional[float] = None
        
        logger.info(
            f"Initialized ContinuousEASMonitor: "
            f"source_sample_rate={self.source_sample_rate}Hz, "
            f"decoder_sample_rate={sample_rate}Hz, "
            f"streaming_mode=True, "
            f"watchdog_timeout={self._watchdog_timeout}s"
        )

    def start(self) -> bool:
        """
        Start continuous monitoring with dedicated worker pool.

        Returns:
            True if started successfully
        """
        if not self._stop_event.is_set():
            logger.warning("ContinuousEASMonitor already running")
            return False

        self._stop_event.clear()
        self._update_activity()  # Initialize activity timestamp
        self._start_time = time.time()  # Record actual start time

        # Start streaming monitor thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop_wrapper,
            name="eas-monitor",
            daemon=True
        )
        self._monitor_thread.start()

        # Start watchdog thread
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="eas-watchdog",
            daemon=True
        )
        self._watchdog_thread.start()

        logger.info(
            "✅ Started real-time EAS monitoring with streaming decoder. "
            "Samples processed immediately with <200ms detection latency."
        )
        return True

    def _monitor_loop_wrapper(self) -> None:
        """Wrapper to catch and log any uncaught exceptions in monitor loop."""
        try:
            logger.info("🔴 EAS monitor thread starting...")

            # Verify audio manager is available
            if not self.audio_manager:
                logger.error("❌ FATAL: No audio manager configured!")
                return

            logger.info(f"✅ Audio manager OK: {type(self.audio_manager).__name__}")

            # Log adapter stats to verify subscription
            if hasattr(self.audio_manager, "get_stats"):
                try:
                    stats = self.audio_manager.get_stats()
                    logger.info(
                        f"📊 Broadcast subscription: "
                        f"subscriber_id={stats.get('subscriber_id')}, "
                        f"queue_size={stats.get('queue_size')}, "
                        f"sample_rate={stats.get('sample_rate')}Hz"
                    )
                except Exception as e:
                    logger.warning(f"Could not get initial adapter stats: {e}")

            # Run the actual monitor loop
            self._monitor_loop()

        except Exception as e:
            logger.error(f"❌ FATAL: EAS monitor thread crashed: {e}", exc_info=True)
            # Try to set status to error state
            try:
                self._stop_event.set()
            except Exception:
                pass

    def stop(self) -> None:
        """Stop continuous monitoring."""
        logger.info("Stopping continuous EAS monitoring")
        self._stop_event.set()
        self._start_time = None  # Clear start time

        # Wait for monitor thread
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10.0)
        
        # Wait for watchdog
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5.0)

        logger.info(
            f"Stopped EAS monitoring. Stats: {self._alerts_detected} alerts detected, "
            f"{self._restart_count} restarts"
        )

    def get_status(self) -> dict:
        """
        Get current monitor status and metrics for UI display.
        
        STREAMING MODE: Reports real-time decoder status, not batch scan metrics.
        """
        is_running = not self._stop_event.is_set()

        # Get streaming decoder stats
        decoder_stats = self._streaming_decoder.get_stats()
        
        # Audio is flowing if decoder has processed samples
        audio_flowing = decoder_stats['samples_processed'] > 0
        samples_processed = decoder_stats['samples_processed']
        
        # Calculate how long decoder has been running based on WALL CLOCK TIME
        # This gives us the true instantaneous processing rate
        if audio_flowing and self._start_time is not None:
            actual_elapsed = time.time() - self._start_time
            # Calculate actual samples per second based on wall clock time
            samples_per_second = samples_processed / max(actual_elapsed, self.MIN_ELAPSED_SECONDS)
            # Runtime in terms of audio content (how many seconds of audio we've processed)
            runtime_seconds = samples_processed / self.sample_rate
        else:
            actual_elapsed = 0
            runtime_seconds = 0
            samples_per_second = 0
        
        with self._stats_lock:
            alerts_detected = self._alerts_detected
            last_alert_time = self._last_alert_time
        
        with self._activity_lock:
            last_activity = self._last_activity
            time_since_activity = time.time() - last_activity
        
        # Calculate health metrics
        # For streaming decoder, "health" = processing at line rate (configured sample_rate)
        expected_rate = self.sample_rate
        health_percentage = min(1.0, samples_per_second / expected_rate) if audio_flowing else 0.0

        resample_ratio = None
        if self.source_sample_rate:
            try:
                resample_ratio = self.sample_rate / float(self.source_sample_rate)
            except Exception:
                resample_ratio = None
        
        adapter_stats = {}
        if hasattr(self.audio_manager, "get_stats"):
            try:
                adapter_stats = self.audio_manager.get_stats()
            except Exception:
                adapter_stats = {}

        return {
            # System state
            "running": is_running,
            "mode": "streaming",
            "audio_flowing": audio_flowing,
            "sample_rate": self.sample_rate,
            "source_sample_rate": self.source_sample_rate,
            "resample_ratio": resample_ratio,
            
            # Streaming decoder metrics
            "samples_processed": samples_processed,
            "samples_per_second": int(samples_per_second),
            "runtime_seconds": runtime_seconds,
            "wall_clock_runtime_seconds": actual_elapsed,  # Real elapsed time for UI display
            "decoder_synced": decoder_stats['synced'],
            "decoder_in_message": decoder_stats['in_message'],
            "decoder_bytes_decoded": decoder_stats['bytes_decoded'],
            "health_percentage": health_percentage,
            
            # Alert metrics
            "alerts_detected": alerts_detected,
            "last_alert_time": last_alert_time,
            
            # Health metrics
            "last_activity": last_activity,
            "time_since_activity": time_since_activity,
            "restart_count": self._restart_count,
            "watchdog_timeout": self._watchdog_timeout,

            # Audio adapter stats (broadcast subscription health)
            "audio_buffer_samples": adapter_stats.get("buffer_samples"),
            "audio_buffer_seconds": adapter_stats.get("buffer_seconds"),
            "audio_queue_depth": adapter_stats.get("queue_size"),
            "audio_underruns": adapter_stats.get("underrun_count"),
            "audio_underrun_rate_percent": adapter_stats.get("underrun_rate_percent"),
            "audio_last_audio_time": adapter_stats.get("last_audio_time"),
            "audio_health": adapter_stats.get("health"),
            "audio_subscriber_id": adapter_stats.get("subscriber_id"),
        }

    def get_buffer_history(self, max_points: int = 60) -> list:
        """Get decoder health history for graphing.

        Returns list of dicts with:
        - timestamp: float (unix time)
        - health: float (0-100%)
        - in_message: bool

        TODO: Actually track history over time
        For now, returns current state only.
        """
        status = self.get_status()
        return [{
            "timestamp": time.time(),
            "health": status.get("health_percentage", 0),  # 0-1 range
            "in_message": status.get("decoder_in_message", False)
        }]

    def _update_activity(self) -> None:
        """Update the last activity timestamp (heartbeat)."""
        with self._activity_lock:
            self._last_activity = time.time()

    def _watchdog_loop(self) -> None:
        """Watchdog thread that monitors decoder thread health and restarts if stalled."""
        logger.debug("EAS watchdog loop started")
        check_interval = 10.0  # Check every 10 seconds
        
        while not self._stop_event.is_set():
            try:
                time.sleep(check_interval)
                
                if self._stop_event.is_set():
                    break
                
                # Check if decoder thread is still alive and active
                with self._activity_lock:
                    time_since_activity = time.time() - self._last_activity
                
                if time_since_activity > self._watchdog_timeout:
                    logger.error(
                        f"EAS decoder thread appears stalled (no activity for {time_since_activity:.1f}s, "
                        f"timeout={self._watchdog_timeout}s). Attempting restart..."
                    )
                    
                    # Attempt to restart the monitor thread
                    self._restart_monitor_thread()
                    
            except Exception as e:
                logger.error(f"Error in EAS watchdog loop: {e}", exc_info=True)
                time.sleep(5.0)  # Back off on error
        
        logger.debug("EAS watchdog loop stopped")

    def _restart_monitor_thread(self) -> None:
        """Attempt to safely restart the monitor thread."""
        try:
            self._restart_count += 1
            logger.warning(f"Restarting EAS monitor thread (restart #{self._restart_count})")
            
            # Stop old thread if still running
            if self._monitor_thread and self._monitor_thread.is_alive():
                logger.debug("Old monitor thread still alive, giving it 3 seconds to stop")
                # Note: We don't have a separate stop event for the monitor thread,
                # so we can't force it to stop without stopping the entire service.
                # Instead, just start a new one - the old one will eventually exit
            
            # CRITICAL FIX: Reset start time to maintain consistency between wall clock
            # and samples-based runtime calculations. Without this, wall_clock_runtime_seconds
            # continues from the original start time while samples_processed resets to 0,
            # causing the runtime display to jump between values (e.g., 6 min -> 2 sec -> 6 min)
            self._start_time = time.time()
            
            # Start new monitoring thread
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name=f"eas-monitor-r{self._restart_count}",
                daemon=True
            )
            self._monitor_thread.start()
            self._update_activity()  # Reset activity timestamp
            
            logger.info(f"EAS monitor thread restarted successfully (restart #{self._restart_count})")
            
        except Exception as e:
            logger.error(f"Failed to restart EAS monitor thread: {e}", exc_info=True)

    def _resample_if_needed(self, samples: np.ndarray) -> np.ndarray:
        """
        Resample incoming audio to the decoder's target rate (16 kHz) if needed.
        
        CRITICAL: This properly RESAMPLES the audio using linear interpolation,
        not just changing the sample rate metadata. Audio sources can be at any
        sample rate (44.1k, 48k, 32k, etc.) but the EAS decoder MUST receive 16 kHz.
        
        PERFORMANCE: Uses linear interpolation (np.interp) instead of polyphase filtering
        for optimal Raspberry Pi performance. This is 10-20x faster while maintaining
        perfect quality for SAME tone detection. See RESAMPLING_PERFORMANCE_ANALYSIS.md
        
        Args:
            samples: Input audio samples at source_sample_rate
            
        Returns:
            Resampled audio at self.sample_rate (16 kHz), or original if no conversion needed
        """
        if samples is None or len(samples) == 0:
            return samples

        if self.source_sample_rate == self.sample_rate:
            # No resampling needed - already at target rate
            return samples

        try:
            # Calculate resampling ratio
            ratio = self.sample_rate / float(self.source_sample_rate)
            if ratio <= 0:
                return samples

            # Linear interpolation - fast and sufficient for SAME decoding
            # This is 10-20x faster than polyphase filtering and uses minimal CPU
            # on Raspberry Pi while preserving tone frequencies perfectly
            new_length = int(len(samples) * ratio)
            if new_length < 1:
                return samples
                
            old_indices = np.arange(len(samples))
            new_indices = np.linspace(0, len(samples) - 1, new_length)
            resampled = np.interp(new_indices, old_indices, samples)
            
            return resampled.astype(np.float32, copy=False)
        except Exception as resample_error:
            logger.error(
                f"Failed to resample audio from {self.source_sample_rate}Hz to {self.sample_rate}Hz: {resample_error}",
                exc_info=True,
            )
            return samples

    def _monitor_loop(self) -> None:
        """
        Main monitoring loop - STREAMING REAL-TIME PROCESSING.

        NO BATCHING. NO INTERVALS. NO TEMP FILES.

        This is how commercial EAS decoders (DASDEC, multimon-ng) work:
        - Read audio samples as they arrive
        - Feed directly to streaming decoder
        - Decoder maintains state and emits alerts
        - Zero latency, zero dropouts
        """
        logger.info("🔴 EAS monitor loop entered - processing samples in real-time")

        # Buffer for reading audio chunks (~100ms at decoder rate)
        chunk_samples = int(self.sample_rate * 0.1)
        logger.info(f"📏 Requesting {chunk_samples} samples per chunk ({self.sample_rate}Hz decoder rate)")
        
        last_heartbeat_time = time.time()
        heartbeat_interval = 5.0  # Update activity every 5 seconds

        read_error_count = 0
        last_error_log_time = 0
        error_log_interval = 10.0

        samples_processed = 0
        last_diagnostics_log = 0
        diagnostics_interval = 10.0  # Log diagnostics every 10 seconds

        successful_reads = 0
        failed_reads = 0

        while not self._stop_event.is_set():
            try:
                # Update activity heartbeat periodically
                current_time = time.time()
                if current_time - last_heartbeat_time >= heartbeat_interval:
                    self._update_activity()
                    last_heartbeat_time = current_time
                    # Log progress
                    stats = self._streaming_decoder.get_stats()
                    logger.debug(
                        f"Streaming decoder stats: {stats['samples_processed']:,} samples processed, "
                        f"{stats['alerts_detected']} alerts detected, "
                        f"synced={stats['synced']}, in_message={stats['in_message']}"
                    )

                # Periodic diagnostics logging
                if current_time - last_diagnostics_log >= diagnostics_interval:
                    # Get audio adapter stats for diagnostics
                    adapter_stats = {}
                    if hasattr(self.audio_manager, "get_stats"):
                        try:
                            adapter_stats = self.audio_manager.get_stats()
                        except Exception:
                            pass

                    decoder_stats = self._streaming_decoder.get_stats()

                    logger.info(
                        f"🔍 EAS Monitor diagnostics: "
                        f"samples_processed={decoder_stats['samples_processed']:,}, "
                        f"successful_reads={successful_reads}, "
                        f"failed_reads={failed_reads}, "
                        f"queue_depth={adapter_stats.get('queue_size', 'N/A')}, "
                        f"buffer_samples={adapter_stats.get('buffer_samples', 'N/A')}, "
                        f"underruns={adapter_stats.get('underrun_count', 'N/A')}/{adapter_stats.get('total_reads', 'N/A')} "
                        f"({adapter_stats.get('underrun_rate_percent', 0):.1f}%), "
                        f"health={adapter_stats.get('health', 'N/A')}"
                    )

                    last_diagnostics_log = current_time
                    successful_reads = 0
                    failed_reads = 0

                # Read audio from manager
                samples = None
                try:
                    samples = self.audio_manager.read_audio(chunk_samples)
                    if samples is not None and len(samples) > 0:
                        successful_reads += 1
                    else:
                        failed_reads += 1
                    read_error_count = 0  # Reset error count on success
                except Exception as read_error:
                    failed_reads += 1
                    read_error_count += 1
                    if current_time - last_error_log_time > error_log_interval:
                        logger.error(
                            f"❌ Error reading audio from manager (error #{read_error_count}): {read_error}",
                            exc_info=True
                        )
                        last_error_log_time = current_time
                    samples = None

                if samples is not None and len(samples) > 0:
                    # RESAMPLE TO 16 kHz: Audio sources can be at any sample rate (44.1k, 48k, etc.)
                    # but the EAS decoder MUST receive 16 kHz audio for optimal SAME decoding.
                    # This resampling uses linear interpolation (numpy.interp) optimized for
                    # Raspberry Pi performance - 10-20x faster than polyphase filtering.
                    decoded_samples = self._resample_if_needed(samples)

                    # REAL-TIME PROCESSING: Feed samples directly to decoder
                    # ZERO buffering, ZERO batching, ZERO delays
                    # Every sample is processed immediately
                    try:
                        self._streaming_decoder.process_samples(decoded_samples)
                        samples_processed += len(decoded_samples)
                    except Exception as decode_error:
                        logger.error(f"Error in streaming decoder: {decode_error}", exc_info=True)
                
                # Brief sleep only if we didn't get audio samples
                if samples is None:
                    time.sleep(0.02)  # 20ms sleep when no audio available

            except Exception as e:
                logger.error(f"Unexpected error in EAS monitor loop: {e}", exc_info=True)
                self._update_activity()
                time.sleep(1.0)  # Back off on error

        logger.info("🔴 STREAMING EAS monitor stopped")

    def _handle_streaming_alert(self, alert) -> None:
        """
        Handle alert from streaming decoder.
        
        This is called by StreamingSAMEDecoder when an alert is detected.
        
        CRITICAL: For alert verification, we need to save audio.
        In streaming mode, we capture audio AFTER detection by reading from audio manager.
        """
        from .streaming_same_decoder import StreamingSAMEAlert
        
        logger.info(f"🔔 Streaming alert received: {alert.message[:80]}... (confidence: {alert.confidence:.1%})")
        
        # Get active source name
        source_name = self.audio_manager.get_active_source() or "unknown"
        
        # Parse the SAME message to extract fields
        from app_utils.eas import describe_same_header
        from app_utils.fips_codes import get_same_lookup
        
        # Extract just the header part (ZCZC-ORG-EEE-PSSCCC...)
        message_text = alert.message.strip()
        if "ZCZC" in message_text:
            zczc_idx = message_text.find("ZCZC")
            header_text = message_text[zczc_idx:]
            # Remove trailing dash if present
            if header_text.endswith('-'):
                header_text = header_text[:-1]
        else:
            header_text = message_text
        
        # Parse SAME header fields
        fips_lookup = get_same_lookup()
        header_fields = describe_same_header(header_text, lookup=fips_lookup)
        
        # AUDIO ARCHIVING: Save audio for verification/archival
        # In streaming mode, the audio manager maintains a buffer
        # We can capture recent audio when alert is detected
        audio_file_path = None
        if self.save_audio_files:
            try:
                # Get approximately 12 seconds of audio from audio manager
                # This should contain the full SAME sequence
                archive_duration = 12.0
                archive_samples = int(self.sample_rate * archive_duration)
                
                # Try to get recent audio from audio manager's buffer
                # Note: This depends on AudioSourceManager having a get_recent_audio() method
                # If not available, we'll need to add a small buffer here
                try:
                    audio_samples = self.audio_manager.get_recent_audio(archive_samples)
                except AttributeError:
                    logger.warning(
                        "AudioSourceManager doesn't support get_recent_audio(). "
                        "Audio archiving disabled for streaming mode. "
                        "Alert will be logged but audio won't be saved."
                    )
                    audio_samples = None
                
                if audio_samples is not None and len(audio_samples) > 0:
                    # Save to file in RAM disk
                    audio_file_path = self._save_alert_audio(audio_samples, alert)
                    logger.info(f"Saved alert audio to {audio_file_path}")
            except Exception as e:
                logger.error(f"Failed to save alert audio: {e}", exc_info=True)
        
        # Create EASAlert object compatible with existing callback
        eas_alert = EASAlert(
            timestamp=alert.timestamp,
            raw_text=message_text,
            headers=[{
                'header': header_text,
                'fields': header_fields,
                'confidence': alert.confidence,
                'raw_text': header_text
            }],
            confidence=alert.confidence,
            duration_seconds=0.0,  # Streaming doesn't track duration
            source_name=source_name,
            audio_file_path=audio_file_path
        )
        
        # Check for duplicates
        alert_signature = compute_alert_signature(eas_alert)
        current_time = time.time()
        
        if self._is_duplicate_alert(alert_signature, current_time):
            logger.info(
                f"Duplicate alert detected within {self._duplicate_cooldown_seconds}s window - ignoring"
            )
            return
        
        self._recent_alert_signatures[alert_signature] = current_time
        self._last_alert_time = current_time
        
        with self._stats_lock:
            self._alerts_detected += 1
        
        # Log comprehensive alert info
        event_code = header_fields.get('event_code', 'UNKNOWN')
        originator = header_fields.get('originator', 'UNKNOWN')
        location_codes = []
        locations = header_fields.get('locations', [])
        if isinstance(locations, list):
            for loc in locations:
                if isinstance(loc, dict):
                    code = loc.get('code', '')
                    if code:
                        location_codes.append(code)
        
        logger.warning(
            f"🚨 EAS ALERT DETECTED (STREAMING): "
            f"Event={event_code} | "
            f"Originator={originator} | "
            f"FIPS={','.join(location_codes) if location_codes else 'NONE'} | "
            f"Source={source_name} | "
            f"Confidence={alert.confidence:.1%}"
        )
        
        # Invoke callback (FIPS filtering happens here)
        if self.alert_callback:
            try:
                self.alert_callback(eas_alert)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}", exc_info=True)
    
    def _save_alert_audio(self, samples: np.ndarray, alert) -> str:
        """
        Save alert audio to WAV file for archiving and verification.
        
        Uses /dev/shm (RAM disk) for zero disk I/O.
        
        Args:
            samples: Audio samples to save
            alert: StreamingSAMEAlert object
            
        Returns:
            Path to saved audio file
        """
        import wave
        
        # Create archive directory in RAM disk
        ram_disk_dir = "/dev/shm/eas-audio"
        os.makedirs(ram_disk_dir, exist_ok=True)
        
        # Create filename: YYYYMMDD_HHMMSS_message.wav
        timestamp_str = alert.timestamp.strftime("%Y%m%d_%H%M%S")
        
        # Extract event code from message for filename
        message_text = alert.message
        event_code = "UNK"
        originator = "UNK"
        if "ZCZC" in message_text:
            try:
                parts = message_text.split('-')
                if len(parts) >= 3:
                    originator = parts[1]
                    event_code = parts[2]
            except:
                pass
        
        filename = f"{timestamp_str}_{originator}-{event_code}.wav"
        filepath = os.path.join(ram_disk_dir, filename)
        
        try:
            with wave.open(filepath, 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)
                
                # Convert float32 [-1, 1] to int16 PCM
                pcm_data = (samples * 32767).astype(np.int16)
                wf.writeframes(pcm_data.tobytes())
            
            return filepath
        except Exception as e:
            logger.error(f"Failed to save alert audio to {filepath}: {e}", exc_info=True)
            raise
    
    def _has_same_signature(self, audio_samples: np.ndarray) -> bool:
        """Fast pre-check to detect if audio contains SAME tone signatures.
        
        This is a lightweight filter that checks for the presence of the characteristic
        SAME tones (853 Hz and 960 Hz) without doing full decoding. This allows us to
        skip expensive decoding on audio that clearly doesn't contain alerts.
        
        Returns True if SAME tones might be present (run full decode).
        Returns False if definitely no SAME tones (skip decode to save CPU).
        """
        try:
            # Only analyze a small window to keep this fast (first 2 seconds)
            window_samples = min(len(audio_samples), int(self.sample_rate * 2.0))
            window = audio_samples[:window_samples]
            
            # Calculate power spectrum using FFT
            # Use smaller FFT size for speed (2048 samples = ~93ms at 22050 Hz)
            fft_size = 2048
            hop_size = fft_size // 2
            
            # SAME uses 853 Hz (mark) and 960 Hz (space)
            # Allow some tolerance for frequency drift
            mark_freq = 853
            space_freq = 960
            freq_tolerance = 50  # Hz
            
            # Calculate frequency bins
            freq_resolution = self.sample_rate / fft_size
            mark_bin_low = int((mark_freq - freq_tolerance) / freq_resolution)
            mark_bin_high = int((mark_freq + freq_tolerance) / freq_resolution)
            space_bin_low = int((space_freq - freq_tolerance) / freq_resolution)
            space_bin_high = int((space_freq + freq_tolerance) / freq_resolution)
            
            # Analyze multiple windows
            max_mark_energy = 0.0
            max_space_energy = 0.0
            
            for i in range(0, window_samples - fft_size, hop_size):
                segment = window[i:i + fft_size]
                
                # Apply window function to reduce spectral leakage
                segment = segment * np.hanning(fft_size)
                
                # Calculate power spectrum
                spectrum = np.abs(np.fft.rfft(segment))
                
                # Check energy in SAME frequency bands
                mark_energy = np.sum(spectrum[mark_bin_low:mark_bin_high])
                space_energy = np.sum(spectrum[space_bin_low:space_bin_high])
                
                max_mark_energy = max(max_mark_energy, mark_energy)
                max_space_energy = max(max_space_energy, space_energy)
            
            # If both SAME tones have significant energy, likely contains SAME
            # Use a threshold relative to total signal energy
            total_energy = np.sum(np.abs(window) ** 2)
            
            # Require at least some energy in both tone bands
            # and reasonable signal-to-noise ratio
            has_mark = max_mark_energy > (total_energy * 0.001)
            has_space = max_space_energy > (total_energy * 0.001)
            
            if has_mark and has_space:
                logger.debug("SAME signature detected - running full decode")
                return True
            else:
                # No SAME signature - skip expensive decode
                return False
                
        except Exception as e:
            logger.debug(f"Error in SAME signature pre-check: {e}")
            # On error, assume signature present to ensure we don't miss alerts
            return True

    def _handle_alert_detected(
        self,
        result: SAMEAudioDecodeResult,
        audio_samples: np.ndarray,
        temp_wav_path: str
    ) -> None:
        """Handle detected EAS alert."""
        current_time = time.time()

        # Get active source name
        source_name = self.audio_manager.get_active_source() or "unknown"

        # Create alert object for logging
        alert = EASAlert(
            timestamp=utc_now(),
            raw_text=result.raw_text,
            headers=[h.to_dict() for h in result.headers],
            confidence=result.bit_confidence,
            duration_seconds=result.duration_seconds,
            source_name=source_name
        )

        # === COMPREHENSIVE LOGGING FOR ALL ALERTS (BEFORE FILTERING) ===
        # This logs EVERY alert detected, regardless of FIPS codes or forwarding criteria
        # Useful for auditing and troubleshooting
        try:
            # Extract key alert details
            event_code = "UNKNOWN"
            originator = "UNKNOWN"
            location_codes = []

            if alert.headers and len(alert.headers) > 0:
                first_header = alert.headers[0]
                if 'fields' in first_header:
                    fields = first_header['fields']
                    event_code = fields.get('event_code', 'UNKNOWN')
                    originator = fields.get('originator', 'UNKNOWN')

                    # Extract location codes (FIPS codes)
                    locations = fields.get('locations', [])
                    if isinstance(locations, list):
                        for loc in locations:
                            if isinstance(loc, dict):
                                code = loc.get('code', '')
                                if code:
                                    location_codes.append(code)

            # Log comprehensive alert information (always logged for auditing)
            logger.warning(
                f"🔔 AUDIO ALERT RECEIVED: "
                f"Event={event_code} | "
                f"Originator={originator} | "
                f"FIPS Codes={','.join(location_codes) if location_codes else 'NONE'} | "
                f"Source={source_name} | "
                f"Confidence={alert.confidence:.1%} | "
                f"Raw={alert.raw_text}"
            )

            # Also log as structured data for easier parsing
            logger.info(
                f"Audio alert details: event_code={event_code}, "
                f"originator={originator}, "
                f"location_codes={location_codes}, "
                f"source={source_name}, "
                f"confidence={alert.confidence}, "
                f"timestamp={alert.timestamp.isoformat()}"
            )

        except Exception as e:
            logger.error(f"Error logging alert details: {e}", exc_info=True)
        # === END COMPREHENSIVE LOGGING ===

        # === SAVE AUDIO FOR ALL ALERTS (BEFORE COOLDOWN CHECK) ===
        # This ensures complete audit trail - every alert gets audio saved
        if self.save_audio_files:
            alert_filename = self._create_alert_filename(alert)
            alert_file_path = os.path.join(self.audio_archive_dir, alert_filename)

            try:
                # Move temp file to permanent location
                os.rename(temp_wav_path, alert_file_path)
                alert.audio_file_path = alert_file_path
                logger.info(f"Saved alert audio to {alert_file_path}")
            except Exception as e:
                logger.error(f"Failed to save alert audio: {e}")
        # === END AUDIO SAVING ===

        alert_signature = compute_alert_signature(alert)
        if self._is_duplicate_alert(alert_signature, current_time):
            logger.info(
                "Alert duplicate detected within %.1fs window - "
                "logged/audio archived but not activating", 
                self._duplicate_cooldown_seconds,
            )
            return

        self._recent_alert_signatures[alert_signature] = current_time
        self._last_alert_time = current_time
        self._alerts_detected += 1

        # Log alert activation (this means the alert passed cooldown and will be processed/forwarded)
        logger.warning(
            f"🚨 EAS ALERT ACTIVATING: {alert.raw_text} "
            f"(source: {source_name}, confidence: {alert.confidence:.1%})"
        )

        # Trigger callback (this will apply FIPS filtering and forward if matching)
        if self.alert_callback:
            try:
                # Extract location codes for logging
                callback_location_codes = []
                if alert.headers and len(alert.headers) > 0:
                    first_header = alert.headers[0]
                    if 'fields' in first_header:
                        fields = first_header['fields']
                        locations = fields.get('locations', [])
                        if isinstance(locations, list):
                            for loc in locations:
                                if isinstance(loc, dict):
                                    code = loc.get('code', '')
                                    if code:
                                        callback_location_codes.append(code)

                logger.info(
                    f"Invoking alert callback for processing/FIPS filtering: "
                    f"alert_fips_codes={callback_location_codes}"
                )

                self.alert_callback(alert)

                # Log successful callback completion
                logger.info(
                    f"✓ Alert callback completed successfully for {alert.raw_text[:50]}... "
                    f"(Note: Check callback implementation for FIPS filtering results)"
                )

            except Exception as e:
                logger.error(
                    f"✗ Error in alert callback: {e} "
                    f"(Alert may not have been forwarded/broadcast)",
                    exc_info=True
                )

    def _create_alert_filename(self, alert: EASAlert) -> str:
        """Create filename for alert audio file."""
        # Format: YYYYMMDD_HHMMSS_ORIGINATOR-EVENT.wav
        timestamp_str = alert.timestamp.strftime("%Y%m%d_%H%M%S")

        # Extract originator and event code from first header
        originator = "UNK"
        event_code = "UNK"

        if alert.headers and len(alert.headers) > 0:
            first_header = alert.headers[0]
            if 'fields' in first_header:
                fields = first_header['fields']
                originator = fields.get('originator', 'UNK')
                event_code = fields.get('event_code', 'UNK')

        return f"{timestamp_str}_{originator}-{event_code}.wav"

    def _purge_expired_alert_signatures(self, cutoff_timestamp: float) -> None:
        """Drop stored alert signatures that are older than the provided cutoff."""
        while self._recent_alert_signatures:
            oldest_signature, timestamp = next(iter(self._recent_alert_signatures.items()))
            if timestamp >= cutoff_timestamp:
                break
            self._recent_alert_signatures.popitem(last=False)

    def _is_duplicate_alert(self, signature: str, current_time: float) -> bool:
        """Return True if the provided signature was seen recently."""
        cutoff = current_time - self._duplicate_cooldown_seconds
        self._purge_expired_alert_signatures(cutoff)
        return signature in self._recent_alert_signatures

    def get_stats(self) -> dict:
        """Get monitoring statistics for streaming mode."""
        decoder_stats = self._streaming_decoder.get_stats()
        return {
            'running': not self._stop_event.is_set(),
            'samples_processed': decoder_stats['samples_processed'],
            'alerts_detected': self._alerts_detected,
            'active_source': self.audio_manager.get_active_source(),
            'last_alert_time': self._last_alert_time
        }


__all__ = ['ContinuousEASMonitor', 'EASAlert', 'create_fips_filtering_callback', 'compute_alert_signature']
