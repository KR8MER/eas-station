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

"""Marking alerts expired and clearing expired alerts."""

from flask import current_app, jsonify, request
from sqlalchemy import or_
from sqlalchemy.orm import defer

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import CAPAlert, SystemLog
from app_utils import local_now, utc_now

from .blueprint import maintenance_bp


@maintenance_bp.route("/admin/mark_expired", methods=["POST"])
@require_permission('system.configure')
def mark_expired():
    try:
        now = utc_now()

        # Only status and updated_at are written; the geometry and raw CAP
        # payload of every expiring alert are dead weight here.
        expired_alerts = CAPAlert.query.options(
            defer(CAPAlert.geom),
            defer(CAPAlert.raw_json),
            defer(CAPAlert.certificate_info),
            defer(CAPAlert.description),
            defer(CAPAlert.instruction),
        ).filter(
            CAPAlert.expires < now, CAPAlert.status != "Expired"
        ).all()

        count = len(expired_alerts)

        if count == 0:
            return jsonify({"message": "No alerts need to be marked as expired"})

        for alert in expired_alerts:
            alert.status = "Expired"
            alert.updated_at = now

        db.session.commit()

        log_entry = SystemLog(
            level="INFO",
            message=f"Marked {count} alerts as expired (data preserved)",
            module="admin",
            details={
                "marked_at_utc": now.isoformat(),
                "marked_at_local": local_now().isoformat(),
                "count": count,
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify(
            {
                "message": f"Marked {count} alerts as expired",
                "note": "Alert data has been preserved in the database",
                "marked_count": count,
            }
        )

    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Error marking expired alerts: %s", exc)
        return jsonify({"error": str(exc)}), 500

@maintenance_bp.route("/admin/clear_expired", methods=["POST"])
@require_permission('system.configure')
def clear_expired():
    try:
        now = utc_now()
        payload = request.get_json(silent=True) or {}
        confirmed = payload.get("confirmed", False)

        # Nothing is read off these rows -- they are only counted and passed
        # to db.session.delete() -- so their geometry and raw CAP payloads
        # need never leave the database.
        expired_alerts = CAPAlert.query.options(
            defer(CAPAlert.geom),
            defer(CAPAlert.raw_json),
            defer(CAPAlert.certificate_info),
            defer(CAPAlert.description),
            defer(CAPAlert.instruction),
        ).filter(
            or_(CAPAlert.expires < now, CAPAlert.status == "Expired")
        ).all()

        count = len(expired_alerts)

        if count == 0:
            return jsonify({"message": "No expired alerts found to delete."})

        if not confirmed:
            return jsonify(
                {
                    "requires_confirmation": True,
                    "message": (
                        f"This will permanently delete {count} expired alert(s) "
                        "from the database."
                    ),
                    "warning": "This action cannot be undone. All expired alert data will be lost.",
                    "count": count,
                }
            )

        identifiers = [a.identifier for a in expired_alerts]
        for alert in expired_alerts:
            db.session.delete(alert)

        log_entry = SystemLog(
            level="WARNING",
            message=f"Permanently deleted {count} expired alerts",
            module="admin",
            details={
                "deleted_at_utc": now.isoformat(),
                "deleted_at_local": local_now().isoformat(),
                "count": count,
                "identifiers": identifiers,
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        current_app.logger.warning(
            "Admin permanently deleted %d expired alerts", count
        )

        return jsonify(
            {
                "message": f"Permanently deleted {count} expired alert(s).",
                "deleted_count": count,
            }
        )

    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Error clearing expired alerts: %s", exc)
        return jsonify({"error": str(exc)}), 500
