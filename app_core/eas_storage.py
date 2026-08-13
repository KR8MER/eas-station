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

"""Helpers for managing persisted EAS audio and metadata payloads."""

import csv
import io
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from flask import current_app
from sqlalchemy import or_, select, text
from sqlalchemy.orm import defer

from app_core.extensions import db
from app_core.models import (
    AlertDeliveryReport,
    CAPAlert,
    EASDecodedAudio,
    EASMessage,
    ManualEASActivation,
    ReceivedEASAlert,
)
from app_utils import ALERT_SOURCE_UNKNOWN
from app_utils.alert_sources import (
    ALERT_SOURCE_EAS_RF,
    ALERT_SOURCE_EAS_STREAM,
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_NOAA,
)
from app_utils.eas import ORIGINATOR_DESCRIPTIONS
from app_utils.eas_codes import get_event_name, get_originator_name
from app_utils.eas_decode import (
    SAMEAudioDecodeResult,
    build_plain_language_summary,
)
from app_utils.time import format_local_datetime, utc_now
from app_utils.optimized_parsing import json_loads, json_dumps, JSONDecodeError

# Import precedence levels for priority tracking
try:
    from app_core.audio.playout_queue import PrecedenceLevel
    PRECEDENCE_AVAILABLE = True
except ImportError:
    PRECEDENCE_AVAILABLE = False
    PrecedenceLevel = None


TEST_EVENT_KEYWORDS = (
    "Required Weekly Test",
    "Required Monthly Test",
    "RWT",
    "RMT",
)

DELIVERED_EVENT_STATUSES = {"delivered", "completed", "success", "ok", "played"}
FAILED_EVENT_STATUSES = {"failed", "error", "timeout", "aborted"}
PENDING_EVENT_STATUSES = {"pending", "queued", "waiting", "scheduled"}


def _ensure_header_summary(header: Any) -> Any:
    """Ensure legacy SAME header payloads include a summary string."""

    if not isinstance(header, dict):
        return header

    if header.get("summary"):
        return header

    header_text = header.get("header")
    fields = header.get("fields")
    if isinstance(header_text, str) and isinstance(fields, dict):
        try:
            summary = build_plain_language_summary(header_text, fields)
        except Exception:  # pragma: no cover - defensive fallback
            summary = None
        if summary:
            enriched = dict(header)
            enriched["summary"] = summary
            return enriched

    return header


def record_audio_decode_result(
    *,
    filename: Optional[str],
    content_type: Optional[str],
    decode_payload: SAMEAudioDecodeResult,
):
    """Persist the results of decoding an uploaded SAME audio payload."""

    safe_filename = (filename or "").strip()[:255] or None
    safe_type = (content_type or "").strip()[:128] or None

    segments = decode_payload.segments
    segment_metadata = decode_payload.segment_metadata

    same_headers = []
    for header in decode_payload.headers:
        payload = header.to_dict()
        if not payload.get("summary"):
            payload = _ensure_header_summary(payload)
        same_headers.append(payload)

    record = EASDecodedAudio(
        original_filename=safe_filename,
        content_type=safe_type,
        raw_text=decode_payload.raw_text,
        same_headers=same_headers,
        quality_metrics={
            "bit_count": decode_payload.bit_count,
            "frame_count": decode_payload.frame_count,
            "frame_errors": decode_payload.frame_errors,
            "duration_seconds": decode_payload.duration_seconds,
            "sample_rate": decode_payload.sample_rate,
            "bit_confidence": decode_payload.bit_confidence,
            "min_bit_confidence": decode_payload.min_bit_confidence,
            "segment_count": len(segments),
            "endec_mode": decode_payload.endec_mode,
        },
        segment_metadata=segment_metadata,
        header_audio_data=(
            segments.get("header").wav_bytes if "header" in segments else None
        ),
        attention_tone_audio_data=(
            segments.get("attention_tone").wav_bytes if "attention_tone" in segments else None
        ),
        narration_audio_data=(
            segments.get("narration").wav_bytes if "narration" in segments else None
        ),
        eom_audio_data=(segments.get("eom").wav_bytes if "eom" in segments else None),
        buffer_audio_data=(
            segments.get("buffer").wav_bytes if "buffer" in segments else None
        ),
        composite_audio_data=(
            segments.get("composite").wav_bytes if "composite" in segments else None
        ),
        # Deprecated: keep for backward compatibility
        message_audio_data=(
            segments.get("message").wav_bytes if "message" in segments else None
        ),
    )

    try:
        db.session.add(record)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return record


def load_recent_audio_decodes(limit: int = 5) -> List[Dict[str, Any]]:
    """Return the most recent decoded audio payloads for display.

    Uses ``IS NOT NULL`` projections instead of selecting the BYTEA blob
    columns so that the listing view never pulls the full audio payloads
    (which can be megabytes per row) just to populate the ``has_*`` flags.
    """

    try:
        query = (
            db.session.query(
                EASDecodedAudio.id,
                EASDecodedAudio.created_at,
                EASDecodedAudio.original_filename,
                EASDecodedAudio.content_type,
                EASDecodedAudio.raw_text,
                EASDecodedAudio.same_headers,
                EASDecodedAudio.quality_metrics,
                EASDecodedAudio.segment_metadata,
                EASDecodedAudio.header_audio_data.isnot(None).label(
                    "has_header_audio"
                ),
                EASDecodedAudio.message_audio_data.isnot(None).label(
                    "has_message_audio"
                ),
                EASDecodedAudio.eom_audio_data.isnot(None).label("has_eom_audio"),
                EASDecodedAudio.buffer_audio_data.isnot(None).label(
                    "has_buffer_audio"
                ),
            )
            .order_by(EASDecodedAudio.created_at.desc())
        )
        if limit > 0:
            query = query.limit(limit)
        rows = query.all()
    except Exception:
        db.session.rollback()
        return []

    results: List[Dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "original_filename": row.original_filename,
                "content_type": row.content_type,
                "raw_text": row.raw_text,
                "same_headers": [
                    _ensure_header_summary(header)
                    for header in list(row.same_headers or [])
                ],
                "quality_metrics": dict(row.quality_metrics or {}),
                "segment_metadata": dict(row.segment_metadata or {}),
                "has_header_audio": bool(row.has_header_audio),
                "has_message_audio": bool(row.has_message_audio),
                "has_eom_audio": bool(row.has_eom_audio),
                "has_buffer_audio": bool(row.has_buffer_audio),
            }
        )

    return results


def _resolve_delay_threshold_seconds() -> int:
    try:
        value = int(
            current_app.config.get("ALERT_VERIFICATION_DELAY_THRESHOLD_SECONDS", 120)
        )
    except (TypeError, ValueError):
        value = 120
    return max(value, 0)


def _ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _ensure_aware(value)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return _ensure_aware(parsed)

    return None


def _extract_playout_events(
    message: EASMessage, alert_sent: Optional[datetime]
) -> List[Dict[str, Any]]:
    metadata = message.metadata_payload or {}
    raw_events: Iterable[Any] = ()

    if isinstance(metadata, dict):
        for key in ("playout_events", "playout_log", "delivery_events"):
            value = metadata.get(key)
            if isinstance(value, list):
                raw_events = value
                break

    events: List[Dict[str, Any]] = []
    sent_ts = _ensure_aware(alert_sent)

    for item in raw_events:
        if not isinstance(item, dict):
            continue

        target = item.get("target") or item.get("device") or "unknown"
        target_str = str(target).strip() or "unknown"

        status = str(item.get("status") or "unknown").strip().lower()
        timestamp = _parse_timestamp(item.get("timestamp"))

        latency = item.get("latency_seconds")
        if isinstance(latency, (int, float)):
            latency_seconds: Optional[float] = float(latency)
        else:
            latency_seconds = None

        if latency_seconds is None:
            latency_ms = item.get("latency_ms")
            if isinstance(latency_ms, (int, float)):
                latency_seconds = float(latency_ms) / 1000.0

        if latency_seconds is None and timestamp and sent_ts:
            delta = (timestamp - sent_ts).total_seconds()
            latency_seconds = max(delta, 0.0)

        events.append(
            {
                "target": target_str,
                "status": status or "unknown",
                "timestamp": timestamp,
                "latency_seconds": latency_seconds,
                "raw": item,
            }
        )

    return events


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


