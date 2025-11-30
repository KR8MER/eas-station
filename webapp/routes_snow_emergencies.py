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

Routes for managing local snow emergencies.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from flask import Flask, jsonify, request, g
from sqlalchemy import inspect

from app_core.extensions import db
from app_core.models import (
    SnowEmergency,
    SNOW_EMERGENCY_LEVELS,
    PUTNAM_REGION_COUNTIES,
)
from app_core.auth.decorators import require_role
from app_utils import utc_now

route_logger = logging.getLogger(__name__)


def _ensure_snow_emergencies_table() -> bool:
    """Ensure the snow_emergencies table exists."""
    try:
        inspector = inspect(db.engine)
        return "snow_emergencies" in inspector.get_table_names()
    except Exception as exc:
        route_logger.warning("Could not check snow_emergencies table: %s", exc)
        return False


def _initialize_counties() -> None:
    """Initialize snow emergency records for all tracked counties if not present."""
    if not _ensure_snow_emergencies_table():
        return

    try:
        for fips, info in PUTNAM_REGION_COUNTIES.items():
            existing = SnowEmergency.query.filter_by(county_fips=fips).first()
            if not existing:
                emergency = SnowEmergency(
                    county_fips=fips,
                    county_name=info["name"],
                    state_code=info["state"],
                    level=0,
                    level_set_by="System",
                    issues_emergencies=True,
                )
                db.session.add(emergency)
        db.session.commit()
    except Exception as exc:
        route_logger.warning("Could not initialize snow emergency counties: %s", exc)
        db.session.rollback()


def _get_current_username() -> str:
    """Get the current user's username from session/auth."""
    # Try to get from Flask-Login current_user (imported at module level if available)
    try:
        from flask_login import current_user
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            return getattr(current_user, 'username', None) or getattr(current_user, 'email', None) or "Unknown"
    except ImportError:
        pass
    except Exception:
        pass

    # Try from g object
    if hasattr(g, "user") and g.user:
        return getattr(g.user, "username", None) or getattr(g.user, "email", None) or "Unknown"

    return "Anonymous"


