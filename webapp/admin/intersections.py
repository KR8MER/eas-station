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

"""Administrative endpoints for managing alert-boundary intersections."""

from flask import Blueprint, current_app

from typing import Dict

from flask import Flask, jsonify
from sqlalchemy import func

from app_core.alerts import calculate_alert_intersections
from .coverage import try_build_geometry_from_same_codes
from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection, SystemLog
from app_core.auth.roles import require_permission
from app_utils import utc_now


# Create Blueprint for intersections routes
intersections_bp = Blueprint("intersections", __name__)

def register_intersection_routes(app: Flask, logger) -> None:
    """Register routes."""
    
    # Register the blueprint with the app
    app.register_blueprint(intersections_bp)
    logger.info("Intersections routes registered")


# Route definitions

def recalculate_active_alert_intersections() -> Dict[str, int]:
    """Recalculate intersections for every currently-active (unexpired) alert.

    Called automatically after a boundary is uploaded, edited, or replaced
    (see webapp/admin/boundaries.py) so alerts that already existed pick up
    the new/changed boundary immediately, instead of requiring an operator
    to notice and click one of the manual "Fix Intersections" buttons.
    Scoped to active alerts rather than the full history so it stays fast
    enough to run inline in the upload request.
    """
    now = utc_now()
    active_alerts = (
        CAPAlert.query
        .filter(CAPAlert.geom.isnot(None))
        .filter(CAPAlert.expires.isnot(None))
        .filter(CAPAlert.expires > now)
        .all()
    )

    intersections_created = 0
    errors = 0
    for alert in active_alerts:
        try:
            intersections_created += calculate_alert_intersections(alert)
        except Exception as exc:  # pragma: no cover - defensive
            errors += 1
            current_app.logger.error(
                "Error recalculating intersections for alert %s after boundary change: %s",
                alert.identifier, exc,
            )

    db.session.commit()
    return {
        "alerts_processed": len(active_alerts),
        "intersections_created": intersections_created,
        "errors": errors,
    }


