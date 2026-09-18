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

"""One-time backfill helpers for columns added by schema_migrations.py."""

import os

from sqlalchemy import or_

from app_core.extensions import db
from app_core.models import EASMessage, ManualEASActivation
from app_utils.optimized_parsing import json_loads, JSONDecodeError

from .file_cache import resolve_eas_disk_path, _get_eas_output_root


def backfill_eas_message_payloads(logger) -> None:
    """Populate missing cached payload columns from on-disk artifacts."""

    try:
        candidates = (
            EASMessage.query.filter(
                or_(
                    EASMessage.audio_data.is_(None),
                    EASMessage.eom_audio_data.is_(None),
                    EASMessage.text_payload.is_(None),
                )
            )
            .order_by(EASMessage.id.asc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Unable to inspect cached EAS payloads: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return

    if not candidates:
        return

    updated = 0

    for message in candidates:
        changed = False

        if message.audio_data is None and message.audio_filename:
            disk_path = resolve_eas_disk_path(message.audio_filename)
            if disk_path:
                try:
                    with open(disk_path, "rb") as handle:
                        audio_bytes = handle.read()
                except OSError as exc:
                    logger.debug(
                        "Unable to backfill primary audio for message %s: %s",
                        message.id,
                        exc,
                    )
                else:
                    if audio_bytes:
                        message.audio_data = audio_bytes
                        changed = True

        metadata = message.metadata_payload or {}
        eom_filename = metadata.get("eom_filename") if isinstance(metadata, dict) else None
        if message.eom_audio_data is None and eom_filename:
            disk_path = resolve_eas_disk_path(eom_filename)
            if disk_path:
                try:
                    with open(disk_path, "rb") as handle:
                        eom_bytes = handle.read()
                except OSError as exc:
                    logger.debug(
                        "Unable to backfill EOM audio for message %s: %s",
                        message.id,
                        exc,
                    )
                else:
                    if eom_bytes:
                        message.eom_audio_data = eom_bytes
                        changed = True

        if (message.text_payload is None or message.text_payload == {}) and message.text_filename:
            disk_path = resolve_eas_disk_path(message.text_filename)
            if disk_path:
                try:
                    with open(disk_path, "r", encoding="utf-8") as handle:
                        payload = json_loads(handle)
                except (OSError, JSONDecodeError) as exc:
                    logger.debug(
                        "Unable to backfill summary payload for message %s: %s",
                        message.id,
                        exc,
                    )
                else:
                    message.text_payload = payload
                    changed = True

        if changed:
            db.session.add(message)
            updated += 1

    if not updated:
        return

    try:
        db.session.commit()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Failed to persist cached EAS payload backfill: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
    else:
        logger.info("Backfilled cached payloads for %s EAS messages", updated)

def backfill_manual_eas_audio(logger) -> None:
    """Populate missing cached audio columns from on-disk artifacts for manual EAS."""

    output_root = _get_eas_output_root()
    if not output_root:
        return

    try:
        candidates = (
            ManualEASActivation.query.filter(
                or_(
                    ManualEASActivation.composite_audio_data.is_(None),
                    ManualEASActivation.same_audio_data.is_(None),
                    ManualEASActivation.attention_audio_data.is_(None),
                    ManualEASActivation.tts_audio_data.is_(None),
                    ManualEASActivation.eom_audio_data.is_(None),
                )
            )
            .order_by(ManualEASActivation.id.asc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Unable to inspect cached manual EAS audio: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return

    if not candidates:
        return

    updated = 0

    for activation in candidates:
        changed = False
        components = activation.components_payload or {}

        # Map component keys to column names and filenames
        audio_mapping = {
            'composite': 'composite_audio_data',
            'same': 'same_audio_data',
            'attention': 'attention_audio_data',
            'tts': 'tts_audio_data',
            'eom': 'eom_audio_data',
        }

        for component_key, column_name in audio_mapping.items():
            # Skip if already cached
            if getattr(activation, column_name) is not None:
                continue

            # Get filename from components_payload
            component_meta = components.get(component_key)
            if not component_meta or not isinstance(component_meta, dict):
                continue

            storage_subpath = component_meta.get('storage_subpath')
            if not storage_subpath:
                continue

            disk_path = os.path.join(output_root, storage_subpath)
            if not os.path.exists(disk_path):
                continue

            try:
                with open(disk_path, "rb") as handle:
                    audio_bytes = handle.read()
            except OSError as exc:
                logger.debug(
                    "Unable to backfill %s audio for manual activation %s: %s",
                    component_key,
                    activation.id,
                    exc,
                )
                continue

            if audio_bytes:
                setattr(activation, column_name, audio_bytes)
                changed = True

        if changed:
            db.session.add(activation)
            updated += 1

    if not updated:
        return

    try:
        db.session.commit()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Failed to persist cached manual EAS audio backfill: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
    else:
        logger.info("Backfilled cached audio for %s manual EAS activations", updated)
