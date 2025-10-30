"""Data export routes for alerts, boundaries, and statistics."""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Flask, jsonify, request
from sqlalchemy import func

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection
from app_utils import (
    format_local_datetime,
    get_location_timezone_name,
    is_alert_expired,
    local_now,
    utc_now,
)


def register(app: Flask, logger) -> None:
    """Attach JSON export endpoints to the Flask app."""

    route_logger = logger.getChild("routes_exports")

    @app.route("/export/alerts")
    def export_alerts():
        try:
            # Add limit parameter to prevent unbounded data loading (default 10,000, max 50,000)
            limit = request.args.get('limit', 10000, type=int)
            limit = min(max(1, limit), 50000)  # Clamp between 1 and 50,000

            alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(limit).all()
            alerts_data: List[Dict[str, Any]] = []

            for alert in alerts:
                sent_local = (
                    format_local_datetime(alert.sent, include_utc=False) if alert.sent else ""
                )
                expires_local = (
                    format_local_datetime(alert.expires, include_utc=False)
                    if alert.expires
                    else ""
                )
                created_local = (
                    format_local_datetime(alert.created_at, include_utc=False)
                    if alert.created_at
                    else ""
                )

                alerts_data.append(
                    {
                        "ID": alert.id,
                        "Identifier": alert.identifier,
                        "Source": alert.source,
                        "Event": alert.event,
                        "Status": alert.status,
                        "Severity": alert.severity or "",
                        "Urgency": alert.urgency or "",
                        "Certainty": alert.certainty or "",
                        "Sent_Local_Time": sent_local,
                        "Expires_Local_Time": expires_local,
                        "Sent_UTC": alert.sent.isoformat() if alert.sent else "",
                        "Expires_UTC": alert.expires.isoformat() if alert.expires else "",
                        "Headline": alert.headline or "",
                        "Area_Description": alert.area_desc or "",
                        "Created_Local_Time": created_local,
                        "Is_Expired": is_alert_expired(alert.expires),
                    }
                )

            return jsonify(
                {
                    "data": alerts_data,
                    "total": len(alerts_data),
                    "limit": limit,
                    "exported_at": utc_now().isoformat(),
                    "exported_at_local": local_now().isoformat(),
                    "timezone": get_location_timezone_name(),
                }
            )
        except Exception as exc:
            route_logger.error("Error exporting alerts: %s", exc)
            return jsonify({"error": "Failed to export alerts data"}), 500

    @app.route("/export/boundaries")
    def export_boundaries():
        try:
            # Add limit parameter to prevent unbounded data loading (default 5,000, max 20,000)
            limit = request.args.get('limit', 5000, type=int)
            limit = min(max(1, limit), 20000)  # Clamp between 1 and 20,000

            boundaries = Boundary.query.order_by(Boundary.type, Boundary.name).limit(limit).all()
            boundaries_data: List[Dict[str, Any]] = []

            for boundary in boundaries:
                created_local = (
                    format_local_datetime(boundary.created_at, include_utc=False)
                    if boundary.created_at
                    else ""
                )
                updated_local = (
                    format_local_datetime(boundary.updated_at, include_utc=False)
                    if boundary.updated_at
                    else ""
                )

                boundaries_data.append(
                    {
                        "ID": boundary.id,
                        "Name": boundary.name,
                        "Type": boundary.type,
                        "Description": boundary.description or "",
                        "Created_Local_Time": created_local,
                        "Updated_Local_Time": updated_local,
                        "Created_UTC": boundary.created_at.isoformat() if boundary.created_at else "",
                        "Updated_UTC": boundary.updated_at.isoformat() if boundary.updated_at else "",
                    }
                )

            return jsonify(
                {
                    "data": boundaries_data,
                    "total": len(boundaries_data),
                    "limit": limit,
                    "exported_at": utc_now().isoformat(),
                    "exported_at_local": local_now().isoformat(),
                    "timezone": get_location_timezone_name(),
                }
            )
        except Exception as exc:
            route_logger.error("Error exporting boundaries: %s", exc)
            return jsonify({"error": "Failed to export boundaries data"}), 500

    @app.route("/export/statistics")
    def export_statistics():
        try:
            stats_data: List[Dict[str, Any]] = [
                {"Metric": "Total Alerts", "Value": CAPAlert.query.count(), "Category": "Alerts"},
                {
                    "Metric": "Active Alerts",
                    "Value": get_active_alerts_query().count(),
                    "Category": "Alerts",
                },
                {
                    "Metric": "Expired Alerts",
                    "Value": get_expired_alerts_query().count(),
                    "Category": "Alerts",
                },
                {
                    "Metric": "Total Boundaries",
                    "Value": Boundary.query.count(),
                    "Category": "Boundaries",
                },
            ]

            severity_stats = (
                db.session.query(CAPAlert.severity, func.count(CAPAlert.id).label("count"))
                .filter(CAPAlert.severity.isnot(None))
                .group_by(CAPAlert.severity)
                .all()
            )
            for severity, count in severity_stats:
                stats_data.append(
                    {
                        "Metric": f"Alerts - {severity}",
                        "Value": count,
                        "Category": "Severity",
                    }
                )

            boundary_stats = (
                db.session.query(Boundary.type, func.count(Boundary.id).label("count"))
                .group_by(Boundary.type)
                .all()
            )
            for boundary_type, count in boundary_stats:
                stats_data.append(
                    {
                        "Metric": f"Boundaries - {boundary_type.title()}",
                        "Value": count,
                        "Category": "Boundary Types",
                    }
                )

            return jsonify(
                {
                    "data": stats_data,
                    "total": len(stats_data),
                    "exported_at": utc_now().isoformat(),
                    "exported_at_local": local_now().isoformat(),
                    "timezone": get_location_timezone_name(),
                }
            )
        except Exception as exc:
            route_logger.error("Error exporting statistics: %s", exc)
            return jsonify({"error": "Failed to export statistics data"}), 500

    @app.route("/export/intersections")
    def export_intersections():
        try:
            intersections = (
                db.session.query(Intersection, CAPAlert, Boundary)
                .join(CAPAlert, Intersection.cap_alert_id == CAPAlert.id)
                .join(Boundary, Intersection.boundary_id == Boundary.id)
                .all()
            )

            intersection_data: List[Dict[str, Any]] = []
            for intersection, alert, boundary in intersections:
                created_local = (
                    format_local_datetime(intersection.created_at, include_utc=False)
                    if intersection.created_at
                    else ""
                )
                alert_sent_local = (
                    format_local_datetime(alert.sent, include_utc=False) if alert.sent else ""
                )

                intersection_data.append(
                    {
                        "Intersection_ID": intersection.id,
                        "Alert_ID": alert.id,
                        "Alert_Identifier": alert.identifier,
                        "Alert_Event": alert.event,
                        "Alert_Severity": alert.severity or "",
                        "Alert_Sent_Local": alert_sent_local,
                        "Boundary_ID": boundary.id,
                        "Boundary_Name": boundary.name,
                        "Boundary_Type": boundary.type,
                        "Intersection_Area": intersection.intersection_area or 0,
                        "Created_Local_Time": created_local,
                        "Created_UTC": intersection.created_at.isoformat() if intersection.created_at else "",
                    }
                )

            return jsonify(
                {
                    "data": intersection_data,
                    "total": len(intersection_data),
                    "exported_at": utc_now().isoformat(),
                    "exported_at_local": local_now().isoformat(),
                    "timezone": get_location_timezone_name(),
                }
            )
        except Exception as exc:
            route_logger.error("Error exporting intersections: %s", exc)
            return jsonify({"error": "Failed to export intersection data"}), 500


__all__ = ["register"]
