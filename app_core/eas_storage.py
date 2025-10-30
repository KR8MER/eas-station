"""Helpers for managing persisted EAS audio and metadata payloads."""

from __future__ import annotations

import csv
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from flask import current_app
from sqlalchemy import or_, text
from sqlalchemy.orm import joinedload

from app_core.extensions import db
from app_core.models import CAPAlert, EASMessage, ManualEASActivation
from app_utils.time import format_local_datetime, utc_now


TEST_EVENT_KEYWORDS = (
    "Required Weekly Test",
    "Required Monthly Test",
    "RWT",
    "RMT",
)


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

    column_definitions = {
        "audio_data": "BYTEA",
        "eom_audio_data": "BYTEA",
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
            .options(joinedload(CAPAlert.eas_messages))
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

