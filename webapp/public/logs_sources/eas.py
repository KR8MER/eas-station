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

"""The EAS message categories on /logs.

Every table here carries LargeBinary audio columns that this list view must not
transfer. Each loader is therefore **column-scoped** — it names the columns it
wants with ``with_entities`` and pushes any "is there audio?" test down into SQL
as ``isnot(None)``. Loading the blobs just to evaluate ``is not None`` cost
~1.8 GB of resident memory for 100 EASMessage rows, which is why these queries
look the way they do. Do not replace them with a plain ``Model.query``.
"""

from app_core.models import (
    EASDecodedAudio,
    EASMessage,
    ManualEASActivation,
    ReceivedEASAlert,
)

from .common import LogPage, LogQuery


def load_eas_messages(query: LogQuery) -> LogPage:
    """Generated EAS messages, reporting which audio segments exist."""
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
        .limit(query.limit)
        .all()
    )
    return LogPage("EAS Messages Generated", [
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
    ])


def load_decoded_audio(query: LogQuery) -> LogPage:
    """Uploaded audio that the SAME decoder has processed."""
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
        .limit(query.limit)
        .all()
    )
    return LogPage("Decoded EAS Audio", [
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
    ])


def load_manual_activations(query: LogQuery) -> LogPage:
    """Alerts an operator originated from this station."""
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
        .limit(query.limit)
        .all()
    )
    return LogPage("Manual EAS Activations", [
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
    ])


def load_received_alerts(query: LogQuery) -> LogPage:
    """Alerts decoded off a monitored audio source, with the relay decision."""
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
        .limit(query.limit)
        .all()
    )
    return LogPage("Received EAS Alerts", [
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
    ])


LOADERS = {
    'eas_messages': load_eas_messages,
    'decoded_audio': load_decoded_audio,
    'manual_activations': load_manual_activations,
    'received_alerts': load_received_alerts,
}

__all__ = [
    "LOADERS",
    "load_decoded_audio",
    "load_eas_messages",
    "load_manual_activations",
    "load_received_alerts",
]
