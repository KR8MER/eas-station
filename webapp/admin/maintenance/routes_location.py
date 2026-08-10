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

"""Location settings, alert filtering, and the county/FIPS lookup."""

from flask import current_app, jsonify, request

from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core.location import (
    describe_location_reference,
    get_location_settings,
    update_location_settings,
)

from .blueprint import maintenance_bp


@maintenance_bp.route("/admin/location_settings", methods=["GET", "PUT"])
@require_permission('system.configure')
def admin_location_settings():
    """GET or update location settings."""
    try:
        if request.method == "GET":
            settings = get_location_settings()
            return jsonify({"settings": settings})

        payload = request.get_json(silent=True) or {}
        updated = update_location_settings(
            {
                "county_name": payload.get("county_name"),
                "state_code": payload.get("state_code"),
                "timezone": payload.get("timezone"),
                "fips_codes": payload.get("fips_codes"),
                "zone_codes": payload.get("zone_codes"),
                "storage_zone_codes": payload.get("storage_zone_codes"),
                "area_terms": payload.get("area_terms"),
                "led_default_lines": payload.get("led_default_lines"),
                "map_center_lat": payload.get("map_center_lat"),
                "map_center_lng": payload.get("map_center_lng"),
                "map_default_zoom": payload.get("map_default_zoom"),
            }
        )
        # Record only the keys this route actually applies. Use ``k in payload``
        # (not ``v is not None``) so an explicit null — an intentional clear —
        # is still captured in the audit trail.
        location_fields = {
            "county_name", "state_code", "timezone", "fips_codes", "zone_codes",
            "storage_zone_codes", "area_terms", "led_default_lines",
            "map_center_lat", "map_center_lng", "map_default_zoom",
        }
        AuditLogger.log_config_change(
            resource_type='location_settings',
            details={'changed_fields': sorted(k for k in location_fields if k in payload)},
        )
        return jsonify({"success": "Location settings updated", "settings": updated})
    except Exception as exc:
        current_app.logger.error("Error processing location settings update: %s", exc)
        return jsonify({"error": f"Failed to process location settings: {exc}"}), 500

@maintenance_bp.route("/admin/alert_filtering", methods=["GET", "POST"])
@require_permission('system.configure')
def admin_alert_filtering():
    """GET or update alert filtering settings."""
    try:
        from app_core.alert_filtering import get_alert_filter_settings, update_alert_filter_settings
        
        if request.method == "GET":
            settings = get_alert_filter_settings()
            return jsonify({"settings": settings})

        payload = request.get_json(silent=True) or {}
        updated = update_alert_filter_settings(payload)
        # When the updater echoes the applied settings, constrain the audit
        # entry to keys that were actually recognised/persisted.
        if isinstance(updated, dict):
            changed_fields = sorted(k for k in payload if k in updated)
        else:
            changed_fields = sorted(payload.keys())
        AuditLogger.log_config_change(
            resource_type='alert_filter_settings',
            details={'changed_fields': changed_fields},
        )
        return jsonify({"success": "Alert filtering settings updated", "settings": updated})
    except Exception as exc:
        current_app.logger.error("Error processing alert filtering update: %s", exc)
        return jsonify({"error": "Failed to process alert filtering settings"}), 500

@maintenance_bp.route("/admin/location_reference", methods=["GET"])
def admin_location_reference():
    try:
        summary = describe_location_reference()
        return jsonify(summary)
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.error("Failed to load location reference data: %s", exc)
        return (
            jsonify(
                {
                    "error": "Failed to load location reference data.",
                }
            ),
            500,
        )

@maintenance_bp.route("/admin/lookup_county_fips", methods=["POST"])
@require_permission('system.configure')
def admin_lookup_county_fips():
    """Look up FIPS codes for counties by state and county name."""
    try:
        from app_utils.fips_codes import get_us_state_county_tree

        data = request.get_json() or {}
        state_code = data.get("state_code", "").strip().upper()
        county_query = data.get("county_name", "").strip().lower()

        if not state_code:
            return jsonify({"error": "State code is required"}), 400

        # Get the state/county tree
        state_tree = get_us_state_county_tree()

        # Find the state
        state_data = None
        for state in state_tree:
            if state.get("abbr", "").upper() == state_code:
                state_data = state
                break

        if not state_data:
            return jsonify({"error": f"State {state_code} not found"}), 404

        # If no county query, return all counties for the state
        if not county_query:
            counties = [
                {
                    "name": county.get("name", ""),
                    "fips": county.get("same", "")
                }
                for county in state_data.get("counties", [])
            ]
            return jsonify({"counties": counties})

        # Search for matching counties
        matching_counties = []
        for county in state_data.get("counties", []):
            county_name = county.get("name", "").lower()
            if county_query in county_name:
                matching_counties.append({
                    "name": county.get("name", ""),
                    "fips": county.get("same", "")
                })

        if not matching_counties:
            return jsonify({"error": f"No counties found matching '{county_query}' in {state_code}"}), 404

        return jsonify({"counties": matching_counties})

    except Exception as exc:
        current_app.logger.error("Error looking up FIPS codes: %s", exc)
        return jsonify({"error": f"Failed to lookup FIPS codes: {str(exc)}"}), 500