def register(app: Flask, logger) -> None:
    """Register snow emergency routes."""

    @app.route("/api/snow_emergencies", methods=["GET"])
    def get_snow_emergencies():
        """Get current snow emergency status for all tracked counties.

        Returns only counties with active emergencies (level > 0) by default.
        Use ?all=true to get all counties regardless of level.
        """
        if not _ensure_snow_emergencies_table():
            return jsonify({
                "emergencies": [],
                "levels": SNOW_EMERGENCY_LEVELS,
                "counties": PUTNAM_REGION_COUNTIES,
                "error": "Snow emergencies table not initialized",
            })

        _initialize_counties()

        try:
            show_all = request.args.get("all", "false").lower() == "true"
            include_history = request.args.get("history", "false").lower() == "true"

            if show_all:
                emergencies = SnowEmergency.query.all()
            else:
                emergencies = SnowEmergency.query.filter(
                    SnowEmergency.level > 0, SnowEmergency.issues_emergencies.is_(True)
                ).all()

            # Sort by county order defined in PUTNAM_REGION_COUNTIES
            def get_order(e):
                info = PUTNAM_REGION_COUNTIES.get(e.county_fips, {})
                return info.get("order", 999)

            emergencies = sorted(emergencies, key=get_order)

            return jsonify({
                "emergencies": [e.to_dict(include_history=include_history) for e in emergencies],
                "levels": SNOW_EMERGENCY_LEVELS,
                "has_active": any(e.is_active() for e in emergencies),
            })
        except Exception as exc:
            route_logger.error("Error fetching snow emergencies: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/snow_emergencies/all", methods=["GET"])
    @require_role("Admin", "Operator")
    def get_all_snow_emergencies():
        """Get snow emergency status for ALL tracked counties (for management UI)."""
        if not _ensure_snow_emergencies_table():
            # Return default state for all counties
            return jsonify({
                "emergencies": [
                    {
                        "county_fips": fips,
                        "county_name": info["name"],
                        "state_code": info["state"],
                        "level": 0,
                        "level_name": "None",
                        "level_color": "#28a745",
                        "is_active": False,
                        "is_primary": info.get("is_primary", False),
                    }
                    for fips, info in sorted(
                        PUTNAM_REGION_COUNTIES.items(),
                        key=lambda x: x[1].get("order", 999)
                    )
                ],
                "levels": SNOW_EMERGENCY_LEVELS,
            })

        _initialize_counties()

        try:
            emergencies = SnowEmergency.query.all()

            # Create a map for quick lookup
            emergency_map = {e.county_fips: e for e in emergencies}

            # Build response with all counties in order
            result = []
            for fips, info in sorted(
                PUTNAM_REGION_COUNTIES.items(),
                key=lambda x: x[1].get("order", 999)
            ):
                if fips in emergency_map:
                    e = emergency_map[fips]
                    data = e.to_dict(include_history=True)
                    data["is_primary"] = info.get("is_primary", False)
                    result.append(data)
                else:
                    # County not in database yet
                    result.append({
                        "county_fips": fips,
                        "county_name": info["name"],
                        "state_code": info["state"],
                        "level": 0,
                        "level_name": "None",
                        "level_color": "#28a745",
                        "is_active": False,
                        "is_primary": info.get("is_primary", False),
                    })

            return jsonify({
                "emergencies": result,
                "levels": SNOW_EMERGENCY_LEVELS,
            })
        except Exception as exc:
            route_logger.error("Error fetching all snow emergencies: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/snow_emergencies/<county_fips>", methods=["PUT"])
    @require_role("Admin", "Operator")
    def update_snow_emergency(county_fips: str):
        """Update snow emergency level for a specific county.

        Request body:
        {
            "level": 0-3,
            "issues_emergencies": bool (optional)
        }
        """
        if not _ensure_snow_emergencies_table():
            return jsonify({"error": "Snow emergencies not available"}), 503

        _initialize_counties()

        # Validate county
        if county_fips not in PUTNAM_REGION_COUNTIES:
            return jsonify({"error": f"Invalid county FIPS: {county_fips}"}), 400

        try:
            data = request.get_json() or {}
            new_level = data.get("level")
            issues_emergencies = data.get("issues_emergencies")

            if new_level is None and issues_emergencies is None:
                return jsonify({"error": "Request must include 'level' or 'issues_emergencies'"}), 400

            if new_level is not None:
                try:
                    new_level = int(new_level)
                except (ValueError, TypeError):
                    return jsonify({"error": "Level must be an integer 0-3"}), 400

                if new_level < 0 or new_level > 3:
                    return jsonify({"error": "Level must be between 0 and 3"}), 400

            if issues_emergencies is not None:
                issues_emergencies = bool(issues_emergencies)

            # Get or create the emergency record
            emergency = SnowEmergency.query.filter_by(county_fips=county_fips).first()
            if not emergency:
                county_info = PUTNAM_REGION_COUNTIES[county_fips]
                emergency = SnowEmergency(
                    county_fips=county_fips,
                    county_name=county_info["name"],
                    state_code=county_info["state"],
                    level=0,
                    issues_emergencies=True,
                )
                db.session.add(emergency)

            # Get current user
            username = _get_current_username()

            if issues_emergencies is not None:
                emergency.issues_emergencies = issues_emergencies
                if not issues_emergencies and emergency.level != 0:
                    emergency.set_level(0, username)

            if new_level is None:
                db.session.commit()
                return jsonify({
                    "success": True,
                    "emergency": emergency.to_dict(include_history=True),
                })

            # Update level (this also records history)
            emergency.set_level(new_level, username)
            db.session.commit()

            route_logger.info(
                "Snow emergency updated: %s (%s) -> Level %d by %s",
                emergency.county_name,
                county_fips,
                new_level,
                username,
            )

            return jsonify({
                "success": True,
                "emergency": emergency.to_dict(include_history=True),
            })

        except Exception as exc:
            route_logger.error("Error updating snow emergency for %s: %s", county_fips, exc)
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/snow_emergencies/<county_fips>/history", methods=["GET"])
    @require_role("Admin", "Operator")
    def get_snow_emergency_history(county_fips: str):
        """Get change history for a specific county's snow emergency."""
        if not _ensure_snow_emergencies_table():
            return jsonify({"history": []})

        if county_fips not in PUTNAM_REGION_COUNTIES:
            return jsonify({"error": f"Invalid county FIPS: {county_fips}"}), 400

        try:
            emergency = SnowEmergency.query.filter_by(county_fips=county_fips).first()
            if not emergency:
                return jsonify({"history": []})

            return jsonify({
                "county_fips": county_fips,
                "county_name": emergency.county_name,
                "current_level": emergency.level,
                "history": list(emergency.history or []),
            })
        except Exception as exc:
            route_logger.error("Error fetching history for %s: %s", county_fips, exc)
            return jsonify({"error": str(exc)}), 500

    route_logger.info("Registered snow emergency routes")
