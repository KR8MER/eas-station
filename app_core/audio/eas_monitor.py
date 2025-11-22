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
from dataclasses import dataclass
from datetime import datetime
from collections import OrderedDict
from typing import Optional, Callable, List

import numpy as np

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

    def __init__(
        self,
        audio_manager: AudioSourceManager,
        buffer_duration: float = 12.0,  # 12 seconds to capture full SAME sequence (3s × 3 bursts + margin)
        scan_interval: float = 3.0,  # Scan every 3 seconds for 75% overlap to never miss alerts
        sample_rate: int = 22050,
        alert_callback: Optional[Callable[[EASAlert], None]] = None,
        save_audio_files: bool = True,
        audio_archive_dir: str = "/tmp/eas-audio",
        max_concurrent_scans: int = 2  # Maximum number of concurrent scan threads
    ):
        """
        Initialize continuous EAS monitor.

        Args:
            audio_manager: AudioSourceManager instance providing audio
            buffer_duration: Seconds of audio to buffer for analysis
                            12s ensures full SAME capture (3 bursts × ~3s each)
            scan_interval: Seconds between decode attempts
                          3s provides 75% overlap (12s buffer, 3s interval)
                          This ensures no SAME sequence can be missed at boundaries
            sample_rate: Audio sample rate in Hz (default: 22050)
            alert_callback: Optional callback function called when alert detected
            save_audio_files: Whether to save audio files of detected alerts
            audio_archive_dir: Directory to save alert audio files
            max_concurrent_scans: Maximum number of concurrent scan threads (default: 2)
                                 Increase for faster hardware or longer scan intervals
                                 Decrease if scans are consuming too many resources
            
        Note on overlap strategy:
            SAME headers consist of 3 bursts, each ~3 seconds long = ~9 seconds total.
            With 12s buffer and 3s scan interval, we get 75% overlap:
            
            Time:    0    3    6    9    12   15   18
            Scan 1:  [------------]
            Scan 2:       [------------]
            Scan 3:            [------------]
            
            Any SAME sequence will appear COMPLETELY in at least one scan window,
            ensuring 100% detection with no missed alerts at boundaries.
        """
        self.audio_manager = audio_manager
        self.buffer_duration = buffer_duration
        self.scan_interval = scan_interval
        self.sample_rate = sample_rate
        self.alert_callback = alert_callback
        self.save_audio_files = save_audio_files
        self.audio_archive_dir = audio_archive_dir
        self.max_concurrent_scans = max(1, max_concurrent_scans)  # Ensure at least 1

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

        # Calculate overlap percentage for logging
        overlap_pct = ((buffer_duration - scan_interval) / buffer_duration * 100) if buffer_duration > 0 else 0
        
        logger.info(
            f"Initialized ContinuousEASMonitor: buffer={buffer_duration}s, "
            f"scan_interval={scan_interval}s ({overlap_pct:.0f}% overlap), "
            f"sample_rate={sample_rate}Hz, max_concurrent_scans={self.max_concurrent_scans}, "
            f"watchdog_timeout={self._watchdog_timeout}s"
        )
        
        if overlap_pct < 50:
            logger.warning(
                f"Low scan overlap ({overlap_pct:.0f}%) may miss alerts at window boundaries. "
                f"Recommend scan_interval <= {buffer_duration * 0.5:.1f}s for 50%+ overlap."
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

        # Start worker threads - one per configured worker
        # These threads pull from the queue and process scans
        self._worker_threads = []
        for i in range(self.max_concurrent_scans):
            worker = threading.Thread(
                target=self._scan_worker_loop,
                name=f"eas-worker-{i+1}",
                daemon=True
            )
            worker.start()
            self._worker_threads.append(worker)
        
        logger.info(f"Started {self.max_concurrent_scans} EAS scan worker threads")

        # Start monitoring thread (queues scans)
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
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

        overlap_pct = ((self.buffer_duration - self.scan_interval) / self.buffer_duration * 100)
        logger.info(
            f"Started continuous EAS monitoring with {overlap_pct:.0f}% overlapping windows. "
            f"SAME sequences (9s) will appear completely in at least one scan window. "
            f"Queue-based processing ensures ZERO dropped scans."
        )
        return True

    def stop(self) -> None:
        """Stop continuous monitoring and worker threads."""
        logger.info("Stopping continuous EAS monitoring")
        self._stop_event.set()

        # Wait for monitor thread
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10.0)
        
        # Send poison pills to worker threads to make them exit
        for _ in range(len(self._worker_threads)):
            try:
                self._scan_queue.put(None, timeout=1.0)
            except queue.Full:
                pass
        
        # Wait for workers to finish
        for worker in self._worker_threads:
            worker.join(timeout=5.0)
        
        # Wait for watchdog
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5.0)

        logger.info(
            f"Stopped EAS monitoring. Stats: {self._scans_completed} scans completed, "
            f"{self._alerts_detected} alerts detected, {self._scans_queue_full} queue full errors, "
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
        
        # Calculate how long decoder has been running based on samples
        if audio_flowing:
            runtime_seconds = samples_processed / self.sample_rate
            samples_per_second = samples_processed / max(runtime_seconds, 1.0)
        else:
            runtime_seconds = 0
            samples_per_second = 0
        
        with self._stats_lock:
            alerts_detected = self._alerts_detected
            last_alert_time = self._last_alert_time
        
        with self._activity_lock:
            last_activity = self._last_activity
            time_since_activity = time.time() - last_activity
        
        # Calculate health metrics
        # For streaming decoder, "health" = processing at line rate (22050 samples/sec)
        expected_rate = self.sample_rate
        health_percentage = min(1.0, samples_per_second / expected_rate) if audio_flowing else 0.0
        
        return {
            # System state
            "running": is_running,
            "mode": "streaming",  # NEW: Indicate we're in streaming mode
            "audio_flowing": audio_flowing,
            "sample_rate": self.sample_rate,
            
            # Streaming decoder metrics (OPERATOR CONFIRMATION)
            "samples_processed": samples_processed,
            "samples_per_second": int(samples_per_second),
            "runtime_seconds": runtime_seconds,
            "decoder_synced": decoder_stats['synced'],
            "decoder_in_message": decoder_stats['in_message'],
            "decoder_bytes_decoded": decoder_stats['bytes_decoded'],
            "health_percentage": health_percentage,
            
            # Alert metrics
            "alerts_detected": alerts_detected,
            "last_alert_time": last_alert_time,
            
            # Legacy compatibility (for UI that expects these)
            "buffer_duration": self.buffer_duration,
            "scan_interval": 0.0,  # N/A in streaming mode
            "effective_scan_interval": 0.0,  # N/A in streaming mode  
            "scan_interval_auto_adjusted": False,
            "buffer_utilization": health_percentage,  # Repurpose as health indicator
            "buffer_fill_seconds": runtime_seconds,
            "scans_performed": samples_processed // (self.sample_rate * 100),  # Rough estimate: 1 "scan" per 100s
            "scans_skipped": 0,  # N/A in streaming mode
            "scans_no_signature": 0,  # N/A in streaming mode
            "total_scan_attempts": samples_processed // (self.sample_rate * 100),
            "active_scans": 1 if decoder_stats['in_message'] else 0,
            "max_concurrent_scans": 1,  # Streaming = always 1 decoder thread
            "dynamic_max_concurrent_scans": 1,
            "scan_warnings": 0,
            
            # Health metrics
            "last_activity": last_activity,
            "time_since_activity": time_since_activity,
            "restart_count": self._restart_count,
            "watchdog_timeout": self._watchdog_timeout,
            
            # Streaming-specific stats
            "avg_scan_duration_seconds": None,  # N/A
            "min_scan_duration_seconds": None,
            "max_scan_duration_seconds": None,
            "last_scan_duration_seconds": None,
            "scan_history_size": 0
            "buffer_fill_seconds": buffer_fill_seconds,
            "scans_performed": scans_performed,
            "scans_skipped": scans_skipped,
            "scans_no_signature": scans_no_signature,
            "total_scan_attempts": total_scan_attempts,
            "alerts_detected": self._alerts_detected,
            "last_scan_time": self._last_scan_time,
            "last_alert_time": self._last_alert_time,
            "active_scans": active_scans,
            "max_concurrent_scans": self.max_concurrent_scans,
            "dynamic_max_concurrent_scans": self._dynamic_max_scans,
            "audio_flowing": audio_flowing,
            "sample_rate": self.sample_rate,
            "scan_warnings": scans_skipped,  # Alias for backward compatibility
            "last_activity": last_activity,
            "time_since_activity": time_since_activity,
            "restart_count": self._restart_count,
            "watchdog_timeout": self._watchdog_timeout,
            # Scan timing metrics
            "avg_scan_duration_seconds": avg_scan_duration,
            "min_scan_duration_seconds": min_scan_duration,
            "max_scan_duration_seconds": max_scan_duration,
            "last_scan_duration_seconds": last_scan_duration,
            "scan_history_size": len(self._scan_durations)
        }

    def get_buffer_history(self, max_points: int = 60) -> list:
        """Get recent buffer utilization history for graphing.

        Returns list of dicts with:
        - timestamp: float (unix time)
        - utilization: float (0-100%)
        - active_scans: int

        TODO: Actually track history over time
        For now, returns current state only.
        """
        status = self.get_status()
        return [{
            "timestamp": time.time(),
            "utilization": status["buffer_utilization"],
            "active_scans": status["active_scans"]
        }]

    def _update_activity(self) -> None:
        """Update the last activity timestamp (heartbeat)."""
        with self._activity_lock:
            self._last_activity = time.time()

    def _update_scan_parameters(self) -> None:
        """Self-regulating feedback loop that adjusts scan parameters based on performance.
        
        This implements a control system that:
        1. Monitors scan performance (duration, skip rate, queue depth)
        2. Adjusts concurrency and interval to maintain optimal performance
        3. Prevents oscillation with cooldown periods
        4. Logs adjustments for visibility
        
        Goals:
        - Zero skipped scans (all alerts detected)
        - Minimize scan interval (fast detection)
        - Minimize resource usage
        """
        with self._scan_lock:
            # Need enough history to make informed decisions
            if not self._scan_durations or self._scans_performed < 10:
                return
            
            current_time = time.time()
            
            # Don't adjust too frequently - let changes stabilize
            if current_time - self._last_adjustment_time < self._adjustment_cooldown:
                return
            
            # Calculate performance metrics
            recent_scans = self._scan_durations[-20:]  # Last 20 scans
            avg_scan_duration = sum(recent_scans) / len(recent_scans)
            max_scan_duration = max(recent_scans)
            min_scan_duration = min(recent_scans)
            
            # Calculate skip rate (recent history) 
            # Use ratio of skips to total attempts (skips + performed)
            # This gives true skip rate for recent operations
            total_recent_attempts = self._scans_performed + self._scans_skipped
            if total_recent_attempts > 20:
                # For long-running monitors, estimate recent skip rate
                # by assuming last 20 attempts follow overall ratio
                skip_rate = self._scans_skipped / total_recent_attempts if total_recent_attempts > 0 else 0
            else:
                # For new monitors, use actual totals
                skip_rate = self._scans_skipped / total_recent_attempts if total_recent_attempts > 0 else 0
            
            # Calculate queue pressure (how often are all slots full?)
            queue_pressure = self._active_scans / self._dynamic_max_scans if self._dynamic_max_scans > 0 else 0
            
            # Determine optimal interval: scan_duration + buffer for safety
            optimal_interval = avg_scan_duration * self.SCAN_BUFFER_FACTOR
            
            # Determine if we need to adjust
            needs_adjustment = False
            adjustment_reason = []
            
            # CONDITION 1: Scans are being skipped - we're overloaded
            # CRITICAL: For life-safety systems, we NEVER reduce scan rate
            # If hardware can't keep up, operator MUST be alerted to upgrade
            if skip_rate > 0.05:  # More than 5% skip rate
                logger.critical(
                    f"🚨 CRITICAL: High scan skip rate ({skip_rate:.1%})! "
                    f"System cannot maintain configured scan rate. "
                    f"Avg scan time: {avg_scan_duration:.2f}s, Interval: {self._dynamic_scan_interval:.2f}s. "
                    f"ACTION REQUIRED: Increase MAX_CONCURRENT_EAS_SCANS from {self.max_concurrent_scans} "
                    f"or upgrade hardware. ALERT COVERAGE MAY BE COMPROMISED!"
                )
                # DO NOT increase interval - that reduces alert coverage
                # DO NOT reduce workers - that makes it worse
                # The only fix is more workers or better hardware
            
            # CONDITION 2: System performing well - log success
            elif skip_rate < 0.01 and avg_scan_duration < self._dynamic_scan_interval:
                # System is healthy - no adjustment needed
                # Just ensure interval hasn't drifted from configured value
                if self._dynamic_scan_interval != self._configured_scan_interval:
                    self._dynamic_scan_interval = self._configured_scan_interval
                    logger.info(
                        f"✓ EAS scanner healthy: avg_scan={avg_scan_duration:.2f}s, "
                        f"skip_rate={skip_rate:.1%}. Reset interval to configured {self._configured_scan_interval:.2f}s"
                    )
            
            # NOTE: Auto-tuning has been DISABLED for life-safety systems
            # Previously, the system would increase scan interval when scans were slow
            # This caused missed scans (80 instead of 200 in 10 minutes)
            # For EAS decoders, scan rate MUST be maintained at configured value
            # If hardware can't keep up, that's a critical error requiring operator action
                    f"max_scans={self._dynamic_max_scans}."
                )
    
    def _get_effective_scan_interval(self) -> float:
        """Get the scan interval.
        
        CRITICAL: For life-safety EAS systems, we ALWAYS use the configured interval.
        Auto-tuning has been disabled because it was causing missed scans.
        
        Returns:
            Configured scan interval in seconds (never adjusted)
        """
        return self._configured_scan_interval
    
    def _get_effective_max_concurrent_scans(self) -> int:
        """Get the current dynamically-adjusted max concurrent scans.
        
        Returns:
            Current effective max concurrent scans
        """
        return self._dynamic_max_scans

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
        logger.info("🔴 STREAMING EAS monitor started - processing samples in real-time")

        # Buffer for reading audio chunks (100ms = 2205 samples at 22050 Hz)
        chunk_samples = int(self.sample_rate * 0.1)
        
        last_heartbeat_time = time.time()
        heartbeat_interval = 5.0  # Update activity every 5 seconds

        read_error_count = 0
        last_error_log_time = 0
        error_log_interval = 10.0
        
        samples_processed = 0
        
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

                # Read audio from manager
                samples = None
                try:
                    samples = self.audio_manager.read_audio(chunk_samples)
                    read_error_count = 0  # Reset error count on success
                except Exception as read_error:
                    read_error_count += 1
                    if current_time - last_error_log_time > error_log_interval:
                        logger.error(
                            f"Error reading audio from manager (error #{read_error_count}): {read_error}",
                            exc_info=True
                        )
                        last_error_log_time = current_time
                    samples = None

                if samples is not None and len(samples) > 0:
                    # REAL-TIME PROCESSING: Feed samples directly to decoder
                    # ZERO buffering, ZERO batching, ZERO delays
                    # Every sample is processed immediately
                    try:
                        self._streaming_decoder.process_samples(samples)
                        samples_processed += len(samples)
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
    
    def _add_to_buffer(self, samples: np.ndarray) -> None:
        """Add samples to circular buffer (for audio archiving only)."""
        if self._buffer_lock is None:
            return  # Archiving disabled
        
        with self._buffer_lock:
            num_samples = len(samples)
            buffer_len = len(self._audio_buffer)

            # Handle wraparound
            if self._buffer_pos + num_samples <= buffer_len:
                # Fits without wraparound
                self._audio_buffer[self._buffer_pos:self._buffer_pos + num_samples] = samples
                self._buffer_pos = (self._buffer_pos + num_samples) % buffer_len
            else:
                # Needs wraparound
                first_chunk = buffer_len - self._buffer_pos
                self._audio_buffer[self._buffer_pos:] = samples[:first_chunk]
                remaining = num_samples - first_chunk
                self._audio_buffer[:remaining] = samples[first_chunk:]
                self._buffer_pos = remaining

    def _get_buffer_contents(self) -> np.ndarray:
        """Get current buffer contents in correct order.

        Returns a COPY of the buffer to avoid holding locks during processing.
        """
        with self._buffer_lock:
            # Return a COPY starting from current position (oldest data first)
            # Using .copy() ensures we don't hold the lock during decode
            return np.concatenate([
                self._audio_buffer[self._buffer_pos:],
                self._audio_buffer[:self._buffer_pos]
            ]).copy()

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

    def _scan_for_alerts(self) -> bool:
        """Queue audio buffer for scan - NEVER drops scans.
        
        This is a life-safety system. Commercial EAS decoders NEVER skip audio analysis.
        We use a queue to ensure every scan request is eventually processed.
        
        Returns:
            True if scan was queued successfully
            False only if queue is full (CRITICAL ERROR - log and alert operators)
        """
        # Get buffer copy (fast, lock released immediately)
        audio_samples = self._get_buffer_contents()
        
        # Create scan job
        scan_job = {
            'audio_samples': audio_samples,
            'timestamp': time.time(),
            'scan_id': None  # Will be assigned by worker
        }
        
        # Try to queue the scan
        try:
            # Use put_nowait to avoid blocking the monitor loop
            # If queue is full, it raises queue.Full
            self._scan_queue.put_nowait(scan_job)
            
            with self._scan_lock:
                self._scans_queued += 1
                current_depth = self._scan_queue.qsize()
                if current_depth > self._max_queue_depth_seen:
                    self._max_queue_depth_seen = current_depth
                    if current_depth > self.max_concurrent_scans:
                        logger.warning(
                            f"⚠️ Scan queue depth at {current_depth} (workers={self.max_concurrent_scans}). "
                            f"System is falling behind. Consider increasing MAX_CONCURRENT_EAS_SCANS."
                        )
            
            return True
            
        except queue.Full:
            # CRITICAL ERROR: Queue is full - we're about to drop a scan
            # This should NEVER happen in a properly configured system
            with self._scan_lock:
                self._scans_queue_full += 1
            
            logger.critical(
                f"🚨 CRITICAL: EAS scan queue FULL! Dropped scan #{self._scans_queue_full}. "
                f"Queue size: {self._scan_queue.maxsize}, Workers: {self.max_concurrent_scans}. "
                f"IMMEDIATE ACTION REQUIRED: Increase MAX_CONCURRENT_EAS_SCANS or upgrade hardware. "
                f"ALERT COVERAGE IS COMPROMISED!"
            )
            return False

    def _scan_worker_loop(self) -> None:
        """Worker thread that processes scans from the queue.
        
        This ensures EVERY queued scan is processed with dedicated worker threads.
        Multiple workers process scans in parallel for maximum throughput.
        """
        worker_name = threading.current_thread().name
        logger.info(f"{worker_name} started and waiting for scan jobs")
        
        while not self._stop_event.is_set():
            try:
                # Get next scan job from queue (blocks until available)
                # Use timeout so we can check stop_event periodically
                try:
                    scan_job = self._scan_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Check for poison pill (None = shutdown signal)
                if scan_job is None:
                    logger.info(f"{worker_name} received shutdown signal")
                    break
                
                # Process the scan
                self._process_scan_job(scan_job, worker_name)
                
                # Mark job as done
                self._scan_queue.task_done()
                
            except Exception as e:
                logger.error(f"{worker_name} error in worker loop: {e}", exc_info=True)
                time.sleep(0.1)  # Brief pause on error
        
        logger.info(f"{worker_name} shutting down")
    
    def _process_scan_job(self, scan_job: dict, worker_name: str) -> None:
        """Process a single scan job from the queue.
        
        Args:
            scan_job: Dict with 'audio_samples', 'timestamp', 'scan_id'
            worker_name: Name of the worker thread for logging
        """
        temp_wav = None
        scan_start_time = time.time()
        audio_samples = scan_job['audio_samples']
        
        try:
            # Assign scan ID
            with self._scan_lock:
                self._scans_performed += 1
                scan_id = self._scans_performed
            
            scan_job['scan_id'] = scan_id
            
            # Check queue lag
            queue_lag = scan_start_time - scan_job['timestamp']
            if queue_lag > 5.0:
                logger.warning(
                    f"⚠️ Scan #{scan_id} has {queue_lag:.1f}s queue lag. "
                    f"System is falling behind real-time. Consider adding workers."
                )

            # Save to temporary WAV file for decoder
            temp_wav = self._save_to_temp_wav(audio_samples)

            try:
                # Run decoder - NO TIMEOUT, NO FILTERING
                # Every audio buffer MUST be analyzed completely
                # This is what commercial EAS decoders do
                result = decode_same_audio(temp_wav, sample_rate=self.sample_rate)

                # Check if we found an alert
                if result.headers and len(result.headers) > 0:
                    # Alert detected!
                    self._handle_alert_detected(result, audio_samples, temp_wav)
                    temp_wav = None  # Don't clean up - _handle_alert_detected manages it

            except Exception as decode_error:
                logger.error(f"Scan #{scan_id} decoder error: {decode_error}", exc_info=True)
                # Continue - don't let decoder errors stop monitoring

        except Exception as e:
            logger.error(f"Scan #{scan_job.get('scan_id', '?')} processing error: {e}", exc_info=True)
        finally:
            # Record scan duration
            scan_duration = time.time() - scan_start_time
            with self._scan_lock:
                self._scans_completed += 1
                self._scan_durations.append(scan_duration)
                # Keep only recent history
                if len(self._scan_durations) > self._max_scan_history:
                    self._scan_durations = self._scan_durations[-self._max_scan_history:]
            
            logger.debug(f"Scan #{scan_job.get('scan_id', '?')} completed in {scan_duration:.2f}s by {worker_name}")
            
            # Clean up temp file if we're not saving it
            if temp_wav and not self.save_audio_files and os.path.exists(temp_wav):
                try:
                    os.unlink(temp_wav)
                except Exception as cleanup_error:
                    logger.debug(f"Error cleaning up temp file {temp_wav}: {cleanup_error}")

    def _save_to_temp_wav(self, samples: np.ndarray) -> str:
        """Save samples to temporary WAV file in RAM disk.
        
        Uses /dev/shm (tmpfs RAM disk) for zero disk I/O.
        This is standard practice for high-frequency temp file operations.
        """
        try:
            # CRITICAL: Use /dev/shm (RAM disk) instead of /tmp (disk)
            # This eliminates disk I/O latency and wear
            # /dev/shm is a tmpfs mount guaranteed to be in RAM on Linux
            ram_disk_dir = "/dev/shm"
            os.makedirs(ram_disk_dir, exist_ok=True)
            
            # Create temp file in RAM
            fd, temp_path = tempfile.mkstemp(
                suffix=".wav", 
                prefix="eas_scan_", 
                dir=ram_disk_dir
            )
            os.close(fd)

            # Write WAV file
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)

                # Convert float32 [-1, 1] to int16 PCM
                pcm_data = (samples * 32767).astype(np.int16)
                wf.writeframes(pcm_data.tobytes())

            return temp_path
        except Exception as e:
            logger.error(f"Failed to save temporary WAV file for EAS scan: {e}", exc_info=True)
            raise  # Re-raise so scan_worker can handle it

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
        """Get monitoring statistics."""
        return {
            'running': not self._stop_event.is_set(),
            'scans_performed': self._scans_performed,
            'alerts_detected': self._alerts_detected,
            'buffer_duration_seconds': self.buffer_duration,
            'scan_interval_seconds': self.scan_interval,
            'active_source': self.audio_manager.get_active_source(),
            'last_alert_time': self._last_alert_time
        }


__all__ = ['ContinuousEASMonitor', 'EASAlert', 'create_fips_filtering_callback', 'compute_alert_signature']
