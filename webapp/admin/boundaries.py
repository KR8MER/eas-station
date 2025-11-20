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
"""

"""Administrative routes and helpers for managing boundary data."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set

from flask import Blueprint, Flask, jsonify, request
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

# Create Blueprint for boundary routes
boundaries_bp = Blueprint('boundaries', __name__)


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


def convert_shapefile_to_geojson(shapefile_path: str) -> Dict[str, Any]:
    """
    Convert a shapefile to GeoJSON format.

    Args:
        shapefile_path: Path to the .shp file

    Returns:
        GeoJSON FeatureCollection dictionary

    Raises:
        ImportError: If pyshp library is not installed
        Exception: If shapefile cannot be read
    """
    import shapefile

    # Read the shapefile
    sf = shapefile.Reader(shapefile_path)

    # Get field names (skip deletion flag field)
    fields = sf.fields[1:]
    field_names = [field[0] for field in fields]

    # Convert to GeoJSON features
    features = []

    for shape_record in sf.shapeRecords():
        shape = shape_record.shape
        record = shape_record.record

        # Build properties from attributes
        properties = {}
        for i, field_name in enumerate(field_names):
            value = record[i]
            # Convert bytes to string if needed
            if isinstance(value, bytes):
                value = value.decode('utf-8', errors='ignore')
            properties[field_name] = value

        # Convert shape to GeoJSON geometry using __geo_interface__
        geometry = shape.__geo_interface__

        # Create GeoJSON feature
        feature = {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry
        }
        features.append(feature)

    # Create GeoJSON FeatureCollection
    return {
        "type": "FeatureCollection",
        "features": features
    }


def register_boundary_routes(app: Flask, logger) -> None:
    """Register boundary management endpoints."""
    
    # Register the blueprint with the app
    app.register_blueprint(boundaries_bp)
    logger.info("Boundary routes registered")


# Route definitions

@boundaries_bp.route("/admin/preview_geojson", methods=["POST"])
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

@boundaries_bp.route("/admin/upload_boundaries", methods=["POST"])
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

@boundaries_bp.route("/admin/list_shapefiles", methods=["GET"])
def list_shapefiles():
    """List available shapefiles in the server directory."""
    try:
        from pathlib import Path

        base_dir = Path("/home/user/eas-station")
        shapefile_dir = base_dir / "streams and ponds"

        if not shapefile_dir.exists():
            return jsonify({
                "shapefiles": [],
                "message": "Shapefile directory not found"
            })

        # Find all .shp files
        shp_files = list(shapefile_dir.glob("*.shp"))

        shapefiles = []
        for shp_file in shp_files:
            # Check for companion files
            shp_path = shp_file.stem
            has_shx = (shapefile_dir / f"{shp_path}.shx").exists()
            has_dbf = (shapefile_dir / f"{shp_path}.dbf").exists()
            has_prj = (shapefile_dir / f"{shp_path}.prj").exists()

            complete = has_shx and has_dbf

            # Suggest boundary type based on filename
            suggested_type = "unknown"
            if "linear" in shp_file.name.lower() or "stream" in shp_file.name.lower():
                suggested_type = "rivers"
            elif "area" in shp_file.name.lower() or "water" in shp_file.name.lower():
                suggested_type = "waterbodies"

            shapefiles.append({
                "filename": shp_file.name,
                "path": str(shp_file),
                "size_mb": shp_file.stat().st_size / (1024 * 1024),
                "complete": complete,
                "has_shx": has_shx,
                "has_dbf": has_dbf,
                "has_prj": has_prj,
                "suggested_type": suggested_type,
                "suggested_label": get_boundary_display_label(suggested_type)
            })

        return jsonify({
            "shapefiles": shapefiles,
            "directory": str(shapefile_dir)
        })

    except Exception as exc:
        route_logger.error("Error listing shapefiles: %s", exc)
        return jsonify({"error": f"Failed to list shapefiles: {exc}"}), 500

@boundaries_bp.route("/admin/upload_shapefile", methods=["POST"])
def upload_shapefile():
    """Upload shapefile (with companion files) and convert to boundaries."""
    try:
        import io
        import tempfile
        import zipfile
        from pathlib import Path

        try:
            import shapefile
        except ImportError:
            return jsonify({
                "error": "Shapefile library not installed. Install pyshp: pip install pyshp==2.3.1"
            }), 500

        raw_boundary_type = request.form.get("boundary_type", "unknown")
        boundary_type = normalize_boundary_type(raw_boundary_type)
        boundary_label = get_boundary_display_label(raw_boundary_type)

        # Handle ZIP file upload containing shapefile components
        if "file" in request.files:
            file = request.files["file"]
            if file.filename == "":
                return jsonify({"error": "No file selected"}), 400

            # Accept either .zip or .shp files
            filename_lower = file.filename.lower()

            if filename_lower.endswith(".zip"):
                # Extract ZIP to temporary directory
                with tempfile.TemporaryDirectory() as tmpdir:
                    zip_data = io.BytesIO(file.read())
                    with zipfile.ZipFile(zip_data, 'r') as zip_ref:
                        zip_ref.extractall(tmpdir)

                    # Find .shp file in extracted contents
                    shp_files = list(Path(tmpdir).glob("**/*.shp"))
                    if not shp_files:
                        return jsonify({
                            "error": "No .shp file found in ZIP archive"
                        }), 400

                    shp_path = str(shp_files[0])
                    geojson_data = convert_shapefile_to_geojson(shp_path)

            elif filename_lower.endswith(".shp"):
                return jsonify({
                    "error": "Please upload a ZIP file containing .shp, .shx, .dbf, and .prj files"
                }), 400
            else:
                return jsonify({
                    "error": "File must be a ZIP archive containing shapefile components"
                }), 400

        # Handle directory path for existing shapefiles on server
        elif "shapefile_path" in request.form:
            shp_path = request.form["shapefile_path"]
            if not Path(shp_path).exists():
                return jsonify({"error": f"Shapefile not found: {shp_path}"}), 400

            geojson_data = convert_shapefile_to_geojson(shp_path)
        else:
            return jsonify({
                "error": "Either file upload or shapefile_path must be provided"
            }), 400

        # Now process the GeoJSON using existing logic
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

            except Exception as exc:
                errors.append(f"Feature {i + 1}: {exc}")

        try:
            db.session.commit()
            route_logger.info(
                "Successfully uploaded %s %s boundaries from shapefile",
                boundaries_added,
                boundary_label,
            )
        except Exception as exc:
            db.session.rollback()
            return jsonify({"error": f"Database error: {exc}"}), 500

        response_data = {
            "success": (
                f"Successfully uploaded {boundaries_added} {boundary_label} "
                f"boundaries from shapefile"
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

    except Exception as exc:
        route_logger.error("Error uploading shapefile: %s", exc)
        return jsonify({"error": f"Shapefile upload failed: {exc}"}), 500

@boundaries_bp.route("/admin/clear_boundaries/<boundary_type>", methods=["DELETE"])
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

@boundaries_bp.route("/admin/clear_all_boundaries", methods=["DELETE"])
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
