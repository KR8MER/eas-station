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

"""Data export routes for alerts, boundaries, and statistics."""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from xml.dom import minidom

from flask import Flask, Response, jsonify, request
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

_CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"


def _cap_elem(tag: str, text: str | None = None) -> ET.Element:
    """Create an element in the CAP 1.2 namespace."""
    el = ET.Element(f"{{{_CAP_NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def _alert_to_cap_element(alert: CAPAlert) -> ET.Element:
    """Convert a CAPAlert row to a CAP 1.2 <alert> XML element."""
    root = ET.Element(f"{{{_CAP_NS}}}alert")
    root.set("xmlns", _CAP_NS)

    root.append(_cap_elem("identifier", alert.identifier or f"eas-station-{alert.id}"))
    root.append(_cap_elem("sender", alert.source or "eas-station"))
    root.append(_cap_elem("sent", alert.sent.isoformat() if alert.sent else ""))
    root.append(_cap_elem("status", alert.status or "Actual"))
    root.append(_cap_elem("msgType", "Alert"))
    root.append(_cap_elem("scope", "Public"))

    info = _cap_elem("info")
    info.append(_cap_elem("language", "en-US"))
    info.append(_cap_elem("category", "Met"))
    info.append(_cap_elem("event", alert.event or ""))
    info.append(_cap_elem("urgency", alert.urgency or "Unknown"))
    info.append(_cap_elem("severity", alert.severity or "Unknown"))
    info.append(_cap_elem("certainty", alert.certainty or "Unknown"))

    if alert.sent:
        info.append(_cap_elem("effective", alert.sent.isoformat()))
    if alert.expires:
        info.append(_cap_elem("expires", alert.expires.isoformat()))
    if alert.headline:
        info.append(_cap_elem("headline", alert.headline))

    if alert.area_desc:
        area = _cap_elem("area")
        area.append(_cap_elem("areaDesc", alert.area_desc))
        info.append(area)

    root.append(info)
    return root


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

    @app.route("/export/alerts/cap.xml")
    def export_alerts_cap_xml():
        """Export alerts as OASIS CAP 1.2 XML feed."""
        try:
            limit = request.args.get("limit", 1000, type=int)
            limit = min(max(1, limit), 10000)

            alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(limit).all()

            feed = ET.Element(f"{{{_CAP_NS}}}feed")
            feed.set("xmlns", _CAP_NS)
            feed.set("exported_at", utc_now().isoformat())
            feed.set("count", str(len(alerts)))

            for alert in alerts:
                feed.append(_alert_to_cap_element(alert))

            raw = ET.tostring(feed, encoding="unicode", xml_declaration=False)
            pretty = minidom.parseString(
                f'<?xml version="1.0" encoding="UTF-8"?>{raw}'
            ).toprettyxml(indent="  ", encoding=None)
            # minidom adds its own declaration; strip the one we prepended
            pretty = "\n".join(
                line for line in pretty.splitlines() if line.strip()
            )

            return Response(pretty, mimetype="application/xml; charset=utf-8")
        except Exception as exc:
            route_logger.error("Error exporting CAP XML: %s", exc)
            return Response(
                f"<error>Failed to export CAP XML: {exc}</error>",
                status=500,
                mimetype="application/xml",
            )

    @app.route("/export/alerts/csv")
    def export_alerts_csv():
        """Export alerts as a CSV file download."""
        try:
            from app_utils.export import generate_csv

            limit = request.args.get("limit", 10000, type=int)
            limit = min(max(1, limit), 50000)

            alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(limit).all()
            rows: List[Dict[str, Any]] = []
            for alert in alerts:
                rows.append(
                    {
                        "ID": alert.id,
                        "Identifier": alert.identifier,
                        "Source": alert.source,
                        "Event": alert.event,
                        "Status": alert.status,
                        "Severity": alert.severity or "",
                        "Urgency": alert.urgency or "",
                        "Certainty": alert.certainty or "",
                        "Sent_UTC": alert.sent.isoformat() if alert.sent else "",
                        "Expires_UTC": alert.expires.isoformat() if alert.expires else "",
                        "Sent_Local": format_local_datetime(alert.sent, include_utc=False) if alert.sent else "",
                        "Headline": alert.headline or "",
                        "Area_Description": alert.area_desc or "",
                        "Is_Expired": is_alert_expired(alert.expires),
                    }
                )

            csv_text = generate_csv(rows)
            return Response(
                csv_text,
                mimetype="text/csv",
                headers={"Content-Disposition": 'attachment; filename="eas_alerts.csv"'},
            )
        except Exception as exc:
            route_logger.error("Error exporting alerts CSV: %s", exc)
            return jsonify({"error": "Failed to export CSV"}), 500

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
