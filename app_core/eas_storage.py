"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Helpers for managing persisted EAS audio and metadata payloads."""

from __future__ import annotations

import csv
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from flask import current_app
from sqlalchemy import or_, text
from sqlalchemy.orm import joinedload

from app_core.extensions import db
from app_core.models import (
    AlertDeliveryReport,
    CAPAlert,
    EASDecodedAudio,
    EASMessage,
    ManualEASActivation,
)
from app_utils import ALERT_SOURCE_UNKNOWN
from app_utils.eas_decode import (
    SAMEAudioDecodeResult,
    build_plain_language_summary,
)
from app_utils.time import format_local_datetime, utc_now

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
    """Return the most recent decoded audio payloads for display."""

    try:
        query = EASDecodedAudio.query.order_by(EASDecodedAudio.created_at.desc())
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
                "has_header_audio": row.header_audio_data is not None,
                "has_message_audio": row.message_audio_data is not None,
                "has_eom_audio": row.eom_audio_data is not None,
                "has_buffer_audio": row.buffer_audio_data is not None,
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
                    text(f"ALTER TABLE eas_messages ADD COLUMN {column} {definition}")
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
                        payload = json.load(handle)
                except (OSError, json.JSONDecodeError) as exc:
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
                    text(f"ALTER TABLE manual_eas_activations ADD COLUMN {column} {definition}")
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
            EASMessage.query.filter(EASMessage.created_at >= window_start)
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


