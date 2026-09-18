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

"""Building per-alert delivery records from CAP alerts and their EAS messages."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from flask import current_app

from app_core.extensions import db
from app_core.models import CAPAlert, EASMessage
from app_utils.time import utc_now

from .reports_common import _normalize_window_days


DELIVERED_EVENT_STATUSES = {"delivered", "completed", "success", "ok", "played"}

FAILED_EVENT_STATUSES = {"failed", "error", "timeout", "aborted"}

PENDING_EVENT_STATUSES = {"pending", "queued", "waiting", "scheduled"}

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
