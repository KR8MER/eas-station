#!/usr/bin/env python3
"""
NOAA CAP Alerts and GIS Boundary Mapping System
Flask Web Application with Enhanced Boundary Management and Alerts History

Author: KR8MER Amateur Radio Emergency Communications
Description: Emergency alert system with configurable U.S. jurisdiction support and proper timezone handling
Version: 2.1.9 - Adds per-line LED formatting support and WYSIWYG message editing
"""

# =============================================================================
# IMPORTS AND DEPENDENCIES
# =============================================================================

import base64
import io
import os
import json
import math
import re
import psutil
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from urllib.parse import quote, urljoin, urlparse
from types import SimpleNamespace

from dotenv import load_dotenv
import pytz

# Application utilities
from app_utils import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_MANUAL,
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    UTC_TZ,
    format_bytes,
    get_location_timezone_name,
    local_now,
    normalize_alert_source,
    parse_nws_datetime as _parse_nws_datetime,
    set_location_timezone,
    utc_now,
)
from app_utils.eas import (
    P_DIGIT_MEANINGS,
    EASAudioGenerator,
    ORIGINATOR_DESCRIPTIONS,
    PRIMARY_ORIGINATORS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    build_same_header,
    describe_same_header,
    load_eas_config,
    manual_default_same_codes,
    samples_to_wav_bytes,
)
from app_core.eas_storage import get_eas_static_prefix
from app_core.system_health import get_system_health
from webapp import register_routes
# Re-export manual import utilities for CLI scripts that import from ``app``.
from webapp.admin.maintenance import (
    NOAAImportError,
    format_noaa_timestamp,
    normalize_manual_import_datetime,
    retrieve_noaa_alerts,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree

# Flask and extensions
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    flash,
    redirect,
    url_for,
    render_template_string,
    has_app_context,
    session,
    g,
    send_file,
    abort,
)
from geoalchemy2.functions import ST_GeomFromGeoJSON, ST_Intersects, ST_AsGeoJSON
from sqlalchemy import text, func, or_, desc
from sqlalchemy.exc import OperationalError

# Logging
import logging
import click

from app_core.alerts import (
    assign_alert_geometry,
    calculate_alert_intersections,
    ensure_multipolygon,
    get_active_alerts_query,
    get_expired_alerts_query,
    parse_noaa_cap_alert,
)
from app_core.boundaries import (
    BOUNDARY_GROUP_LABELS,
    BOUNDARY_TYPE_CONFIG,
    calculate_geometry_length_miles,
    describe_mtfcc,
    extract_name_and_description,
    get_boundary_color,
    get_boundary_display_label,
    get_boundary_group,
    get_field_mappings,
    normalize_boundary_type,
)
from app_core.extensions import db
from app_core.led import (
    LED_AVAILABLE,
    ensure_led_tables,
    initialise_led_controller,
    led_controller,
)
from app_core.location import get_location_settings, update_location_settings
from app_core.models import (
    AdminUser,
    Boundary,
    CAPAlert,
    EASMessage,
    ManualEASActivation,
    Intersection,
    LEDMessage,
    LEDSignStatus,
    LocationSettings,
    PollHistory,
    SystemLog,
)

# =============================================================================
# CONFIGURATION AND SETUP
# =============================================================================

# Load environment variables early for local CLI usage
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Application versioning (exposed via templates for quick deployment verification)
SYSTEM_VERSION = os.environ.get('APP_BUILD_VERSION', '2.2.0')

def _build_database_url() -> str:
    url = os.getenv('DATABASE_URL')
    if url:
        return url

    user = os.getenv('POSTGRES_USER', 'postgres') or 'postgres'
    password = os.getenv('POSTGRES_PASSWORD', '')
    host = os.getenv('POSTGRES_HOST', 'postgres') or 'postgres'
    port = os.getenv('POSTGRES_PORT', '5432') or '5432'
    database = os.getenv('POSTGRES_DB', user) or user

    user_part = quote(user, safe='')
    if password:
        auth_part = f"{user_part}:{quote(password, safe='')}"
    else:
        auth_part = user_part

    return f"postgresql+psycopg2://{auth_part}@{host}:{port}/{database}"


def _get_eas_output_root() -> Optional[str]:
    output_root = str(app.config.get('EAS_OUTPUT_DIR') or '').strip()
    return output_root or None


def _get_eas_static_prefix() -> str:
    return app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')


def _resolve_eas_disk_path(filename: Optional[str]) -> Optional[str]:
    output_root = _get_eas_output_root()
    if not output_root or not filename:
        return None

    safe_fragment = str(filename).strip().lstrip('/\\')
    if not safe_fragment:
        return None

    candidate = os.path.abspath(os.path.join(output_root, safe_fragment))
    root = os.path.abspath(output_root)

    try:
        common = os.path.commonpath([candidate, root])
    except ValueError:
        return None

    if common != root:
        return None

    if os.path.exists(candidate):
        return candidate

    return None


