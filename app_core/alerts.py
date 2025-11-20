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

"""Alert processing helpers shared by the Flask routes and CLI tools."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, List, Optional, Sequence, Set, Tuple

from flask import current_app, has_app_context
from sqlalchemy import or_, text

from app_utils import ALERT_SOURCE_NOAA, normalize_alert_source, utc_now

from .extensions import db
from .models import CAPAlert, EASMessage, Intersection


_INVALID_BOUNDARY_IDS_LOGGED: Set[object] = set()


def _log_invalid_boundary_geometries():
    """Log boundaries with invalid geometries so they can be corrected."""

    invalid_boundaries = db.session.execute(
        text(
            """
            SELECT id, name
            FROM boundaries
            WHERE geom IS NOT NULL
              AND NOT ST_IsValid(geom)
            """
        )
    ).all()

    for boundary in invalid_boundaries:
        if boundary.id in _INVALID_BOUNDARY_IDS_LOGGED:
            continue

        _INVALID_BOUNDARY_IDS_LOGGED.add(boundary.id)
        _logger().warning(
            "Skipping invalid boundary geometry %s (%s)",
            boundary.id,
            boundary.name,
        )


def _fetch_bulk_intersections(alert_geom) -> List[Dict[str, object]]:
    """Return intersecting boundaries using a single SQL query."""

    _log_invalid_boundary_geometries()

    rows = db.session.execute(
        text(
            """
            SELECT id, name,
                   ST_Area(ST_Intersection(:alert_geom, geom)) AS intersection_area
            FROM boundaries
            WHERE geom IS NOT NULL
              AND ST_IsValid(geom)
              AND ST_Intersects(:alert_geom, geom)
            """
        ),
        {"alert_geom": alert_geom},
    ).all()

    intersections: List[Dict[str, object]] = []
    for row in rows:
        area = float(row.intersection_area) if row.intersection_area is not None else 0.0
        if area <= 0:
            continue
        intersections.append({"id": row.id, "name": row.name, "intersection_area": area})

    return intersections


def _fetch_intersections_per_boundary(alert: CAPAlert, alert_geom) -> List[Dict[str, object]]:
    """Fallback path that processes each boundary individually."""

    boundaries = db.session.execute(
        text(
            """
            SELECT id, name, geom
            FROM boundaries
            WHERE geom IS NOT NULL
            """
        )
    ).all()

    intersections: List[Dict[str, object]] = []

    for boundary in boundaries:
        boundary_geom = getattr(boundary, "geom", None)
        if boundary_geom is None:
            continue

        if isinstance(boundary_geom, memoryview):
            boundary_geom_param = boundary_geom.tobytes()
        elif isinstance(boundary_geom, (bytes, bytearray)):
            boundary_geom_param = bytes(boundary_geom)
        else:
            boundary_geom_param = boundary_geom

        try:
            result = db.session.execute(
                text(
                    """
                    WITH boundary AS (
                        SELECT ST_GeomFromEWKB(:boundary_geom) AS geom
                    )
                    SELECT
                        ST_Intersects(:alert_geom, boundary.geom) AS intersects,
                        ST_Area(ST_Intersection(:alert_geom, boundary.geom)) AS intersection_area
                    FROM boundary
                    """
                ),
                {"alert_geom": alert_geom, "boundary_geom": boundary_geom_param},
            ).one()
        except Exception as exc:  # pragma: no cover - defensive
            _logger().error(
                "Error calculating intersection for boundary %s: %s",
                boundary.id,
                exc,
            )
            continue

        if not result.intersects:
            continue

        area = float(result.intersection_area) if result.intersection_area is not None else 0.0
        if area <= 0:
            continue

        intersections.append(
            {"id": boundary.id, "name": boundary.name, "intersection_area": area}
        )

    return intersections


_fallback_logger = logging.getLogger("eas_station")


def _logger():
    if has_app_context():
        return current_app.logger
    return _fallback_logger


def get_active_alerts_query():
    """Return a query for active (non-expired) alerts."""

    now = utc_now()
    return CAPAlert.query.filter(
        or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
    ).filter(CAPAlert.status != "Expired")


def get_expired_alerts_query():
    """Return a query for expired alerts."""

    now = utc_now()
    return CAPAlert.query.filter(CAPAlert.expires < now)


def _extract_text_from_payload(payload: Dict[str, object]) -> Optional[str]:
    """Best-effort extraction of narration text from an EAS summary payload."""

    if not isinstance(payload, dict):
        return None

    candidate_keys = (
        "message_text",
        "plain_text",
        "summary",
        "description",
        "headline",
        "instruction",
    )
    for key in candidate_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_alert_plain_text_map(alert_ids: Sequence[int]) -> Dict[int, str]:
    """Return a mapping of CAP alert IDs to EAS narration text."""

    if not alert_ids:
        return {}

    rows = (
        db.session.query(EASMessage)
        .filter(EASMessage.cap_alert_id.in_(alert_ids))
        .order_by(EASMessage.cap_alert_id.asc(), EASMessage.created_at.desc())
        .all()
    )

    plain_text_map: Dict[int, str] = {}
    seen: Set[int] = set()

    for message in rows:
        if not message.cap_alert_id or message.cap_alert_id in seen:
            continue

        payload_text: Optional[str] = None
        if isinstance(message.text_payload, dict):
            payload_text = _extract_text_from_payload(message.text_payload)

        if not payload_text and message.text_filename:
            try:  # pragma: no cover - defensive disk cache fallback
                from app_core.eas_storage import load_or_cache_summary_payload

                payload = load_or_cache_summary_payload(message)
            except Exception:
                payload = None
            if payload:
                payload_text = _extract_text_from_payload(payload)

        if payload_text:
            plain_text_map[message.cap_alert_id] = payload_text

        seen.add(message.cap_alert_id)

    return plain_text_map


def ensure_multipolygon(geometry: Dict[str, object]) -> Dict[str, object]:
    """Convert Polygon GeoJSON objects to MultiPolygon for storage consistency."""

    if geometry.get("type") == "Polygon":
        return {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
    return geometry


def calculate_alert_intersections(alert: CAPAlert) -> int:
    """Calculate intersections between an alert polygon and loaded boundaries."""

    alert_geom = alert.geom
    if not alert_geom:
        return 0

    try:
        intersecting_boundaries = _fetch_bulk_intersections(alert_geom)
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        _logger().warning(
            "Bulk intersection query failed for alert %s, falling back to per-boundary processing: %s",
            alert.identifier,
            exc,
        )
        intersecting_boundaries = _fetch_intersections_per_boundary(alert, alert_geom)

    if not intersecting_boundaries:
        try:
            db.session.query(Intersection).filter_by(
                cap_alert_id=alert.id
            ).delete(synchronize_session=False)
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            _logger().error(
                "Error clearing intersections for alert %s: %s",
                alert.identifier,
                exc,
            )
            raise

        return 0

    created_at = utc_now()
    intersections_created = 0
    new_intersections = []
    created_boundary_names = []

    for boundary in intersecting_boundaries:
        new_intersections.append(
            Intersection(
                cap_alert_id=alert.id,
                boundary_id=boundary["id"],
                intersection_area=float(boundary["intersection_area"]),
                created_at=created_at,
            )
        )

        intersections_created += 1
        created_boundary_names.append(boundary["name"])

    try:
        db.session.query(Intersection).filter_by(
            cap_alert_id=alert.id
        ).delete(synchronize_session=False)
        db.session.bulk_save_objects(new_intersections)
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        _logger().error(
            "Error updating intersections for alert %s: %s",
            alert.identifier,
            exc,
        )
        raise

    for boundary_name in created_boundary_names:
        _logger().debug(
            "Created intersection: Alert %s <-> Boundary %s",
            alert.identifier,
            boundary_name,
        )

    return intersections_created


def assign_alert_geometry(alert: CAPAlert, geometry_data: Optional[dict]) -> bool:
    """Assign GeoJSON geometry to an alert record, returning True when data changed."""

    previous_geom = alert.geom

    try:
        if geometry_data and isinstance(geometry_data, dict):
            normalized = (
                ensure_multipolygon(geometry_data)
                if geometry_data.get("type") == "Polygon"
                else geometry_data
            )
            geom_json = json.dumps(normalized)
            alert.geom = db.session.execute(
                text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)"),
                {"geom": geom_json},
            ).scalar()
        else:
            alert.geom = None
    except Exception as exc:  # pragma: no cover - defensive
        _logger().warning(
            "Failed to assign geometry for alert %s: %s",
            getattr(alert, "identifier", "?"),
            exc,
        )
        alert.geom = None

    return previous_geom != alert.geom


def parse_noaa_cap_alert(alert_payload: dict) -> Optional[Tuple[dict, Optional[dict]]]:
    """Parse a NOAA API alert payload into CAPAlert column values and geometry."""

    try:
        properties = alert_payload.get("properties", {}) or {}
        geometry = alert_payload.get("geometry")

        identifier = properties.get("identifier")
        if not identifier:
            event_name = properties.get("event", "Unknown")
            sent_value = properties.get("sent", "") or ""
            hash_input = f"{event_name}:{sent_value}:{utc_now().isoformat()}"
            identifier = f"manual_{hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:16]}"

        sent_value = properties.get("sent")
        expires_value = properties.get("expires")

        from app import parse_nws_datetime  # local import to avoid circular

        sent_dt = parse_nws_datetime(sent_value) if sent_value else None
        expires_dt = parse_nws_datetime(expires_value) if expires_value else None

        area_desc = properties.get("areaDesc", "")
        if isinstance(area_desc, list):
            area_desc = "; ".join([part for part in area_desc if part])

        parsed = {
            "identifier": identifier,
            "sent": sent_dt or utc_now(),
            "expires": expires_dt,
            "status": properties.get("status", "Unknown"),
            "message_type": properties.get("messageType", "Unknown"),
            "scope": properties.get("scope", "Unknown"),
            "category": properties.get("category", "Unknown"),
            "event": properties.get("event", "Unknown"),
            "urgency": properties.get("urgency", "Unknown"),
            "severity": properties.get("severity", "Unknown"),
            "certainty": properties.get("certainty", "Unknown"),
            "area_desc": area_desc or "",
            "headline": properties.get("headline", "") or "",
            "description": properties.get("description", "") or "",
            "instruction": properties.get("instruction", "") or "",
            "raw_json": alert_payload,
            "source": normalize_alert_source(properties.get("source") or ALERT_SOURCE_NOAA),
        }

        return parsed, geometry
    except Exception as exc:  # pragma: no cover - defensive
        _logger().error("Failed to parse NOAA alert payload: %s", exc)
        return None


__all__ = [
    "assign_alert_geometry",
    "calculate_alert_intersections",
    "ensure_multipolygon",
    "get_active_alerts_query",
    "get_expired_alerts_query",
    "parse_noaa_cap_alert",
]
