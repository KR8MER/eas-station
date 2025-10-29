"""Debugging endpoints for inspecting alerts and boundaries."""

from __future__ import annotations

from flask import Flask, jsonify
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection


def register(app: Flask, logger) -> None:
    """Attach debug inspection routes to the Flask app."""

    route_logger = logger.getChild("routes_debug")

    @app.route("/debug/alert/<int:alert_id>")
    def debug_alert(alert_id: int):
        """Inspect intersections for a specific alert."""

        try:
            alert = CAPAlert.query.get_or_404(alert_id)

            geometry_info = {}
            try:
                geom_details = db.session.query(
                    func.ST_GeometryType(alert.geom).label("geom_type"),
                    func.ST_SRID(alert.geom).label("srid"),
                    func.ST_Area(alert.geom).label("area"),
                ).first()
                if geom_details:
                    geometry_info = {
                        "type": geom_details.geom_type,
                        "srid": geom_details.srid,
                        "area": float(geom_details.area) if geom_details.area else 0,
                    }
            except Exception as exc:  # pragma: no cover - defensive
                route_logger.error(
                    "Error retrieving geometry info for alert %s: %s", alert_id, exc
                )

            boundaries = Boundary.query.all()
            intersection_results = []

            for boundary in boundaries:
                try:
                    result = db.session.query(
                        func.ST_Intersects(alert.geom, boundary.geom).label(
                            "intersects"
                        ),
                        func.ST_Area(
                            func.ST_Intersection(alert.geom, boundary.geom)
                        ).label("area"),
                    ).first()

                    intersection_results.append(
                        {
                            "boundary_id": boundary.id,
                            "boundary_name": boundary.name,
                            "boundary_type": boundary.type,
                            "intersects": bool(result.intersects)
                            if result and result.intersects is not None
                            else False,
                            "intersection_area": float(result.area)
                            if result and result.area
                            else 0,
                        }
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    route_logger.error(
                        "Error checking intersection with boundary %s: %s",
                        boundary.id,
                        exc,
                    )

            existing_intersections = (
                db.session.query(Intersection)
                .filter_by(cap_alert_id=alert_id)
                .count()
            )
            boundaries_in_db = Boundary.query.count()

            debug_info = {
                "alert_id": alert_id,
                "alert_event": alert.event,
                "alert_area_desc": alert.area_desc,
                "has_geometry": alert.geom is not None,
                "geometry_info": geometry_info,
                "boundaries_in_db": boundaries_in_db,
                "existing_intersections": existing_intersections,
                "intersection_results": intersection_results,
                "intersections_found": len(
                    [result for result in intersection_results if result["intersects"]]
                ),
                "errors": [],
            }

            return jsonify(debug_info)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error debugging alert %s: %s", alert_id, exc)
            return jsonify({"error": f"Debug failed: {exc}"}), 500

    @app.route("/debug/boundaries/<int:alert_id>")
    def debug_boundaries(alert_id: int):
        """Debug boundary intersections for a specific alert."""

        try:
            alert = CAPAlert.query.get_or_404(alert_id)

            debug_info = {
                "alert_id": alert_id,
                "alert_event": alert.event,
                "alert_area_desc": alert.area_desc,
                "has_geometry": alert.geom is not None,
                "boundaries_in_db": Boundary.query.count(),
                "existing_intersections": Intersection.query.filter_by(
                    cap_alert_id=alert_id
                ).count(),
                "errors": [],
            }

            if not alert.geom:
                debug_info["errors"].append("Alert has no geometry data")
                return jsonify(debug_info)

            boundaries = Boundary.query.all()
            intersection_results = []

            for boundary in boundaries:
                try:
                    intersection_test = db.session.query(
                        func.ST_Intersects(alert.geom, boundary.geom).label(
                            "intersects"
                        ),
                        func.ST_Area(
                            func.ST_Intersection(alert.geom, boundary.geom)
                        ).label("area"),
                    ).first()

                    intersection_results.append(
                        {
                            "boundary_id": boundary.id,
                            "boundary_name": boundary.name,
                            "boundary_type": boundary.type,
                            "intersects": bool(intersection_test.intersects)
                            if intersection_test and intersection_test.intersects is not None
                            else False,
                            "intersection_area": float(intersection_test.area)
                            if intersection_test and intersection_test.area
                            else 0,
                        }
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    debug_info["errors"].append(
                        f"Error testing boundary {boundary.id}: {exc}"
                    )

            debug_info["intersection_results"] = intersection_results
            debug_info["intersections_found"] = len(
                [result for result in intersection_results if result["intersects"]]
            )

            try:
                geom_info = db.session.query(
                    func.ST_GeometryType(alert.geom).label("geom_type"),
                    func.ST_SRID(alert.geom).label("srid"),
                    func.ST_Area(alert.geom).label("area"),
                ).first()

                debug_info["geometry_info"] = {
                    "type": geom_info.geom_type if geom_info else "Unknown",
                    "srid": geom_info.srid if geom_info else "Unknown",
                    "area": float(geom_info.area)
                    if geom_info and geom_info.area
                    else 0,
                }
            except Exception as exc:  # pragma: no cover - defensive
                debug_info["errors"].append(
                    f"Error getting geometry info: {exc}"
                )

            return jsonify(debug_info)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error in debug_boundaries for %s: %s", alert_id, exc)
            return jsonify({"error": str(exc), "alert_id": alert_id}), 500


__all__ = ["register"]