def _load_or_cache_audio_data(message: EASMessage, *, variant: str = 'primary') -> Optional[bytes]:
    if variant == 'eom':
        data = message.eom_audio_data
        filename = (message.metadata_payload or {}).get('eom_filename') if message.metadata_payload else None
    else:
        data = message.audio_data
        filename = message.audio_filename

    if data:
        return data

    disk_path = _resolve_eas_disk_path(filename)
    if not disk_path:
        return None

    try:
        with open(disk_path, 'rb') as handle:
            data = handle.read()
    except OSError:
        return None

    if not data:
        return None

    if variant == 'eom':
        message.eom_audio_data = data
    else:
        message.audio_data = data

    try:
        db.session.add(message)
        db.session.commit()
    except Exception:
        db.session.rollback()

    return data


def _load_or_cache_summary_payload(message: EASMessage) -> Optional[Dict[str, Any]]:
    if message.text_payload:
        return dict(message.text_payload)

    disk_path = _resolve_eas_disk_path(message.text_filename)
    if not disk_path:
        return None

    try:
        with open(disk_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug('Unable to load summary payload from %s: %s', disk_path, exc)
        return None

    message.text_payload = payload
    try:
        db.session.add(message)
        db.session.commit()
    except Exception:
        db.session.rollback()

    return dict(payload)


def _remove_eas_files(message: EASMessage) -> None:
    filenames = {
        message.audio_filename,
        message.text_filename,
    }
    metadata = message.metadata_payload or {}
    eom_filename = metadata.get('eom_filename') if isinstance(metadata, dict) else None
    filenames.add(eom_filename)

    for filename in filenames:
        disk_path = _resolve_eas_disk_path(filename)
        if not disk_path:
            continue
        try:
            os.remove(disk_path)
        except OSError:
            continue


# Database configuration
DATABASE_URL = _build_database_url()
os.environ.setdefault('DATABASE_URL', DATABASE_URL)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Configure EAS output integration
EAS_CONFIG = load_eas_config(app.root_path)
app.config['EAS_BROADCAST_ENABLED'] = bool(EAS_CONFIG.get('enabled'))
app.config['EAS_OUTPUT_DIR'] = EAS_CONFIG.get('output_dir')
app.config['EAS_OUTPUT_WEB_SUBDIR'] = EAS_CONFIG.get('web_subdir', 'eas_messages')

# Guard database schema preparation so we only attempt it once per process.
_db_initialized = False
_db_initialization_error = None
logger.info("NOAA Alerts System startup")

# Register route modules
register_routes(app, logger)

# =============================================================================
# BOUNDARY TYPE METADATA
# =============================================================================

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,64}$')

# =============================================================================
# TIMEZONE AND DATETIME UTILITIES
# =============================================================================


def parse_nws_datetime(dt_string):
    """Parse NWS datetime strings while reusing the shared utility logger."""

    return _parse_nws_datetime(dt_string, logger=logger)



# =============================================================================
# SYSTEM MONITORING UTILITIES
# =============================================================================
# =============================================================================
# INTERSECTION CALCULATION ROUTES
# =============================================================================

