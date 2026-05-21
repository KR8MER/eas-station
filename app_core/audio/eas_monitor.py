"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
EAS Continuous Monitor - Simplified Single Implementation

Provides continuous EAS/SAME alert monitoring with:
- Robust audio reading with timeout detection
- Consistent status reporting
- Clear health metrics
- Proper error recovery
- FIPS code filtering utilities
"""

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass

import numpy as np

from app_utils import utc_now
from app_utils.eas_codes import get_event_name, get_originator_name
from .fips_utils import determine_fips_matches

logger = logging.getLogger(__name__)


# =============================================================================
# Alert Types
# =============================================================================

@dataclass
class EASAlert:
    """
    Detected EAS alert with metadata.

    Used by self_test.py and other utilities that need structured alert data.
    The core EASMonitor uses dict alerts for simplicity.
    """
    timestamp: Any  # datetime
    raw_text: str
    headers: List[Dict[str, Any]]
    confidence: float
    duration_seconds: float
    source_name: str
    audio_file_path: Optional[str] = None


# =============================================================================
# Alert Utilities
# =============================================================================

def _same_alert_to_dict(alert: Any) -> Dict[str, Any]:
    """Convert a StreamingSAMEAlert dataclass to the alert dict format expected downstream.

    The streaming decoder emits StreamingSAMEAlert objects (raw message + confidence).
    All downstream code—FIPS filtering, database storage, OTA auto-forward—expects a
    plain dict with parsed fields (event_code, location_codes, originator, etc.).
    This function bridges that gap by calling describe_same_header() on the raw string.
    """
    raw_msg = getattr(alert, 'message', '') or ''
    try:
        from app_utils.eas import describe_same_header
        fields = describe_same_header(raw_msg) or {}
    except Exception:
        fields = {}

    # Normalise raw location strings to plain 6-digit FIPS codes
    location_codes = []
    for loc in fields.get('raw_locations', []):
        digits = ''.join(c for c in str(loc) if c.isdigit()).zfill(6)[:6]
        if len(digits) == 6:
            location_codes.append(digits)

    # Derive purge_time ISO string from issue_time + purge_minutes
    purge_time = None
    issue_time_iso = fields.get('issue_time_iso')
    purge_minutes = fields.get('purge_minutes')
    if issue_time_iso and purge_minutes:
        try:
            issue_dt = datetime.fromisoformat(issue_time_iso)
            purge_time = (issue_dt + timedelta(minutes=purge_minutes)).isoformat()
        except Exception:
            pass

    ts = getattr(alert, 'timestamp', None)
    return {
        'raw_header': raw_msg,
        'event_code': fields.get('event_code', ''),
        'originator': fields.get('originator', ''),
        'location_codes': location_codes,
        'callsign': (fields.get('station_identifier') or '').strip('-').strip(),
        'issue_time': issue_time_iso,
        'purge_time': purge_time,
        'confidence': getattr(alert, 'confidence', 0.0),
        'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
        'endec_mode': getattr(alert, 'endec_mode', 'UNKNOWN') or 'UNKNOWN',
        'burst_timing_gaps_ms': list(getattr(alert, 'burst_timing_gaps_ms', [])),
    }


def compute_alert_signature(alert: Dict[str, Any]) -> str:
    """
    Create a deterministic hash of alert data for deduplication.

    Args:
        alert: Alert dictionary with keys like 'raw_header', 'event_code', etc.

    Returns:
        SHA256 hash string
    """
    # Try to use raw header text first
    raw_header = alert.get('raw_header') or alert.get('raw_text', '')

    if raw_header:
        base_text = raw_header.strip()
    else:
        # Fall back to event code + location codes + timestamp
        event_code = alert.get('event_code', 'UNKNOWN')
        location_codes = alert.get('location_codes', [])
        source_name = alert.get('source_name', 'unknown')

        parts = [event_code, ','.join(location_codes), source_name]
        base_text = '|'.join(parts)

    if not base_text:
        # Last resort: use timestamp
        base_text = str(time.time())

    return hashlib.sha256(base_text.encode('utf-8', 'ignore')).hexdigest()


def _store_received_alert(
    alert: Dict[str, Any],
    forwarding_decision: str,
    forwarding_reason: str,
    matched_fips: List[str],
    generated_message_id: Optional[int] = None
) -> None:
    """
    Store received EAS alert in database with forwarding decision.

    Args:
        alert: Alert dictionary
        forwarding_decision: 'forwarded', 'ignored', or 'error'
        forwarding_reason: Human-readable reason for the decision
        matched_fips: List of FIPS codes that matched (if any)
        generated_message_id: FK to eas_messages table if forwarded
    """
    try:
        from app_core.models import ReceivedEASAlert
        from app_core.extensions import db
        from flask import has_app_context

        if not has_app_context():
            logger.debug("Not in Flask app context, skipping database storage")
            return

        # Extract data from alert dict
        event_code = alert.get('event_code', 'UNKNOWN')
        event_name = get_event_name(event_code) if event_code != 'UNKNOWN' else None
        originator_code = alert.get('originator', 'UNKNOWN')
        originator_name = get_originator_name(originator_code) if originator_code != 'UNKNOWN' else None
        fips_codes = alert.get('location_codes', [])
        callsign = alert.get('callsign')
        raw_same_header = alert.get('raw_header') or alert.get('raw_text')
        source_name = alert.get('source_name', 'unknown')

        # Determine canonical ingest path (EAS-RF vs EAS-STREAM) by looking up
        # the audio source configuration.  This is a rare code path (only on
        # actual EAS detections) so a single DB lookup is acceptable.
        alert_source = alert.get('alert_source')
        if not alert_source:
            try:
                from app_core.models import AudioSourceConfigDB
                from app_core.audio.ingest import AudioSourceType
                from app_utils.alert_sources import ALERT_SOURCE_EAS_RF, ALERT_SOURCE_EAS_STREAM
                _RF_TYPES = {AudioSourceType.SDR.value, AudioSourceType.ALSA.value,
                             AudioSourceType.PULSE.value, 'redis_sdr'}
                cfg = AudioSourceConfigDB.query.filter_by(name=source_name).first()
                if cfg:
                    alert_source = ALERT_SOURCE_EAS_RF if cfg.source_type in _RF_TYPES else ALERT_SOURCE_EAS_STREAM
            except Exception:
                pass

        # Parse timestamps if present
        issue_datetime = None
        purge_datetime = None
        issue_time = alert.get('issue_time')
        purge_time = alert.get('purge_time')
        if issue_time:
            issue_datetime = datetime.fromisoformat(issue_time) if isinstance(issue_time, str) else issue_time
        if purge_time:
            purge_datetime = datetime.fromisoformat(purge_time) if isinstance(purge_time, str) else purge_time

        # Check for duplicates within 10 minute window
        dedup_cutoff = utc_now() - timedelta(minutes=10)
        duplicate_filters = [ReceivedEASAlert.received_at >= dedup_cutoff]
        if raw_same_header:
            duplicate_filters.append(ReceivedEASAlert.raw_same_header == raw_same_header)
        else:
            duplicate_filters.append(ReceivedEASAlert.event_code == event_code)
            duplicate_filters.append(ReceivedEASAlert.originator_code == originator_code)
            if callsign:
                duplicate_filters.append(ReceivedEASAlert.callsign == callsign)

        duplicate_record = db.session.query(ReceivedEASAlert).filter(*duplicate_filters).first()
        if duplicate_record:
            # When burst 1 was stored before terminators arrived, its endec_mode is
            # UNKNOWN.  Bursts 2 and 3 carry the correct fingerprint once the DLL has
            # consumed burst 1's terminator bytes.  Promote the stored record here.
            incoming_endec = full_alert_json.get('endec_mode') or 'UNKNOWN'
            stored_endec = (duplicate_record.full_alert_data or {}).get('endec_mode') or 'UNKNOWN'
            if incoming_endec != 'UNKNOWN' and stored_endec == 'UNKNOWN':
                updated = dict(duplicate_record.full_alert_data or {})
                updated['endec_mode'] = incoming_endec
                updated['burst_timing_gaps_ms'] = full_alert_json.get('burst_timing_gaps_ms', [])
                duplicate_record.full_alert_data = updated
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            logger.info(
                "Duplicate received alert suppressed within 10-minute window: %s",
                raw_same_header or event_code,
            )
            return

        # Create database record
        # Strip the raw audio bytes from the JSON payload — the binary is
        # already stored in the dedicated raw_audio_data column.  Leaving it
        # in the dict would cause JSONB serialization to fail (bytes are not
        # JSON-serializable), which would roll back the entire commit and lose
        # the alert record entirely.  relay_audio_wav is also bytes and must be
        # stripped for the same reason.
        _BINARY_KEYS = {'raw_audio_wav', 'relay_audio_wav'}
        full_alert_json = {k: v for k, v in alert.items() if k not in _BINARY_KEYS}
        # numpy float64 is not JSON-serializable — convert to plain Python float
        # so the JSONB commit does not fail and silently drop the alert record.
        if 'confidence' in full_alert_json and full_alert_json['confidence'] is not None:
            try:
                full_alert_json['confidence'] = float(full_alert_json['confidence'])
            except (TypeError, ValueError):
                pass

        received_alert = ReceivedEASAlert(
            received_at=utc_now(),
            source_name=source_name,
            alert_source=alert_source,
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
            decode_confidence=alert.get('confidence', 0.0),
            full_alert_data=full_alert_json,
            raw_audio_data=alert.get('raw_audio_wav'),
        )

        db.session.add(received_alert)
        try:
            db.session.commit()
            logger.info(f"Stored received alert in database: {event_code} from {source_name}")
        except Exception as commit_exc:
            db.session.rollback()
            # If the commit failed because a new column doesn't exist yet
            # (migration not applied), retry with a minimal record that omits
            # both `raw_audio_data` (added 2026-03-25) and `alert_source`
            # (added 2026-04-01).  The original retry only cleared
            # raw_audio_data but left alert_source in the INSERT, causing the
            # retry to fail with the same "column does not exist" error and
            # silently drop every alert record.
            err_str = str(commit_exc).lower()
            if 'raw_audio_data' in err_str or 'alert_source' in err_str or 'column' in err_str:
                logger.warning(
                    "DB column missing in received_eas_alerts — storing alert without "
                    "optional new columns (run 'alembic upgrade head' to apply pending "
                    "migrations): %s",
                    commit_exc,
                )
                # Build a fresh record that omits both new columns so SQLAlchemy
                # does not include them in the INSERT at all.  Setting a column to
                # None still puts NULL in the INSERT; only omitting it from the
                # constructor leaves the column out of the generated SQL entirely.
                minimal_alert = ReceivedEASAlert(
                    received_at=received_alert.received_at,
                    source_name=received_alert.source_name,
                    # alert_source intentionally omitted — may not exist in DB
                    raw_same_header=received_alert.raw_same_header,
                    event_code=received_alert.event_code,
                    event_name=received_alert.event_name,
                    originator_code=received_alert.originator_code,
                    originator_name=received_alert.originator_name,
                    fips_codes=received_alert.fips_codes,
                    issue_datetime=received_alert.issue_datetime,
                    purge_datetime=received_alert.purge_datetime,
                    callsign=received_alert.callsign,
                    forwarding_decision=received_alert.forwarding_decision,
                    forwarding_reason=received_alert.forwarding_reason,
                    matched_fips_codes=received_alert.matched_fips_codes,
                    generated_message_id=received_alert.generated_message_id,
                    forwarded_at=received_alert.forwarded_at,
                    decode_confidence=received_alert.decode_confidence,
                    full_alert_data=received_alert.full_alert_data,
                    # raw_audio_data intentionally omitted — may not exist in DB
                )
                db.session.add(minimal_alert)
                db.session.commit()
                logger.info(
                    "Stored received alert (degraded — run 'alembic upgrade head') "
                    "in database: %s from %s",
                    event_code, source_name,
                )
            else:
                raise

    except Exception as e:
        logger.error(f"Failed to store received alert in database: {e}", exc_info=True)
        try:
            from app_core.extensions import db
            db.session.rollback()
        except Exception:
            pass


def create_fips_filtering_callback(
    configured_fips_codes: List[str],
    forward_callback: Callable[[Dict[str, Any]], Any],
    logger_instance: Optional[logging.Logger] = None
) -> Callable[[Dict[str, Any]], None]:
    """
    Create an alert callback that filters by FIPS codes.

    Args:
        configured_fips_codes: List of FIPS codes to match
        forward_callback: Function to call when alert matches FIPS codes
        logger_instance: Optional logger (defaults to module logger)

    Returns:
        Callback function for EASMonitor
    """
    log = logger_instance or logger

    def fips_filtering_callback(alert: Dict[str, Any]) -> None:
        """Filter alerts by FIPS codes."""
        # Extract alert info
        alert_fips_codes = alert.get('location_codes', [])
        event_code = alert.get('event_code', 'UNKNOWN')
        originator = alert.get('originator', 'UNKNOWN')

        # Low-confidence decodes: log to DB but never forward to air.
        # The confidence threshold lives here (not in StreamingSAMEDecoder) so
        # that every decoded header is always stored in received_eas_alerts for
        # operator visibility, regardless of signal quality.
        _MIN_FORWARD_CONFIDENCE = 0.25
        confidence = float(alert.get('confidence', 0.0))
        if confidence < _MIN_FORWARD_CONFIDENCE:
            log.warning(
                "LOW CONFIDENCE - LOGGING ONLY (%.1f%% < %.0f%%): Event=%s | "
                "Originator=%s | FIPS=%s",
                confidence * 100, _MIN_FORWARD_CONFIDENCE * 100,
                event_code, originator, ','.join(alert_fips_codes) or 'NONE',
            )
            _store_received_alert(
                alert=alert,
                forwarding_decision='ignored',
                forwarding_reason=(
                    f"Low confidence decode: {confidence:.1%} < "
                    f"{_MIN_FORWARD_CONFIDENCE:.0%} threshold"
                ),
                matched_fips=[],
            )
            return

        # If no FIPS codes configured, accept ALL alerts
        if not configured_fips_codes:
            log.warning(
                f"NO FIPS FILTERING - ACCEPTING ALL: Event={event_code} | "
                f"Originator={originator} | FIPS={','.join(alert_fips_codes) or 'NONE'}"
            )
            try:
                result = forward_callback(alert)
                outcome = _broadcast_outcome(result)
                if outcome['actually_forwarded']:
                    _store_received_alert(
                        alert=alert,
                        forwarding_decision='forwarded',
                        forwarding_reason='No FIPS filtering configured - accepting all alerts',
                        matched_fips=alert_fips_codes,
                        generated_message_id=outcome['message_id'],
                    )
                else:
                    # Forward callback ran without raising but no broadcast
                    # record was persisted (event suppressed, unsupported
                    # status, broadcaster disabled, missing app context, …).
                    # Don't claim the alert was forwarded when nothing went
                    # to air — that's the bug behind "Forwarded but no
                    # broadcast record linked."
                    log.info(
                        "Alert accepted but broadcast not triggered: %s (%s)",
                        event_code, outcome['reason'],
                    )
                    _store_received_alert(
                        alert=alert,
                        forwarding_decision='ignored',
                        forwarding_reason=(
                            f"Broadcast not triggered: {outcome['reason']}"
                        ),
                        matched_fips=alert_fips_codes,
                    )
            except Exception as e:
                log.error(f"Error forwarding alert: {e}", exc_info=True)
                _store_received_alert(
                    alert=alert,
                    forwarding_decision='error',
                    forwarding_reason=f"Forwarding failed: {str(e)}",
                    matched_fips=[]
                )
            return

        # Check for FIPS match
        matched_fips_list = determine_fips_matches(alert_fips_codes, configured_fips_codes)

        if matched_fips_list:
            # FIPS match - forward alert
            forwarding_reason = f"FIPS match: {', '.join(matched_fips_list)}"
            log.warning(
                f"FIPS MATCH - FORWARDING: Event={event_code} | "
                f"Originator={originator} | Matched={','.join(matched_fips_list)}"
            )
            try:
                result = forward_callback(alert)
                outcome = _broadcast_outcome(result)
                if outcome['actually_forwarded']:
                    _store_received_alert(
                        alert=alert,
                        forwarding_decision='forwarded',
                        forwarding_reason=forwarding_reason,
                        matched_fips=matched_fips_list,
                        generated_message_id=outcome['message_id'],
                    )
                else:
                    log.info(
                        "FIPS match but broadcast not triggered: %s (%s)",
                        event_code, outcome['reason'],
                    )
                    _store_received_alert(
                        alert=alert,
                        forwarding_decision='ignored',
                        forwarding_reason=(
                            f"{forwarding_reason}; broadcast not triggered: "
                            f"{outcome['reason']}"
                        ),
                        matched_fips=matched_fips_list,
                    )
            except Exception as e:
                log.error(f"Error forwarding alert: {e}", exc_info=True)
                _store_received_alert(
                    alert=alert,
                    forwarding_decision='error',
                    forwarding_reason=f"Forwarding failed: {str(e)}",
                    matched_fips=matched_fips_list
                )
        else:
            # No FIPS match - ignore
            log.info(
                f"NO FIPS MATCH - IGNORING: Event={event_code} | "
                f"Alert FIPS={','.join(alert_fips_codes) or 'NONE'}"
            )
            if alert_fips_codes:
                forwarding_reason = f"No FIPS match. Alert: {', '.join(alert_fips_codes)}"
            else:
                forwarding_reason = "No FIPS codes in alert"
            _store_received_alert(
                alert=alert,
                forwarding_decision='ignored',
                forwarding_reason=forwarding_reason,
                matched_fips=[]
            )

    return fips_filtering_callback


def _extract_message_id(result: Any) -> Optional[int]:
    """Extract message ID from various callback return types."""
    if result is None:
        return None
    if isinstance(result, int):
        return result
    if isinstance(result, dict):
        # Direct record_id/message_id/id at top level
        # auto_forward_ota_alert / auto_forward_cap_alert put record_id here.
        msg_id = (
            result.get('record_id')
            or result.get('message_id')
            or result.get('id')
        )
        if msg_id:
            return int(msg_id)
        # Nested inside broadcast_detail (forward_alert_to_api return format)
        detail = result.get('broadcast_detail')
        if isinstance(detail, dict):
            nested = detail.get('record_id') or detail.get('message_id') or detail.get('id')
            if nested:
                return int(nested)
    if hasattr(result, 'id'):
        return getattr(result, 'id')
    return None


def _broadcast_outcome(result: Any) -> Dict[str, Any]:
    """Inspect a forward_callback return value and report whether a broadcast
    record was actually persisted.

    Returns a dict with:
        actually_forwarded (bool): True iff a broadcast record was committed.
        message_id (Optional[int]): FK to eas_messages.id when known.
        reason (Optional[str]): Human-readable reason when the broadcast was
            *not* triggered (e.g. unsupported status, event suppressed,
            missing Flask app context, broadcast disabled).
    """
    message_id = _extract_message_id(result)
    outcome: Dict[str, Any] = {
        'actually_forwarded': False,
        'message_id': message_id,
        'reason': None,
    }

    if message_id is not None:
        outcome['actually_forwarded'] = True
        return outcome

    if not isinstance(result, dict):
        # Non-dict success result with no extractable id — assume not
        # broadcast and leave reason None for the caller to fill in.
        return outcome

    # forward_alert_to_api wraps auto_forward_*; check the nested detail first
    # because that's where the authoritative same_triggered flag lives.
    detail = result.get('broadcast_detail')
    if isinstance(detail, dict):
        if detail.get('same_triggered') or detail.get('forwarded'):
            # Broadcast claims success but no id surfaced — accept as
            # forwarded so we don't lose track of a real on-air event.
            outcome['actually_forwarded'] = True
            return outcome
        outcome['reason'] = (
            detail.get('reason')
            or detail.get('error')
            or 'Broadcast not triggered'
        )
        return outcome

    # Direct auto_forward result (no wrapper)
    if result.get('same_triggered') or result.get('forwarded'):
        outcome['actually_forwarded'] = True
        return outcome

    outcome['reason'] = (
        result.get('reason')
        or result.get('error')
        or 'Broadcast not triggered'
    )
    return outcome


# =============================================================================
# Health Tracking
# =============================================================================

@dataclass
class MonitorHealth:
    """Health tracking for EAS monitor."""
    last_audio_time: float = 0.0
    consecutive_empty_reads: int = 0
    consecutive_errors: int = 0
    total_errors: int = 0
    audio_flowing: bool = False
    health_score: float = 1.0


# =============================================================================
# EAS Monitor
# =============================================================================

class EASMonitor:
    """
    Continuous EAS/SAME alert monitor.

    Features:
    - Robust audio pipeline with health tracking
    - Clear, consistent status reporting
    - Proper timeout detection
    - Graceful error recovery
    - Real-time health metrics
    """

    def __init__(
        self,
        audio_source=None,
        sample_rate: int = 16000,
        alert_callback: Optional[Callable] = None,
        source_name: str = "unknown",
        audio_manager=None,  # Backwards compatibility - deprecated
        save_audio_files: bool = False  # Backwards compatibility - deprecated
    ):
        """
        Initialize monitor.

        Args:
            audio_source: Object with read_audio(num_samples) method
            sample_rate: Target sample rate for decoder (16kHz for SAME)
            alert_callback: Function to call when alert detected
            source_name: Human-readable name for this source
            audio_manager: DEPRECATED - use audio_source instead (for backwards compatibility)
            save_audio_files: DEPRECATED - ignored (for backwards compatibility)
        """
        # Handle backwards compatibility with audio_manager parameter
        if audio_manager is not None and audio_source is None:
            audio_source = audio_manager
            logger.warning("audio_manager parameter is deprecated, use audio_source instead")
        
        if audio_source is None:
            raise ValueError("audio_source parameter is required")
        
        self.audio_source = audio_source
        self.sample_rate = sample_rate
        self.alert_callback = alert_callback
        self.source_name = source_name

        # Get source sample rate if available
        self.source_sample_rate = getattr(audio_source, 'sample_rate', sample_rate)

        # Initialize streaming decoder
        from .streaming_same_decoder import StreamingSAMEDecoder
        self._decoder = StreamingSAMEDecoder(
            sample_rate=sample_rate,
            alert_callback=self._handle_alert
        )
        # Alias for backward compatibility with tests and external callers
        self._streaming_decoder = self._decoder

        # State management
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        self._alerts_detected = 0
        self._samples_processed = 0
        self._restart_count = 0

        # Per-source duplicate suppression.
        # The same SAME header text received within the cooldown window is
        # silently dropped so that multi-burst alerts (three identical
        # ZCZC headers broadcast back-to-back) are not forwarded three times.
        self._duplicate_cooldown_seconds: float = 300.0  # 5 minutes
        self._seen_alert_hashes: Dict[str, float] = {}  # signature → timestamp
        self._seen_alerts_lock = threading.Lock()

        # Health tracking
        self._health = MonitorHealth()
        self._health_lock = threading.Lock()

        # Configuration
        self._chunk_duration_ms = 100
        self._chunk_size = int(self.sample_rate * self._chunk_duration_ms / 1000)
        self._audio_timeout_seconds = 5.0
        self._max_empty_reads = 50
        self._max_errors = 100

        logger.info(
            f"EASMonitor initialized for '{source_name}': "
            f"{self.source_sample_rate}Hz -> {sample_rate}Hz, "
            f"chunk={self._chunk_duration_ms}ms ({self._chunk_size} samples)"
        )

    def start(self) -> bool:
        """Start monitoring."""
        if self._running:
            logger.warning(f"Monitor '{self.source_name}' already running")
            return False

        self._running = True
        self._start_time = time.time()
        self._samples_processed = 0
        self._alerts_detected = 0

        with self._health_lock:
            self._health = MonitorHealth()

        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=f"eas-monitor-{self.source_name}",
            daemon=True
        )
        self._thread.start()

        logger.info(f"EAS monitor '{self.source_name}' started")
        return True

    def stop(self) -> None:
        """Stop monitoring."""
        if not self._running:
            return

        logger.info(f"Stopping EAS monitor '{self.source_name}'...")
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning(f"Monitor thread '{self.source_name}' did not stop cleanly")

        logger.info(
            f"EAS monitor '{self.source_name}' stopped. "
            f"Processed {self._samples_processed:,} samples, "
            f"detected {self._alerts_detected} alerts"
        )

    def _restart_monitor_thread(self) -> None:
        """Reset timing and decoder state as if the monitor is freshly started.

        Called by the watchdog or external supervisors when the monitor thread
        needs to be restarted.  Increments the restart counter and resets
        ``_start_time`` so that runtime reporting stays consistent.
        """
        self._restart_count += 1
        self._start_time = time.time()
        self._samples_processed = 0
        # Reset decoder sample counter so runtime_seconds stays in sync
        try:
            self._streaming_decoder._core.samples_processed = 0
        except AttributeError:
            logger.debug(
                "EASMonitor '%s': could not reset decoder sample counter on restart",
                self.source_name,
            )
        logger.info(
            f"EAS monitor '{self.source_name}' thread restarted "
            f"(restart #{self._restart_count})"
        )

    def _resample_if_needed(self, audio) -> Any:
        """Convert stereo/multi-channel audio to mono and resample if necessary.

        Args:
            audio: 1-D or 2-D numpy array of audio samples.  For 2-D input the
                   first axis is the frame index and the second is the channel
                   index (shape ``(frames, channels)``).

        Returns:
            A 1-D numpy float32 array at ``self.sample_rate``.
        """
        import numpy as np

        audio = np.asarray(audio, dtype=np.float32)

        # Convert multi-channel audio to mono
        if audio.ndim == 2:
            if audio.shape[1] >= 2:
                audio = audio.mean(axis=1)
            else:
                audio = audio[:, 0]

        # Resample if source rate differs from target rate
        source_rate = getattr(self.audio_source, 'sample_rate', self.sample_rate)
        if source_rate != self.sample_rate and source_rate > 0:
            try:
                from scipy import signal as scipy_signal
                new_length = int(round(len(audio) * self.sample_rate / source_rate))
                if new_length > 0:
                    audio = scipy_signal.resample(audio, new_length).astype(np.float32)
            except ImportError:
                # scipy not available; fall back to linear interpolation via numpy.
                # Note: linear interpolation introduces aliasing for large
                # decimation ratios. Install scipy for production-quality resampling.
                ratio = self.sample_rate / source_rate
                new_length = int(round(len(audio) * ratio))
                if new_length > 0:
                    indices = np.linspace(0, len(audio) - 1, new_length)
                    audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

        return audio

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status."""
        decoder_stats = self._decoder.get_stats()

        with self._health_lock:
            health = self._health

        # Compute runtime even when the monitor is stopped, as long as _start_time is known.
        # This lets callers inspect elapsed time after a stop or before a full restart.
        samples_processed = self._streaming_decoder.samples_processed
        if self._start_time is not None:
            wall_clock_runtime = time.time() - self._start_time
            if samples_processed > 0:
                audio_runtime = samples_processed / self.sample_rate
                samples_per_second = samples_processed / max(wall_clock_runtime, 0.1)
                health_percentage = min(1.0, samples_per_second / self.sample_rate)
            else:
                audio_runtime = 0
                samples_per_second = 0
                health_percentage = 0.0
        else:
            wall_clock_runtime = 0
            audio_runtime = 0
            samples_per_second = 0
            health_percentage = 0.0

        time_since_audio = time.time() - health.last_audio_time if health.last_audio_time > 0 else 999999
        audio_flowing = (
            self._running and
            samples_processed > 0 and
            time_since_audio < self._audio_timeout_seconds
        )

        adapter_stats = {}
        if hasattr(self.audio_source, 'get_stats'):
            try:
                adapter_stats = self.audio_source.get_stats()
            except Exception:
                pass

        return {
            "running": self._running,
            "mode": "streaming",
            "source_name": self.source_name,
            "audio_flowing": audio_flowing,
            "samples_processed": samples_processed,
            "samples_per_second": int(samples_per_second),
            "wall_clock_runtime_seconds": wall_clock_runtime,
            "runtime_seconds": audio_runtime,
            "health_percentage": health_percentage,
            "time_since_last_audio": time_since_audio,
            "consecutive_empty_reads": health.consecutive_empty_reads,
            "consecutive_errors": health.consecutive_errors,
            "total_errors": health.total_errors,
            "decoder_synced": decoder_stats.get('synced', False),
            "decoder_in_message": decoder_stats.get('in_message', False),
            "decoder_bytes_decoded": decoder_stats.get('bytes_decoded', 0),
            "alerts_detected": self._alerts_detected,
            "sample_rate": self.sample_rate,
            "source_sample_rate": self.source_sample_rate,
            "restart_count": self._restart_count,
            "audio_buffer_samples": adapter_stats.get("buffer_samples", 0),
            "audio_queue_depth": adapter_stats.get("queue_size", 0),
            "audio_underruns": adapter_stats.get("underrun_count", 0),
        }

    def _handle_alert(self, alert_data) -> None:
        """Handle detected alert."""
        self._alerts_detected += 1

        # The streaming decoder emits StreamingSAMEAlert objects; convert to dict.
        from .streaming_same_decoder import StreamingSAMEAlert
        if isinstance(alert_data, StreamingSAMEAlert):
            alert_data = _same_alert_to_dict(alert_data)

        # Prefer the currently active audio source name reported by the adapter
        # (e.g. "RF Receiver 1") over the static monitor label so that the
        # database record reflects the actual ingest path.
        active_source: Optional[str] = None
        if self.audio_source is not None:
            try:
                active_source = self.audio_source.get_active_source()
            except Exception:
                pass
        alert_data['source_name'] = active_source or self.source_name

        logger.info(
            f"EAS Alert detected on '{alert_data['source_name']}': "
            f"{alert_data.get('event_code', 'UNKNOWN')}"
        )

        if self.alert_callback:
            try:
                self.alert_callback(alert_data)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}", exc_info=True)

    def _handle_alert_detected(
        self,
        result: Any,
        samples: Any,
        wav_file_path: Optional[str] = None,
    ) -> None:
        """Handle a decoded alert result, suppressing duplicates within the cooldown window.

        This method provides backward-compatible support for callers that pass a
        ``SAMEAudioDecodeResult`` (or similar object with a ``raw_text`` attribute)
        instead of a ``StreamingSAMEAlert``.  It mirrors the deduplication logic
        that was previously baked into the old ``ContinuousEASMonitor`` class so
        that unit tests and legacy code paths continue to work correctly.

        Duplicate detection uses a SHA-256 hash of ``raw_text``; if the same
        signature arrives within ``_duplicate_cooldown_seconds`` it is silently
        dropped.  Stale entries are pruned on each call to keep memory bounded.

        Args:
            result: Object with ``raw_text`` attribute (e.g. ``SAMEAudioDecodeResult``),
                    or a plain dict with a ``'raw_text'`` key.
            samples: Audio samples array – accepted for API compatibility but unused.
            wav_file_path: Optional on-disk path to the decoded audio file.
        """
        raw_text: str = ''
        if isinstance(result, dict):
            raw_text = result.get('raw_text', '') or ''
        else:
            raw_text = getattr(result, 'raw_text', '') or ''

        alert_sig = hashlib.sha256(raw_text.encode('utf-8', 'ignore')).hexdigest()
        current_time = time.time()

        with self._seen_alerts_lock:
            last_seen = self._seen_alert_hashes.get(alert_sig)
            if last_seen is not None and (current_time - last_seen) < self._duplicate_cooldown_seconds:
                logger.debug(
                    "Suppressing duplicate alert on '%s' "
                    "(seen %.1fs ago, cooldown %.0fs)",
                    self.source_name,
                    current_time - last_seen,
                    self._duplicate_cooldown_seconds,
                )
                return
            self._seen_alert_hashes[alert_sig] = current_time
            # Prune entries older than the cooldown window to bound memory use.
            cutoff = current_time - self._duplicate_cooldown_seconds
            self._seen_alert_hashes = {
                k: v for k, v in self._seen_alert_hashes.items() if v >= cutoff
            }

        # Build the alert dict from the result object if needed, then delegate
        # to the normal _handle_alert path (which fires the alert_callback).
        if isinstance(result, dict):
            alert_data: Dict[str, Any] = dict(result)
        else:
            # SAMEAudioDecodeResult: extract fields from the first header.
            headers_list = getattr(result, 'headers', []) or []
            first_fields: Dict[str, Any] = {}
            if headers_list:
                first = headers_list[0]
                first_fields = getattr(first, 'fields', {}) or {}

            location_codes: List[str] = []
            for loc in (first_fields.get('locations') or []):
                if isinstance(loc, dict):
                    code = loc.get('code', '')
                else:
                    code = str(loc)
                # Keep only the numeric portion and normalise to exactly 6 digits.
                digits = ''.join(c for c in code if c.isdigit())
                if len(digits) <= 6:
                    digits = digits.zfill(6)
                else:
                    digits = digits[:6]
                if digits:
                    location_codes.append(digits)

            alert_data = {
                'raw_header': raw_text,
                'event_code': first_fields.get('event_code', ''),
                'originator': first_fields.get('originator', ''),
                'location_codes': location_codes,
                'callsign': (first_fields.get('station_identifier') or '').strip('- '),
                'confidence': getattr(result, 'bit_confidence', 0.0),
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            }

        self._handle_alert(alert_data)

    def _resample_linear(self, samples: np.ndarray) -> np.ndarray:
        """Fast linear resampling."""
        if self.source_sample_rate == self.sample_rate:
            return samples

        try:
            if samples.ndim == 2:
                samples = samples.mean(axis=1)
            elif samples.ndim > 2:
                samples = samples.flatten()

            if samples.dtype != np.float32:
                samples = samples.astype(np.float32)

            ratio = self.sample_rate / float(self.source_sample_rate)
            new_length = max(1, int(len(samples) * ratio))

            old_indices = np.arange(len(samples))
            new_indices = np.linspace(0, len(samples) - 1, new_length)
            resampled = np.interp(new_indices, old_indices, samples)

            return resampled.astype(np.float32)

        except Exception as e:
            logger.error(f"Resampling error on '{self.source_name}': {e}")
            with self._health_lock:
                self._health.total_errors += 1
            return samples

    def _update_health(self, got_audio: bool, error: bool = False) -> None:
        """Update health tracking."""
        with self._health_lock:
            if error:
                self._health.consecutive_errors += 1
                self._health.total_errors += 1
                self._health.consecutive_empty_reads = 0
            elif got_audio:
                self._health.last_audio_time = time.time()
                self._health.consecutive_empty_reads = 0
                self._health.consecutive_errors = 0
                self._health.audio_flowing = True
            else:
                self._health.consecutive_empty_reads += 1
                self._health.consecutive_errors = 0
                time_since_audio = time.time() - self._health.last_audio_time if self._health.last_audio_time > 0 else 999999
                if time_since_audio > self._audio_timeout_seconds:
                    self._health.audio_flowing = False

            health_factors = [
                1.0 - min(1.0, self._health.consecutive_errors / 100),
                1.0 - min(1.0, self._health.consecutive_empty_reads / 100),
                1.0 if self._health.audio_flowing else 0.5,
            ]
            self._health.health_score = sum(health_factors) / len(health_factors)

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info(f"Monitor loop starting for '{self.source_name}'...")

        while self._running:
            try:
                samples = self.audio_source.read_audio(self._chunk_size)

                if samples is None or len(samples) == 0:
                    self._update_health(got_audio=False)

                    with self._health_lock:
                        empty_reads = self._health.consecutive_empty_reads

                    if empty_reads == self._max_empty_reads:
                        logger.warning(
                            f"'{self.source_name}': No audio for {empty_reads} reads"
                        )
                    elif empty_reads > self._max_empty_reads and empty_reads % 100 == 0:
                        logger.warning(
                            f"'{self.source_name}': Still no audio after {empty_reads} reads"
                        )

                    time.sleep(0.05)
                    continue

                self._update_health(got_audio=True)

                if self.source_sample_rate != self.sample_rate:
                    samples = self._resample_linear(samples)

                self._decoder.process_samples(samples)
                self._samples_processed += len(samples)
                
                # CRITICAL FIX: Prevent CPU hammering by sleeping briefly after processing audio
                # Without this sleep, the loop spins at maximum speed when audio is flowing,
                # consuming 100% CPU. A 10ms sleep reduces CPU usage dramatically while still
                # processing audio in near-realtime (chunk_size is typically 4096 samples at
                # 16kHz = 256ms of audio, so 10ms sleep is only 4% overhead).
                time.sleep(0.01)  # 10ms sleep to prevent CPU spinning

            except Exception as e:
                logger.error(f"Error in monitor loop for '{self.source_name}': {e}", exc_info=True)
                self._update_health(got_audio=False, error=True)

                with self._health_lock:
                    if self._health.consecutive_errors >= self._max_errors:
                        logger.error(
                            f"'{self.source_name}': Too many errors, stopping monitor"
                        )
                        self._running = False
                        break

                time.sleep(0.1)

        logger.info(f"Monitor loop exited for '{self.source_name}'")


# Backwards compatibility aliases
EASMonitorV2 = EASMonitor
ContinuousEASMonitor = EASMonitor
