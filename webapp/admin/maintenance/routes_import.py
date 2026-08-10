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

"""Manually importing one alert from the NOAA API by identifier."""

from typing import Any, Dict, List

from flask import current_app, jsonify, request

from app_core.alerts import (
    assign_alert_geometry,
    calculate_alert_intersections,
    parse_noaa_cap_alert,
)
from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import CAPAlert, SystemLog
from app_utils import local_now, utc_now

from .blueprint import maintenance_bp
from .noaa import (
    NOAAImportError,
    format_noaa_timestamp,
    normalize_manual_import_datetime,
    retrieve_noaa_alerts,
)


@maintenance_bp.route("/admin/import_alert", methods=["POST"])
@require_permission('system.configure')
def import_specific_alert():
    data = request.get_json(silent=True) or request.form or {}

    identifier = (data.get("identifier") or "").strip()
    start_raw = (data.get("start") or "").strip()
    end_raw = (data.get("end") or "").strip()
    area = (data.get("area") or "").strip()
    event_filter = (data.get("event") or "").strip()

    try:
        limit_value = int(data.get("limit", 10))
    except (TypeError, ValueError):
        limit_value = 10
    limit_value = max(1, min(limit_value, 50))

    start_dt = normalize_manual_import_datetime(start_raw)
    end_dt = normalize_manual_import_datetime(end_raw)

    if start_raw and start_dt is None:
        return (
            jsonify(
                {
                    "error": "Could not parse the provided start timestamp. Use ISO 8601 format (e.g., 2025-01-15T13:00:00-05:00).",
                }
            ),
            400,
        )

    if end_raw and end_dt is None:
        return (
            jsonify(
                {
                    "error": "Could not parse the provided end timestamp. Use ISO 8601 format (e.g., 2025-01-15T18:00:00-05:00).",
                }
            ),
            400,
        )

    if not identifier and not (start_dt and end_dt):
        return (
            jsonify(
                {
                    "error": "Provide an alert identifier or both start and end timestamps.",
                }
            ),
            400,
        )

    now_utc = utc_now()
    if end_dt and end_dt > now_utc:
        current_app.logger.info(
            "Clamping manual NOAA import end time %s to current UTC %s",
            end_dt.isoformat(),
            now_utc.isoformat(),
        )
        end_dt = now_utc

    if start_dt and end_dt and start_dt > end_dt:
        return jsonify({"error": "The start time must be before the end time."}), 400

    cleaned_area = "".join(ch for ch in area.upper() if ch.isalpha()) if area else ""
    normalized_area = cleaned_area[:2] if cleaned_area else None

    if identifier:
        if area and (not normalized_area or len(normalized_area) != 2):
            return (
                jsonify({"error": "State filters must use the two-letter postal abbreviation."}),
                400,
            )
    else:
        if not normalized_area or len(normalized_area) != 2:
            return (
                jsonify(
                    {
                        "error": "Provide the two-letter state code when searching without an identifier.",
                    }
                ),
                400,
            )

    try:
        alerts_payloads, query_url, params = retrieve_noaa_alerts(
            identifier=identifier or None,
            start=start_dt,
            end=end_dt,
            area=normalized_area,
            event=event_filter or None,
            limit=limit_value,
        )
    except NOAAImportError as exc:
        status_code = exc.status_code or 502
        response_payload: Dict[str, Any] = {
            "error": str(exc),
            "status_code": exc.status_code,
            "query_url": exc.query_url,
            "params": exc.params,
        }
        if exc.detail:
            response_payload["detail"] = exc.detail
        if status_code == 404 and identifier:
            response_payload["identifier"] = identifier
        return jsonify(response_payload), status_code

    start_iso = format_noaa_timestamp(start_dt)
    end_iso = format_noaa_timestamp(end_dt)

    inserted = 0
    updated = 0
    skipped = 0
    identifiers: List[str] = []

    try:
        for feature in alerts_payloads:
            parsed_result = parse_noaa_cap_alert(feature)
            if not parsed_result:
                skipped += 1
                continue

            parsed, geometry = parsed_result
            alert_identifier = parsed["identifier"]
            if alert_identifier not in identifiers:
                identifiers.append(alert_identifier)

            existing = CAPAlert.query.filter_by(identifier=alert_identifier).first()

            if existing:
                for key, value in parsed.items():
                    setattr(existing, key, value)
                existing.updated_at = utc_now()
                assign_alert_geometry(existing, geometry)
                db.session.flush()
                try:
                    if existing.geom:
                        calculate_alert_intersections(existing)
                except Exception as intersection_error:
                    current_app.logger.warning(
                        "Intersection recalculation failed for alert %s: %s",
                        alert_identifier,
                        intersection_error,
                    )
                updated += 1
            else:
                new_alert = CAPAlert(**parsed)
                new_alert.created_at = utc_now()
                new_alert.updated_at = utc_now()
                assign_alert_geometry(new_alert, geometry)
                db.session.add(new_alert)
                db.session.flush()
                try:
                    if new_alert.geom:
                        calculate_alert_intersections(new_alert)
                except Exception as intersection_error:
                    current_app.logger.warning(
                        "Intersection calculation failed for new alert %s: %s",
                        alert_identifier,
                        intersection_error,
                    )
                inserted += 1

        log_entry = SystemLog(
            level="INFO",
            message="Manual NOAA alert import executed",
            module="admin",
            details={
                "identifiers": identifiers,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "query_url": query_url,
                "params": params,
                "requested_filters": {
                    "identifier": identifier or None,
                    "start": start_iso,
                    "end": end_iso,
                    "area": normalized_area,
                    "event": event_filter or None,
                    "limit": limit_value,
                },
                "requested_at_utc": utc_now().isoformat(),
                "requested_at_local": local_now().isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Manual NOAA alert import failed: %s", exc)
        return jsonify({"error": f"Failed to import NOAA alert data: {exc}"}), 500

    return jsonify(
        {
            "message": f"Imported {inserted} alert(s) and updated {updated} existing alert(s).",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "identifiers": identifiers,
            "query_url": query_url,
            "params": params,
        }
    )
