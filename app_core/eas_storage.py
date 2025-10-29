"""Helpers for managing persisted EAS audio and metadata payloads."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from flask import current_app
from sqlalchemy import text

from app_core.extensions import db


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

    if variant == "eom":
        data = message.eom_audio_data
        filename = (message.metadata_payload or {}).get("eom_filename") if message.metadata_payload else None
    else:
        data = message.audio_data
        filename = message.audio_filename

    if data:
        return data

    disk_path = resolve_eas_disk_path(filename)
    if not disk_path:
        return None

    try:
        with open(disk_path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None

    if not data:
        return None

    if variant == "eom":
        message.eom_audio_data = data
    else:
        message.audio_data = data

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
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
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


def ensure_eas_audio_columns(logger) -> bool:
    """Ensure blob columns exist for caching generated audio payloads."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    column_check_sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'eas_messages'
          AND column_name = :column
          AND table_schema = current_schema()
        LIMIT 1
        """
    )

    try:
        changed = False
        for column in ("audio_data", "eom_audio_data"):
            exists = db.session.execute(column_check_sql, {"column": column}).scalar()
            if exists:
                continue

            logger.info(
                "Adding eas_messages.%s column for cached audio payloads", column
            )
            db.session.execute(
                text(f"ALTER TABLE eas_messages ADD COLUMN {column} BYTEA")
            )
            changed = True

        if changed:
            db.session.commit()

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure EAS audio columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False

