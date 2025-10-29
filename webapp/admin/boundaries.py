"""Administrative routes and helpers for managing boundary data."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set

from flask import Flask, jsonify, request
from sqlalchemy import func, text

from app_core.boundaries import (
    BOUNDARY_GROUP_LABELS,
    calculate_geometry_length_miles,
    describe_mtfcc,
    extract_name_and_description,
    get_boundary_display_label,
    get_boundary_group,
    get_field_mappings,
    normalize_boundary_type,
)
from app_core.extensions import db
from app_core.models import Boundary, SystemLog
from app_utils import (
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    local_now,
    utc_now,
)


def ensure_alert_source_columns(logger) -> bool:
    """Ensure provenance columns exist for CAP alerts and poll history."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        return True

    try:
        changed = False

        cap_alerts_has_source = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'cap_alerts'
                  AND column_name = 'source'
                  AND table_schema = current_schema()
                """
            )
        ).scalar()

        if not cap_alerts_has_source:
            logger.info(
                "Adding cap_alerts.source column for alert provenance tracking"
            )
            db.session.execute(text("ALTER TABLE cap_alerts ADD COLUMN source VARCHAR(32)"))
            db.session.execute(
                text("UPDATE cap_alerts SET source = :default WHERE source IS NULL"),
                {"default": ALERT_SOURCE_NOAA},
            )
            db.session.execute(
                text("ALTER TABLE cap_alerts ALTER COLUMN source SET DEFAULT :default"),
                {"default": ALERT_SOURCE_UNKNOWN},
            )
            db.session.execute(
                text("ALTER TABLE cap_alerts ALTER COLUMN source SET NOT NULL")
            )
            changed = True

        poll_history_has_source = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'poll_history'
                  AND column_name = 'data_source'
                  AND table_schema = current_schema()
                """
            )
        ).scalar()

        if not poll_history_has_source:
            logger.info("Adding poll_history.data_source column for polling metadata")
            db.session.execute(
                text("ALTER TABLE poll_history ADD COLUMN data_source VARCHAR(64)")
            )
            changed = True

        if changed:
            db.session.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not ensure alert source columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        return False


