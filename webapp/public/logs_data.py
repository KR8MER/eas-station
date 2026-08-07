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

from __future__ import annotations

"""Query layer for the unified /logs hub.

``load_logs_data`` gathers every log category the hub can render."""

from app_core.config import get_all_log_services
from app_core.extensions import db
from app_core.models import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    EASDecodedAudio,
    EASMessage,
    GPIOActivationLog,
    ManualEASActivation,
    PollDebugRecord,
    PollHistory,
    ReceivedEASAlert,
    SystemLog,
)
from app_utils.gpio_logs import gpio_log_level, gpio_log_message
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from webapp.routes_logs import get_systemd_logs

MIN_LOGS_PER_CATEGORY = 10  # Minimum logs to show per category in "All Logs" view


def build_logs_loader(route_logger):
    """Return the loader the /logs routes call.

    Bound to ``route_logger`` the same way the original
    nested definition closed over it.
    """
    def _load_logs_data(
        log_type: str,
        limit: int,
        service_filter: str = None,
        action_filter: str = None,
    ) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Load the requested log data and metadata for rendering or export.

        Returns a triple of ``(display_name, logs_data, report_meta)``.  The
        third element is populated only for ``report_*`` log types and carries
        the FCC report's column labels, summary lines, and window — the
        template uses it to render a real columnar layout instead of cramming
        every column into the generic ``message`` cell.

        ``action_filter`` applies only to the ``audit`` log type and restricts
        the query to a single ``AuditAction`` value (e.g. ``config.updated``)
        at the database level so the newest matching rows aren't lost behind
        the ``limit`` window.
        """

        log_type_name = "System Logs"
        logs_data: List[Dict[str, Any]] = []
        report_meta: Optional[Dict[str, Any]] = None

        if log_type == 'all':
            log_type_name = "All Logs"
            # For 'all' type, return logs organized by category
            # Each category gets a portion of the limit
            logs_per_category = max(MIN_LOGS_PER_CATEGORY, limit // 10)
            all_logs = []

            # System logs - wrapped in try-except for resilience
            try:
                for log in SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(logs_per_category).all():
                    all_logs.append({
                        'timestamp': log.timestamp,
                        'level': log.level,
                        'module': log.module or 'system',
                        'message': log.message,
                        'details': log.details,
                        'category': 'System'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load system logs: %s", e)

            # Polling logs
            try:
                for log in PollHistory.query.order_by(PollHistory.timestamp.desc()).limit(logs_per_category).all():
                    all_logs.append({
                        'timestamp': log.timestamp,
                        'level': 'ERROR' if log.error_message else 'SUCCESS' if (log.status or '').lower() == 'success' else 'INFO',
                        'module': f"Alert Polling ({log.data_source or 'UNKNOWN'})",
                        'message': f"Status: {log.status} | Fetched: {log.alerts_fetched} | New: {log.alerts_new} | Updated: {log.alerts_updated}",
                        'details': {
                            'execution_time_ms': log.execution_time_ms,
                            'error': log.error_message,
                            'data_source': log.data_source,
                        },
                        'category': 'Polling'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load polling logs: %s", e)

            # Audio alerts
            try:
                for log in AudioAlert.query.order_by(AudioAlert.created_at.desc()).limit(logs_per_category).all():
                    all_logs.append({
                        'timestamp': log.created_at,
                        'level': log.alert_level.upper(),
                        'module': f'Audio Alert: {log.source_name}',
                        'message': log.message,
                        'details': {
                            'alert_type': log.alert_type,
                            'acknowledged': log.acknowledged,
                        },
                        'category': 'Audio'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load audio alerts: %s", e)

            # GPIO logs
            try:
                for log in GPIOActivationLog.query.order_by(GPIOActivationLog.activated_at.desc()).limit(logs_per_category).all():
                    all_logs.append({
                        'timestamp': log.activated_at,
                        'level': gpio_log_level(log),
                        'module': f'GPIO Pin {log.pin}',
                        'message': gpio_log_message(log),
                        'details': {
                            'pin': log.pin,
                            'activation_type': log.activation_type,
                            'success': log.success,
                            'error_message': log.error_message,
                        },
                        'category': 'GPIO'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load GPIO logs: %s", e)

            # EAS Messages (column-scoped: six audio blobs go unread here)
            try:
                eas_message_rows = (
                    EASMessage.query
                    .with_entities(
                        EASMessage.created_at,
                        EASMessage.same_header,
                        EASMessage.tts_provider,
                        EASMessage.audio_filename,
                    )
                    .order_by(EASMessage.created_at.desc())
                    .limit(logs_per_category)
                    .all()
                )
                for log in eas_message_rows:
                    all_logs.append({
                        'timestamp': log.created_at,
                        'level': 'INFO',
                        'module': 'EAS Message Generator',
                        'message': f"SAME: {log.same_header} | TTS: {log.tts_provider or 'None'}",
                        'details': {
                            'same_header': log.same_header,
                            'audio_filename': log.audio_filename,
                        },
                        'category': 'EAS Messages'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load EAS messages: %s", e)

            # Manual Activations (column-scoped: ten audio blobs go unread)
            try:
                manual_rows = (
                    ManualEASActivation.query
                    .with_entities(
                        ManualEASActivation.created_at,
                        ManualEASActivation.event_name,
                        ManualEASActivation.event_code,
                        ManualEASActivation.status,
                    )
                    .order_by(ManualEASActivation.created_at.desc())
                    .limit(logs_per_category)
                    .all()
                )
                for log in manual_rows:
                    all_logs.append({
                        'timestamp': log.created_at,
                        'level': 'WARNING' if log.status == 'ALERT' else 'INFO',
                        'module': 'Manual EAS Activation',
                        'message': f"Event: {log.event_name} ({log.event_code}) | Status: {log.status}",
                        'details': {
                            'event_code': log.event_code,
                            'status': log.status,
                        },
                        'category': 'Manual Activations'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load manual activations: %s", e)

            # Received EAS Alerts (column-scoped: skips the WAV capture)
            try:
                received_rows = (
                    ReceivedEASAlert.query
                    .with_entities(
                        ReceivedEASAlert.received_at,
                        ReceivedEASAlert.source_name,
                        ReceivedEASAlert.event_code,
                        ReceivedEASAlert.event_name,
                        ReceivedEASAlert.callsign,
                        ReceivedEASAlert.forwarding_decision,
                        ReceivedEASAlert.forwarding_reason,
                    )
                    .order_by(ReceivedEASAlert.received_at.desc())
                    .limit(logs_per_category)
                    .all()
                )
                for log in received_rows:
                    all_logs.append({
                        'timestamp': log.received_at,
                        'level': 'INFO' if log.forwarding_decision == 'forwarded'
                                 else 'WARNING' if log.forwarding_decision == 'ignored'
                                 else 'ERROR',
                        'module': f'Audio Monitor: {log.source_name}',
                        'message': (
                            f"Event: {log.event_code} ({log.event_name or 'Unknown'}) | "
                            f"Decision: {log.forwarding_decision} | "
                            f"Source: {log.callsign or log.source_name}"
                        ),
                        'details': {
                            'event_code': log.event_code,
                            'forwarding_decision': log.forwarding_decision,
                            'forwarding_reason': log.forwarding_reason,
                        },
                        'category': 'Received EAS'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load received EAS alerts: %s", e)

            # Polling Debug records
            try:
                for record in PollDebugRecord.query.order_by(PollDebugRecord.created_at.desc()).limit(logs_per_category).all():
                    identifier = record.alert_identifier or record.alert_event or 'Unknown alert'
                    if not record.parse_success:
                        level = 'ERROR'
                    elif record.is_relevant:
                        level = 'INFO'
                    else:
                        level = 'WARNING'
                    all_logs.append({
                        'timestamp': record.created_at,
                        'level': level,
                        'module': f"Polling Debug ({record.data_source or 'unknown'})",
                        'message': (
                            f"Run {record.poll_run_id}: {identifier} | "
                            f"Status {(record.poll_status or 'UNKNOWN').upper()} | "
                            f"Relevant: {'yes' if record.is_relevant else 'no'}"
                        ),
                        'details': {
                            'poll_run_id': record.poll_run_id,
                            'data_source': record.data_source,
                            'relevance_reason': record.relevance_reason,
                            'parse_error': record.parse_error,
                        },
                        'category': 'Polling Debug'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load polling debug records: %s", e)

            # Audio Metrics
            try:
                for log in AudioSourceMetrics.query.order_by(AudioSourceMetrics.timestamp.desc()).limit(logs_per_category).all():
                    all_logs.append({
                        'timestamp': log.timestamp,
                        'level': 'WARNING' if log.silence_detected or log.clipping_detected else 'INFO',
                        'module': f'Audio Metrics: {log.source_name}',
                        'message': (
                            f"Peak: {log.peak_level_db:.1f}dB | RMS: {log.rms_level_db:.1f}dB | "
                            f"SR: {log.sample_rate}Hz"
                        ),
                        'details': {
                            'source_type': log.source_type,
                            'silence': log.silence_detected,
                            'clipping': log.clipping_detected,
                        },
                        'category': 'Audio Metrics'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load audio metrics: %s", e)

            # Audio Health
            try:
                for log in AudioHealthStatus.query.order_by(AudioHealthStatus.timestamp.desc()).limit(logs_per_category).all():
                    all_logs.append({
                        'timestamp': log.timestamp,
                        'level': 'ERROR' if log.error_detected else 'WARNING' if not log.is_healthy else 'INFO',
                        'module': f'Audio Health: {log.source_name}',
                        'message': (
                            f"Health Score: {log.health_score:.1f}/100 | Active: {log.is_active} | "
                            f"Uptime: {log.uptime_seconds:.1f}s"
                        ),
                        'details': {
                            'healthy': log.is_healthy,
                            'silence_detected': log.silence_detected,
                        },
                        'category': 'Audio Health'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load audio health status: %s", e)

            # Decoded EAS Audio (column-scoped: seven audio blobs go unread)
            try:
                decoded_rows = (
                    EASDecodedAudio.query
                    .with_entities(
                        EASDecodedAudio.id,
                        EASDecodedAudio.created_at,
                        EASDecodedAudio.original_filename,
                        EASDecodedAudio.content_type,
                        EASDecodedAudio.same_headers,
                    )
                    .order_by(EASDecodedAudio.created_at.desc())
                    .limit(logs_per_category)
                    .all()
                )
                for log in decoded_rows:
                    all_logs.append({
                        'timestamp': log.created_at,
                        'level': 'INFO',
                        'module': 'EAS Audio Decoder',
                        'message': (
                            f"File: {log.original_filename or 'Unknown'} | "
                            f"SAME Headers: {len(log.same_headers or [])} | "
                            f"Type: {log.content_type or 'N/A'}"
                        ),
                        'details': {
                            'id': log.id,
                            'original_filename': log.original_filename,
                            'same_headers': log.same_headers or [],
                        },
                        'category': 'Decoded Audio'
                    })
            except Exception as e:
                db.session.rollback()
                route_logger.warning("Failed to load decoded EAS audio: %s", e)

            # Service Logs (systemd) - fetch recent logs without date restriction
            try:
                services = get_all_log_services()
                lines_per_service = max(3, logs_per_category // len(services)) if services else 10
                for service in services:
                    result = get_systemd_logs(service, lines=lines_per_service, priority=None, since=None)
                    if result.get('success') and result.get('logs'):
                        for log_entry in result['logs']:
                            all_logs.append({
                                'timestamp': datetime.fromtimestamp(int(log_entry['timestamp']) / 1000000) if log_entry.get('timestamp') else None,
                                'level': 'ERROR' if log_entry.get('priority', '6') in ['0', '1', '2', '3'] else 'WARNING' if log_entry.get('priority') == '4' else 'INFO',
                                'module': log_entry.get('unit', service),
                                'message': log_entry.get('message', ''),
                                'details': {'service': service},
                                'category': 'Services'
                            })
            except Exception as e:
                route_logger.warning("Failed to load service logs: %s", e)

            # Sort all logs by timestamp (handle both timezone-aware and naive datetimes)
            def get_sort_key(log_entry):
                ts = log_entry.get('timestamp')
                if ts is None:
                    return datetime.min.replace(tzinfo=None)
                # Strip timezone info for consistent comparison
                if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                    return ts.replace(tzinfo=None)
                return ts

            all_logs.sort(key=get_sort_key, reverse=True)
            logs_data = all_logs[:limit]

        elif log_type == 'system':
            log_type_name = "System Logs"
            logs_result = (
                SystemLog.query
                .order_by(SystemLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': log.level,
                    'module': log.module or 'system',
                    'message': log.message,
                    'alert_identifier': log.alert_identifier,
                    'details': log.details,
                }
                for log in logs_result
            ]

        elif log_type == 'polling':
            log_type_name = "CAP Polling Logs"
            logs_result = (
                PollHistory.query
                .order_by(PollHistory.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = []
            for log in logs_result:
                # Merge basic info with detailed info from JSON field
                details = {
                    'execution_time_ms': log.execution_time_ms,
                    'error': log.error_message,
                    'data_source': log.data_source,
                    'alerts_fetched': log.alerts_fetched,
                    'alerts_new': log.alerts_new,
                    'alerts_updated': log.alerts_updated,
                }
                # Add endpoint/config details if available
                if log.details:
                    details.update(log.details)

                # Build more informative message
                msg_parts = [f"Status: {log.status}"]
                msg_parts.append(f"Fetched: {log.alerts_fetched}")
                if log.details:
                    accepted = log.details.get('alerts_accepted', 0)
                    filtered = log.details.get('alerts_filtered', 0)
                    msg_parts.append(f"Accepted: {accepted}")
                    msg_parts.append(f"Filtered: {filtered}")
                msg_parts.append(f"New: {log.alerts_new}")
                msg_parts.append(f"Updated: {log.alerts_updated}")

                logs_data.append({
                    'timestamp': log.timestamp,
                    'level': 'ERROR'
                    if log.error_message
                    else 'SUCCESS'
                    if (log.status or '').lower() == 'success'
                    else 'INFO',
                    'module': f"Alert Polling ({log.data_source or 'UNKNOWN'})",
                    'message': ' | '.join(msg_parts),
                    'details': details,
                })

        elif log_type == 'polling_debug':
            log_type_name = "Polling Debug Logs"
            logs_result = (
                PollDebugRecord.query
                .order_by(PollDebugRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            for record in logs_result:
                status_value = (record.poll_status or 'UNKNOWN').upper()
                identifier = record.alert_identifier or record.alert_event or 'Unknown alert'
                if not record.parse_success:
                    level = 'ERROR'
                elif record.is_relevant:
                    level = 'INFO'
                else:
                    level = 'WARNING'
                message = (
                    f"Run {record.poll_run_id}: {identifier} | Status {status_value} | "
                    f"Relevant: {'yes' if record.is_relevant else 'no'} | Saved: {'yes' if record.was_saved else 'no'}"
                )
                logs_data.append(
                    {
                        'timestamp': record.created_at,
                        'level': level,
                        'module': f"Polling Debug ({record.data_source or 'unknown'})",
                        'message': message,
                        'details': {
                            'poll_run_id': record.poll_run_id,
                            'poll_status': record.poll_status,
                            'data_source': record.data_source,
                            'alert_identifier': record.alert_identifier,
                            'alert_event': record.alert_event,
                            'alert_sent': record.alert_sent.isoformat()
                            if record.alert_sent
                            else None,
                            'created_at': record.created_at.isoformat()
                            if record.created_at
                            else None,
                            'is_relevant': record.is_relevant,
                            'relevance_reason': record.relevance_reason,
                            'relevance_matches': record.relevance_matches or [],
                            'ugc_codes': record.ugc_codes or [],
                            'area_desc': record.area_desc,
                            'was_saved': record.was_saved,
                            'was_new': record.was_new,
                            'alert_db_id': record.alert_db_id,
                            'parse_success': record.parse_success,
                            'parse_error': record.parse_error,
                            'polygon_count': record.polygon_count,
                            'geometry_type': record.geometry_type,
                            'raw_xml_present': record.raw_xml_present,
                            'notes': record.notes,
                        },
                    }
                )

        elif log_type == 'audio':
            log_type_name = "Audio System Logs"
            logs_result = (
                AudioAlert.query
                .order_by(AudioAlert.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': log.alert_level.upper(),
                    'module': f'Audio Alert: {log.source_name}',
                    'message': log.message,
                    'alert_identifier': log.alert_identifier,
                    'details': {
                        'alert_type': log.alert_type,
                        'acknowledged': log.acknowledged,
                        'resolved': log.resolved,
                        'created_at': log.created_at.isoformat() if log.created_at else None,
                        'updated_at': log.updated_at.isoformat() if log.updated_at else None,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'audio_metrics':
            log_type_name = "Audio Metrics Logs"
            logs_result = (
                AudioSourceMetrics.query
                .order_by(AudioSourceMetrics.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': 'WARNING'
                    if log.silence_detected or log.clipping_detected
                    else 'INFO',
                    'module': f'Audio Metrics: {log.source_name}',
                    'message': (
                        f"Peak: {log.peak_level_db:.1f}dB | RMS: {log.rms_level_db:.1f}dB | "
                        f"SR: {log.sample_rate}Hz"
                    ),
                    'details': {
                        'source_type': log.source_type,
                        'channels': log.channels,
                        'frames': log.frames_captured,
                        'silence': log.silence_detected,
                        'clipping': log.clipping_detected,
                        'buffer_utilization': log.buffer_utilization,
                        'stream_info': log.source_metadata,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'audio_health':
            log_type_name = "Audio Health Logs"
            logs_result = (
                AudioHealthStatus.query
                .order_by(AudioHealthStatus.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': 'ERROR'
                    if log.error_detected
                    else 'WARNING'
                    if not log.is_healthy
                    else 'INFO',
                    'module': f'Audio Health: {log.source_name}',
                    'message': (
                        f"Health Score: {log.health_score:.1f}/100 | Active: {log.is_active} | "
                        f"Uptime: {log.uptime_seconds:.1f}s"
                    ),
                    'details': {
                        'healthy': log.is_healthy,
                        'silence_detected': log.silence_detected,
                        'silence_duration': log.silence_duration_seconds,
                        'time_since_signal': log.time_since_last_signal_seconds,
                        'trend': (
                            f"{log.level_trend} ({log.trend_value_db:.1f}dB)"
                            if log.level_trend
                            else None
                        ),
                        'metadata': log.health_metadata,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'gpio':
            log_type_name = "GPIO Activation Logs"
            logs_result = (
                GPIOActivationLog.query
                .order_by(GPIOActivationLog.activated_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.activated_at,
                    'level': gpio_log_level(log),
                    'module': f'GPIO Pin {log.pin}',
                    'message': gpio_log_message(log),
                    # GPIOActivationLog uses the legacy ``alert_id`` field
                    # but the UI shows it under the canonical name.
                    'alert_identifier': log.alert_id,
                    'details': {
                        'pin': log.pin,
                        'activation_type': log.activation_type,
                        'activated_at': log.activated_at.isoformat()
                        if log.activated_at
                        else None,
                        'deactivated_at': log.deactivated_at.isoformat()
                        if log.deactivated_at
                        else None,
                        'duration': log.duration_seconds,
                        'alert_id': log.alert_id,
                        'reason': log.reason,
                        'success': log.success,
                        'error_message': log.error_message,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'eas_messages':
            log_type_name = "EAS Messages Generated"
            # Column-scoped: EASMessage carries six LargeBinary audio blobs
            # and this view only needs to know whether each is populated.
            # Ask the database for the NULL test instead of transferring the
            # audio — loading the blobs to evaluate ``is not None`` cost
            # ~1.8 GB of resident memory for 100 rows.
            logs_result = (
                EASMessage.query
                .with_entities(
                    EASMessage.id,
                    EASMessage.created_at,
                    EASMessage.cap_alert_id,
                    EASMessage.alert_identifier,
                    EASMessage.same_header,
                    EASMessage.audio_filename,
                    EASMessage.text_filename,
                    EASMessage.tts_provider,
                    EASMessage.tts_warning,
                    EASMessage.text_payload,
                    EASMessage.metadata_payload,
                    EASMessage.audio_data.isnot(None).label('has_audio_data'),
                    EASMessage.eom_audio_data.isnot(None).label('has_eom_audio'),
                    EASMessage.same_audio_data.isnot(None).label('has_same_audio'),
                    EASMessage.attention_audio_data.isnot(None).label('has_attention_audio'),
                    EASMessage.tts_audio_data.isnot(None).label('has_tts_audio'),
                )
                .order_by(EASMessage.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': 'INFO',
                    'module': 'EAS Message Generator',
                    'message': (
                        f"SAME: {log.same_header} | "
                        f"TTS Provider: {log.tts_provider or 'None'} | "
                        f"Audio: {log.audio_filename}"
                    ),
                    'alert_identifier': log.alert_identifier,
                    'details': {
                        'id': log.id,
                        'cap_alert_id': log.cap_alert_id,
                        'alert_identifier': log.alert_identifier,
                        'same_header': log.same_header,
                        'audio_filename': log.audio_filename,
                        'text_filename': log.text_filename,
                        'has_audio_data': log.has_audio_data,
                        'has_eom_audio': log.has_eom_audio,
                        'has_same_audio': log.has_same_audio,
                        'has_attention_audio': log.has_attention_audio,
                        'has_tts_audio': log.has_tts_audio,
                        'tts_provider': log.tts_provider,
                        'tts_warning': log.tts_warning,
                        'text_payload': log.text_payload,
                        'metadata': log.metadata_payload,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'decoded_audio':
            log_type_name = "Decoded EAS Audio"
            # EASDecodedAudio carries seven LargeBinary segments (header,
            # attention tone, narration, EOM, buffer, composite, and the
            # deprecated message blob).  This view only reports which are
            # present, so the NULL tests run in SQL.
            logs_result = (
                EASDecodedAudio.query
                .with_entities(
                    EASDecodedAudio.id,
                    EASDecodedAudio.created_at,
                    EASDecodedAudio.original_filename,
                    EASDecodedAudio.content_type,
                    EASDecodedAudio.raw_text,
                    EASDecodedAudio.same_headers,
                    EASDecodedAudio.quality_metrics,
                    EASDecodedAudio.segment_metadata,
                    EASDecodedAudio.header_audio_data.isnot(None).label('has_header_audio'),
                    EASDecodedAudio.attention_tone_audio_data.isnot(None).label('has_attention_tone'),
                    EASDecodedAudio.narration_audio_data.isnot(None).label('has_narration'),
                    EASDecodedAudio.eom_audio_data.isnot(None).label('has_eom_audio'),
                    EASDecodedAudio.composite_audio_data.isnot(None).label('has_composite'),
                )
                .order_by(EASDecodedAudio.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': 'INFO',
                    'module': 'EAS Audio Decoder',
                    'message': (
                        f"File: {log.original_filename or 'Unknown'} | "
                        f"SAME Headers: {len(log.same_headers or [])} | "
                        f"Type: {log.content_type or 'N/A'}"
                    ),
                    'details': {
                        'id': log.id,
                        'original_filename': log.original_filename,
                        'content_type': log.content_type,
                        'raw_text': log.raw_text,
                        'same_headers': log.same_headers or [],
                        'quality_metrics': log.quality_metrics or {},
                        'segment_metadata': log.segment_metadata or {},
                        'has_header_audio': log.has_header_audio,
                        'has_attention_tone': log.has_attention_tone,
                        'has_narration': log.has_narration,
                        'has_eom_audio': log.has_eom_audio,
                        'has_composite': log.has_composite,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'manual_activations':
            log_type_name = "Manual EAS Activations"
            # ManualEASActivation carries ten LargeBinary audio columns and
            # this view reads none of them — not even to test for NULL.
            logs_result = (
                ManualEASActivation.query
                .with_entities(
                    ManualEASActivation.id,
                    ManualEASActivation.created_at,
                    ManualEASActivation.identifier,
                    ManualEASActivation.event_code,
                    ManualEASActivation.event_name,
                    ManualEASActivation.status,
                    ManualEASActivation.message_type,
                    ManualEASActivation.same_header,
                    ManualEASActivation.same_locations,
                    ManualEASActivation.tone_profile,
                    ManualEASActivation.tone_seconds,
                    ManualEASActivation.includes_tts,
                    ManualEASActivation.tts_warning,
                    ManualEASActivation.sent_at,
                    ManualEASActivation.expires_at,
                    ManualEASActivation.headline,
                    ManualEASActivation.message_text,
                    ManualEASActivation.instruction_text,
                    ManualEASActivation.duration_minutes,
                    ManualEASActivation.storage_path,
                    ManualEASActivation.archived_at,
                )
                .order_by(ManualEASActivation.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': 'WARNING' if log.status == 'ALERT' else 'INFO',
                    'module': 'Manual EAS Activation',
                    'message': (
                        f"Event: {log.event_name} ({log.event_code}) | "
                        f"Status: {log.status} | "
                        f"Type: {log.message_type}"
                    ),
                    'details': {
                        'id': log.id,
                        'identifier': log.identifier,
                        'event_code': log.event_code,
                        'event_name': log.event_name,
                        'status': log.status,
                        'message_type': log.message_type,
                        'same_header': log.same_header,
                        'same_locations': log.same_locations or [],
                        'tone_profile': log.tone_profile,
                        'tone_seconds': log.tone_seconds,
                        'includes_tts': log.includes_tts,
                        'tts_warning': log.tts_warning,
                        'sent_at': log.sent_at.isoformat() if log.sent_at else None,
                        'expires_at': log.expires_at.isoformat() if log.expires_at else None,
                        'headline': log.headline,
                        'message_text': log.message_text,
                        'instruction_text': log.instruction_text,
                        'duration_minutes': log.duration_minutes,
                        'storage_path': log.storage_path,
                        'archived_at': log.archived_at.isoformat() if log.archived_at else None,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'received_alerts':
            log_type_name = "Received EAS Alerts"
            # Skip raw_audio_data (the WAV capture) and full_alert_data
            # (JSONB); neither is displayed in this list view.
            logs_result = (
                ReceivedEASAlert.query
                .with_entities(
                    ReceivedEASAlert.id,
                    ReceivedEASAlert.received_at,
                    ReceivedEASAlert.source_name,
                    ReceivedEASAlert.raw_same_header,
                    ReceivedEASAlert.event_code,
                    ReceivedEASAlert.event_name,
                    ReceivedEASAlert.originator_code,
                    ReceivedEASAlert.originator_name,
                    ReceivedEASAlert.fips_codes,
                    ReceivedEASAlert.forwarding_decision,
                    ReceivedEASAlert.forwarding_reason,
                    ReceivedEASAlert.matched_fips_codes,
                    ReceivedEASAlert.decode_confidence,
                    ReceivedEASAlert.generated_message_id,
                    ReceivedEASAlert.callsign,
                )
                .order_by(ReceivedEASAlert.received_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.received_at,
                    'level': 'INFO' if log.forwarding_decision == 'forwarded'
                             else 'WARNING' if log.forwarding_decision == 'ignored'
                             else 'ERROR',
                    'module': f'Audio Monitor: {log.source_name}',
                    'message': (
                        f"Event: {log.event_code} ({log.event_name or 'Unknown'}) | "
                        f"Decision: {log.forwarding_decision} | "
                        f"Source: {log.callsign or log.source_name}"
                    ),
                    'details': {
                        'id': log.id,
                        'source_name': log.source_name,
                        'raw_same_header': log.raw_same_header,
                        'event_code': log.event_code,
                        'event_name': log.event_name,
                        'originator_code': log.originator_code,
                        'originator_name': log.originator_name,
                        'fips_codes': log.fips_codes or [],
                        'forwarding_decision': log.forwarding_decision,
                        'forwarding_reason': log.forwarding_reason,
                        'matched_fips_codes': log.matched_fips_codes or [],
                        'decode_confidence': log.decode_confidence,
                        'generated_message_id': log.generated_message_id,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'audit':
            log_type_name = "Audit Log"
            from app_core.auth.audit import AuditLog
            audit_query = AuditLog.query
            # Optional action filter (e.g. config.updated) applied at the DB
            # level so the newest matching rows survive the limit window.
            if action_filter:
                audit_query = audit_query.filter(AuditLog.action == action_filter)
            logs_result = (
                audit_query
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': 'INFO' if log.success else 'WARNING',
                    'module': f"audit:{log.action}",
                    'message': (
                        f"{log.action}"
                        + (f" by {log.username}" if log.username else " (anonymous)")
                        + (f" on {log.resource_type}#{log.resource_id}"
                           if log.resource_type and log.resource_id else "")
                        + ("" if log.success else " — FAILED")
                    ),
                    'alert_identifier': None,  # AuditLog isn't alert-keyed
                    'details': {
                        'action': log.action,
                        'success': log.success,
                        'username': log.username,
                        'user_id': log.user_id,
                        'resource_type': log.resource_type,
                        'resource_id': log.resource_id,
                        'ip_address': log.ip_address,
                        'user_agent': log.user_agent,
                        'details': log.details,
                        # Tamper-evidence chain fields (see
                        # docs/security/AUDIT_LOG_INTEGRITY.md).  Surfacing
                        # all three lets an operator cross-check a single
                        # row against an exported copy or the verify API.
                        'prev_hash': log.prev_hash,
                        'entry_hash': log.entry_hash,
                        'signature': log.signature,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'compliance':
            log_type_name = "Compliance Log"
            # Pull the unified compliance entries (CAPAlert received +
            # EASMessage relayed + ManualEASActivation), defaulting to the
            # last 30 days so the page is useful out of the box.
            from app_core.eas_storage import collect_compliance_log_entries
            try:
                entries, _, _ = collect_compliance_log_entries(window_days=30)
            except Exception as exc:
                route_logger.error("compliance log query failed: %s", exc)
                entries = []
            logs_data = []
            for entry in entries[:limit]:
                category = entry.get('category', 'unknown')
                level = (
                    'INFO' if category == 'received'
                    else 'SUCCESS' if category == 'relayed'
                    else 'WARNING' if category == 'manual'
                    else 'SECONDARY'
                )
                logs_data.append({
                    'timestamp': entry.get('timestamp'),
                    'level': level,
                    'module': f"compliance:{category}",
                    'message': (
                        f"{(entry.get('event_label') or 'Unknown event')} "
                        f"— {entry.get('status') or 'no status'}"
                    ),
                    'alert_identifier': entry.get('identifier'),
                    'details': entry.get('details') or {},
                })

        elif log_type.startswith('report_'):
            # FCC-shaped report rendered inline on /logs.  Each row is also
            # mirrored into ``logs_data`` so the page's search/level/date
            # filters and the generic CSV exporter keep working — but the
            # template renders the proper columnar layout from
            # ``report_meta`` instead of cramming every column into the
            # generic ``message`` cell (which was unreadable on mobile).
            #
            # The rich PDF/CSV exports still go through
            # /admin/compliance/report/<kind>.<fmt> which keeps the
            # report-specific column layout.
            from app_core.eas_storage import REPORT_BUILDERS, resolve_report_window
            report_kind = log_type[len('report_'):]
            builder = REPORT_BUILDERS.get(report_kind)
            if builder is None:
                log_type_name = "Unknown report"
                logs_data = []
            else:
                titles = {
                    'received': 'Received Alerts (FCC report)',
                    'forwarded': 'Forwarded Alerts (FCC report)',
                    'ignored': 'Ignored Alerts (FCC report)',
                    'initiated': 'Initiated Alerts (FCC report)',
                    'weekly': 'Weekly Summary (FCC report)',
                    'monthly': 'Monthly Summary (FCC report)',
                }
                log_type_name = titles.get(report_kind, f"Report: {report_kind}")
                try:
                    window_start, window_end = resolve_report_window(days=30)
                    report = builder(window_start=window_start, window_end=window_end)
                except Exception as exc:
                    route_logger.error("report builder %s failed: %s", report_kind, exc)
                    # If a query inside the builder raised, the SQLAlchemy
                    # session/connection is left in an aborted-transaction
                    # state.  Without a rollback every subsequent query on
                    # this connection (including the per-request auth
                    # permission check) hits InFailedSqlTransaction.
                    try:
                        from app_core.extensions import db as _db
                        _db.session.rollback()
                    except Exception:  # pragma: no cover - defensive
                        route_logger.exception("rollback after report builder failure failed")
                    report = {
                        "columns": [],
                        "rows": [],
                        "summary_lines": [],
                        "window_start": None,
                        "window_end": None,
                    }
                column_labels = [c.get("label", "") for c in report.get("columns", [])]
                for row in report.get("rows", [])[:limit]:
                    cells = [str(c) if c is not None else "" for c in row]
                    # Keep a readable fallback ``message`` for search matching
                    # and the generic CSV export, but the template prefers
                    # ``details`` (label→value) when ``report`` is set.
                    pairs = " · ".join(
                        f"{label}: {value}" for label, value in zip(column_labels, cells) if value
                    )
                    # Use first column (typically timestamp) as the row's
                    # display timestamp where possible.
                    ts = None
                    if cells:
                        try:
                            from datetime import datetime as _dt
                            # The report builder formats timestamps as
                            # local strings — try to recover ISO portion.
                            first = cells[0]
                            ts = _dt.fromisoformat(first.split(' / ')[-1].split(' UTC')[0])
                        except Exception:
                            ts = None
                    logs_data.append({
                        'timestamp': ts,
                        'level': 'INFO',
                        'module': f"report:{report_kind}",
                        'message': pairs or " · ".join(cells),
                        'alert_identifier': None,
                        'details': dict(zip(column_labels, cells)),
                    })

                report_meta = {
                    'kind': report_kind,
                    'title': report.get('title') or log_type_name,
                    'subtitle': report.get('subtitle'),
                    'columns': column_labels,
                    'summary_lines': list(report.get('summary_lines') or []),
                    'window_start': report.get('window_start'),
                    'window_end': report.get('window_end'),
                    'row_count': report.get('row_count', len(logs_data)),
                }

        elif log_type == 'services':
            log_type_name = "Service Logs (systemd)"
            # Fetch systemd journal logs for EAS Station services
            logs_data = []

            # If a specific service is selected, only fetch from that service
            if service_filter and service_filter in get_all_log_services():
                services_to_fetch = [service_filter]
                lines_per_service = limit
            else:
                services_to_fetch = get_all_log_services()
                lines_per_service = max(5, limit // len(services_to_fetch)) if services_to_fetch else limit

            for service in services_to_fetch:
                # Don't restrict to 'today' - fetch recent logs regardless of date
                result = get_systemd_logs(service, lines=lines_per_service, priority=None, since=None)
                if result.get('success') and result.get('logs'):
                    for log_entry in result['logs']:
                        logs_data.append({
                            'timestamp': datetime.fromtimestamp(int(log_entry['timestamp']) / 1000000) if log_entry.get('timestamp') else None,
                            'level': 'ERROR' if log_entry.get('priority', '6') in ['0', '1', '2', '3'] else 'WARNING' if log_entry.get('priority') == '4' else 'INFO',
                            'module': log_entry.get('unit', service),
                            'message': log_entry.get('message', ''),
                            'details': {'service': service, 'priority': log_entry.get('priority')},
                        })
                elif not result.get('success'):
                    # Log the error but continue with other services
                    route_logger.debug("Failed to fetch logs for %s: %s", service, result.get('error', 'Unknown error'))

            # Sort by timestamp (handle both timezone-aware and naive datetimes)
            def get_sort_key(log_entry):
                ts = log_entry.get('timestamp')
                if ts is None:
                    return datetime.min.replace(tzinfo=None)
                if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                    return ts.replace(tzinfo=None)
                return ts

            logs_data.sort(key=get_sort_key, reverse=True)
            logs_data = logs_data[:limit]

        return log_type_name, logs_data, report_meta

    return _load_logs_data


__all__ = ["build_logs_loader"]
