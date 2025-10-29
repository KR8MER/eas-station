"""Alert processing helpers shared by the Flask routes and CLI tools."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, Optional, Tuple

from flask import current_app, has_app_context
from sqlalchemy import or_, text

from app_utils import ALERT_SOURCE_NOAA, normalize_alert_source, utc_now

from .extensions import db
from .models import Boundary, CAPAlert, Intersection


_fallback_logger = logging.getLogger("noaa_alerts_systems")


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


def ensure_multipolygon(geometry: Dict[str, object]) -> Dict[str, object]:
    """Convert Polygon GeoJSON objects to MultiPolygon for storage consistency."""

    if geometry.get("type") == "Polygon":
        return {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
    return geometry


def calculate_alert_intersections(alert: CAPAlert) -> int:
    """Calculate intersections between an alert polygon and loaded boundaries."""

    if not alert.geom:
        return 0

    intersections_created = 0

    try:
        boundaries = Boundary.query.all()

        for boundary in boundaries:
            if not boundary.geom:
                continue

            try:
                intersection_result = db.session.execute(
                    text(
                        """
                        SELECT ST_Intersects(:alert_geom, :boundary_geom) as intersects,
                               ST_Area(ST_Intersection(:alert_geom, :boundary_geom)) as area
                        """
                    ),
                    {"alert_geom": alert.geom, "boundary_geom": boundary.geom},
                ).fetchone()

                if intersection_result and intersection_result.intersects:
                    db.session.query(Intersection).filter_by(
                        cap_alert_id=alert.id,
                        boundary_id=boundary.id,
                    ).delete()

                    intersection = Intersection(
                        cap_alert_id=alert.id,
                        boundary_id=boundary.id,
                        intersection_area=float(intersection_result.area)
                        if intersection_result.area
                        else 0.0,
                        created_at=utc_now(),
                    )
                    db.session.add(intersection)
                    intersections_created += 1

                    _logger().debug(
                        "Created intersection: Alert %s <-> Boundary %s",
                        alert.identifier,
                        boundary.name,
                    )

            except Exception as exc:  # pragma: no cover - defensive
                _logger().error(
                    "Error calculating intersection for boundary %s: %s",
                    boundary.id,
                    exc,
                )
                continue

    except Exception as exc:  # pragma: no cover - defensive
        _logger().error(
            "Error in calculate_alert_intersections for alert %s: %s",
            alert.identifier,
            exc,
        )
        raise

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