# Chunk size for the IN () clauses used when purging. Postgres caps a
# statement at 65535 bound parameters, so a large purge must be batched.
PURGE_CHUNK = 1000


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

    column_definitions = {
        "audio_data": "BYTEA",
        "eom_audio_data": "BYTEA",
        "same_audio_data": "BYTEA",
        "attention_audio_data": "BYTEA",
        "tts_audio_data": "BYTEA",
        "buffer_audio_data": "BYTEA",
        "text_payload": "JSONB",
    }

    try:
        added_columns = []
        with engine.begin() as connection:
            for column, definition in column_definitions.items():
                exists = connection.execute(column_check_sql, {"column": column}).scalar()
                if exists:
                    continue

                logger.info(
                    "Adding eas_messages.%s column for cached message payloads", column
                )
                connection.execute(
                    text(f"ALTER TABLE eas_messages ADD COLUMN IF NOT EXISTS {column} {definition}")
                )
                added_columns.append(column)

        if "text_payload" in added_columns:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE eas_messages ALTER COLUMN text_payload SET DEFAULT '{}'::jsonb"
                        )
                    )
                    connection.execute(
                        text(
                            "UPDATE eas_messages SET text_payload = '{}'::jsonb WHERE text_payload IS NULL"
                        )
                    )
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning(
                    "Could not initialize default data for eas_messages.text_payload: %s",
                    exc,
                )

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure EAS audio columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False


def ensure_eas_message_foreign_key(logger) -> bool:
    """Ensure the cap_alert_id foreign key has proper ON DELETE SET NULL behavior."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    # Check if the foreign key constraint exists and what its delete rule is
    constraint_check_sql = text(
        """
        SELECT con.conname, pg_get_constraintdef(con.oid) as constraint_def
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE rel.relname = 'eas_messages'
          AND con.contype = 'f'
          AND nsp.nspname = current_schema()
          AND pg_get_constraintdef(con.oid) LIKE '%cap_alerts%'
        """
    )

    try:
        with engine.begin() as connection:
            result = connection.execute(constraint_check_sql).fetchone()

            if result:
                constraint_name = result[0]
                constraint_def = result[1]

                # Check if it already has ON DELETE SET NULL
                if "ON DELETE SET NULL" in constraint_def.upper():
                    logger.debug("EAS message foreign key constraint already has proper ON DELETE behavior")
                    return True

                # Drop the old constraint
                logger.info("Updating eas_messages.cap_alert_id foreign key constraint to SET NULL on delete")
                connection.execute(
                    text(f"ALTER TABLE eas_messages DROP CONSTRAINT {constraint_name}")
                )

                # Add the new constraint with ON DELETE SET NULL
                connection.execute(
                    text(
                        "ALTER TABLE eas_messages ADD CONSTRAINT eas_messages_cap_alert_id_fkey "
                        "FOREIGN KEY (cap_alert_id) REFERENCES cap_alerts(id) ON DELETE SET NULL"
                    )
                )
                logger.info("Successfully updated foreign key constraint on eas_messages.cap_alert_id")

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure EAS message foreign key constraint: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False


def ensure_eas_settings_columns(logger) -> bool:
    """Ensure all expected columns exist on the eas_settings table.

    Guards against deployments where the Alembic migration has not yet run
    (e.g. manual git-pull without running update.sh).  Currently handles:
      - forwarded_event_codes  JSONB NOT NULL DEFAULT '[]'::jsonb
    """

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    column_check_sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name   = 'eas_settings'
          AND column_name  = :column
          AND table_schema = current_schema()
        LIMIT 1
        """
    )

    columns_to_ensure = {
        "forwarded_event_codes": "JSONB NOT NULL DEFAULT '[]'::jsonb",
    }

    try:
        with engine.begin() as connection:
            for column, definition in columns_to_ensure.items():
                exists = connection.execute(column_check_sql, {"column": column}).scalar()
                if exists:
                    continue
                logger.info(
                    "Adding eas_settings.%s column (migration not yet applied)", column
                )
                connection.execute(
                    text(f"ALTER TABLE eas_settings ADD COLUMN IF NOT EXISTS {column} {definition}")
                )
        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure eas_settings columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False


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


def ensure_manual_eas_audio_columns(logger) -> bool:
    """Ensure blob columns exist for caching manual EAS audio payloads."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    column_check_sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'manual_eas_activations'
          AND column_name = :column
          AND table_schema = current_schema()
        LIMIT 1
        """
    )

    column_definitions = {
        "composite_audio_data": "BYTEA",
        "same_audio_data": "BYTEA",
        "attention_audio_data": "BYTEA",
        "tts_audio_data": "BYTEA",
        "eom_audio_data": "BYTEA",
    }

    try:
        with engine.begin() as connection:
            for column, definition in column_definitions.items():
                exists = connection.execute(column_check_sql, {"column": column}).scalar()
                if exists:
                    continue

                logger.info(
                    "Adding manual_eas_activations.%s column for cached audio payloads", column
                )
                connection.execute(
                    text(f"ALTER TABLE manual_eas_activations ADD COLUMN IF NOT EXISTS {column} {definition}")
                )

        return True
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Could not ensure manual EAS audio columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return False


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


def _normalize_window_days(window_days: int) -> int:
    try:
        days = int(window_days)
    except (TypeError, ValueError):
        return 30
    return max(1, min(days, 365))


def _event_matches_test(label: Optional[str]) -> bool:
    if not label:
        return False
    normalized = str(label).lower()
    return any(keyword.lower() in normalized for keyword in TEST_EVENT_KEYWORDS)


def _build_delivery_record(
    alert: CAPAlert,
    messages: Sequence[EASMessage],
    *,
    delay_threshold: int,
) -> Dict[str, Any]:
    sent_ts = _ensure_aware(alert.sent)
    record: Dict[str, Any] = {
        "alert_id": alert.id,
        "identifier": alert.identifier,
        "event": alert.event,
        "sent": sent_ts,
        "source": alert.source,
        "status": alert.status,
        "message_type": alert.message_type,
        "messages": [],
        "playout_targets": [],
        "target_details": [],
        "issues": [],
        "latency_samples": [],
        "min_latency_seconds": None,
        "max_latency_seconds": None,
        "average_latency_seconds": None,
        "delivery_status": "missing",
    }

    if not messages:
        record["issues"].append("No EAS message was generated for this CAP alert.")
        return record

    target_map: Dict[str, Dict[str, Any]] = {}

    for message in messages:
        events = _extract_playout_events(message, alert_sent=sent_ts)
        message_info = {
            "id": message.id,
            "created_at": _ensure_aware(message.created_at),
            "same_header": message.same_header,
            "playout_events": events,
        }
        record["messages"].append(message_info)

        for event in events:
            target_key = event.get("target") or "unknown"
            target_entry = target_map.setdefault(
                target_key,
                {
                    "target": target_key,
                    "events": [],
                    "latencies": [],
                    "delivered": False,
                    "failed": False,
                    "pending": False,
                },
            )
            target_entry["events"].append(event)

            latency_value = event.get("latency_seconds")
            if isinstance(latency_value, (int, float)):
                target_entry["latencies"].append(float(latency_value))
                record["latency_samples"].append(float(latency_value))

            status = str(event.get("status") or "").lower()
            if status in DELIVERED_EVENT_STATUSES:
                target_entry["delivered"] = True
            elif status in FAILED_EVENT_STATUSES:
                target_entry["failed"] = True
            elif status in PENDING_EVENT_STATUSES:
                target_entry["pending"] = True

    delivered_targets = 0
    failed_targets = 0
    pending_targets = 0
    delayed_targets = 0

    for target_key, entry in target_map.items():
        latencies = entry["latencies"]
        latency_seconds = min(latencies) if latencies else None
        if latency_seconds is not None:
            if record["min_latency_seconds"] is None:
                record["min_latency_seconds"] = latency_seconds
            else:
                record["min_latency_seconds"] = min(
                    record["min_latency_seconds"], latency_seconds
                )

            if record["max_latency_seconds"] is None:
                record["max_latency_seconds"] = latency_seconds
            else:
                record["max_latency_seconds"] = max(
                    record["max_latency_seconds"], latency_seconds
                )

        delayed = bool(
            latency_seconds is not None and latency_seconds > float(delay_threshold)
        )
        if delayed:
            delayed_targets += 1

        status = "unknown"
        if entry["delivered"] and not entry["failed"]:
            status = "delivered"
            delivered_targets += 1
        elif entry["delivered"] and entry["failed"]:
            status = "partial"
            delivered_targets += 1
            failed_targets += 1
        elif entry["failed"]:
            status = "failed"
            failed_targets += 1
        elif entry["pending"]:
            status = "pending"
            pending_targets += 1

        record["target_details"].append(
            {
                "target": target_key,
                "status": status,
                "latency_seconds": latency_seconds,
                "delayed": delayed,
                "delivered": entry["delivered"],
                "failed": entry["failed"],
                "pending": entry["pending"],
                "events": entry["events"],
            }
        )

    record["playout_targets"] = [item["target"] for item in record["target_details"]]

    latency_samples = record["latency_samples"]
    if latency_samples:
        record["average_latency_seconds"] = sum(latency_samples) / max(
            len(latency_samples), 1
        )

    if not record["target_details"]:
        record["delivery_status"] = "awaiting_playout"
        record["issues"].append("Audio was generated but no playout events were logged.")
    elif delivered_targets and not failed_targets and not pending_targets:
        record["delivery_status"] = "delivered"
    elif delivered_targets:
        record["delivery_status"] = "partial"
        record["issues"].append(
            "At least one output path reported failures or delays during playout."
        )
    elif pending_targets:
        record["delivery_status"] = "pending"
        record["issues"].append("Playout is still pending for one or more targets.")
    else:
        record["delivery_status"] = "awaiting_playout"
        record["issues"].append("No successful playout events were recorded.")

    if delayed_targets:
        record["issues"].append(
            f"{delayed_targets} target(s) exceeded the {delay_threshold}s delivery threshold."
        )

    return record


