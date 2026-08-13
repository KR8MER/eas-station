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
    """Calculate and store intersections for a specific alert."""

    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        if not alert.geom:
            return jsonify({"error": f"Alert {alert_id} has no geometry"}), 400

        existing_count = Intersection.query.filter_by(
            cap_alert_id=alert_id
        ).count()
        if existing_count > 0:
            Intersection.query.filter_by(cap_alert_id=alert_id).delete()
            current_app.logger.info(
                "Removed %s existing intersections for alert %s",
                existing_count,
                alert_id,
            )

        boundaries = Boundary.query.all()
        if not boundaries:
            return (
                jsonify(
                    {
                        "error": "No boundaries found in database. Upload some boundary files first.",
                    }
                ),
                400,
            )

        intersections_created = 0
        intersections_with_area = 0

        for boundary in boundaries:
            if not boundary.geom:
                continue

            result = db.session.query(
                func.ST_Intersects(alert.geom, func.ST_MakeValid(boundary.geom)).label("intersects"),
                func.ST_Area(
                    func.ST_Intersection(alert.geom, func.ST_MakeValid(boundary.geom))
                ).label("intersection_area"),
            ).first()

            if result and result.intersects:
                intersection_area = result.intersection_area or 0
                intersection = Intersection(
                    cap_alert_id=alert_id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_area,
                )
                db.session.add(intersection)
                intersections_created += 1
                if intersection_area:
                    intersections_with_area += 1

        db.session.commit()

        return jsonify(
            {
                "success": f"Calculated intersections for alert {alert_id}",
                "intersections_created": intersections_created,
                "intersections_with_area": intersections_with_area,
                "boundaries_checked": len(boundaries),
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
    """Calculate intersections for every alert with geometry."""

    try:
        alerts_with_geom = (
            CAPAlert.query.filter(CAPAlert.geom.isnot(None)).all()
        )

        total_alerts = len(alerts_with_geom)
        total_intersections = 0
        processed_alerts = 0

        for alert in alerts_with_geom:
            Intersection.query.filter_by(cap_alert_id=alert.id).delete()

            boundaries = Boundary.query.all()

            alert_intersections = 0
            for boundary in boundaries:
                if not boundary.geom:
                    continue

                intersection_result = db.session.query(
                    func.ST_Intersects(alert.geom, func.ST_MakeValid(boundary.geom)).label(
                        "intersects"
                    ),
                    func.ST_Area(
                        func.ST_Intersection(alert.geom, func.ST_MakeValid(boundary.geom))
                    ).label("intersection_area"),
                ).first()

                if intersection_result.intersects:
                    intersection = Intersection(
                        cap_alert_id=alert.id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_result.intersection_area
                        or 0,
                    )
                    db.session.add(intersection)
                    alert_intersections += 1

            total_intersections += alert_intersections
            processed_alerts += 1

            if processed_alerts % 10 == 0:
                db.session.commit()
                current_app.logger.info(
                    "Processed %s/%s alerts", processed_alerts, total_alerts
                )

        db.session.commit()

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

        deleted_count = Intersection.query.filter_by(
            cap_alert_id=alert_id
        ).delete()

        boundaries = Boundary.query.all()

        if not boundaries:
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

        intersections_created = 0
        errors = []

        for boundary in boundaries:
            if not boundary.geom:
                continue
            try:
                intersection_query = (
                    db.session.query(
                        func.ST_Area(
                            func.ST_Intersection(alert.geom, func.ST_MakeValid(boundary.geom))
                        ).label("intersection_area"),
                    )
                    .filter(func.ST_Intersects(alert.geom, func.ST_MakeValid(boundary.geom)))
                    .first()
                )

                if (
                    intersection_query
                    and intersection_query.intersection_area
                    and intersection_query.intersection_area > 0
                ):
                    intersection = Intersection(
                        cap_alert_id=alert_id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_query.intersection_area,
                    )
                    db.session.add(intersection)
                    intersections_created += 1

            except Exception as boundary_error:  # pragma: no cover - defensive
                error_msg = f"Boundary {boundary.id}: {boundary_error}"
                errors.append(error_msg)
                current_app.logger.warning(error_msg)

        db.session.commit()

        return jsonify(
            {
                "success": "Successfully calculated"
                f" {intersections_created} boundary intersections",
                "intersections_created": intersections_created,
                "boundaries_tested": len(boundaries),
                "deleted_intersections": deleted_count,
                "errors": errors,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        current_app.logger.error(
            "Error calculating single alert intersections: %s", exc
        )
        return jsonify({"error": f"Failed to calculate intersections: {exc}"}), 500


__all__ = ["register_intersection_routes", "recalculate_active_alert_intersections"]
