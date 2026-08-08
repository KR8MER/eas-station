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

"""One collector per category feeding the "All Logs" timeline.

Each takes a per-category row cap and returns rows already shaped for the
merged view — meaning every row carries a ``category`` label and a trimmed
``details`` payload. That shape is deliberately **not** the one the focused
per-category loaders produce, so these are not thin wrappers around
``database.py`` / ``eas.py`` and must not be replaced by them.

Collectors raise on failure; ``aggregate.load_all`` is what decides that a
failing category is skipped rather than fatal.
"""

from typing import Any, Callable, Dict, List, Tuple

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

Collector = Callable[[int], List[Dict[str, Any]]]


def _collect_system(cap: int) -> List[Dict[str, Any]]:
    return [
        {
            'timestamp': log.timestamp,
            'level': log.level,
            'module': log.module or 'system',
            'message': log.message,
            'details': log.details,
            'category': 'System'
        }
        for log in SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(cap).all()
    ]


def _collect_polling(cap: int) -> List[Dict[str, Any]]:
    return [
        {
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
        }
        for log in PollHistory.query.order_by(PollHistory.timestamp.desc()).limit(cap).all()
    ]


def _collect_audio_alerts(cap: int) -> List[Dict[str, Any]]:
    return [
        {
            'timestamp': log.created_at,
            'level': log.alert_level.upper(),
            'module': f'Audio Alert: {log.source_name}',
            'message': log.message,
            'details': {
                'alert_type': log.alert_type,
                'acknowledged': log.acknowledged,
            },
            'category': 'Audio'
        }
        for log in AudioAlert.query.order_by(AudioAlert.created_at.desc()).limit(cap).all()
    ]


def _collect_gpio(cap: int) -> List[Dict[str, Any]]:
    return [
        {
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
        }
        for log in GPIOActivationLog.query.order_by(GPIOActivationLog.activated_at.desc()).limit(cap).all()
    ]


def _collect_eas_messages(cap: int) -> List[Dict[str, Any]]:
    # Column-scoped: six audio blobs go unread here.
    eas_message_rows = (
        EASMessage.query
        .with_entities(
            EASMessage.created_at,
            EASMessage.same_header,
            EASMessage.tts_provider,
            EASMessage.audio_filename,
        )
        .order_by(EASMessage.created_at.desc())
        .limit(cap)
        .all()
    )
    return [
        {
            'timestamp': log.created_at,
            'level': 'INFO',
            'module': 'EAS Message Generator',
            'message': f"SAME: {log.same_header} | TTS: {log.tts_provider or 'None'}",
            'details': {
                'same_header': log.same_header,
                'audio_filename': log.audio_filename,
            },
            'category': 'EAS Messages'
        }
        for log in eas_message_rows
    ]


def _collect_manual_activations(cap: int) -> List[Dict[str, Any]]:
    # Column-scoped: ten audio blobs go unread.
    manual_rows = (
        ManualEASActivation.query
        .with_entities(
            ManualEASActivation.created_at,
            ManualEASActivation.event_name,
            ManualEASActivation.event_code,
            ManualEASActivation.status,
        )
        .order_by(ManualEASActivation.created_at.desc())
        .limit(cap)
        .all()
    )
    return [
        {
            'timestamp': log.created_at,
            'level': 'WARNING' if log.status == 'ALERT' else 'INFO',
            'module': 'Manual EAS Activation',
            'message': f"Event: {log.event_name} ({log.event_code}) | Status: {log.status}",
            'details': {
                'event_code': log.event_code,
                'status': log.status,
            },
            'category': 'Manual Activations'
        }
        for log in manual_rows
    ]


def _collect_received_alerts(cap: int) -> List[Dict[str, Any]]:
    # Column-scoped: skips the WAV capture.
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
        .limit(cap)
        .all()
    )
    return [
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
                'event_code': log.event_code,
                'forwarding_decision': log.forwarding_decision,
                'forwarding_reason': log.forwarding_reason,
            },
            'category': 'Received EAS'
        }
        for log in received_rows
    ]


def _collect_polling_debug(cap: int) -> List[Dict[str, Any]]:
    rows = []
    for record in PollDebugRecord.query.order_by(PollDebugRecord.created_at.desc()).limit(cap).all():
        identifier = record.alert_identifier or record.alert_event or 'Unknown alert'
        if not record.parse_success:
            level = 'ERROR'
        elif record.is_relevant:
            level = 'INFO'
        else:
            level = 'WARNING'
        rows.append({
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
    return rows


def _collect_audio_metrics(cap: int) -> List[Dict[str, Any]]:
    return [
        {
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
        }
        for log in AudioSourceMetrics.query.order_by(AudioSourceMetrics.timestamp.desc()).limit(cap).all()
    ]


def _collect_audio_health(cap: int) -> List[Dict[str, Any]]:
    return [
        {
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
        }
        for log in AudioHealthStatus.query.order_by(AudioHealthStatus.timestamp.desc()).limit(cap).all()
    ]


def _collect_decoded_audio(cap: int) -> List[Dict[str, Any]]:
    # Column-scoped: seven audio blobs go unread.
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
        .limit(cap)
        .all()
    )
    return [
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
                'same_headers': log.same_headers or [],
            },
            'category': 'Decoded Audio'
        }
        for log in decoded_rows
    ]


# (collector, message used when it raises). The order is the order rows are
# appended in before the merge sort, and matches the original view.
COLLECTORS: Tuple[Tuple[Collector, str], ...] = (
    (_collect_system, "Failed to load system logs: %s"),
    (_collect_polling, "Failed to load polling logs: %s"),
    (_collect_audio_alerts, "Failed to load audio alerts: %s"),
    (_collect_gpio, "Failed to load GPIO logs: %s"),
    (_collect_eas_messages, "Failed to load EAS messages: %s"),
    (_collect_manual_activations, "Failed to load manual activations: %s"),
    (_collect_received_alerts, "Failed to load received EAS alerts: %s"),
    (_collect_polling_debug, "Failed to load polling debug records: %s"),
    (_collect_audio_metrics, "Failed to load audio metrics: %s"),
    (_collect_audio_health, "Failed to load audio health status: %s"),
    (_collect_decoded_audio, "Failed to load decoded EAS audio: %s"),
)


__all__ = ["COLLECTORS", "Collector"]
