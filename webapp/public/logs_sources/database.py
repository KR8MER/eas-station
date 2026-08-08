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

"""The plain database-backed /logs categories.

One loader per table, each reading the newest ``limit`` rows and shaping them
into the generic log dict the template renders. The ``level`` is derived by a
different rule in every one of these — that derivation is the only real logic
here, and each rule is pinned by ``tests/test_public_logs_data.py``.
"""

from app_core.models import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    GPIOActivationLog,
    PollDebugRecord,
    PollHistory,
    SystemLog,
)
from app_utils.gpio_logs import gpio_log_level, gpio_log_message

from .common import LogPage, LogQuery


def load_system(query: LogQuery) -> LogPage:
    """Application log rows written through the SystemLog model."""
    logs_result = (
        SystemLog.query
        .order_by(SystemLog.timestamp.desc())
        .limit(query.limit)
        .all()
    )
    return LogPage("System Logs", [
        {
            'timestamp': log.timestamp,
            'level': log.level,
            'module': log.module or 'system',
            'message': log.message,
            'alert_identifier': log.alert_identifier,
            'details': log.details,
        }
        for log in logs_result
    ])


def load_polling(query: LogQuery) -> LogPage:
    """CAP poll runs, with the per-run counters folded into the message."""
    logs_result = (
        PollHistory.query
        .order_by(PollHistory.timestamp.desc())
        .limit(query.limit)
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

    return LogPage("CAP Polling Logs", logs_data)


def load_polling_debug(query: LogQuery) -> LogPage:
    """Per-alert poller decisions — why each alert was kept or dropped."""
    logs_result = (
        PollDebugRecord.query
        .order_by(PollDebugRecord.created_at.desc())
        .limit(query.limit)
        .all()
    )
    logs_data = []
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

    return LogPage("Polling Debug Logs", logs_data)


def load_audio(query: LogQuery) -> LogPage:
    """Audio-subsystem alerts (silence, clipping, disconnects)."""
    logs_result = (
        AudioAlert.query
        .order_by(AudioAlert.created_at.desc())
        .limit(query.limit)
        .all()
    )
    return LogPage("Audio System Logs", [
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
    ])


def load_audio_metrics(query: LogQuery) -> LogPage:
    """Per-source level measurements sampled by the audio service."""
    logs_result = (
        AudioSourceMetrics.query
        .order_by(AudioSourceMetrics.timestamp.desc())
        .limit(query.limit)
        .all()
    )
    return LogPage("Audio Metrics Logs", [
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
    ])


def load_audio_health(query: LogQuery) -> LogPage:
    """Rolled-up health scores per audio source."""
    logs_result = (
        AudioHealthStatus.query
        .order_by(AudioHealthStatus.timestamp.desc())
        .limit(query.limit)
        .all()
    )
    return LogPage("Audio Health Logs", [
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
    ])


def load_gpio(query: LogQuery) -> LogPage:
    """Relay/GPIO activations, including the ones that failed."""
    logs_result = (
        GPIOActivationLog.query
        .order_by(GPIOActivationLog.activated_at.desc())
        .limit(query.limit)
        .all()
    )
    return LogPage("GPIO Activation Logs", [
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
    ])


LOADERS = {
    'system': load_system,
    'polling': load_polling,
    'polling_debug': load_polling_debug,
    'audio': load_audio,
    'audio_metrics': load_audio_metrics,
    'audio_health': load_audio_health,
    'gpio': load_gpio,
}

__all__ = [
    "LOADERS",
    "load_audio",
    "load_audio_health",
    "load_audio_metrics",
    "load_gpio",
    "load_polling",
    "load_polling_debug",
    "load_system",
]
