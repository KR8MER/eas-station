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

"""The admin alert list and the per-alert detail view."""

from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app, jsonify, request
from sqlalchemy import desc, or_

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.led import ensure_led_tables
from app_core.models import CAPAlert, Intersection, LEDMessage, SystemLog
from app_utils import utc_now

from .blueprint import maintenance_bp
from .noaa import normalize_manual_import_datetime
from .serialization import _alert_datetime_to_iso, serialize_admin_alert


@maintenance_bp.route("/admin/alerts", methods=["GET"])
def admin_list_alerts():
    try:
        include_expired = request.args.get("include_expired", "false").lower() == "true"
        search_term = (request.args.get("search") or "").strip()
        limit_param = request.args.get("limit", type=int)
        limit = 100 if not limit_param else max(1, min(limit_param, 200))

        base_query = CAPAlert.query

        if not include_expired:
            now = utc_now()
            base_query = base_query.filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
            )

        if search_term:
            like_pattern = f"%{search_term}%"
            base_query = base_query.filter(
                or_(
                    CAPAlert.identifier.ilike(like_pattern),
                    CAPAlert.event.ilike(like_pattern),
                    CAPAlert.headline.ilike(like_pattern),
                )
            )

        total_count = base_query.order_by(None).count()
        alerts = (
            base_query.order_by(desc(CAPAlert.sent)).limit(limit).all()
        )

        serialized_alerts = [serialize_admin_alert(alert) for alert in alerts]

        return jsonify(
            {
                "alerts": serialized_alerts,
                "returned": len(serialized_alerts),
                "total": total_count,
                "include_expired": include_expired,
                "limit": limit,
                "search": search_term or None,
            }
        )
    except Exception as exc:
        current_app.logger.error("Failed to load alerts for admin listing: %s", exc)
        return jsonify({"error": "Failed to load alerts."}), 500

@maintenance_bp.route("/admin/alerts/<int:alert_id>", methods=["GET", "PATCH", "DELETE"])
@require_permission('system.configure')
def admin_alert_detail(alert_id: int):
    alert = CAPAlert.query.get(alert_id)
    if not alert:
        return jsonify({"error": "Alert not found."}), 404

    if request.method == "GET":
        return jsonify({"alert": serialize_admin_alert(alert)})

    if request.method == "DELETE":
        identifier = alert.identifier
        try:
            Intersection.query.filter_by(cap_alert_id=alert.id).delete(
                synchronize_session=False
            )

            try:
                if ensure_led_tables():
                    LEDMessage.query.filter_by(alert_id=alert.id).delete(
                        synchronize_session=False
                    )
            except Exception as led_cleanup_error:
                current_app.logger.warning(
                    "Failed to clean LED messages for alert %s during deletion: %s",
                    identifier,
                    led_cleanup_error,
                )
                db.session.rollback()
                return (
                    jsonify(
                        {
                            "error": "Failed to remove LED sign entries linked to this alert.",
                        }
                    ),
                    500,
                )

            db.session.delete(alert)

            log_entry = SystemLog(
                level="WARNING",
                message="Alert deleted from admin interface",
                module="admin",
                details={
                    "alert_id": alert_id,
                    "identifier": identifier,
                    "deleted_at_utc": utc_now().isoformat(),
                },
            )
            db.session.add(log_entry)
            db.session.commit()

            current_app.logger.info("Admin deleted alert %s (%s)", identifier, alert_id)
            return jsonify(
                {"message": f"Alert {identifier} deleted.", "identifier": identifier}
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(
                "Failed to delete alert %s (%s): %s", identifier, alert_id, exc
            )
            return jsonify({"error": "Failed to delete alert."}), 500

    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({"error": "No update payload provided."}), 400

    allowed_fields = {
        "event",
        "headline",
        "description",
        "instruction",
        "area_desc",
        "status",
        "severity",
        "urgency",
        "certainty",
        "category",
        "expires",
    }
    required_non_empty = {"event", "status"}

    updates: Dict[str, Any] = {}
    change_details: Dict[str, Dict[str, Optional[str]]] = {}

    for field in allowed_fields:
        if field not in payload:
            continue

        value = payload[field]

        if field == "expires":
            if value in (None, "", []):
                updates[field] = None
            else:
                normalized = normalize_manual_import_datetime(value)
                if not normalized:
                    return jsonify(
                        {"error": "Could not parse the provided expiration time."}
                    ), 400
                updates[field] = normalized
        else:
            if isinstance(value, str):
                value = value.strip()
            if field in required_non_empty and not value:
                return (
                    jsonify(
                        {
                            "error": f"{field.replace('_', ' ').title()} is required.",
                        }
                    ),
                    400,
                )
            updates[field] = value or None

        previous_value = getattr(alert, field)
        if isinstance(previous_value, datetime):
            previous_rendered = _alert_datetime_to_iso(previous_value)
        else:
            previous_rendered = previous_value

        new_value = updates[field]
        if isinstance(new_value, datetime):
            new_rendered: Optional[str] = new_value.isoformat()
        else:
            new_rendered = new_value

        change_details[field] = {
            "old": previous_rendered,
            "new": new_rendered,
        }

    if not updates:
        return jsonify(
            {"message": "No changes detected.", "alert": serialize_admin_alert(alert)}
        )

    try:
        for field, value in updates.items():
            setattr(alert, field, value)

        alert.updated_at = utc_now()

        log_entry = SystemLog(
            level="INFO",
            message="Alert updated from admin interface",
            module="admin",
            details={
                "alert_id": alert.id,
                "identifier": alert.identifier,
                "changes": change_details,
                "updated_at_utc": alert.updated_at.isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        current_app.logger.info(
            "Admin updated alert %s fields: %s",
            alert.identifier,
            ", ".join(sorted(updates.keys())),
        )

        db.session.refresh(alert)
        return jsonify(
            {
                "message": "Alert updated successfully.",
                "alert": serialize_admin_alert(alert),
            }
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(
            "Failed to update alert %s (%s): %s", alert.identifier, alert.id, exc
        )
        return jsonify({"error": "Failed to update alert."}), 500
