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

"""Resolving and caching EAS audio/summary files on disk, and purging old messages."""

import os
from typing import Any, Dict, List, Optional

from flask import current_app

from app_core.extensions import db
from app_core.models import EASMessage, ReceivedEASAlert
from app_utils.optimized_parsing import json_loads, JSONDecodeError


# Chunk size for the IN () clauses used when purging. Postgres caps a
# statement at 65535 bound parameters, so a large purge must be batched.
PURGE_CHUNK = 1000

def _get_eas_output_root() -> Optional[str]:
    output_root = str(current_app.config.get("EAS_OUTPUT_DIR") or "").strip()
    return output_root or None

def resolve_eas_disk_path(filename: Optional[str]) -> Optional[str]:
    """Resolve an EAS artifact filename to an on-disk path inside the output directory."""

    output_root = _get_eas_output_root()
    if not output_root or not filename:
        return None

    safe_fragment = str(filename).strip().lstrip("/\\")
    if not safe_fragment:
        return None

    candidate = os.path.abspath(os.path.join(output_root, safe_fragment))
    root = os.path.abspath(output_root)

    try:
        common = os.path.commonpath([candidate, root])
    except ValueError:
        return None

    if common != root:
        return None

    if os.path.exists(candidate):
        return candidate

    return None

def get_eas_static_prefix() -> str:
    """Return the configured static prefix for exposed EAS artifacts."""

    return current_app.config.get("EAS_OUTPUT_WEB_SUBDIR", "eas_messages").strip("/")

def load_or_cache_audio_data(message, *, variant: str = "primary") -> Optional[bytes]:
    """Return audio bytes for an ``EASMessage``, populating the database if needed."""

    normalized = (variant or "primary").strip().lower()
    metadata = message.metadata_payload or {}

    column_map = {
        "primary": "audio_data",
        "eom": "eom_audio_data",
        "same": "same_audio_data",
        "attention": "attention_audio_data",
        "tts": "tts_audio_data",
        "buffer": "buffer_audio_data",
    }

    if normalized not in column_map:
        return None

    column_name = column_map[normalized]
    data = getattr(message, column_name)

    fallback_filename: Optional[str] = None
    if normalized == "primary":
        fallback_filename = message.audio_filename
    elif normalized == "eom":
        fallback_filename = metadata.get("eom_filename") if isinstance(metadata, dict) else None

    if data:
        return data

    if not fallback_filename:
        return None

    disk_path = resolve_eas_disk_path(fallback_filename)
    if not disk_path:
        return None

    try:
        with open(disk_path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None

    if not data:
        return None

    setattr(message, column_name, data)

    try:
        db.session.add(message)
        db.session.commit()
    except Exception:  # pragma: no cover - best effort cache population
        db.session.rollback()

    return data

def load_or_cache_summary_payload(message) -> Optional[Dict[str, Any]]:
    """Return the JSON summary payload for an ``EASMessage``."""

    if message.text_payload:
        return dict(message.text_payload)

    disk_path = resolve_eas_disk_path(message.text_filename)
    if not disk_path:
        return None

    try:
        with open(disk_path, "r", encoding="utf-8") as handle:
            payload = json_loads(handle)
    except (OSError, JSONDecodeError):
        current_app.logger.debug("Unable to load summary payload from %s", disk_path)
        return None

    message.text_payload = payload
    try:
        db.session.add(message)
        db.session.commit()
    except Exception:  # pragma: no cover - best effort cache population
        db.session.rollback()

    return dict(payload)

def remove_eas_files(message) -> None:
    """Delete any EAS artifacts linked to the provided ``EASMessage`` instance."""

    filenames = {
        message.audio_filename,
        message.text_filename,
    }
    metadata = message.metadata_payload or {}
    eom_filename = metadata.get("eom_filename") if isinstance(metadata, dict) else None
    filenames.add(eom_filename)

    for filename in filenames:
        disk_path = resolve_eas_disk_path(filename)
        if not disk_path:
            continue
        try:
            os.remove(disk_path)
        except OSError:
            continue

def purge_eas_messages(query) -> List[int]:
    """Delete the EASMessage rows matched by ``query`` and their disk files.

    ``query`` is an EASMessage query carrying the caller's selection
    criteria; it is narrowed to the columns needed for cleanup rather than
    loaded whole. Whole rows would drag in six LargeBinary audio columns
    per message -- gigabytes for an "older than N days" purge, all of it
    read only to be thrown away.

    Returns the deleted IDs.
    """
    doomed = query.with_entities(
        EASMessage.id,
        EASMessage.audio_filename,
        EASMessage.text_filename,
        EASMessage.metadata_payload,
    ).all()
    if not doomed:
        return []

    deleted_ids = [row.id for row in doomed]
    for row in doomed:
        remove_eas_files(row)

    # received_eas_alerts.generated_message_id has no ON DELETE rule, so the
    # database rejects the delete while a reference survives. The previous
    # per-object db.session.delete() relied on SQLAlchemy's default cascade
    # to null it out; a set-based delete has to do that explicitly.
    for offset in range(0, len(deleted_ids), PURGE_CHUNK):
        chunk = deleted_ids[offset:offset + PURGE_CHUNK]
        ReceivedEASAlert.query.filter(
            ReceivedEASAlert.generated_message_id.in_(chunk)
        ).update(
            {ReceivedEASAlert.generated_message_id: None},
            synchronize_session=False,
        )
        EASMessage.query.filter(EASMessage.id.in_(chunk)).delete(
            synchronize_session=False
        )

    return deleted_ids