@app.route('/admin/fix_county_intersections', methods=['POST'])
def fix_county_intersections():
    """Recalculate intersection areas for all active alerts"""
    try:
        active_alerts = get_active_alerts_query().all()
        total_updated = 0

        for alert in active_alerts:
            if not alert.geom:
                continue

            # Delete existing intersections
            Intersection.query.filter_by(cap_alert_id=alert.id).delete()

            # Find all intersecting boundaries
            intersecting_boundaries = db.session.query(
                Boundary.id,
                func.ST_Area(func.ST_Intersection(alert.geom, Boundary.geom)).label('intersection_area')
            ).filter(
                func.ST_Intersects(alert.geom, Boundary.geom),
                func.ST_Area(func.ST_Intersection(alert.geom, Boundary.geom)) > 0
            ).all()

            # Create new intersection records
            for boundary_id, intersection_area in intersecting_boundaries:
                intersection = Intersection(
                    cap_alert_id=alert.id,
                    boundary_id=boundary_id,
                    intersection_area=intersection_area
                )
                db.session.add(intersection)
                total_updated += 1

        db.session.commit()

        return jsonify({
            'success': f'Successfully recalculated intersections for {len(active_alerts)} alerts. Updated {total_updated} intersection records.',
            'alerts_processed': len(active_alerts),
            'intersections_updated': total_updated
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error fixing county intersections: {str(e)}")
        return jsonify({'error': f'Failed to fix intersections: {str(e)}'}), 500


@app.route('/admin/recalculate_intersections', methods=['POST'])
def recalculate_intersections():
    """Recalculate all alert-boundary intersections"""
    try:
        logger.info("Starting full intersection recalculation")

        deleted_count = db.session.query(Intersection).delete()
        logger.info(f"Cleared {deleted_count} existing intersections")

        alerts_with_geometry = db.session.query(CAPAlert).filter(
            CAPAlert.geom.isnot(None)
        ).all()

        stats = {
            'alerts_processed': 0,
            'intersections_created': 0,
            'errors': 0,
            'deleted_intersections': deleted_count
        }

        for alert in alerts_with_geometry:
            try:
                intersections_created = calculate_alert_intersections(alert)
                stats['alerts_processed'] += 1
                stats['intersections_created'] += intersections_created
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error processing alert {alert.identifier}: {str(e)}")

        db.session.commit()

        message = f"Recalculated intersections for {stats['alerts_processed']} alerts, created {stats['intersections_created']} new intersections"
        if stats['errors'] > 0:
            message += f" ({stats['errors']} errors)"

        logger.info(message)
        return jsonify({
            'success': message,
            'stats': stats
        })

    except Exception as e:
        logger.error(f"Error in recalculate_intersections: {str(e)}")
        db.session.rollback()
        return jsonify({'error': f'Failed to recalculate intersections: {str(e)}'}), 500


@app.route('/admin/calculate_intersections/<int:alert_id>', methods=['POST'])
def calculate_intersections_for_alert(alert_id):
    """Calculate and store intersections for a specific alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        if not alert.geom:
            return jsonify({'error': f'Alert {alert_id} has no geometry'}), 400

        # Remove existing intersections for this alert
        existing_count = Intersection.query.filter_by(cap_alert_id=alert_id).count()
        if existing_count > 0:
            Intersection.query.filter_by(cap_alert_id=alert_id).delete()
            logger.info(f"Removed {existing_count} existing intersections for alert {alert_id}")

        # Get all boundaries
        boundaries = Boundary.query.all()

        intersections_created = 0
        intersections_with_area = 0

        for boundary in boundaries:
            if not boundary.geom:
                continue

            # Calculate intersection using PostGIS
            intersection_result = db.session.query(
                func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('intersection_area')
            ).first()

            if intersection_result.intersects:
                # Create intersection record
                intersection = Intersection(
                    cap_alert_id=alert_id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_result.intersection_area or 0
                )
                db.session.add(intersection)
                intersections_created += 1

                if intersection_result.intersection_area and intersection_result.intersection_area > 0:
                    intersections_with_area += 1

        db.session.commit()

        # Log the operation
        log_entry = SystemLog(
            level='INFO',
            message=f'Calculated intersections for alert {alert_id}',
            module='admin',
            details={
                'alert_id': alert_id,
                'alert_event': alert.event,
                'intersections_created': intersections_created,
                'intersections_with_area': intersections_with_area,
                'boundaries_checked': len(boundaries),
                'calculated_at': utc_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Calculated intersections for alert {alert_id}',
            'intersections_created': intersections_created,
            'intersections_with_area': intersections_with_area,
            'boundaries_checked': len(boundaries),
            'alert_event': alert.event
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating intersections for alert {alert_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/calculate_all_intersections', methods=['POST'])
def calculate_all_intersections():
    """Calculate intersections for all alerts"""
    try:
        # Get all alerts with geometry
        alerts_with_geom = CAPAlert.query.filter(CAPAlert.geom.isnot(None)).all()

        total_alerts = len(alerts_with_geom)
        total_intersections = 0
        processed_alerts = 0

        for alert in alerts_with_geom:
            # Remove existing intersections for this alert
            Intersection.query.filter_by(cap_alert_id=alert.id).delete()

            # Get all boundaries
            boundaries = Boundary.query.all()

            alert_intersections = 0
            for boundary in boundaries:
                if not boundary.geom:
                    continue

                # Calculate intersection using PostGIS
                intersection_result = db.session.query(
                    func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                    func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('intersection_area')
                ).first()

                if intersection_result.intersects:
                    intersection = Intersection(
                        cap_alert_id=alert.id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_result.intersection_area or 0
                    )
                    db.session.add(intersection)
                    alert_intersections += 1

            total_intersections += alert_intersections
            processed_alerts += 1

            # Commit every 10 alerts to avoid memory issues
            if processed_alerts % 10 == 0:
                db.session.commit()
                logger.info(f"Processed {processed_alerts}/{total_alerts} alerts")

        # Final commit
        db.session.commit()

        # Log the operation
        log_entry = SystemLog(
            level='INFO',
            message=f'Calculated intersections for all alerts',
            module='admin',
            details={
                'total_alerts_processed': processed_alerts,
                'total_intersections_created': total_intersections,
                'calculated_at': utc_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Calculated intersections for all alerts',
            'alerts_processed': processed_alerts,
            'total_intersections_created': total_intersections
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating all intersections: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/calculate_single_alert/<int:alert_id>', methods=['POST'])
def calculate_single_alert(alert_id):
    """Calculate intersections for a single alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        if not alert.geom:
            return jsonify({'error': 'Alert has no geometry data'}), 400

        deleted_count = Intersection.query.filter_by(cap_alert_id=alert_id).delete()

        boundaries = Boundary.query.all()

        if not boundaries:
            return jsonify({'error': 'No boundaries found in database. Upload some boundary files first.'}), 400

        intersections_created = 0
        errors = []

        for boundary in boundaries:
            try:
                intersection_query = db.session.query(
                    func.ST_Area(
                        func.ST_Intersection(alert.geom, boundary.geom)
                    ).label('intersection_area')
                ).filter(
                    func.ST_Intersects(alert.geom, boundary.geom)
                ).first()

                if intersection_query and intersection_query.intersection_area > 0:
                    intersection = Intersection(
                        cap_alert_id=alert_id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_query.intersection_area
                    )
                    db.session.add(intersection)
                    intersections_created += 1

            except Exception as boundary_error:
                error_msg = f"Boundary {boundary.id}: {str(boundary_error)}"
                errors.append(error_msg)
                logger.warning(error_msg)

        db.session.commit()

        return jsonify({
            'success': f'Successfully calculated {intersections_created} boundary intersections',
            'intersections_created': intersections_created,
            'boundaries_tested': len(boundaries),
            'deleted_intersections': deleted_count,
            'errors': errors
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating single alert: {str(e)}")
        return jsonify({'error': f'Failed to calculate intersections: {str(e)}'}), 500


# =============================================================================
# BOUNDARY MANAGEMENT ROUTES
# =============================================================================

def ensure_alert_source_columns() -> bool:
    """Ensure provenance columns exist for CAP alerts and poll history."""

    engine = db.engine
    if engine.dialect.name != 'postgresql':
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
            logger.info("Adding cap_alerts.source column for alert provenance tracking")
            db.session.execute(text("ALTER TABLE cap_alerts ADD COLUMN source VARCHAR(32)"))
            db.session.execute(
                text("UPDATE cap_alerts SET source = :default WHERE source IS NULL"),
                {"default": ALERT_SOURCE_NOAA},
            )
            db.session.execute(
                text("ALTER TABLE cap_alerts ALTER COLUMN source SET DEFAULT :default"),
                {"default": ALERT_SOURCE_UNKNOWN},
            )
            db.session.execute(text("ALTER TABLE cap_alerts ALTER COLUMN source SET NOT NULL"))
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
            db.session.execute(text("ALTER TABLE poll_history ADD COLUMN data_source VARCHAR(64)"))
            changed = True

        if changed:
            db.session.commit()
        return True
    except Exception as exc:
        logger.warning("Could not ensure alert source columns: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def ensure_boundary_geometry_column():
    """Ensure the boundaries table accepts any geometry subtype with SRID 4326."""
    engine = db.engine
    if engine.dialect.name != 'postgresql':
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
            {'table': 'boundaries', 'column': 'geom'}
        ).scalar()

        if result and result.upper() == 'MULTIPOLYGON':
            logger.info("Updating boundaries.geom column to support multiple geometry types")
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
            logger.debug("geometry_columns entry for boundaries.geom not found; skipping type verification")
        return True
    except Exception as exc:
        logger.warning("Could not ensure boundaries.geom column configuration: %s", exc)
        db.session.rollback()
        return False


def ensure_postgis_extension() -> bool:
    """Enable the PostGIS extension when running against PostgreSQL."""

    engine = db.engine
    if engine.dialect.name != 'postgresql':
        return True

    try:
        db.session.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
        db.session.commit()
    except OperationalError as exc:
        logger.error('Failed to enable PostGIS extension: %s', exc)
        db.session.rollback()
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('Unexpected error enabling PostGIS extension: %s', exc)
        db.session.rollback()
        raise
    else:
        logger.info('PostGIS extension ensured for the active database')
        return True


@app.route('/admin/check_db_health', methods=['GET'])
def check_db_health():
    """Provide a quick health check of the database connection and size."""
    try:
        db.session.execute(text('SELECT 1'))
        connectivity_status = 'Connected'
    except OperationalError as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return jsonify({'error': 'Database connectivity check failed.'}), 500
    except Exception as exc:
        logger.error("Unexpected error during database health check: %s", exc)
        return jsonify({'error': 'Database health check encountered an unexpected error.'}), 500

    database_size = 'Unavailable'
    try:
        size_bytes = db.session.execute(
            text('SELECT pg_database_size(current_database())')
        ).scalar()
        if size_bytes is not None:
            database_size = format_bytes(size_bytes)
    except Exception as exc:
        logger.warning("Could not determine database size: %s", exc)

    active_connections: Union[str, int] = 'Unavailable'
    try:
        connection_count = db.session.execute(
            text('SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()')
        ).scalar()
        if connection_count is not None:
            active_connections = int(connection_count)
    except Exception as exc:
        logger.warning("Could not determine active connection count: %s", exc)

    return jsonify({
        'connectivity': connectivity_status,
        'database_size': database_size,
        'active_connections': active_connections,
        'checked_at': utc_now().isoformat()
    })


@app.route('/admin/preview_geojson', methods=['POST'])
def preview_geojson():
    """Preview GeoJSON contents and extract useful metadata without persisting."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        raw_boundary_type = request.form.get('boundary_type', 'unknown')
        boundary_type = normalize_boundary_type(raw_boundary_type)
        boundary_label = get_boundary_display_label(raw_boundary_type)

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.lower().endswith('.geojson'):
            return jsonify({'error': 'File must be a GeoJSON file'}), 400

        try:
            file_contents = file.read().decode('utf-8')
        except UnicodeDecodeError:
            return jsonify({'error': 'Unable to decode file. Please ensure it is UTF-8 encoded.'}), 400

        try:
            geojson_data = json.loads(file_contents)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid GeoJSON format'}), 400

        features = geojson_data.get('features')
        if not isinstance(features, list) or not features:
            return jsonify({
                'error': 'GeoJSON file does not contain any features.',
                'boundary_type': boundary_label,
                'total_features': 0
            }), 400

        preview_limit = 5
        previews: List[Dict[str, Any]] = []
        all_fields = set()
        owner_fields = set()
        line_id_fields = set()
        recommended_fields = set()

        for feature in features:
            properties = feature.get('properties', {}) or {}
            all_fields.update(properties.keys())

        for feature in features[:preview_limit]:
            properties = feature.get('properties', {}) or {}
            name, description = extract_name_and_description(properties, boundary_type)
            metadata = extract_feature_metadata(feature)

            preview_entry = {
                'name': name,
                'description': description,
                'owner': metadata.get('owner'),
                'line_id': metadata.get('line_id'),
                'mtfcc': metadata.get('mtfcc'),
                'classification': metadata.get('classification'),
                'length_label': metadata.get('length_label'),
                'additional_details': metadata.get('additional_details'),
            }
            previews.append(preview_entry)

            if metadata.get('owner_field'):
                owner_fields.add(metadata['owner_field'])
            if metadata.get('line_id_field'):
                line_id_fields.add(metadata['line_id_field'])
            recommended_fields.update(metadata.get('recommended_fields', set()))

        response_data = {
            'boundary_type': boundary_label,
            'normalized_type': boundary_type,
            'total_features': len(features),
            'preview_count': len(previews),
            'all_fields': sorted(all_fields),
            'previews': previews,
            'owner_fields': sorted(owner_fields),
            'line_id_fields': sorted(line_id_fields),
            'recommended_additional_fields': sorted(recommended_fields),
            'field_mappings': get_field_mappings().get(boundary_type, {}),
        }

        return jsonify(response_data)

    except Exception as exc:
        logger.error("Error previewing GeoJSON: %s", exc)
        return jsonify({'error': f'Failed to preview GeoJSON: {str(exc)}'}), 500


@app.route('/admin/upload_boundaries', methods=['POST'])
def upload_boundaries():
    """Upload GeoJSON boundary file with enhanced processing"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        raw_boundary_type = request.form.get('boundary_type', 'unknown')
        boundary_type = normalize_boundary_type(raw_boundary_type)
        boundary_label = get_boundary_display_label(raw_boundary_type)

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.lower().endswith('.geojson'):
            return jsonify({'error': 'File must be a GeoJSON file'}), 400

        try:
            geojson_data = json.loads(file.read().decode('utf-8'))
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid GeoJSON format'}), 400

        features = geojson_data.get('features', [])
        boundaries_added = 0
        errors = []

        for i, feature in enumerate(features):
            try:
                properties = feature.get('properties', {})
                geometry = feature.get('geometry')

                if not geometry:
                    errors.append(f"Feature {i + 1}: No geometry")
                    continue

                name, description = extract_name_and_description(properties, boundary_type)

                geometry_json = json.dumps(geometry)

                boundary = Boundary(
                    name=name,
                    type=boundary_type,
                    description=description,
                    created_at=utc_now(),
                    updated_at=utc_now()
                )

                boundary.geom = db.session.execute(
                    text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)"),
                    {"geom": geometry_json}
                ).scalar()

                db.session.add(boundary)
                boundaries_added += 1

            except Exception as e:
                errors.append(f"Feature {i + 1}: {str(e)}")

        try:
            db.session.commit()
            logger.info(
                "Successfully uploaded %s %s boundaries",
                boundaries_added,
                boundary_label,
            )
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Database error: {str(e)}'}), 500

        response_data = {
            'success': f'Successfully uploaded {boundaries_added} {boundary_label} boundaries',
            'boundaries_added': boundaries_added,
            'total_features': len(features),
            'errors': errors[:10] if errors else [],
            'normalized_type': boundary_type,
            'display_label': boundary_label,
        }

        if errors:
            response_data['warning'] = f'{len(errors)} features had errors'

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error uploading boundaries: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


@app.route('/admin/clear_boundaries/<boundary_type>', methods=['DELETE'])
def clear_boundaries(boundary_type):
    """Clear all boundaries of a specific type"""
    try:
        normalized_type = None

        if boundary_type == 'all':
            deleted_count = Boundary.query.delete()
            message = f'Deleted all {deleted_count} boundaries'
        else:
            normalized_type = normalize_boundary_type(boundary_type)
            deleted_count = Boundary.query.filter(
                func.lower(Boundary.type) == normalized_type
            ).delete(synchronize_session=False)
            message = (
                f"Deleted {deleted_count} {get_boundary_display_label(boundary_type)} boundaries"
            )

        db.session.commit()

        log_entry = SystemLog(
            level='WARNING',
            message=message,
            module='admin',
            details={
                'boundary_type': boundary_type,
                'normalized_type': normalized_type if boundary_type != 'all' else 'all',
                'deleted_count': deleted_count,
                'deleted_at_utc': utc_now().isoformat(),
                'deleted_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': message, 'deleted_count': deleted_count})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing boundaries: {str(e)}")
        return jsonify({'error': f'Failed to clear boundaries: {str(e)}'}), 500


@app.route('/admin/clear_all_boundaries', methods=['DELETE'])
def clear_all_boundaries():
    """Clear all boundaries (requires confirmation)"""
    try:
        data = request.get_json() or {}

        confirmation_level = data.get('confirmation_level', 0)
        text_confirmation = data.get('text_confirmation', '')

        if confirmation_level < 2 or text_confirmation != 'DELETE ALL BOUNDARIES':
            return jsonify({'error': 'Invalid confirmation. This action requires proper confirmation.'}), 400

        deleted_count = Boundary.query.delete()
        db.session.commit()

        log_entry = SystemLog(
            level='CRITICAL',
            message=f'DELETED ALL BOUNDARIES: {deleted_count} boundaries permanently removed',
            module='admin',
            details={
                'deleted_count': deleted_count,
                'confirmation_level': confirmation_level,
                'deleted_at_utc': utc_now().isoformat(),
                'deleted_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Successfully deleted all {deleted_count} boundaries',
            'deleted_count': deleted_count
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing all boundaries: {str(e)}")
        return jsonify({'error': f'Failed to clear all boundaries: {str(e)}'}), 500


# =============================================================================
# DEBUG AND TESTING ROUTES
# =============================================================================

@app.route('/debug/alert/<int:alert_id>')
def debug_alert(alert_id):
    """Debug route to inspect alert geometry and intersections"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        geometry_info = None
        if alert.geom:
            geom_result = db.session.execute(
                text("""
                    SELECT 
                        ST_GeometryType(:geom) as type,
                        ST_SRID(:geom) as srid,
                        ST_Area(:geom) as area
                """),
                {"geom": alert.geom}
            ).fetchone()

            geometry_info = {
                'type': geom_result.type,
                'srid': geom_result.srid,
                'area': float(geom_result.area)
            }

        intersection_results = []
        if alert.geom:
            boundaries = Boundary.query.all()
            for boundary in boundaries:
                if boundary.geom:
                    try:
                        intersection_result = db.session.execute(
                            text("""
                                SELECT ST_Intersects(:alert_geom, :boundary_geom) as intersects,
                                       ST_Area(ST_Intersection(:alert_geom, :boundary_geom)) as area
                            """),
                            {
                                'alert_geom': alert.geom,
                                'boundary_geom': boundary.geom
                            }
                        ).fetchone()

                        intersection_results.append({
                            'boundary_id': boundary.id,
                            'boundary_name': boundary.name,
                            'boundary_type': boundary.type,
                            'intersects': bool(intersection_result.intersects),
                            'intersection_area': float(intersection_result.area) if intersection_result.area else 0
                        })
                    except Exception as e:
                        logger.error(f"Error checking intersection with boundary {boundary.id}: {e}")

        existing_intersections = db.session.query(Intersection).filter_by(cap_alert_id=alert_id).count()
        boundaries_in_db = Boundary.query.count()

        debug_info = {
            'alert_id': alert_id,
            'alert_event': alert.event,
            'alert_area_desc': alert.area_desc,
            'has_geometry': alert.geom is not None,
            'geometry_info': geometry_info,
            'boundaries_in_db': boundaries_in_db,
            'existing_intersections': existing_intersections,
            'intersection_results': intersection_results,
            'intersections_found': len([r for r in intersection_results if r['intersects']]),
            'errors': []
        }

        return jsonify(debug_info)

    except Exception as e:
        logger.error(f"Error debugging alert {alert_id}: {str(e)}")
        return jsonify({'error': f'Debug failed: {str(e)}'}), 500


@app.route('/debug/boundaries/<int:alert_id>')
def debug_boundaries(alert_id):
    """Debug boundary intersections for a specific alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        debug_info = {
            'alert_id': alert_id,
            'alert_event': alert.event,
            'alert_area_desc': alert.area_desc,
            'has_geometry': alert.geom is not None,
            'boundaries_in_db': Boundary.query.count(),
            'existing_intersections': Intersection.query.filter_by(cap_alert_id=alert_id).count(),
            'errors': []
        }

        if not alert.geom:
            debug_info['errors'].append('Alert has no geometry data')
            return jsonify(debug_info)

        boundaries = Boundary.query.all()
        intersection_results = []

        for boundary in boundaries:
            try:
                intersection_test = db.session.query(
                    func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                    func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('area')
                ).first()

                intersection_results.append({
                    'boundary_id': boundary.id,
                    'boundary_name': boundary.name,
                    'boundary_type': boundary.type,
                    'intersects': bool(
                        intersection_test.intersects) if intersection_test.intersects is not None else False,
                    'intersection_area': float(intersection_test.area) if intersection_test.area else 0
                })

            except Exception as boundary_error:
                debug_info['errors'].append(f'Error testing boundary {boundary.id}: {str(boundary_error)}')

        debug_info['intersection_results'] = intersection_results
        debug_info['intersections_found'] = len([r for r in intersection_results if r['intersects']])

        try:
            geom_info = db.session.query(
                func.ST_GeometryType(alert.geom).label('geom_type'),
                func.ST_SRID(alert.geom).label('srid'),
                func.ST_Area(alert.geom).label('area')
            ).first()

            debug_info['geometry_info'] = {
                'type': geom_info.geom_type if geom_info else 'Unknown',
                'srid': geom_info.srid if geom_info else 'Unknown',
                'area': float(geom_info.area) if geom_info and geom_info.area else 0
            }
        except Exception as geom_error:
            debug_info['errors'].append(f'Error getting geometry info: {str(geom_error)}')

        return jsonify(debug_info)

    except Exception as e:
        logger.error(f"Error in debug_boundaries: {str(e)}")
        return jsonify({'error': str(e), 'alert_id': alert_id}), 500


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found_error(error):
    """Enhanced 404 error page"""
    return render_template_string("""
    <h1>404 - Page Not Found</h1>
    <p>The page you're looking for doesn't exist.</p>
    <p><a href='/'>← Back to Main</a> | <a href='/admin'>Admin</a> | <a href='/alerts'>Alerts</a></p>
    """), 404


@app.errorhandler(500)
def internal_error(error):
    """Enhanced 500 error page"""
    if hasattr(db, 'session') and db.session:
        db.session.rollback()

    return render_template_string("""
    <h1>500 - Internal Server Error</h1>
    <p>Something went wrong on our end. Please try again later.</p>
    <p><a href='/'>← Back to Main</a> | <a href='/admin'>Admin</a></p>
    """), 500


@app.errorhandler(403)
def forbidden_error(error):
    """403 Forbidden error page"""
    return render_template_string("""
    <h1>403 - Forbidden</h1>
    <p>You don't have permission to access this resource.</p>
    <p><a href='/'>← Back to Main</a></p>
    """), 403


@app.errorhandler(400)
def bad_request_error(error):
    """400 Bad Request error page"""
    return render_template_string("""
    <h1>400 - Bad Request</h1>
    <p>The request was malformed or invalid.</p>
    <p><a href='/'>← Back to Main</a></p>
    """), 400


# =============================================================================
# HEALTH CHECK AND MONITORING ROUTES
# =============================================================================

@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    try:
        # Test database connection
        db.session.execute(text('SELECT 1')).fetchone()

        return jsonify({
            'status': 'healthy',
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat(),
            'version': SYSTEM_VERSION,
            'database': 'connected',
            'led_available': LED_AVAILABLE
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat()
        }), 500


@app.route('/ping')
def ping():
    """Simple ping endpoint"""
    return jsonify({
        'pong': True,
        'timestamp': utc_now().isoformat(),
        'local_timestamp': local_now().isoformat()
    })


@app.route('/version')
def version():
    """Version information endpoint"""
    location = get_location_settings()
    return jsonify({
        'version': SYSTEM_VERSION,
        'name': 'NOAA CAP Alerts System',
        'author': 'KR8MER Amateur Radio Emergency Communications',
        'description': f"Emergency alert system for {location['county_name']}, {location['state_code']}",
        'timezone': get_location_timezone_name(),
        'led_available': LED_AVAILABLE,
        'timestamp': utc_now().isoformat(),
        'local_timestamp': local_now().isoformat()
    })


# =============================================================================
# ADDITIONAL UTILITY ROUTES
# =============================================================================

@app.route('/favicon.ico')
def favicon():
    """Serve favicon"""
    return '', 204


@app.route('/robots.txt')
def robots():
    """Robots.txt for web crawlers"""
    return """User-agent: *
Disallow: /admin/
Disallow: /api/
Disallow: /debug/
Allow: /
""", 200, {'Content-Type': 'text/plain'}


# =============================================================================
# CONTEXT PROCESSORS FOR TEMPLATES
# =============================================================================

@app.context_processor
def inject_global_vars():
    """Inject global variables into all templates"""
    location_settings = get_location_settings()
    return {
        'current_utc_time': utc_now(),
        'current_local_time': local_now(),
        'timezone_name': get_location_timezone_name(),
        'led_available': LED_AVAILABLE,
        'system_version': SYSTEM_VERSION,
        'location_settings': location_settings,
        'boundary_type_config': BOUNDARY_TYPE_CONFIG,
        'boundary_group_labels': BOUNDARY_GROUP_LABELS,
        'current_user': getattr(g, 'current_user', None),
        'eas_broadcast_enabled': app.config.get('EAS_BROADCAST_ENABLED', False),
        'eas_output_web_subdir': app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
    }


# =============================================================================
# REQUEST HOOKS
# =============================================================================

@app.before_request
def before_request():
    """Before request hook for logging and setup"""
    # Log API requests for debugging
    if request.path.startswith('/api/') and request.method in ['POST', 'PUT', 'DELETE']:
        logger.info(f"{request.method} {request.path} from {request.remote_addr}")

    # Ensure the database schema exists before handling the request.
    initialize_database()

    # Load the current user from the session for downstream use.
    g.current_user = None
    user_id = session.get('user_id')
    if user_id is not None:
        user = AdminUser.query.get(user_id)
        if user and user.is_active:
            g.current_user = user
        else:
            session.pop('user_id', None)

    try:
        g.admin_setup_mode = AdminUser.query.count() == 0
    except Exception:
        g.admin_setup_mode = False

    # Allow authentication endpoints without additional checks.
    if request.endpoint in {'login', 'static'}:
        return

    protected_prefixes = ('/admin', '/logs')
    if any(request.path.startswith(prefix) for prefix in protected_prefixes):
        if g.current_user is None:
            if g.admin_setup_mode and request.endpoint in {'admin', 'admin_users'}:
                if request.method == 'GET' or (request.method == 'POST' and request.endpoint == 'admin_users'):
                    return
            accept_header = request.headers.get('Accept', '')
            next_url = request.full_path if request.query_string else request.path
            if request.method != 'GET' or 'application/json' in accept_header or request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login', next=next_url))


@app.after_request
def after_request(response):
    """After request hook for headers and cleanup"""
    # Add CORS headers for API endpoints
    if request.path.startswith('/api/'):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

    # Add security headers
    response.headers.add('X-Content-Type-Options', 'nosniff')
    response.headers.add('X-Frame-Options', 'DENY')
    response.headers.add('X-XSS-Protection', '1; mode=block')

    return response


# Flask 3 removed the ``before_first_request`` hook in favour of
# ``before_serving``.  Older Flask releases (including the one bundled with
# this project) do not provide ``before_serving`` though, so we register the
# handler dynamically depending on which hook is available.  If neither hook is
# present we fall back to running the initialization immediately within an
# application context.
def initialize_database():
    """Create all database tables, logging any initialization failure."""
    global _db_initialized, _db_initialization_error

    if _db_initialized:
        return

    try:
        if not ensure_postgis_extension():
            _db_initialization_error = RuntimeError("PostGIS extension could not be ensured")
            return False
        db.create_all()
        if not ensure_alert_source_columns():
            _db_initialization_error = RuntimeError("CAP alert source columns could not be ensured")
            return False
        ensure_boundary_geometry_column()
        settings = get_location_settings(force_reload=True)
        timezone_name = settings.get('timezone')
        if timezone_name:
            set_location_timezone(timezone_name)
        if not LED_AVAILABLE:
            initialise_led_controller(logger)
            ensure_led_tables()
    except OperationalError as db_error:
        _db_initialization_error = db_error
        logger.error("Database initialization failed: %s", db_error)
        return False
    except Exception as db_error:
        _db_initialization_error = db_error
        logger.error("Database initialization failed: %s", db_error)
        raise
    else:
        _db_initialized = True
        _db_initialization_error = None
        logger.info("Database tables ensured on startup")
        return True


if hasattr(app, "before_serving"):
    app.before_serving(initialize_database)
elif hasattr(app, "before_first_request"):
    app.before_first_request(initialize_database)
else:
    with app.app_context():
        initialize_database()


# =============================================================================
# CLI COMMANDS (for future use with Flask CLI)
# =============================================================================

@app.cli.command()
def init_db():
    """Initialize the database tables"""
    initialize_database()
    logger.info("Database tables created successfully")


@app.cli.command()
def test_led():
    """Test LED controller connection"""
    if led_controller:
        try:
            status = led_controller.get_status()
            logger.info(f"LED Status: {status}")

            # Send test message
            result = led_controller.send_message("TEST MESSAGE")
            logger.info(f"Test message sent: {result}")
        except Exception as e:
            logger.error(f"LED test failed: {e}")
    else:
        logger.warning("LED controller not available")


@app.cli.command('create-admin-user')
@click.option('--username', prompt=True)
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin_user_cli(username: str, password: str):
    """Create a new administrator user account."""
    initialize_database()

    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        raise click.ClickException('Usernames must be 3-64 characters and may include letters, numbers, dots, underscores, and hyphens.')

    if len(password) < 8:
        raise click.ClickException('Password must be at least 8 characters long.')

    existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
    if existing:
        raise click.ClickException('That username already exists.')

    user = AdminUser(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.add(SystemLog(
        level='INFO',
        message='Administrator account created via CLI',
        module='auth',
        details={'username': username},
    ))
    db.session.commit()

    click.echo(f'Created administrator account for {username}.')


@app.cli.command()
def cleanup_expired():
    """Mark expired alerts as expired (safe cleanup)"""
    try:
        now = utc_now()
        expired_alerts = CAPAlert.query.filter(
            CAPAlert.expires < now,
            CAPAlert.status != 'Expired'
        ).all()

        count = 0
        for alert in expired_alerts:
            alert.status = 'Expired'
            alert.updated_at = now
            count += 1

        db.session.commit()
        logger.info(f"Marked {count} alerts as expired")

    except Exception as e:
        logger.error(f"Error in cleanup: {e}")
        db.session.rollback()


# =============================================================================
# APPLICATION STARTUP AND CONFIGURATION
# =============================================================================

def create_app(config=None):
    """Application factory pattern for testing"""
    if config:
        app.config.update(config)

    with app.app_context():
        initialize_database()

    return app


# =============================================================================
# APPLICATION STARTUP
# =============================================================================

if __name__ == '__main__':
    with app.app_context():
        initialize_database()

    app.run(debug=True, host='0.0.0.0', port=5000)