def ensure_boundary_geometry_column(logger) -> bool:
    """Ensure the boundaries table accepts any geometry subtype with SRID 4326."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        logger.debug(
            "Skipping boundaries.geom verification for non-PostgreSQL database (%s)",
            engine.dialect.name,
        )
        return True

    try:
        result = db.session.execute(
            text(
                """
                SELECT type
                FROM geometry_columns
                WHERE f_table_name = :table
                  AND f_geometry_column = :column
                ORDER BY (f_table_schema = current_schema()) DESC
                LIMIT 1
                """
            ),
            {"table": "boundaries", "column": "geom"},
        ).scalar()

        if result and result.upper() == "MULTIPOLYGON":
            logger.info(
                "Updating boundaries.geom column to support multiple geometry types"
            )
            db.session.execute(
                text(
                    """
                    ALTER TABLE boundaries
                    ALTER COLUMN geom TYPE geometry(GEOMETRY, 4326)
                    USING ST_SetSRID(geom, 4326)
                    """
                )
            )
            db.session.commit()
        elif not result:
            logger.debug(
                "geometry_columns entry for boundaries.geom not found; skipping type verification"
            )
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not ensure boundaries.geom column configuration: %s", exc)
        db.session.rollback()
        return False


def extract_feature_metadata(
    feature: Dict[str, Any], boundary_type: str
) -> Dict[str, Any]:
    """Derive helpful metadata for a boundary feature preview."""

    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}

    owner_candidates: Iterable[str] = (
        "OWNER",
        "Owner",
        "owner",
        "AGENCY",
        "Agency",
        "agency",
        "ORGANIZATION",
        "Organisation",
        "ORGANISATION",
        "ORG_NAME",
        "ORGNAME",
    )
    owner_field = next(
        (field for field in owner_candidates if properties.get(field)), None
    )
    owner = str(properties.get(owner_field)).strip() if owner_field else None

    line_id_candidates: Iterable[str] = (
        "LINE_ID",
        "LINEID",
        "LINE_ID_NO",
        "ID",
        "OBJECTID",
        "OBJECT_ID",
        "GLOBALID",
        "GlobalID",
    )
    line_id_field = next(
        (field for field in line_id_candidates if properties.get(field)), None
    )
    line_id = str(properties.get(line_id_field)).strip() if line_id_field else None

    mtfcc = properties.get("MTFCC") or properties.get("mtfcc")
    classification = describe_mtfcc(mtfcc) if mtfcc else None
    if not classification:
        group_key = get_boundary_group(boundary_type)
        classification = BOUNDARY_GROUP_LABELS.get(
            group_key, group_key.replace("_", " ").title()
        )

    length_miles = calculate_geometry_length_miles(geometry)
    length_label = f"Approx. {length_miles:.2f} miles" if length_miles else None

    recommended_fields: Set[str] = set()
    mapping = get_field_mappings().get(boundary_type, {})
    for field_name in mapping.get("name_fields", []):
        recommended_fields.add(field_name)
    for field_name in mapping.get("description_fields", []):
        recommended_fields.add(field_name)

    additional_details: List[str] = []
    if mtfcc:
        detail = describe_mtfcc(mtfcc)
        if detail:
            additional_details.append(f"MTFCC {mtfcc}: {detail}")
        else:
            additional_details.append(f"MTFCC: {mtfcc}")
    if length_label:
        additional_details.append(length_label)
    if owner:
        additional_details.append(f"Owner: {owner}")

    if owner_field:
        recommended_fields.add(owner_field)
    if line_id_field:
        recommended_fields.add(line_id_field)

    return {
        "owner": owner,
        "owner_field": owner_field,
        "line_id": line_id,
        "line_id_field": line_id_field,
        "mtfcc": mtfcc,
        "classification": classification,
        "length_label": length_label,
        "additional_details": additional_details,
        "recommended_fields": recommended_fields,
    }


def register_boundary_routes(app: Flask, logger) -> None:
    """Attach administrative boundary management endpoints to the Flask app."""

    route_logger = logger.getChild("admin.boundaries")

    @app.route("/admin/preview_geojson", methods=["POST"])
    def preview_geojson():
        """Preview GeoJSON contents and extract useful metadata without persisting."""

        try:
            if "file" not in request.files:
                return jsonify({"error": "No file provided"}), 400

            file = request.files["file"]
            raw_boundary_type = request.form.get("boundary_type", "unknown")
            boundary_type = normalize_boundary_type(raw_boundary_type)
            boundary_label = get_boundary_display_label(raw_boundary_type)

            if file.filename == "":
                return jsonify({"error": "No file selected"}), 400

            if not file.filename.lower().endswith(".geojson"):
                return jsonify({"error": "File must be a GeoJSON file"}), 400

            try:
                file_contents = file.read().decode("utf-8")
            except UnicodeDecodeError:
                return (
                    jsonify(
                        {
                            "error": "Unable to decode file. Please ensure it is UTF-8 encoded.",
                        }
                    ),
                    400,
                )

            try:
                geojson_data = json.loads(file_contents)
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid GeoJSON format"}), 400

            features = geojson_data.get("features")
            if not isinstance(features, list) or not features:
                return (
                    jsonify(
                        {
                            "error": "GeoJSON file does not contain any features.",
                            "boundary_type": boundary_label,
                            "total_features": 0,
                        }
                    ),
                    400,
                )

            preview_limit = 5
            previews: List[Dict[str, Any]] = []
            all_fields: Set[str] = set()
            owner_fields: Set[str] = set()
            line_id_fields: Set[str] = set()
            recommended_fields: Set[str] = set()

            for feature in features:
                properties = feature.get("properties", {}) or {}
                all_fields.update(properties.keys())

            for feature in features[:preview_limit]:
                properties = feature.get("properties", {}) or {}
                name, description = extract_name_and_description(
                    properties, boundary_type
                )
                metadata = extract_feature_metadata(feature, boundary_type)

                preview_entry = {
                    "name": name,
                    "description": description,
                    "owner": metadata.get("owner"),
                    "line_id": metadata.get("line_id"),
                    "mtfcc": metadata.get("mtfcc"),
                    "classification": metadata.get("classification"),
                    "length_label": metadata.get("length_label"),
                    "additional_details": metadata.get("additional_details"),
                }
                previews.append(preview_entry)

                if metadata.get("owner_field"):
                    owner_fields.add(metadata["owner_field"])
                if metadata.get("line_id_field"):
                    line_id_fields.add(metadata["line_id_field"])
                recommended_fields.update(metadata.get("recommended_fields", set()))

            response_data = {
                "boundary_type": boundary_label,
                "normalized_type": boundary_type,
                "total_features": len(features),
                "preview_count": len(previews),
                "all_fields": sorted(all_fields),
                "previews": previews,
                "owner_fields": sorted(owner_fields),
                "line_id_fields": sorted(line_id_fields),
                "recommended_additional_fields": sorted(recommended_fields),
                "field_mappings": get_field_mappings().get(boundary_type, {}),
            }

            return jsonify(response_data)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error previewing GeoJSON: %s", exc)
            return jsonify({"error": f"Failed to preview GeoJSON: {exc}"}), 500

    @app.route("/admin/upload_boundaries", methods=["POST"])
    def upload_boundaries():
        """Upload GeoJSON boundary file with enhanced processing."""

        try:
            if "file" not in request.files:
                return jsonify({"error": "No file provided"}), 400

            file = request.files["file"]
            raw_boundary_type = request.form.get("boundary_type", "unknown")
            boundary_type = normalize_boundary_type(raw_boundary_type)
            boundary_label = get_boundary_display_label(raw_boundary_type)

            if file.filename == "":
                return jsonify({"error": "No file selected"}), 400

            if not file.filename.lower().endswith(".geojson"):
                return jsonify({"error": "File must be a GeoJSON file"}), 400

            try:
                geojson_data = json.loads(file.read().decode("utf-8"))
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid GeoJSON format"}), 400

            features = geojson_data.get("features", [])
            boundaries_added = 0
            errors: List[str] = []

            for i, feature in enumerate(features):
                try:
                    properties = feature.get("properties", {}) or {}
                    geometry = feature.get("geometry")

                    if not geometry:
                        errors.append(f"Feature {i + 1}: No geometry")
                        continue

                    name, description = extract_name_and_description(
                        properties, boundary_type
                    )

                    geometry_json = json.dumps(geometry)

                    boundary = Boundary(
                        name=name,
                        type=boundary_type,
                        description=description,
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )

                    boundary.geom = db.session.execute(
                        text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)"),
                        {"geom": geometry_json},
                    ).scalar()

                    db.session.add(boundary)
                    boundaries_added += 1

                except Exception as exc:  # pragma: no cover - defensive
                    errors.append(f"Feature {i + 1}: {exc}")

            try:
                db.session.commit()
                route_logger.info(
                    "Successfully uploaded %s %s boundaries",
                    boundaries_added,
                    boundary_label,
                )
            except Exception as exc:  # pragma: no cover - defensive
                db.session.rollback()
                return jsonify({"error": f"Database error: {exc}"}), 500

            response_data = {
                "success": (
                    f"Successfully uploaded {boundaries_added} {boundary_label} boundaries"
                ),
                "boundaries_added": boundaries_added,
                "total_features": len(features),
                "errors": errors[:10] if errors else [],
                "normalized_type": boundary_type,
                "display_label": boundary_label,
            }

            if errors:
                response_data["warning"] = f"{len(errors)} features had errors"

            return jsonify(response_data)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error uploading boundaries: %s", exc)
            return jsonify({"error": f"Upload failed: {exc}"}), 500

    @app.route("/admin/clear_boundaries/<boundary_type>", methods=["DELETE"])
    def clear_boundaries(boundary_type: str):
        """Clear all boundaries of a specific type."""

        try:
            normalized_type: Optional[str] = None

            if boundary_type == "all":
                deleted_count = Boundary.query.delete()
                message = f"Deleted all {deleted_count} boundaries"
            else:
                normalized_type = normalize_boundary_type(boundary_type)
                deleted_count = (
                    Boundary.query.filter(
                        func.lower(Boundary.type) == normalized_type
                    ).delete(synchronize_session=False)
                )
                message = (
                    "Deleted {count} {label} boundaries".format(
                        count=deleted_count,
                        label=get_boundary_display_label(boundary_type),
                    )
                )

            db.session.commit()

            log_entry = SystemLog(
                level="WARNING",
                message=message,
                module="admin",
                details={
                    "boundary_type": boundary_type,
                    "normalized_type": normalized_type if boundary_type != "all" else "all",
                    "deleted_count": deleted_count,
                    "deleted_at_utc": utc_now().isoformat(),
                    "deleted_at_local": local_now().isoformat(),
                },
            )
            db.session.add(log_entry)
            db.session.commit()

            return jsonify({"success": message, "deleted_count": deleted_count})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Error clearing boundaries: %s", exc)
            return jsonify({"error": f"Failed to clear boundaries: {exc}"}), 500

    @app.route("/admin/clear_all_boundaries", methods=["DELETE"])
    def clear_all_boundaries():
        """Clear all boundaries (requires confirmation)."""

        try:
            data = request.get_json() or {}

            confirmation_level = data.get("confirmation_level", 0)
            text_confirmation = data.get("text_confirmation", "")

            if (
                confirmation_level < 2
                or text_confirmation != "DELETE ALL BOUNDARIES"
            ):
                return (
                    jsonify(
                        {
                            "error": "Invalid confirmation. This action requires proper confirmation.",
                        }
                    ),
                    400,
                )

            deleted_count = Boundary.query.delete()
            db.session.commit()

            log_entry = SystemLog(
                level="CRITICAL",
                message=(
                    "DELETED ALL BOUNDARIES: "
                    f"{deleted_count} boundaries permanently removed"
                ),
                module="admin",
                details={
                    "deleted_count": deleted_count,
                    "confirmation_level": confirmation_level,
                    "confirmed_text": text_confirmation,
                    "deleted_at_utc": utc_now().isoformat(),
                    "deleted_at_local": local_now().isoformat(),
                },
            )
            db.session.add(log_entry)
            db.session.commit()

            return jsonify({"success": "All boundaries cleared", "deleted_count": deleted_count})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Error clearing all boundaries: %s", exc)
            return jsonify({"error": f"Failed to clear all boundaries: {exc}"}), 500


__all__ = [
    "ensure_alert_source_columns",
    "ensure_boundary_geometry_column",
    "extract_feature_metadata",
    "register_boundary_routes",
]