@intersections_bp.route("/admin/fix_county_intersections", methods=["POST"])
@require_permission('system.configure')
def fix_county_intersections():
    """Recalculate intersection areas for all alerts with geometry."""

    try:
        all_alerts = CAPAlert.query.filter(CAPAlert.geom.isnot(None)).all()
        total_updated = 0
        errors = 0

        for alert in all_alerts:
            try:
                intersections_created = calculate_alert_intersections(alert)
                total_updated += intersections_created
            except Exception as exc:  # pragma: no cover - defensive
                errors += 1
                current_app.logger.error(
                    "Error recalculating intersections for alert %s: %s",
                    alert.id,
                    exc,
                )

        db.session.commit()

        msg = (
            f"Successfully recalculated intersections for {len(all_alerts)} alerts. "
            f"Updated {total_updated} intersection records."
        )
        if errors:
            msg += f" ({errors} alert(s) had errors)"

        return jsonify(
            {
                "success": msg,
                "alerts_processed": len(all_alerts),
                "intersections_updated": total_updated,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        current_app.logger.error("Error fixing county intersections: %s", exc)
        return jsonify({"error": f"Failed to fix intersections: {exc}"}), 500

@intersections_bp.route("/admin/recalculate_intersections", methods=["POST"])
@require_permission('system.configure')
def recalculate_intersections():
    """Recalculate all alert-boundary intersections."""

    try:
        current_app.logger.info("Starting full intersection recalculation")

        deleted_count = db.session.query(Intersection).delete()
        current_app.logger.info("Cleared %s existing intersections", deleted_count)

        alerts_with_geometry = (
            db.session.query(CAPAlert).filter(CAPAlert.geom.isnot(None)).all()
        )

        stats: Dict[str, int] = {
            "alerts_processed": 0,
            "intersections_created": 0,
            "errors": 0,
            "deleted_intersections": deleted_count,
        }

        for alert in alerts_with_geometry:
            try:
                intersections_created = calculate_alert_intersections(alert)
                stats["alerts_processed"] += 1
                stats["intersections_created"] += intersections_created
            except Exception as exc:  # pragma: no cover - defensive
                stats["errors"] += 1
                current_app.logger.error(
                    "Error processing alert %s: %s", alert.identifier, exc
                )

        db.session.commit()

        message = (
            "Recalculated intersections for {alerts_processed} alerts, created "
            "{intersections_created} new intersections"
        ).format(**stats)
        if stats["errors"] > 0:
            message += f" ({stats['errors']} errors)"

        current_app.logger.info(message)
        return jsonify({"success": message, "stats": stats})
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.error("Error in recalculate_intersections: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to recalculate intersections: {exc}"}), 500

@intersections_bp.route("/admin/calculate_intersections/<int:alert_id>", methods=["POST"])
@require_permission('system.configure')
def calculate_intersections_for_alert(alert_id: int):
    """Calculate and store intersections for a specific alert.

    Uses calculate_alert_intersections() -- the same single-batched-query
    helper the other routes in this module already use -- instead of
    running one PostGIS query per boundary. It already handles clearing
    this alert's existing intersections before inserting the new ones.
    """

    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        if not alert.geom:
            return jsonify({"error": f"Alert {alert_id} has no geometry"}), 400

        boundaries_checked = (
            db.session.query(func.count(Boundary.id))
            .filter(Boundary.geom.isnot(None))
            .scalar()
        ) or 0
        if boundaries_checked == 0:
            return (
                jsonify(
                    {
                        "error": "No boundaries found in database. Upload some boundary files first.",
                    }
                ),
                400,
            )

        intersections_created = calculate_alert_intersections(alert)
        db.session.commit()

        return jsonify(
            {
                "success": f"Calculated intersections for alert {alert_id}",
                "intersections_created": intersections_created,
                # calculate_alert_intersections() only keeps intersections with
                # positive overlap area, so every created row already qualifies.
                "intersections_with_area": intersections_created,
                "boundaries_checked": boundaries_checked,
                "alert_event": alert.event,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        current_app.logger.error(
            "Error calculating intersections for alert %s: %s", alert_id, exc
        )
        return jsonify({"error": str(exc)}), 500

@intersections_bp.route("/admin/calculate_all_intersections", methods=["POST"])
@require_permission('system.configure')
def calculate_all_intersections():
    """Calculate intersections for every alert with geometry.

    Uses calculate_alert_intersections() -- one batched PostGIS query per
    alert across all boundaries -- instead of the previous per-alert,
    per-boundary query loop (with boundaries re-fetched on every alert
    iteration too). With N alerts and M boundaries that was N*M individual
    round-trips instead of N; matches the pattern already used by
    recalculate_intersections()/fix_county_intersections() above, including
    committing once at the end rather than every 10 alerts -- that batching
    existed to keep a very slow loop's uncommitted transaction bounded, which
    is no longer a concern at one query per alert.
    """

    try:
        alerts_with_geom = (
            CAPAlert.query.filter(CAPAlert.geom.isnot(None)).all()
        )

        total_alerts = len(alerts_with_geom)
        total_intersections = 0
        processed_alerts = 0
        errors = 0

        for alert in alerts_with_geom:
            try:
                total_intersections += calculate_alert_intersections(alert)
            except Exception as exc:  # pragma: no cover - defensive
                errors += 1
                current_app.logger.error(
                    "Error calculating intersections for alert %s: %s",
                    alert.identifier, exc,
                )
                continue
            processed_alerts += 1

        db.session.commit()

        if errors:
            current_app.logger.warning(
                "calculate_all_intersections: %s/%s alerts failed", errors, total_alerts
            )

        log_entry = SystemLog(
            level="INFO",
            message="Calculated intersections for all alerts",
            module="admin",
            details={
                "total_alerts_processed": processed_alerts,
                "total_intersections_created": total_intersections,
                "calculated_at": utc_now().isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify(
            {
                "success": "Calculated intersections for all alerts",
                "alerts_processed": processed_alerts,
                "total_intersections_created": total_intersections,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        current_app.logger.error("Error calculating all intersections: %s", exc)
        return jsonify({"error": str(exc)}), 500

@intersections_bp.route("/admin/calculate_single_alert/<int:alert_id>", methods=["POST"])
@require_permission('system.configure')
def calculate_single_alert(alert_id: int):
    """Calculate intersections for a single alert."""

    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        # Always attempt to build/update geometry from available sources.
        # try_build_geometry_from_same_codes prioritises the raw_json polygon
        # over any previously-stored SAME-derived geometry, so this corrects
        # stale county-union geometry whenever the real alert polygon is present.
        from .coverage import try_build_geometry_from_same_codes
        try_build_geometry_from_same_codes(alert_id)
        # Re-fetch to pick up any newly committed geometry.
        alert = CAPAlert.query.get(alert_id)

        if not alert or not alert.geom:
            return jsonify({
                "error": (
                    "Alert has no geometry data. SAME codes may not match any "
                    "county boundaries in the database, or the alert polygon "
                    "could not be parsed."
                )
            }), 400

        boundaries_tested = (
            db.session.query(func.count(Boundary.id))
            .filter(Boundary.geom.isnot(None))
            .scalar()
        ) or 0

        if boundaries_tested == 0:
            return (
                jsonify(
                    {
                        "error": (
                            "No boundaries found in database. Upload some "
                            "boundary files first."
                        )
                    }
                ),
                400,
            )

        # calculate_alert_intersections() clears this alert's existing
        # intersections and inserts the new ones in one batched PostGIS
        # query across all boundaries, instead of one query per boundary.
        intersections_created = calculate_alert_intersections(alert)

        db.session.commit()

        return jsonify(
            {
                "success": "Successfully calculated"
                f" {intersections_created} boundary intersections",
                "intersections_created": intersections_created,
                "boundaries_tested": boundaries_tested,
                "errors": [],
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        current_app.logger.error(
            "Error calculating single alert intersections: %s", exc
        )
        return jsonify({"error": f"Failed to calculate intersections: {exc}"}), 500


__all__ = ["register_intersection_routes", "recalculate_active_alert_intersections"]
