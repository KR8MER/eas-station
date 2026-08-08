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

"""Everything the /alerts page attaches to a page of alerts after fetching it.

All three of these are best-effort: the alert list is the page, and none of the
enrichment is worth 500ing over, so each logs and degrades on failure.
"""

import os
from typing import Any, Dict, List, Optional

from app_core.eas_storage import get_eas_static_prefix
from app_core.extensions import db
from app_core.models import EASMessage, ManualEASActivation
from flask import url_for

MANUAL_MESSAGE_LIMIT = 10


def _static_path(filename: Optional[str], static_prefix: str) -> Optional[str]:
    if not filename:
        return None
    parts = [static_prefix, filename] if static_prefix else [filename]
    return "/".join(part for part in parts if part)


def build_audio_map(alerts_list, route_logger) -> Dict[int, List[Dict[str, Any]]]:
    """Generated EAS audio for each alert on the page, keyed by alert id.

    A message whose text was stored in the database links to the route that
    renders it; one whose text only exists on disk links to the static file.
    """
    audio_map: Dict[int, List[Dict[str, Any]]] = {}
    if not alerts_list:
        return audio_map

    alert_ids = [alert.id for alert in alerts_list if getattr(alert, "id", None)]
    if not alert_ids:
        return audio_map

    try:
        eas_messages = (
            EASMessage.query
            .filter(EASMessage.cap_alert_id.in_(alert_ids))
            .order_by(EASMessage.created_at.desc())
            .all()
        )
        static_prefix = get_eas_static_prefix()

        for message in eas_messages:
            if not message.cap_alert_id:
                continue

            audio_entries = audio_map.setdefault(message.cap_alert_id, [])

            audio_url = url_for("eas_message_audio", message_id=message.id)
            if message.text_payload:
                text_url = url_for("eas_message_summary", message_id=message.id)
            else:
                text_path = _static_path(message.text_filename, static_prefix)
                text_url = url_for("static", filename=text_path) if text_path else None

            audio_entries.append(
                {
                    "id": message.id,
                    "created_at": message.created_at,
                    "audio_url": audio_url,
                    "text_url": text_url,
                    "detail_url": url_for("audio_detail", message_id=message.id),
                }
            )
    except Exception as exc:
        db.session.rollback()
        route_logger.warning("Error loading EAS messages for alerts: %s", exc)

    return audio_map


def load_manual_messages(route_logger) -> List[ManualEASActivation]:
    """The most recent operator-originated activations, newest first."""
    try:
        return (
            ManualEASActivation.query
            .order_by(ManualEASActivation.created_at.desc())
            .limit(MANUAL_MESSAGE_LIMIT)
            .all()
        )
    except Exception as exc:
        db.session.rollback()
        route_logger.warning("Error loading manual activations: %s", exc)
        return []


def backfill_ipaws_audio(alerts_list, route_logger) -> None:
    """Extract IPAWS audio for alerts on this page that predate the extractor.

    Lazy on purpose: alerts ingested before the extraction code existed still
    carry the audio inside their stored ``raw_json``, and this pulls it out the
    first time such an alert is viewed rather than requiring a bulk migration.
    """
    if not alerts_list:
        return

    try:
        from app_utils.ipaws_enrichment import save_ipaws_audio

        eas_output = os.getenv('EAS_OUTPUT_DIR') or os.path.join(
            os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static')),
            'eas_messages',
        )
        for alert_obj in alerts_list:
            if getattr(alert_obj, 'ipaws_audio_url', None):
                continue
            raw_json = alert_obj.raw_json if isinstance(alert_obj.raw_json, dict) else {}
            resources = raw_json.get('properties', {}).get('resources', [])
            has_audio = any(
                ('audio' in (r.get('mimeType') or '').lower()
                 or 'eas broadcast' in (r.get('resourceDesc') or '').lower())
                and r.get('derefUri')
                for r in resources
            )
            if has_audio:
                audio_fn = save_ipaws_audio(
                    raw_json,
                    alert_obj.identifier or str(alert_obj.id),
                    eas_output,
                )
                if audio_fn:
                    alert_obj.ipaws_audio_url = audio_fn
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        route_logger.warning("Lazy IPAWS audio backfill failed: %s", exc)


__all__ = [
    "MANUAL_MESSAGE_LIMIT",
    "backfill_ipaws_audio",
    "build_audio_map",
    "load_manual_messages",
]