def collect_alert_delivery_records(
    *, window_days: int = 30
) -> Dict[str, Any]:
    days = _normalize_window_days(window_days)
    window_end = utc_now()
    window_start = window_end - timedelta(days=days)
    delay_threshold = _resolve_delay_threshold_seconds()

    summary = {
        "total": 0,
        "delivered": 0,
        "partial": 0,
        "pending": 0,
        "missing": 0,
        "awaiting_playout": 0,
    }

    records: List[Dict[str, Any]] = []
    orphan_messages: List[Dict[str, Any]] = []

    try:
        alerts = (
            CAPAlert.query.filter(CAPAlert.sent >= window_start)
            .order_by(CAPAlert.sent.desc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        current_app.logger.error("Failed to load CAP alerts for verification: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return {
            "window_start": window_start,
            "window_end": window_end,
            "generated_at": utc_now(),
            "delay_threshold_seconds": delay_threshold,
            "summary": summary,
            "records": records,
            "orphans": orphan_messages,
        }

    try:
        message_query = (
            EASMessage.without_audio()
            .filter(EASMessage.created_at >= window_start)
            .order_by(EASMessage.created_at.asc())
        )
        messages = message_query.all()
    except Exception as exc:  # pragma: no cover - defensive fallback
        current_app.logger.error("Failed to load EAS messages for verification: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        messages = []

    messages_by_alert: Dict[Optional[int], List[EASMessage]] = {}
    for message in messages:
        messages_by_alert.setdefault(message.cap_alert_id, []).append(message)

    for alert in alerts:
        related_messages = messages_by_alert.get(alert.id, [])
        record = _build_delivery_record(
            alert,
            related_messages,
            delay_threshold=delay_threshold,
        )
        records.append(record)
        summary["total"] += 1
        status = record["delivery_status"]
        if status in summary:
            summary[status] += 1

    for orphan in messages_by_alert.get(None, []):
        events = _extract_playout_events(orphan, alert_sent=None)
        orphan_messages.append(
            {
                "id": orphan.id,
                "created_at": _ensure_aware(orphan.created_at),
                "same_header": orphan.same_header,
                "playout_events": events,
            }
        )

    latency_samples = [sample for record in records for sample in record["latency_samples"]]
    average_latency = (
        sum(latency_samples) / len(latency_samples)
        if latency_samples
        else None
    )

    summary["average_latency_seconds"] = average_latency

    return {
        "window_start": window_start,
        "window_end": window_end,
        "generated_at": utc_now(),
        "delay_threshold_seconds": delay_threshold,
        "summary": summary,
        "records": records,
        "orphans": orphan_messages,
    }


def _summarize_delivery_trends(
    records: Sequence[Dict[str, Any]],
    *,
    delay_threshold: int,
) -> Dict[str, Dict[str, Any]]:
    originators: Dict[str, Dict[str, Any]] = {}
    stations: Dict[str, Dict[str, Any]] = {}

    for record in records:
        originator = record.get("source") or ALERT_SOURCE_UNKNOWN
        origin_entry = originators.setdefault(
            originator,
            {
                "label": originator,
                "total": 0,
                "delivered": 0,
                "delayed": 0,
                "latency_sum": 0.0,
                "latency_count": 0,
            },
        )
        origin_entry["total"] += 1

        if record.get("delivery_status") in {"delivered", "partial"}:
            origin_entry["delivered"] += 1

        max_latency = record.get("max_latency_seconds")
        if isinstance(max_latency, (int, float)) and max_latency > float(delay_threshold):
            origin_entry["delayed"] += 1

        for sample in record.get("latency_samples", []):
            if isinstance(sample, (int, float)):
                origin_entry["latency_sum"] += float(sample)
                origin_entry["latency_count"] += 1

        for target in record.get("target_details", []):
            target_label = target.get("target") or "unknown"
            station_entry = stations.setdefault(
                target_label,
                {
                    "label": target_label,
                    "total": 0,
                    "delivered": 0,
                    "delayed": 0,
                    "latency_sum": 0.0,
                    "latency_count": 0,
                },
            )
            station_entry["total"] += 1
            if target.get("delivered"):
                station_entry["delivered"] += 1
            latency_value = target.get("latency_seconds")
            if isinstance(latency_value, (int, float)):
                station_entry["latency_sum"] += float(latency_value)
                station_entry["latency_count"] += 1
                if float(latency_value) > float(delay_threshold):
                    station_entry["delayed"] += 1

    def _finalize(summary: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        finalized: List[Dict[str, Any]] = []
        for entry in summary.values():
            total = entry["total"]
            delivered = entry["delivered"]
            delayed = entry["delayed"]
            latency_avg = None
            if entry["latency_count"]:
                latency_avg = entry["latency_sum"] / entry["latency_count"]
            finalized.append(
                {
                    "label": entry["label"],
                    "total": total,
                    "delivered": delivered,
                    "delayed": delayed,
                    "delivery_rate": (delivered / total * 100.0) if total else None,
                    "average_latency_seconds": latency_avg,
                }
            )
        finalized.sort(key=lambda item: (item["delivery_rate"] or 0.0), reverse=True)
        return finalized

    return {
        "originators": _finalize(originators),
        "stations": _finalize(stations),
    }


def build_alert_delivery_trends(
    records: Sequence[Dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
    delay_threshold: Optional[int] = None,
    logger=None,
) -> Dict[str, Any]:
    threshold = delay_threshold if delay_threshold is not None else _resolve_delay_threshold_seconds()

    trends = _summarize_delivery_trends(records, delay_threshold=threshold)
    generated_at = utc_now()

    report_rows: List[AlertDeliveryReport] = []

    for entry in trends["originators"]:
        report_rows.append(
            AlertDeliveryReport(
                generated_at=generated_at,
                window_start=window_start,
                window_end=window_end,
                scope="originator",
                originator=entry["label"],
                station=None,
                total_alerts=entry["total"],
                delivered_alerts=entry["delivered"],
                delayed_alerts=entry["delayed"],
                average_latency_seconds=(
                    int(entry["average_latency_seconds"])
                    if entry["average_latency_seconds"] is not None
                    else None
                ),
            )
        )

    for entry in trends["stations"]:
        report_rows.append(
            AlertDeliveryReport(
                generated_at=generated_at,
                window_start=window_start,
                window_end=window_end,
                scope="station",
                originator=None,
                station=entry["label"],
                total_alerts=entry["total"],
                delivered_alerts=entry["delivered"],
                delayed_alerts=entry["delayed"],
                average_latency_seconds=(
                    int(entry["average_latency_seconds"])
                    if entry["average_latency_seconds"] is not None
                    else None
                ),
            )
        )

    if report_rows:
        try:
            (
                db.session.query(AlertDeliveryReport)
                .filter(
                    AlertDeliveryReport.window_start == window_start,
                    AlertDeliveryReport.window_end == window_end,
                )
                .delete(synchronize_session=False)
            )
            db.session.add_all(report_rows)
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive fallback
            if logger is not None:
                logger.warning("Failed to persist alert delivery reports: %s", exc)
            try:
                db.session.rollback()
            except Exception:  # pragma: no cover - defensive fallback
                pass

    return {
        "generated_at": generated_at,
        "delay_threshold_seconds": threshold,
        "originators": trends["originators"],
        "stations": trends["stations"],
    }


# ---------------------------------------------------------------------------
# FCC Part 11 log helpers
#
# 47 CFR § 11.35(a) and § 11.54(a)(3) require EAS Participants to record the
# originator (ORG), event code (EEE), location codes (PSSCCC), issue time
# (JJJHHMM), purge time (+TTTT), and station identifier (LLLLLLLL) for every
# received and originated EAS message.  The helpers below extract those
# fields from raw SAME headers and CAP ingest metadata so each entry in the
# compliance log carries the full FCC-required record set.
# ---------------------------------------------------------------------------


# Best-effort CAP source → SAME originator code.  CAP messages do not carry a
# SAME ORG directly; this mirrors the mapping the forwarder uses when it
# composes outgoing SAME audio (see app_core/audio/auto_forward.py).
_CAP_SOURCE_ORIGINATORS: Dict[str, str] = {
    ALERT_SOURCE_NOAA: "WXR",
    ALERT_SOURCE_IPAWS: "EAS",
    ALERT_SOURCE_EAS_RF: "EAS",
    ALERT_SOURCE_EAS_STREAM: "EAS",
}


def _parse_same_header_fields(header: Optional[str]) -> Dict[str, Any]:
    """Return ``{originator, event_code, fips, issue_time, purge_minutes, station}``
    extracted from a SAME header, or an empty dict if the header does not parse.

    Format: ``ZCZC-ORG-EEE-PSSCCC[-PSSCCC...]+TTTT-JJJHHMM-LLLLLLLL-``
    """
    if not header:
        return {}
    text_value = header.strip()
    if not text_value.startswith("ZCZC"):
        return {}
    parts = text_value.split("-")
    if len(parts) < 6:
        return {}
    try:
        originator = parts[1].strip().upper() or None
        event_code = parts[2].strip().upper() or None
        station = parts[-2].strip() or None  # LLLLLLLL
        issue_time = parts[-3].strip() or None  # JJJHHMM
        purge_field = parts[-4]  # last FIPS, carries "+TTTT"
        purge_minutes: Optional[int] = None
        if "+" in purge_field:
            tttt = purge_field.split("+", 1)[1]
            if tttt.isdigit() and len(tttt) == 4:
                purge_minutes = int(tttt[:2]) * 60 + int(tttt[2:])
        fips_codes: List[str] = []
        for raw in parts[3:-3]:
            code = raw.split("+", 1)[0]
            code = "".join(ch for ch in code if ch.isdigit())
            if code:
                fips_codes.append(code.zfill(6)[:6])
        return {
            "originator": originator,
            "event_code": event_code,
            "fips": fips_codes,
            "issue_time": issue_time,
            "purge_minutes": purge_minutes,
            "station": station,
        }
    except (IndexError, ValueError):
        return {}


def _format_purge_minutes(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h{mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _cap_originator_from_source(source: Optional[str]) -> Optional[str]:
    """Map a CAP alert's ingest source to a best-effort SAME originator code."""
    if not source:
        return None
    return _CAP_SOURCE_ORIGINATORS.get(source.strip().upper())


def _cap_fips_codes(raw_json: Any) -> List[str]:
    """Pull SAME-style 6-digit FIPS codes out of a CAP alert's raw_json."""
    if not isinstance(raw_json, dict):
        return []
    seen: List[str] = []
    info_blocks = raw_json.get("info")
    if isinstance(info_blocks, dict):
        info_blocks = [info_blocks]
    if not isinstance(info_blocks, list):
        return []
    for info in info_blocks:
        if not isinstance(info, dict):
            continue
        areas = info.get("area")
        if isinstance(areas, dict):
            areas = [areas]
        if not isinstance(areas, list):
            continue
        for area in areas:
            if not isinstance(area, dict):
                continue
            geocodes = area.get("geocode")
            if isinstance(geocodes, dict):
                geocodes = [geocodes]
            if not isinstance(geocodes, list):
                continue
            for geo in geocodes:
                if not isinstance(geo, dict):
                    continue
                name = (geo.get("valueName") or "").strip().upper()
                value = (geo.get("value") or "").strip()
                if name in {"SAME", "FIPS", "FIPS6"} and value:
                    digits = "".join(ch for ch in value if ch.isdigit())
                    if digits:
                        code = digits.zfill(6)[:6]
                        if code not in seen:
                            seen.append(code)
    return seen


def collect_compliance_log_entries(
    window_days: int = 30,
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], datetime, datetime]:
    """Return compliance activity entries for the requested window.

    When ``window_start`` and ``window_end`` are both provided they take
    precedence over ``window_days``; otherwise the window ends at "now" and
    extends ``window_days`` into the past.
    """

    if window_start is not None and window_end is not None:
        window_start = _coerce_aware_utc(window_start) or window_start
        window_end = _coerce_aware_utc(window_end) or window_end
        if window_start > window_end:
            window_start, window_end = window_end, window_start
    else:
        days = _normalize_window_days(window_days)
        window_end = utc_now()
        window_start = window_end - timedelta(days=days)

    entries: List[Dict[str, Any]] = []

    # Define a reasonable limit for compliance log entries to prevent memory exhaustion
    MAX_ENTRIES_PER_CATEGORY = 10000

    # SQLAlchemy fetches every column on the ORM model by default — including
    # several multi-megabyte LargeBinary columns on EASMessage and a JSONB
    # payload on ReceivedEASAlert.  Naively iterating a 30-day window can
    # balloon a gunicorn worker to multiple GB.  We defer the heavy columns,
    # strip the joined CAPAlert down to only what we read, and stream rows
    # with yield_per() so the working set stays small.
    STREAM_BATCH = 500

    try:
        alert_query = (
            CAPAlert.query.filter(CAPAlert.sent >= window_start)
            .order_by(CAPAlert.sent.desc())
            .limit(MAX_ENTRIES_PER_CATEGORY)
            .yield_per(STREAM_BATCH)
        )

        for alert in alert_query:
            originator_code = _cap_originator_from_source(alert.source)
            originator_name = (
                get_originator_name(originator_code) if originator_code else None
            )
            forwarding_reason = (alert.eas_forwarding_reason or "").strip() or None
            if alert.eas_forwarded:
                action_taken = "Relayed"
            elif forwarding_reason:
                action_taken = "Not relayed"
            else:
                action_taken = "Received"
            entries.append(
                {
                    "timestamp": alert.sent,
                    "category": "received",
                    "event_label": alert.event,
                    "event_code": None,  # CAP feeds carry no SAME code directly
                    "originator_code": originator_code,
                    "originator_name": originator_name,
                    "fips_codes": _cap_fips_codes(alert.raw_json),
                    "issue_time": alert.sent,
                    "purge_time": alert.expires,
                    "station": None,
                    "identifier": alert.identifier,
                    "status": alert.status,
                    "action_taken": action_taken,
                    "action_reason": forwarding_reason,
                    "details": {
                        "message_type": alert.message_type,
                        "scope": alert.scope,
                        "urgency": alert.urgency,
                        "severity": alert.severity,
                        "certainty": alert.certainty,
                        "source": alert.source,
                    },
                }
            )

        # Pull only the columns we actually read from EASMessage + the joined
        # CAPAlert.  audio_data presence is computed at the SQL level so we
        # never transfer the megabyte-scale WAV bytes to Python just to ask
        # "is it non-null?".
        eas_select = (
            select(
                EASMessage.id,
                EASMessage.created_at,
                EASMessage.same_header,
                EASMessage.audio_filename,
                EASMessage.text_filename,
                EASMessage.cap_alert_id,
                EASMessage.audio_data.isnot(None).label("has_audio_blob"),
                EASMessage.text_payload.isnot(None).label("has_text_blob"),
                CAPAlert.event.label("cap_event"),
            )
            .select_from(EASMessage)
            .outerjoin(CAPAlert, EASMessage.cap_alert_id == CAPAlert.id)
            .where(EASMessage.created_at >= window_start)
            .order_by(EASMessage.created_at.desc())
            .execution_options(yield_per=STREAM_BATCH)
        )

        for row in db.session.execute(eas_select):
            same_fields = _parse_same_header_fields(row.same_header)
            originator_code = same_fields.get("originator")
            entries.append(
                {
                    "timestamp": row.created_at,
                    "category": "relayed",
                    "event_label": row.cap_event or (
                        get_event_name(same_fields.get("event_code"))
                        if same_fields.get("event_code")
                        else None
                    ),
                    "event_code": same_fields.get("event_code"),
                    "originator_code": originator_code,
                    "originator_name": get_originator_name(originator_code),
                    "fips_codes": same_fields.get("fips") or [],
                    "issue_time": same_fields.get("issue_time"),
                    "purge_time": _format_purge_minutes(same_fields.get("purge_minutes")),
                    "station": same_fields.get("station"),
                    "identifier": row.same_header,
                    "status": "relayed",
                    "action_taken": "Relayed",
                    "action_reason": None,
                    "details": {
                        "has_audio": bool(row.has_audio_blob or row.audio_filename),
                        "has_text": bool(row.has_text_blob or row.text_filename),
                        "cap_alert_id": row.cap_alert_id,
                    },
                }
            )

        manual_query = (
            ManualEASActivation.query.filter(ManualEASActivation.created_at >= window_start)
            .order_by(ManualEASActivation.created_at.desc())
            .yield_per(STREAM_BATCH)
        )

        for activation in manual_query:
            timestamp = activation.sent_at or activation.created_at
            same_fields = _parse_same_header_fields(activation.same_header)
            originator_code = same_fields.get("originator")
            entries.append(
                {
                    "timestamp": timestamp,
                    "category": "manual",
                    "event_label": activation.event_name,
                    "event_code": activation.event_code or same_fields.get("event_code"),
                    "originator_code": originator_code,
                    "originator_name": get_originator_name(originator_code),
                    "fips_codes": same_fields.get("fips") or [],
                    "issue_time": same_fields.get("issue_time"),
                    "purge_time": _format_purge_minutes(same_fields.get("purge_minutes")),
                    "station": same_fields.get("station"),
                    "identifier": activation.identifier,
                    "status": activation.status,
                    "action_taken": "Initiated",
                    "action_reason": None,
                    "details": {
                        "event_code": activation.event_code,
                        "message_type": activation.message_type,
                        "same_header": activation.same_header,
                    },
                }
            )

        # full_alert_data (JSONB) and raw_audio_data (LargeBinary) are not
        # rendered in the log; deferring them keeps the per-row cost down to
        # the SAME header + a handful of small columns.
        received_query = (
            ReceivedEASAlert.query.options(
                defer(ReceivedEASAlert.full_alert_data),
                defer(ReceivedEASAlert.raw_audio_data),
            )
            .filter(ReceivedEASAlert.received_at >= window_start)
            .order_by(ReceivedEASAlert.received_at.desc())
            .limit(MAX_ENTRIES_PER_CATEGORY)
            .yield_per(STREAM_BATCH)
        )

        for received in received_query:
            same_fields = _parse_same_header_fields(received.raw_same_header)
            originator_code = (
                received.originator_code or same_fields.get("originator")
            )
            originator_name = (
                received.originator_name
                or get_originator_name(originator_code)
            )
            decision = (received.forwarding_decision or "").strip().lower()
            if decision == "forwarded":
                action_taken = "Relayed"
            elif decision == "ignored":
                action_taken = "Not relayed"
            elif decision == "error":
                action_taken = "Decode error"
            else:
                action_taken = "Received"
            entries.append(
                {
                    "timestamp": received.received_at,
                    "category": "off-air",
                    "event_label": received.event_name
                    or get_event_name(received.event_code),
                    "event_code": received.event_code or same_fields.get("event_code"),
                    "originator_code": originator_code,
                    "originator_name": originator_name,
                    "fips_codes": list(received.fips_codes or [])
                    or same_fields.get("fips") or [],
                    "issue_time": received.issue_datetime or same_fields.get("issue_time"),
                    "purge_time": received.purge_datetime
                    or _format_purge_minutes(same_fields.get("purge_minutes")),
                    "station": received.callsign or same_fields.get("station"),
                    "identifier": received.raw_same_header
                    or f"received-eas-{received.id}",
                    "status": received.forwarding_decision or "received",
                    "action_taken": action_taken,
                    "action_reason": (received.forwarding_reason or "").strip() or None,
                    "details": {
                        "source_name": received.source_name,
                        "alert_source": received.alert_source,
                        "decode_confidence": received.decode_confidence,
                        "matched_fips": list(received.matched_fips_codes or []),
                    },
                }
            )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.error("Failed to collect compliance entries: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass

    entries.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)
    return entries, window_start, window_end


def collect_compliance_dashboard_data(
    window_days: int = 30,
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate compliance metrics for dashboard presentation.

    Either supply ``window_days`` for a relative window, or pin the window by
    providing both ``window_start`` and ``window_end`` (explicit bounds win).
    """

    entries, window_start, window_end = collect_compliance_log_entries(
        window_days,
        window_start=window_start,
        window_end=window_end,
    )

    received_total = sum(1 for entry in entries if entry["category"] == "received")
    auto_relay_total = sum(1 for entry in entries if entry["category"] == "relayed")
    manual_relay_total = sum(1 for entry in entries if entry["category"] == "manual")
    relayed_total = auto_relay_total + manual_relay_total

    relay_rate = None
    if received_total:
        relay_rate = (relayed_total / received_total) * 100

    weekly_counts: Dict[datetime, Dict[str, int]] = defaultdict(lambda: {"received": 0, "relayed": 0})

    for entry in entries:
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, datetime):
            continue

        is_test_event = _event_matches_test(entry.get("event_label"))
        details = entry.get("details") or {}
        event_code = str(
            entry.get("event_code") or details.get("event_code") or ""
        ).upper()
        if not is_test_event and event_code not in {"RWT", "RMT"}:
            continue

        week_start = timestamp - timedelta(days=timestamp.weekday())
        week_key = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        category = entry["category"]
        if category == "received":
            weekly_counts[week_key]["received"] += 1
        elif category == "off-air":
            # Off-air ReceivedEASAlert entries can be either received-and-
            # relayed or received-and-ignored; treat them as received unless
            # we actually forwarded them.
            if (entry.get("action_taken") or "").lower() == "relayed":
                weekly_counts[week_key]["relayed"] += 1
            else:
                weekly_counts[week_key]["received"] += 1
        else:
            weekly_counts[week_key]["relayed"] += 1

    weekly_rows = [
        {
            "week_start": key,
            "received": values["received"],
            "relayed": values["relayed"],
            "compliance": (
                (values["relayed"] / values["received"]) * 100
                if values["received"]
                else None
            ),
        }
        for key, values in weekly_counts.items()
    ]
    weekly_rows.sort(key=lambda item: item["week_start"], reverse=True)

    weekly_received_total = sum(row["received"] for row in weekly_rows)
    weekly_relayed_total = sum(row["relayed"] for row in weekly_rows)
    weekly_rate = None
    if weekly_received_total:
        weekly_rate = (weekly_relayed_total / weekly_received_total) * 100

    recent_activity = entries[:25]

    span_seconds = max((window_end - window_start).total_seconds(), 0)
    effective_window_days = max(1, int(round(span_seconds / 86400))) or 1

    return {
        "window_days": effective_window_days,
        "window_start": window_start,
        "window_end": window_end,
        "generated_at": utc_now(),
        "received_vs_relayed": {
            "received": received_total,
            "relayed": relayed_total,
            "auto_relayed": auto_relay_total,
            "manual_relayed": manual_relay_total,
            "relay_rate": relay_rate,
        },
        "weekly_tests": {
            "rows": weekly_rows,
            "received_total": weekly_received_total,
            "relayed_total": weekly_relayed_total,
            "relay_rate": weekly_rate,
        },
        "recent_activity": recent_activity,
        "entries": entries,
    }


def _format_compliance_originator(entry: Dict[str, Any]) -> str:
    """Render the originator code (and name when known) for a log entry."""
    code = (entry.get("originator_code") or "").strip().upper() or None
    name = (entry.get("originator_name") or "").strip() or None
    if code and name and name.lower() != code.lower():
        return f"{code} ({name})"
    if code:
        return code
    if name:
        return name
    return ""


def _format_compliance_fips(entry: Dict[str, Any], *, limit: int = 12) -> str:
    """Render FIPS codes as comma-separated PSSCCC values with an overflow tag.

    The renderer wraps to multiple lines, so we can list far more codes than
    a single-line cell would allow; ``limit`` only kicks in on pathological
    statewide alerts.
    """
    codes = entry.get("fips_codes") or []
    if not codes:
        return ""
    formatted = list(codes)[:limit]
    suffix = "" if len(codes) <= limit else f", +{len(codes) - limit} more"
    return ", ".join(formatted) + suffix


def _format_compliance_issue(entry: Dict[str, Any]) -> str:
    """Render the SAME issue time (datetime or JJJHHMM string) for the log."""
    value = entry.get("issue_time")
    if isinstance(value, datetime):
        return format_local_datetime(value, include_utc=True)
    return str(value or "")


def _format_compliance_purge(entry: Dict[str, Any]) -> str:
    """Render the SAME purge time (datetime, duration string, or empty)."""
    value = entry.get("purge_time")
    if isinstance(value, datetime):
        return format_local_datetime(value, include_utc=True)
    return str(value or "")


_FCC_LOG_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("Timestamp (local)", "_timestamp"),
    ("Category", "category"),
    ("Originator", "_originator"),
    ("Event Code", "event_code"),
    ("Event", "event_label"),
    ("FIPS Codes", "_fips"),
    ("Issue Time", "_issue"),
    ("Purge / Expires", "_purge"),
    ("Station ID", "station"),
    ("Identifier", "identifier"),
    ("Status", "status"),
    ("Action Taken", "action_taken"),
    ("Action Reason", "action_reason"),
    ("Details", "_details_json"),
)


def generate_compliance_log_csv(entries: Sequence[Dict[str, Any]]) -> str:
    """Generate a CSV export for compliance log entries.

    The column layout mirrors the FCC Part 11 logging requirements
    (§§ 11.35(a), 11.54(a)(3)): originator, event code, location codes,
    issue/purge times, station identifier, and the action taken plus reason.
    """

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for label, _ in _FCC_LOG_COLUMNS])

    for entry in entries:
        details = entry.get("details") or {}
        details_json = json_dumps(details, ensure_ascii=False, sort_keys=True)
        derived = {
            "_timestamp": format_local_datetime(
                entry.get("timestamp"), include_utc=True
            ),
            "_originator": _format_compliance_originator(entry),
            "_fips": ", ".join(entry.get("fips_codes") or []),
            "_issue": _format_compliance_issue(entry),
            "_purge": _format_compliance_purge(entry),
            "_details_json": details_json,
        }
        writer.writerow(
            [
                derived.get(key, entry.get(key) if key != "_timestamp" else "")
                if key.startswith("_")
                else (entry.get(key) or "")
                for _, key in _FCC_LOG_COLUMNS
            ]
        )

    return output.getvalue()


_COMPLIANCE_CATEGORY_LABELS: Dict[str, str] = {
    "manual": "Manual",
    "received": "Received",
    "relayed": "Relayed",
    "off-air": "Off-Air",
}


def _format_compliance_details(entry: Dict[str, Any]) -> str:
    """Render the per-entry FCC fields + supplementary details for the PDF.

    The Part 11-required identity fields (originator/event/FIPS/etc.) get
    their own table columns; this string fills the remaining "Details"
    column with the Part 11 fields that didn't get a dedicated column
    (Station ID, Issue Time, Purge Time) plus category-specific extras.
    """
    parts: List[str] = []

    # Station ID has its own table column; do not duplicate it here.
    issue = _format_compliance_issue(entry)
    if issue:
        parts.append(f"Issued: {issue}")
    purge = _format_compliance_purge(entry)
    if purge:
        parts.append(f"Purge: {purge}")
    reason = (entry.get("action_reason") or "").strip()
    if reason:
        parts.append(f"Reason: {reason}")

    details = entry.get("details") or {}
    if isinstance(details, dict):
        cat = (entry.get("category") or "").lower()
        if cat == "received":
            for key in ("severity", "urgency", "certainty"):
                value = details.get(key)
                if value:
                    parts.append(f"{key.title()}: {value}")
        elif cat == "relayed":
            media: List[str] = []
            if details.get("has_audio"):
                media.append("audio")
            if details.get("has_text"):
                media.append("text")
            if media:
                parts.append("Media: " + ", ".join(media))
        elif cat == "off-air":
            src = details.get("source_name") or details.get("alert_source")
            if src:
                parts.append(f"Monitored: {src}")
            confidence = details.get("decode_confidence")
            if isinstance(confidence, (int, float)):
                parts.append(f"Decode: {confidence:.0%}")

    return "; ".join(parts)


def generate_compliance_log_pdf(
    entries: Sequence[Dict[str, Any]],
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> bytes:
    """Generate a paginated PDF summary for compliance log entries."""
    from app_utils.pdf_generator import generate_table_pdf

    if window_start and window_end:
        subtitle = (
            f"Window: {format_local_datetime(window_start, include_utc=False)} "
            f"to {format_local_datetime(window_end, include_utc=False)}"
        )
    else:
        subtitle = None

    # Column layout follows the FCC Part 11 log fields: timestamp, originator
    # (ORG), event code (EEE), location codes (PSSCCC), station identifier
    # (LLLLLLLL — exactly 8 chars per § 11.31), action taken plus the event
    # description and supplemental Details.  Cells wrap to multiple lines
    # (see pdf_generator._wrap_to_width), so weights set the wrap width.
    columns = [
        {"label": "Timestamp (local / UTC)", "weight": 1.3},
        {"label": "Category", "weight": 0.6},
        {"label": "Originator (ORG)", "weight": 1.1},
        {"label": "Event Code", "weight": 0.55},
        {"label": "Event", "weight": 1.5},
        {"label": "FIPS (PSSCCC)", "weight": 1.3},
        {"label": "Station ID (LLLLLLLL)", "weight": 0.9},
        {"label": "Action", "weight": 0.8},
        {"label": "Identifier", "weight": 1.9},
        {"label": "Details", "weight": 2.3},
    ]

    rows: List[List[str]] = []
    category_counts: Dict[str, int] = {}
    originator_counts: Dict[str, int] = {}
    action_counts: Dict[str, int] = {}

    for entry in entries:
        category_raw = (entry.get("category") or "").lower()
        category_label = _COMPLIANCE_CATEGORY_LABELS.get(
            category_raw, category_raw.title() if category_raw else ""
        )
        originator_cell = _format_compliance_originator(entry)
        event_code = (entry.get("event_code") or "").upper()
        action_label = (entry.get("action_taken") or "").strip()
        station_cell = (entry.get("station") or "").strip()

        rows.append([
            format_local_datetime(entry.get("timestamp"), include_utc=True),
            category_label,
            originator_cell,
            event_code,
            str(entry.get("event_label") or ""),
            _format_compliance_fips(entry),
            station_cell,
            action_label,
            str(entry.get("identifier") or ""),
            _format_compliance_details(entry),
        ])

        if category_label:
            category_counts[category_label] = category_counts.get(category_label, 0) + 1
        org_key = (entry.get("originator_code") or "—").upper()
        originator_counts[org_key] = originator_counts.get(org_key, 0) + 1
        if action_label:
            action_counts[action_label] = action_counts.get(action_label, 0) + 1

    summary_lines: List[str] = [f"Total entries: {len(rows)}"]
    if category_counts:
        summary_lines.append(
            "By category: "
            + ", ".join(
                f"{label} ({count})"
                for label, count in sorted(category_counts.items())
            )
        )
    if originator_counts:
        summary_lines.append(
            "By originator (ORG): "
            + ", ".join(
                f"{label} ({count})"
                for label, count in sorted(originator_counts.items())
            )
        )
    if action_counts:
        summary_lines.append(
            "By action: "
            + ", ".join(
                f"{label} ({count})"
                for label, count in sorted(action_counts.items())
            )
        )
    summary_lines.append(
        "Per 47 CFR §§ 11.35(a) and 11.54(a)(3): each entry records the "
        "originator (ORG), event code (EEE), location codes (PSSCCC), "
        "station identifier (LLLLLLLL), issue and purge times, and the "
        "action taken."
    )

    return generate_table_pdf(
        "EAS Part 11 Compliance Log",
        columns,
        rows,
        subtitle=subtitle,
        summary_lines=summary_lines,
        footer_text="EAS Station™ — FCC Part 11 Compliance Log",
        landscape=True,
        empty_message="No compliance activity recorded during this window.",
    )


# ---------------------------------------------------------------------------
# FCC compliance report builders (received / forwarded / ignored / initiated /
# weekly / monthly).  Each builder returns a uniform ``ReportPayload`` dict
# that the PDF and CSV exporters consume.
# ---------------------------------------------------------------------------


REPORT_DECISION_FILTERS: Dict[str, Tuple[str, ...]] = {
    "received": (),  # all decisions
    "forwarded": ("forwarded",),
    "ignored": ("ignored",),
}


def _coerce_aware_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_report_window(
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    days: Optional[int] = None,
) -> Tuple[datetime, datetime]:
    """Resolve a report window from explicit bounds or a relative day count."""
    end_dt = _coerce_aware_utc(end) or utc_now()
    if start is not None:
        start_dt = _coerce_aware_utc(start) or end_dt - timedelta(days=30)
    else:
        window_days = _normalize_window_days(days if days is not None else 30)
        start_dt = end_dt - timedelta(days=window_days)
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    return start_dt, end_dt


def _format_fips(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, (list, tuple, set)):
        return ", ".join(str(v) for v in values)
    return str(values)


def _short(text: Any, limit: int = 80) -> str:
    if text is None:
        return ""
    s = str(text)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


_DECISION_TITLES: Dict[str, str] = {
    "received": "Received Alerts Report",
    "forwarded": "Forwarded Alerts Report",
    "ignored": "Ignored Alerts Report",
}

# Hard ceiling on the number of rows any single report will materialise.
# The export routes accept arbitrary start/end bounds, so a multi-year
# window could otherwise build a list large enough to exhaust the worker.
# Reports that hit the cap say so in their summary block.
REPORT_MAX_ROWS = 25000


def build_received_alerts_report(
    *,
    window_start: datetime,
    window_end: datetime,
    decision: str = "received",
) -> Dict[str, Any]:
    """Build a per-category report covering received_eas_alerts rows.

    ``decision`` selects ``received`` (all), ``forwarded`` or ``ignored``.
    """
    decision_key = decision if decision in REPORT_DECISION_FILTERS else "received"
    filters = REPORT_DECISION_FILTERS[decision_key]

    # Select only the columns the report prints.  Loading whole
    # ``ReceivedEASAlert`` ORM rows drags along ``raw_audio_data``
    # (LargeBinary WAV capture, ~1 MB per alert) and ``full_alert_data``
    # (JSONB) — none of which appear in the output.  On a month of traffic
    # that was hundreds of megabytes of working set per request, enough to
    # get the gunicorn worker OOM-killed, which surfaces to the user as a
    # 502 gateway error on /logs?type=report_received.
    stmt = (
        select(
            ReceivedEASAlert.received_at,
            ReceivedEASAlert.event_code,
            ReceivedEASAlert.event_name,
            ReceivedEASAlert.originator_code,
            ReceivedEASAlert.callsign,
            ReceivedEASAlert.source_name,
            ReceivedEASAlert.matched_fips_codes,
            ReceivedEASAlert.fips_codes,
            ReceivedEASAlert.forwarding_decision,
            ReceivedEASAlert.forwarding_reason,
        )
        .where(
            ReceivedEASAlert.received_at >= window_start,
            ReceivedEASAlert.received_at < window_end,
        )
        .order_by(ReceivedEASAlert.received_at.desc())
        .limit(REPORT_MAX_ROWS)
        .execution_options(yield_per=500)
    )
    if filters:
        stmt = stmt.where(ReceivedEASAlert.forwarding_decision.in_(filters))

    rows: List[List[Any]] = []
    forwarded_count = 0
    ignored_count = 0
    error_count = 0
    for alert in db.session.execute(stmt):
        decision_value = (alert.forwarding_decision or "").lower()
        if decision_value == "forwarded":
            forwarded_count += 1
        elif decision_value == "ignored":
            ignored_count += 1
        elif decision_value == "error":
            error_count += 1
        rows.append([
            format_local_datetime(alert.received_at, include_utc=True),
            alert.event_code or "",
            _short(alert.event_name, 40),
            alert.originator_code or "",
            alert.callsign or alert.source_name or "",
            _format_fips(alert.matched_fips_codes or alert.fips_codes),
            (alert.forwarding_decision or "").upper(),
            _short(alert.forwarding_reason, 60),
        ])

    columns = [
        {"label": "Received (local / UTC)", "weight": 2.4},
        {"label": "Event", "weight": 0.7},
        {"label": "Description", "weight": 2.0},
        {"label": "Originator", "weight": 0.8},
        {"label": "Callsign / Source", "weight": 1.4},
        {"label": "FIPS", "weight": 1.5},
        {"label": "Decision", "weight": 1.0},
        {"label": "Reason", "weight": 2.4},
    ]

    title = _DECISION_TITLES[decision_key]
    subtitle = (
        f"Window: {format_local_datetime(window_start, include_utc=False)}"
        f" to {format_local_datetime(window_end, include_utc=False)}"
    )

    summary_lines = [
        f"Total entries:    {len(rows)}",
        f"Forwarded:        {forwarded_count}",
        f"Ignored:          {ignored_count}",
        f"Errors:           {error_count}",
    ]
    if len(rows) >= REPORT_MAX_ROWS:
        summary_lines.append(
            f"Note: truncated to the newest {REPORT_MAX_ROWS} entries — "
            "narrow the reporting window to see the rest."
        )

    slug = f"{decision_key}-alerts"
    return {
        "slug": slug,
        "title": title,
        "subtitle": subtitle,
        "columns": columns,
        "rows": rows,
        "summary_lines": summary_lines,
        "window_start": window_start,
        "window_end": window_end,
        "row_count": len(rows),
    }


def build_initiated_alerts_report(
    *,
    window_start: datetime,
    window_end: datetime,
) -> Dict[str, Any]:
    """Alerts initiated by this station: auto-relays plus manual activations."""

    # Column-level selects, not whole ORM rows: ``EASMessage`` carries six
    # LargeBinary audio columns and ``CAPAlert`` carries ``raw_json`` plus a
    # PostGIS ``geom``.  A joined eager load of both to print two strings is
    # what pushed this report past the worker's memory ceiling and turned
    # /logs?type=report_initiated into a 502 gateway error.
    auto_stmt = (
        select(
            EASMessage.created_at,
            EASMessage.same_header,
            CAPAlert.event,
            CAPAlert.identifier,
        )
        .select_from(EASMessage)
        .outerjoin(CAPAlert, EASMessage.cap_alert_id == CAPAlert.id)
        .where(
            EASMessage.created_at >= window_start,
            EASMessage.created_at < window_end,
        )
        .order_by(EASMessage.created_at.desc())
        .limit(REPORT_MAX_ROWS)
        .execution_options(yield_per=500)
    )
    manual_stmt = (
        select(
            ManualEASActivation.sent_at,
            ManualEASActivation.created_at,
            ManualEASActivation.event_name,
            ManualEASActivation.event_code,
            ManualEASActivation.same_header,
            ManualEASActivation.status,
            ManualEASActivation.identifier,
        )
        .where(
            ManualEASActivation.created_at >= window_start,
            ManualEASActivation.created_at < window_end,
        )
        .order_by(ManualEASActivation.created_at.desc())
        .limit(REPORT_MAX_ROWS)
        .execution_options(yield_per=500)
    )

    rows: List[List[Any]] = []
    auto_count = 0
    manual_count = 0

    for message in db.session.execute(auto_stmt):
        auto_count += 1
        rows.append([
            format_local_datetime(message.created_at, include_utc=True),
            "AUTO",
            message.event or "",
            "",
            _short(message.same_header, 50),
            "relayed",
            _short(message.identifier or "", 40),
        ])

    for activation in db.session.execute(manual_stmt):
        manual_count += 1
        ts = activation.sent_at or activation.created_at
        rows.append([
            format_local_datetime(ts, include_utc=True),
            "MANUAL",
            activation.event_name or activation.event_code or "",
            activation.event_code or "",
            _short(activation.same_header, 50),
            activation.status or "",
            _short(activation.identifier, 40),
        ])

    rows.sort(key=lambda r: r[0], reverse=True)
    truncated = auto_count >= REPORT_MAX_ROWS or manual_count >= REPORT_MAX_ROWS

    columns = [
        {"label": "Initiated (local / UTC)", "weight": 2.4},
        {"label": "Source", "weight": 0.7},
        {"label": "Event", "weight": 1.6},
        {"label": "Code", "weight": 0.6},
        {"label": "SAME Header", "weight": 3.0},
        {"label": "Status", "weight": 1.0},
        {"label": "Identifier", "weight": 1.8},
    ]

    subtitle = (
        f"Window: {format_local_datetime(window_start, include_utc=False)}"
        f" to {format_local_datetime(window_end, include_utc=False)}"
    )
    summary_lines = [
        f"Total initiated:  {auto_count + manual_count}",
        f"Automated relay:  {auto_count}",
        f"Manual activation:{manual_count}",
    ]
    if truncated:
        summary_lines.append(
            f"Note: truncated to the newest {REPORT_MAX_ROWS} entries per source — "
            "narrow the reporting window to see the rest."
        )

    return {
        "slug": "initiated-alerts",
        "title": "Initiated Alerts Report",
        "subtitle": subtitle,
        "columns": columns,
        "rows": rows,
        "summary_lines": summary_lines,
        "window_start": window_start,
        "window_end": window_end,
        "row_count": len(rows),
    }


def _bucket_received(
    window_start: datetime, window_end: datetime
) -> List[Any]:
    """Return lightweight Row tuples (received_at, forwarding_decision,
    event_code, event_name) for ReceivedEASAlert in the window.

    The full ORM object carries ``full_alert_data`` (JSONB) and
    ``raw_audio_data`` (LargeBinary), both potentially multi-megabyte.
    Loading them just to read four small columns has OOM'd workers in the
    past, so we pull only what the report uses.
    """
    stmt = (
        select(
            ReceivedEASAlert.received_at,
            ReceivedEASAlert.forwarding_decision,
            ReceivedEASAlert.event_code,
            ReceivedEASAlert.event_name,
        )
        .where(
            ReceivedEASAlert.received_at >= window_start,
            ReceivedEASAlert.received_at < window_end,
        )
        .order_by(ReceivedEASAlert.received_at.asc())
        .execution_options(yield_per=500)
    )
    return list(db.session.execute(stmt))


def _bucket_initiated(window_start: datetime, window_end: datetime) -> List[Tuple[datetime, str]]:
    """Return ``(timestamp, source)`` pairs for every initiated EAS message
    in the window.

    EASMessage carries six LargeBinary audio columns; loading the full ORM
    row to read ``created_at`` is the difference between a few KB and a few
    GB of working set on a busy month.  We pull just the timestamps.
    """
    items: List[Tuple[datetime, str]] = []
    eas_stmt = (
        select(EASMessage.created_at)
        .where(
            EASMessage.created_at >= window_start,
            EASMessage.created_at < window_end,
        )
        .execution_options(yield_per=500)
    )
    for (created_at,) in db.session.execute(eas_stmt):
        items.append((created_at, "auto"))
    manual_stmt = (
        select(
            ManualEASActivation.sent_at,
            ManualEASActivation.created_at,
        )
        .where(
            ManualEASActivation.created_at >= window_start,
            ManualEASActivation.created_at < window_end,
        )
        .execution_options(yield_per=500)
    )
    for sent_at, created_at in db.session.execute(manual_stmt):
        items.append((sent_at or created_at, "manual"))
    return items


def _iso_week_start(dt: datetime) -> datetime:
    aware = _coerce_aware_utc(dt) or dt
    monday = aware - timedelta(days=aware.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(dt: datetime) -> datetime:
    aware = _coerce_aware_utc(dt) or dt
    return aware.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _bucket_summary_report(
    *,
    window_start: datetime,
    window_end: datetime,
    period: str,
) -> Dict[str, Any]:
    received_alerts = _bucket_received(window_start, window_end)
    initiated_items = _bucket_initiated(window_start, window_end)

    if period == "weekly":
        bucket_fn = _iso_week_start
        bucket_label = "Week starting"
        title = "Weekly Compliance Summary"
        slug = "weekly-summary"
    else:
        bucket_fn = _month_start
        bucket_label = "Month"
        title = "Monthly Compliance Summary"
        slug = "monthly-summary"

    buckets: Dict[datetime, Dict[str, int]] = defaultdict(
        lambda: {
            "received": 0,
            "forwarded": 0,
            "ignored": 0,
            "errors": 0,
            "tests": 0,
            "auto_initiated": 0,
            "manual_initiated": 0,
        }
    )

    for alert in received_alerts:
        ts = _coerce_aware_utc(alert.received_at)
        if ts is None:
            continue
        key = bucket_fn(ts)
        bucket = buckets[key]
        bucket["received"] += 1
        decision = (alert.forwarding_decision or "").lower()
        if decision == "forwarded":
            bucket["forwarded"] += 1
        elif decision == "ignored":
            bucket["ignored"] += 1
        elif decision == "error":
            bucket["errors"] += 1
        if (alert.event_code or "").upper() in {"RWT", "RMT"} or _event_matches_test(alert.event_name):
            bucket["tests"] += 1

    for ts, source in initiated_items:
        ts_aware = _coerce_aware_utc(ts)
        if ts_aware is None:
            continue
        key = bucket_fn(ts_aware)
        bucket = buckets[key]
        if source == "auto":
            bucket["auto_initiated"] += 1
        else:
            bucket["manual_initiated"] += 1

    sorted_keys = sorted(buckets.keys(), reverse=True)

    rows: List[List[Any]] = []
    totals = {
        "received": 0,
        "forwarded": 0,
        "ignored": 0,
        "errors": 0,
        "tests": 0,
        "auto_initiated": 0,
        "manual_initiated": 0,
    }
    for key in sorted_keys:
        b = buckets[key]
        for k, v in b.items():
            totals[k] += v
        if period == "weekly":
            label = format_local_datetime(key, include_utc=False)
        else:
            local = key
            label = local.strftime("%Y-%m")
        forward_rate = (b["forwarded"] / b["received"] * 100.0) if b["received"] else None
        rate_str = f"{forward_rate:.1f}%" if forward_rate is not None else "—"
        rows.append([
            label,
            b["received"],
            b["forwarded"],
            b["ignored"],
            b["errors"],
            b["tests"],
            b["auto_initiated"],
            b["manual_initiated"],
            rate_str,
        ])

    columns = [
        {"label": bucket_label, "weight": 2.0},
        {"label": "Received", "weight": 1.0},
        {"label": "Forwarded", "weight": 1.0},
        {"label": "Ignored", "weight": 1.0},
        {"label": "Errors", "weight": 0.9},
        {"label": "Tests (RWT/RMT)", "weight": 1.3},
        {"label": "Auto Initiated", "weight": 1.2},
        {"label": "Manual Initiated", "weight": 1.3},
        {"label": "Forward Rate", "weight": 1.1},
    ]

    subtitle = (
        f"Window: {format_local_datetime(window_start, include_utc=False)}"
        f" to {format_local_datetime(window_end, include_utc=False)}"
    )

    forward_rate = (
        (totals["forwarded"] / totals["received"] * 100.0) if totals["received"] else None
    )
    rate_str = f"{forward_rate:.1f}%" if forward_rate is not None else "N/A"
    summary_lines = [
        f"Buckets:           {len(sorted_keys)}",
        f"Received:          {totals['received']}",
        f"Forwarded:         {totals['forwarded']}",
        f"Ignored:           {totals['ignored']}",
        f"Errors:            {totals['errors']}",
        f"Tests (RWT/RMT):   {totals['tests']}",
        f"Auto initiated:    {totals['auto_initiated']}",
        f"Manual initiated:  {totals['manual_initiated']}",
        f"Overall forward rate: {rate_str}",
    ]

    return {
        "slug": slug,
        "title": title,
        "subtitle": subtitle,
        "columns": columns,
        "rows": rows,
        "summary_lines": summary_lines,
        "window_start": window_start,
        "window_end": window_end,
        "row_count": len(rows),
    }


def build_weekly_summary_report(
    *, window_start: datetime, window_end: datetime
) -> Dict[str, Any]:
    return _bucket_summary_report(
        window_start=window_start, window_end=window_end, period="weekly"
    )


def build_monthly_summary_report(
    *, window_start: datetime, window_end: datetime
) -> Dict[str, Any]:
    return _bucket_summary_report(
        window_start=window_start, window_end=window_end, period="monthly"
    )


def generate_report_csv(report: Dict[str, Any]) -> str:
    """Render a report payload as CSV (header row + data + summary block)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([col.get("label", "") for col in report.get("columns", [])])
    for row in report.get("rows", []):
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    summary_lines = report.get("summary_lines") or []
    if summary_lines:
        writer.writerow([])
        writer.writerow(["Summary"])
        for line in summary_lines:
            writer.writerow([line])
    return output.getvalue()


def generate_report_pdf(report: Dict[str, Any]) -> bytes:
    """Render a report payload as a paginated landscape PDF."""
    from app_utils.pdf_generator import generate_table_pdf

    return generate_table_pdf(
        report.get("title", "Compliance Report"),
        report.get("columns", []),
        report.get("rows", []),
        subtitle=report.get("subtitle"),
        summary_lines=report.get("summary_lines"),
        landscape=True,
    )


REPORT_BUILDERS = {
    "received": lambda **kw: build_received_alerts_report(decision="received", **kw),
    "forwarded": lambda **kw: build_received_alerts_report(decision="forwarded", **kw),
    "ignored": lambda **kw: build_received_alerts_report(decision="ignored", **kw),
    "initiated": build_initiated_alerts_report,
    "weekly": build_weekly_summary_report,
    "monthly": build_monthly_summary_report,
}


def determine_alert_precedence(alert: CAPAlert) -> Optional[str]:
    """
    Determine the FCC precedence level for a CAP alert.

    Args:
        alert: CAPAlert database model instance

    Returns:
        String name of precedence level, or None if cannot be determined
    """
    if not PRECEDENCE_AVAILABLE or not PrecedenceLevel:
        return None

    try:
        from app_core.audio.playout_queue import PlayoutItem

        # Use the PlayoutItem logic to determine precedence
        metadata = alert.raw_json or {}
        event_code = None

        # Try to extract event code from metadata
        if isinstance(metadata, dict):
            event_code = metadata.get('event_code')

        precedence_value = PlayoutItem._determine_precedence(
            event_code=event_code,
            scope=alert.scope,
            message_type=alert.message_type,
        )

        return PrecedenceLevel(precedence_value).name

    except Exception:
        return None


def get_precedence_statistics(
    alerts: Sequence[CAPAlert],
) -> Dict[str, Any]:
    """
    Calculate precedence-based statistics for a set of alerts.

    Args:
        alerts: Sequence of CAPAlert instances

    Returns:
        Dictionary with precedence statistics
    """
    if not PRECEDENCE_AVAILABLE:
        return {'available': False}

    precedence_counts: Dict[str, int] = defaultdict(int)
    severity_counts: Dict[str, int] = defaultdict(int)
    urgency_counts: Dict[str, int] = defaultdict(int)

    for alert in alerts:
        precedence = determine_alert_precedence(alert)
        if precedence:
            precedence_counts[precedence] += 1

        if alert.severity:
            severity_counts[alert.severity.upper()] += 1

        if alert.urgency:
            urgency_counts[alert.urgency.upper()] += 1

    return {
        'available': True,
        'precedence_distribution': dict(precedence_counts),
        'severity_distribution': dict(severity_counts),
        'urgency_distribution': dict(urgency_counts),
        'total_alerts': len(alerts),
    }


def enrich_playout_events_with_precedence(
    events: List[Dict[str, Any]],
    alerts_by_id: Dict[int, CAPAlert],
) -> List[Dict[str, Any]]:
    """
    Enrich playout event records with precedence information.

    Args:
        events: List of playout event dictionaries
        alerts_by_id: Mapping of alert IDs to CAPAlert instances

    Returns:
        Updated events list with precedence metadata
    """
    if not PRECEDENCE_AVAILABLE:
        return events

    for event in events:
        alert_id = event.get('alert_id')
        if alert_id and alert_id in alerts_by_id:
            alert = alerts_by_id[alert_id]
            precedence = determine_alert_precedence(alert)
            if precedence:
                event['precedence'] = precedence
                event['severity'] = alert.severity
                event['urgency'] = alert.urgency

    return events

