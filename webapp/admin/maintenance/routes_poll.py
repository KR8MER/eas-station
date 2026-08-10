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

"""Triggering an out-of-band poll of the alert feeds."""

from flask import current_app, jsonify

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import SystemLog
from app_utils import local_now, utc_now

from .blueprint import maintenance_bp


@maintenance_bp.route("/admin/trigger_poll", methods=["POST"])
@require_permission('system.configure')
def trigger_poll():
    try:
        log_entry = SystemLog(
            level="INFO",
            message="Manual CAP poll triggered",
            module="admin",
            details={
                "triggered_at_utc": utc_now().isoformat(),
                "triggered_at_local": local_now().isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({"message": "CAP poll triggered successfully"})
    except Exception as exc:
        current_app.logger.error("Error triggering poll: %s", exc)
        return jsonify({"error": str(exc)}), 500
