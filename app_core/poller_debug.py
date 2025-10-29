"""Utilities for capturing and presenting poller debug information."""

from __future__ import annotations

from typing import Iterable, List

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .models import PollDebugRecord


def ensure_poll_debug_table(logger) -> bool:
    """Ensure the poll_debug_records table exists before it is queried."""

    try:
        PollDebugRecord.__table__.create(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)
        if "poll_debug_records" not in inspector.get_table_names():
            logger.error("poll_debug_records table missing after creation attempt")
            return False
        return True
    except SQLAlchemyError as exc:
        logger.error("Failed to ensure poll_debug_records table: %s", exc)
        return False


def serialise_debug_record(record: PollDebugRecord) -> dict:
    """Convert a ``PollDebugRecord`` into JSON-friendly data for templates."""

    return {
        "id": record.id,
        "created_at": record.created_at,
        "poll_run_id": record.poll_run_id,
        "poll_started_at": record.poll_started_at,
        "poll_status": record.poll_status,
        "data_source": record.data_source,
        "alert_identifier": record.alert_identifier,
        "alert_event": record.alert_event,
        "alert_sent": record.alert_sent,
        "source": record.source,
        "is_relevant": record.is_relevant,
        "relevance_reason": record.relevance_reason,
        "relevance_matches": record.relevance_matches or [],
        "ugc_codes": record.ugc_codes or [],
        "area_desc": record.area_desc,
        "was_saved": record.was_saved,
        "was_new": record.was_new,
        "alert_db_id": record.alert_db_id,
        "parse_success": record.parse_success,
        "parse_error": record.parse_error,
        "polygon_count": record.polygon_count,
        "geometry_type": record.geometry_type,
        "geometry_geojson": record.geometry_geojson,
        "geometry_preview": record.geometry_preview,
        "raw_properties": record.raw_properties,
        "raw_xml_present": record.raw_xml_present,
        "notes": record.notes,
    }


def summarise_run(records: Iterable[PollDebugRecord]) -> dict:
    """Aggregate a poll run into summary metadata plus serialised alerts."""

    serialised: List[dict] = [serialise_debug_record(record) for record in records]
    if not serialised:
        return {"alerts": [], "totals": {}}

    totals = {
        "alerts": len(serialised),
        "accepted": sum(1 for item in serialised if item.get("is_relevant")),
        "saved": sum(1 for item in serialised if item.get("was_saved")),
        "new_saved": sum(1 for item in serialised if item.get("was_new")),
        "parse_failures": sum(1 for item in serialised if not item.get("parse_success")),
    }

    base = serialised[0]
    return {
        "poll_run_id": base.get("poll_run_id"),
        "poll_started_at": base.get("poll_started_at"),
        "poll_status": base.get("poll_status"),
        "data_source": base.get("data_source"),
        "alerts": serialised,
        "totals": totals,
    }


__all__ = [
    "ensure_poll_debug_table",
    "serialise_debug_record",
    "summarise_run",
]