def collect_compliance_log_entries(
    window_days: int = 30,
) -> Tuple[List[Dict[str, Any]], datetime, datetime]:
    """Return compliance activity entries for the requested window."""

    days = _normalize_window_days(window_days)
    window_end = utc_now()
    window_start = window_end - timedelta(days=days)

    entries: List[Dict[str, Any]] = []

    try:
        alert_query = (
            CAPAlert.query.filter(CAPAlert.sent >= window_start)
            .order_by(CAPAlert.sent.desc())
        )

        for alert in alert_query:
            entries.append(
                {
                    "timestamp": alert.sent,
                    "category": "received",
                    "event_label": alert.event,
                    "identifier": alert.identifier,
                    "status": alert.status,
                    "details": {
                        "message_type": alert.message_type,
                        "scope": alert.scope,
                        "urgency": alert.urgency,
                        "severity": alert.severity,
                        "certainty": alert.certainty,
                    },
                }
            )

        eas_query = (
            EASMessage.query.options(joinedload(EASMessage.cap_alert))
            .filter(EASMessage.created_at >= window_start)
            .order_by(EASMessage.created_at.desc())
        )

        for message in eas_query:
            alert = message.cap_alert
            entries.append(
                {
                    "timestamp": message.created_at,
                    "category": "relayed",
                    "event_label": alert.event if alert else None,
                    "identifier": message.same_header,
                    "status": "relayed",
                    "details": {
                        "has_audio": bool(message.audio_data or message.audio_filename),
                        "has_text": bool(message.text_payload or message.text_filename),
                        "cap_alert_id": alert.id if alert else None,
                    },
                }
            )

        manual_query = (
            ManualEASActivation.query.filter(ManualEASActivation.created_at >= window_start)
            .order_by(ManualEASActivation.created_at.desc())
        )

        for activation in manual_query:
            timestamp = activation.sent_at or activation.created_at
            entries.append(
                {
                    "timestamp": timestamp,
                    "category": "manual",
                    "event_label": activation.event_name,
                    "identifier": activation.identifier,
                    "status": activation.status,
                    "details": {
                        "event_code": activation.event_code,
                        "message_type": activation.message_type,
                        "same_header": activation.same_header,
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


def collect_compliance_dashboard_data(window_days: int = 30) -> Dict[str, Any]:
    """Aggregate compliance metrics for dashboard presentation."""

    entries, window_start, window_end = collect_compliance_log_entries(window_days)

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
        event_code = str(details.get("event_code") or "").upper()
        if not is_test_event and event_code not in {"RWT", "RMT"}:
            continue

        week_start = timestamp - timedelta(days=timestamp.weekday())
        week_key = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        if entry["category"] == "received":
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

    return {
        "window_days": _normalize_window_days(window_days),
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


def generate_compliance_log_csv(entries: Sequence[Dict[str, Any]]) -> str:
    """Generate a CSV export for compliance log entries."""

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Timestamp (local)",
        "Category",
        "Event",
        "Identifier",
        "Status",
        "Details",
    ])

    for entry in entries:
        timestamp = format_local_datetime(entry.get("timestamp"), include_utc=True)
        details = entry.get("details") or {}
        details_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
        writer.writerow(
            [
                timestamp,
                entry.get("category"),
                entry.get("event_label"),
                entry.get("identifier"),
                entry.get("status"),
                details_json,
            ]
        )

    return output.getvalue()


def _escape_pdf_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped


def _render_pdf_page(lines: Sequence[str]) -> bytes:
    y = 760
    content_lines = ["BT", "/F1 10 Tf"]
    for line in lines:
        content_lines.append(f"1 0 0 1 40 {y} Tm ({_escape_pdf_text(line)}) Tj")
        y -= 14
        if y < 40:
            y = 760
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", "ignore")
    return stream


def generate_compliance_log_pdf(
    entries: Sequence[Dict[str, Any]],
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> bytes:
    """Generate a minimal PDF summary for compliance logs."""

    header_lines = [
        "NOAA CAP Alerts System — EAS Compliance Log",
        f"Generated: {format_local_datetime(utc_now(), include_utc=True)}",
    ]

    if window_start and window_end:
        header_lines.append(
            "Window: "
            f"{format_local_datetime(window_start, include_utc=False)} "
            f"to {format_local_datetime(window_end, include_utc=False)}"
        )

    header_lines.append("")
    header_lines.append(
        "Timestamp (local/UTC) | Category | Event | Identifier | Status"
    )

    body_lines = []
    for entry in entries:
        timestamp = format_local_datetime(entry.get("timestamp"), include_utc=True)
        body_lines.append(
            " | ".join(
                [
                    timestamp,
                    str(entry.get("category") or ""),
                    str(entry.get("event_label") or ""),
                    str(entry.get("identifier") or ""),
                    str(entry.get("status") or ""),
                ]
            )
        )

    lines = header_lines + (body_lines or ["No compliance activity recorded."])

    pages = []
    current_page: List[str] = []
    for line in lines:
        current_page.append(line)
        if len(current_page) >= 45:
            pages.append(current_page)
            current_page = []

    if current_page:
        pages.append(current_page)

    objects: List[Tuple[int, bytes]] = []
    font_obj_id = 3
    page_objects: List[int] = []
    next_obj_id = 4

    for page_lines in pages:
        content_stream = _render_pdf_page(page_lines)
        content_obj_id = next_obj_id
        next_obj_id += 1

        stream_body = (
            b"<< /Length "
            + str(len(content_stream)).encode("ascii")
            + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        )
        objects.append((content_obj_id, stream_body))

        page_obj_id = next_obj_id
        next_obj_id += 1
        page_objects.append(page_obj_id)

        page_body = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_obj_id} 0 R /Resources << /Font << /F1 {font_obj_id} 0 R >> >> >>"
        ).encode("latin-1")
        objects.append((page_obj_id, page_body))

    pages_body = (
        "<< /Type /Pages /Count {count} /Kids [{kids}] >>".format(
            count=len(page_objects),
            kids=" ".join(f"{obj_id} 0 R" for obj_id in page_objects) or "",
        )
    ).encode("latin-1")

    catalog_body = b"<< /Type /Catalog /Pages 2 0 R >>"
    font_body = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    objects.insert(0, (1, catalog_body))
    objects.insert(1, (2, pages_body))
    objects.insert(2, (font_obj_id, font_body))

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    xref_positions = []
    for obj_id, body in objects:
        xref_positions.append(buffer.tell())
        buffer.write(f"{obj_id} 0 obj\n".encode("latin-1"))
        buffer.write(body)
        buffer.write(b"\nendobj\n")

    startxref = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in xref_positions:
        buffer.write(f"{offset:010d} 00000 n \n".encode("latin-1"))

    buffer.write(b"trailer\n")
    buffer.write(
        f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1")
    )
    buffer.write(f"startxref\n{startxref}\n%%EOF".encode("latin-1"))

    return buffer.getvalue()


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

