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

"""
EAS Alert Processing and Forwarding

Handles processing of received EAS alerts that match configured FIPS codes.
Generates EAS messages, triggers notifications, and manages alert lifecycle.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def process_eas_alert(alert) -> Optional[Dict[str, Any]]:
    """
    Process a received EAS alert that matched configured FIPS codes.

    This function is the standalone entry point for the full alert processing
    pipeline. It can be called directly with either a decoded alert dict or an
    EASAlert-like object.

    The pipeline:
    1. Normalize input to a dict (handles both dict and object inputs)
    2. Load EAS config and location settings from the database
    3. Run cross-source deduplication (prevents double-broadcast)
    4. Generate SAME audio (3x FSK header + attention tone + TTS narration + EOM)
    5. Create EASMessage database record with all audio segments
    6. Publish audio to BroadcastQueue (Icecast + monitoring subscribers)
    7. Activate GPIO relay (forwarding mode transmitter key)
    8. Send email/SMS notifications
    9. Return result dict with message_id for audit trail linking

    Args:
        alert: Alert dict or EASAlert-like object. Expected keys when dict:
               source_name, event_code, location_codes, raw_header, timestamp,
               confidence, issue_time, purge_time, originator, callsign.

    Returns:
        Dict with processing results, or None if processing failed:
            - success: bool — whether a broadcast was triggered
            - event_code: str
            - originator: str
            - source: str
            - message_id: int or None — EASMessage primary key (None if no broadcast)
            - same_header: str or None — generated SAME header string
            - reason: str — human-readable outcome explanation
            - processed_at: ISO timestamp
    """
    try:
        # Normalize input to dict
        if isinstance(alert, dict):
            alert_dict = alert
        else:
            # EASAlert object — convert to dict via attribute inspection
            alert_dict = {}
            for key in (
                'source_name', 'event_code', 'location_codes',
                'raw_header', 'timestamp', 'confidence',
                'issue_time', 'purge_time', 'originator', 'callsign',
            ):
                val = getattr(alert, key, None)
                if val is not None:
                    alert_dict[key] = val

            # Handle headers list (legacy EASAlert format)
            headers = getattr(alert, 'headers', None)
            if headers:
                first = headers[0]
                fields = first.get('fields', {}) if isinstance(first, dict) else {}
                alert_dict.setdefault('event_code', fields.get('event_code', 'UNKNOWN'))
                alert_dict.setdefault('originator', fields.get('originator', 'UNKNOWN'))
                alert_dict.setdefault('location_codes', fields.get('location_codes', []))

        event_code = alert_dict.get('event_code', 'UNKNOWN')
        originator = alert_dict.get('originator', 'UNKNOWN')
        source_name = alert_dict.get('source_name', 'unknown')

        logger.info(
            "Processing EAS alert: Event=%s, Originator=%s, Source=%s",
            event_code, originator, source_name,
        )

        # Require Flask app context for DB access and config loading
        try:
            from flask import has_app_context
            if not has_app_context():
                logger.warning(
                    "process_eas_alert called outside Flask app context; "
                    "broadcast and DB persistence unavailable"
                )
                return {
                    'success': False,
                    'event_code': event_code,
                    'originator': originator,
                    'source': source_name,
                    'message_id': None,
                    'same_header': None,
                    'reason': 'No Flask app context — cannot access database or config',
                    'processed_at': datetime.now(timezone.utc).isoformat(),
                }
        except ImportError:
            pass

        # Load runtime configuration
        from app_utils.eas import load_eas_config
        from app_core.location import get_location_settings
        from app_core.extensions import db
        from app_core.models import EASMessage
        from app_core.audio.auto_forward import auto_forward_ota_alert

        eas_config = load_eas_config()
        location_settings = get_location_settings()

        # Run the full broadcast pipeline (dedup → SAME audio → GPIO → notifications)
        broadcast_result = auto_forward_ota_alert(
            alert_dict=alert_dict,
            db_session=db.session,
            eas_message_cls=EASMessage,
            eas_config=eas_config,
            location_settings=location_settings,
            logger_instance=logger,
        )

        forwarded = broadcast_result.get('forwarded', False)
        record_id = broadcast_result.get('record_id')
        same_header = broadcast_result.get('same_header')
        reason = broadcast_result.get('reason', 'Broadcast not triggered')

        if forwarded:
            logger.info(
                "Alert processing complete: Event=%s, MessageID=%s, Header=%s",
                event_code, record_id, same_header,
            )
        else:
            logger.info(
                "Alert processing complete (no broadcast): Event=%s, Reason=%s",
                event_code, reason,
            )

        return {
            'success': forwarded,
            'event_code': event_code,
            'originator': originator,
            'source': source_name,
            'message_id': record_id,
            'same_header': same_header,
            'reason': reason,
            'processed_at': datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Error processing EAS alert: %s", e, exc_info=True)
        return None
