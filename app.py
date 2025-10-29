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
import requests
import pytz

# Application utilities
from app_utils import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_MANUAL,
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    UTC_TZ,
    format_bytes,
    get_location_timezone,
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

# NOAA API configuration for manual alert import workflows
NOAA_API_BASE_URL = 'https://api.weather.gov/alerts'
# Allowed query parameters documented at
# https://www.weather.gov/documentation/services-web-api#/default/get_alerts
NOAA_ALLOWED_QUERY_PARAMS = frozenset({
    'area',
    'zone',
    'region',
    'region_type',
    'point',
    'start',
    'end',
    'event',
    'status',
    'message_type',
    'urgency',
    'severity',
    'certainty',
    'limit',
    'cursor',
})
NOAA_USER_AGENT = os.environ.get(
    'NOAA_USER_AGENT',
    'KR8MER Emergency Alert Hub/2.1 (+https://github.com/KR8MER/noaa_alerts_systems; NOAA+IPAWS)'
)


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
@app.route('/admin/trigger_poll', methods=['POST'])
def trigger_poll():
    """Manually trigger CAP alert polling with timezone logging"""
    try:
        log_entry = SystemLog(
            level='INFO',
            message='Manual CAP poll triggered',
            module='admin',
            details={
                'triggered_at_utc': utc_now().isoformat(),
                'triggered_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'message': 'CAP poll triggered successfully'})
    except Exception as e:
        logger.error(f"Error triggering poll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/location_settings', methods=['GET', 'PUT'])
def admin_location_settings():
    """Retrieve or update the configurable location settings."""
    try:
        if request.method == 'GET':
            settings = get_location_settings()
            return jsonify({'settings': settings})

        payload = request.get_json(silent=True) or {}
        updated = update_location_settings({
            'county_name': payload.get('county_name'),
            'state_code': payload.get('state_code'),
            'timezone': payload.get('timezone'),
            'zone_codes': payload.get('zone_codes'),
            'area_terms': payload.get('area_terms'),
            'led_default_lines': payload.get('led_default_lines'),
            'map_center_lat': payload.get('map_center_lat'),
            'map_center_lng': payload.get('map_center_lng'),
            'map_default_zoom': payload.get('map_default_zoom'),
        })
        return jsonify({'success': 'Location settings updated', 'settings': updated})
    except Exception as e:
        logger.error("Error processing location settings update: %s", e)
        return jsonify({'error': f'Failed to process location settings: {str(e)}'}), 500


class NOAAImportError(Exception):
    """Raised when manual NOAA alert retrieval fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        query_url: Optional[str] = None,
        params: Optional[Dict[str, Union[str, int]]] = None,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.query_url = query_url
        self.params = params
        self.detail = detail


def normalize_manual_import_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Normalize manual import datetimes to UTC for consistent NOAA queries."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            dt_value = datetime.fromisoformat(raw_value)
        except ValueError:
            try:
                dt_value = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
            except ValueError:
                logger.warning("Manual import received unrecognized datetime format: %s", raw_value)
                return None
    if dt_value.tzinfo is None:
        dt_value = get_location_timezone().localize(dt_value)
    return dt_value.astimezone(UTC_TZ)


def format_noaa_timestamp(dt_value: Optional[datetime]) -> Optional[str]:
    """Render UTC timestamps in the NOAA API's preferred ISO format."""
    if not dt_value:
        return None
    return dt_value.astimezone(UTC_TZ).strftime('%Y-%m-%dT%H:%M:%SZ')


def build_noaa_alert_request(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
) -> Tuple[str, Optional[Dict[str, Union[str, int]]]]:
    """Construct the NOAA alerts endpoint and query parameters for manual imports."""
    query_url = NOAA_API_BASE_URL
    params: Optional[Dict[str, Union[str, int]]] = None

    if identifier:
        encoded_identifier = quote(identifier.strip(), safe=':.')
        query_url = f"{NOAA_API_BASE_URL}/{encoded_identifier}.json"
    else:
        params = {}
        if start:
            formatted_start = format_noaa_timestamp(start)
            if formatted_start:
                params['start'] = formatted_start
        if end:
            formatted_end = format_noaa_timestamp(end)
            if formatted_end:
                params['end'] = formatted_end
        if area:
            params['area'] = area
        if event:
            params['event'] = event

        if params:
            params = {
                key: value
                for key, value in params.items()
                if key in NOAA_ALLOWED_QUERY_PARAMS and value is not None
            } or None
        else:
            params = None

    return query_url, params


def _alert_datetime_to_iso(dt_value: Optional[datetime]) -> Optional[str]:
    """Render alert datetimes in ISO8601 with UTC timezone."""

    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        aware_value = dt_value.replace(tzinfo=UTC_TZ)
    else:
        aware_value = dt_value.astimezone(UTC_TZ)
    return aware_value.isoformat()


def serialize_admin_alert(alert: CAPAlert) -> Dict[str, Any]:
    """Return a JSON-serializable representation of an alert for admin tooling."""

    return {
        'id': alert.id,
        'identifier': alert.identifier,
        'event': alert.event,
        'source': alert.source,
        'headline': alert.headline,
        'description': alert.description,
        'instruction': alert.instruction,
        'area_desc': alert.area_desc,
        'status': alert.status,
        'message_type': alert.message_type,
        'scope': alert.scope,
        'category': alert.category,
        'severity': alert.severity,
        'urgency': alert.urgency,
        'certainty': alert.certainty,
        'sent': _alert_datetime_to_iso(alert.sent),
        'expires': _alert_datetime_to_iso(alert.expires),
        'updated_at': _alert_datetime_to_iso(alert.updated_at),
        'created_at': _alert_datetime_to_iso(alert.created_at),
    }


def retrieve_noaa_alerts(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
) -> Tuple[List[dict], str, Optional[Dict[str, Union[str, int]]]]:
    """Execute a NOAA alerts query and return parsed features."""
    query_url, params = build_noaa_alert_request(
        identifier=identifier,
        start=start,
        end=end,
        area=area,
        event=event,
        limit=limit,
    )

    headers = {
        'Accept': 'application/geo+json, application/json;q=0.9',
        'User-Agent': NOAA_USER_AGENT,
    }

    try:
        response = requests.get(query_url, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        logger.error("NOAA alert import request failed: %s", exc)
        raise NOAAImportError(
            f'Failed to retrieve NOAA alert data: {exc}',
            query_url=query_url,
            params=params,
        ) from exc

    final_url = response.url

    if response.status_code == 404:
        raise NOAAImportError(
            'No alert was found for the supplied identifier or filters.',
            status_code=404,
            query_url=final_url,
            params=params,
        )

    if response.status_code >= 400:
        error_detail: Optional[str] = None
        parameter_errors: Optional[List[str]] = None
        try:
            error_payload = response.json()
            if isinstance(error_payload, dict):
                error_detail = error_payload.get('detail') or error_payload.get('title')
                raw_parameter_errors = error_payload.get('parameterErrors')
                if isinstance(raw_parameter_errors, list):
                    formatted_errors = []
                    for item in raw_parameter_errors:
                        if isinstance(item, dict):
                            name = item.get('parameter')
                            message = item.get('message')
                            if name and message:
                                formatted_errors.append(f"{name}: {message}")
                    if formatted_errors:
                        parameter_errors = formatted_errors
        except ValueError:
            error_detail = response.text.strip() or None

        logger.error(
            "NOAA manual import returned %s for %s with params %s: %s",
            response.status_code,
            final_url,
            params,
            error_detail or 'no error payload provided'
        )

        message = f'Failed to retrieve NOAA alert data: {response.status_code} {response.reason}'
        if error_detail:
            message = f"{message} ({error_detail})"
        if parameter_errors:
            message = f"{message} — {'; '.join(parameter_errors)}"

        raise NOAAImportError(
            message,
            status_code=response.status_code,
            query_url=final_url,
            params=params,
            detail=error_detail,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("NOAA alert import returned invalid JSON: %s", exc)
        raise NOAAImportError(
            'NOAA API response could not be decoded as JSON.',
            query_url=final_url,
            params=params,
        ) from exc

    if identifier:
        if isinstance(payload, dict) and 'features' in payload:
            alerts_payloads = payload.get('features', []) or []
        else:
            alerts_payloads = [payload]
    else:
        alerts_payloads = payload.get('features', []) if isinstance(payload, dict) else []

    if not identifier:
        try:
            effective_limit = max(1, min(int(limit or 10), 50))
        except (TypeError, ValueError):
            effective_limit = 10
        alerts_payloads = alerts_payloads[:effective_limit]

    if not alerts_payloads:
        raise NOAAImportError(
            'NOAA API did not return any alerts for the provided criteria.',
            status_code=404,
            query_url=final_url,
            params=params,
        )

    return alerts_payloads, final_url, params


@app.route('/admin/import_alert', methods=['POST'])
def import_specific_alert():
    """Manually import NOAA alerts (including expired) by identifier or date range."""
    data = request.get_json(silent=True) or request.form or {}

    identifier = (data.get('identifier') or '').strip()
    start_raw = (data.get('start') or '').strip()
    end_raw = (data.get('end') or '').strip()
    area = (data.get('area') or '').strip()
    event_filter = (data.get('event') or '').strip()

    try:
        limit_value = int(data.get('limit', 10))
    except (TypeError, ValueError):
        limit_value = 10
    limit_value = max(1, min(limit_value, 50))

    start_dt = normalize_manual_import_datetime(start_raw)
    end_dt = normalize_manual_import_datetime(end_raw)

    if start_raw and start_dt is None:
        return jsonify({'error': 'Could not parse the provided start timestamp. Use ISO 8601 format (e.g., 2025-01-15T13:00:00-05:00).'}), 400

    if end_raw and end_dt is None:
        return jsonify({'error': 'Could not parse the provided end timestamp. Use ISO 8601 format (e.g., 2025-01-15T18:00:00-05:00).'}), 400

    if not identifier and not (start_dt and end_dt):
        return jsonify({
            'error': 'Provide an alert identifier or both start and end timestamps.'
        }), 400

    now_utc = utc_now()
    if end_dt and end_dt > now_utc:
        logger.info(
            "Clamping manual NOAA import end time %s to current UTC %s", end_dt.isoformat(), now_utc.isoformat()
        )
        end_dt = now_utc

    if start_dt and end_dt and start_dt > end_dt:
        return jsonify({'error': 'The start time must be before the end time.'}), 400

    cleaned_area = ''.join(ch for ch in area.upper() if ch.isalpha()) if area else ''
    normalized_area = cleaned_area[:2] if cleaned_area else None

    if identifier:
        if area and (not normalized_area or len(normalized_area) != 2):
            return jsonify({'error': 'State filters must use the two-letter postal abbreviation.'}), 400
    else:
        if not normalized_area or len(normalized_area) != 2:
            return jsonify({'error': 'Provide the two-letter state code when searching without an identifier.'}), 400

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
        response_payload = {
            'error': str(exc),
            'status_code': exc.status_code,
            'query_url': exc.query_url,
            'params': exc.params,
        }
        if exc.detail:
            response_payload['detail'] = exc.detail
        if status_code == 404 and identifier:
            response_payload['identifier'] = identifier
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
            alert_identifier = parsed['identifier']
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
                    logger.warning(
                        "Intersection recalculation failed for alert %s: %s",
                        alert_identifier,
                        intersection_error
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
                    logger.warning(
                        "Intersection calculation failed for new alert %s: %s",
                        alert_identifier,
                        intersection_error
                    )
                inserted += 1

        log_entry = SystemLog(
            level='INFO',
            message='Manual NOAA alert import executed',
            module='admin',
            details={
                'identifiers': identifiers,
                'inserted': inserted,
                'updated': updated,
                'skipped': skipped,
                'query_url': query_url,
                'params': params,
                'requested_filters': {
                    'identifier': identifier or None,
                    'start': start_iso,
                    'end': end_iso,
                    'area': normalized_area,
                    'event': event_filter or None,
                    'limit': limit_value,
                },
                'requested_at_utc': utc_now().isoformat(),
                'requested_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        logger.error("Manual NOAA alert import failed: %s", exc)
        return jsonify({'error': f'Failed to import NOAA alert data: {exc}'}), 500

    return jsonify({
        'message': f'Imported {inserted} alert(s) and updated {updated} existing alert(s).',
        'inserted': inserted,
        'updated': updated,
        'skipped': skipped,
        'identifiers': identifiers,
        'query_url': query_url,
        'params': params
    })


@app.route('/admin/alerts', methods=['GET'])
def admin_list_alerts():
    """List alerts for the admin UI with optional search and expiration filters."""

    try:
        include_expired = request.args.get('include_expired', 'false').lower() == 'true'
        search_term = (request.args.get('search') or '').strip()
        limit_param = request.args.get('limit', type=int)
        limit = 100 if not limit_param else max(1, min(limit_param, 200))

        base_query = CAPAlert.query

        if not include_expired:
            now = utc_now()
            base_query = base_query.filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
            )

        if search_term:
            like_pattern = f"%{search_term}%"
            base_query = base_query.filter(
                or_(
                    CAPAlert.identifier.ilike(like_pattern),
                    CAPAlert.event.ilike(like_pattern),
                    CAPAlert.headline.ilike(like_pattern)
                )
            )

        total_count = base_query.order_by(None).count()
        alerts = (
            base_query
            .order_by(desc(CAPAlert.sent))
            .limit(limit)
            .all()
        )

        serialized_alerts = [serialize_admin_alert(alert) for alert in alerts]

        return jsonify({
            'alerts': serialized_alerts,
            'returned': len(serialized_alerts),
            'total': total_count,
            'include_expired': include_expired,
            'limit': limit,
            'search': search_term or None,
        })
    except Exception as exc:
        logger.error("Failed to load alerts for admin listing: %s", exc)
        return jsonify({'error': 'Failed to load alerts.'}), 500


@app.route('/admin/alerts/<int:alert_id>', methods=['GET', 'PATCH', 'DELETE'])
def admin_alert_detail(alert_id: int):
    """Retrieve, update, or delete a single alert from the admin interface."""

    alert = CAPAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': 'Alert not found.'}), 404

    if request.method == 'GET':
        return jsonify({'alert': serialize_admin_alert(alert)})

    if request.method == 'DELETE':
        identifier = alert.identifier
        try:
            Intersection.query.filter_by(cap_alert_id=alert.id).delete(synchronize_session=False)

            try:
                if ensure_led_tables():
                    LEDMessage.query.filter_by(alert_id=alert.id).delete(synchronize_session=False)
            except Exception as led_cleanup_error:
                logger.warning(
                    "Failed to clean LED messages for alert %s during deletion: %s",
                    identifier,
                    led_cleanup_error,
                )
                db.session.rollback()
                return jsonify({'error': 'Failed to remove LED sign entries linked to this alert.'}), 500

            db.session.delete(alert)

            log_entry = SystemLog(
                level='WARNING',
                message='Alert deleted from admin interface',
                module='admin',
                details={
                    'alert_id': alert_id,
                    'identifier': identifier,
                    'deleted_at_utc': utc_now().isoformat(),
                },
            )
            db.session.add(log_entry)
            db.session.commit()

            logger.info("Admin deleted alert %s (%s)", identifier, alert_id)
            return jsonify({'message': f'Alert {identifier} deleted.', 'identifier': identifier})
        except Exception as exc:
            db.session.rollback()
            logger.error("Failed to delete alert %s (%s): %s", identifier, alert_id, exc)
            return jsonify({'error': 'Failed to delete alert.'}), 500

    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({'error': 'No update payload provided.'}), 400

    allowed_fields = {
        'event',
        'headline',
        'description',
        'instruction',
        'area_desc',
        'status',
        'severity',
        'urgency',
        'certainty',
        'category',
        'expires',
    }
    required_non_empty = {'event', 'status'}

    updates: Dict[str, Any] = {}
    change_details: Dict[str, Dict[str, Optional[str]]] = {}

    for field in allowed_fields:
        if field not in payload:
            continue

        value = payload[field]

        if field == 'expires':
            if value in (None, '', []):
                updates[field] = None
            else:
                normalized = normalize_manual_import_datetime(value)
                if not normalized:
                    return jsonify({'error': 'Could not parse the provided expiration time.'}), 400
                updates[field] = normalized
        else:
            if isinstance(value, str):
                value = value.strip()
            if field in required_non_empty and not value:
                return jsonify({'error': f'{field.replace("_", " ").title()} is required.'}), 400
            updates[field] = value or None

        previous_value = getattr(alert, field)
        if isinstance(previous_value, datetime):
            previous_rendered = _alert_datetime_to_iso(previous_value)
        else:
            previous_rendered = previous_value

        new_value = updates[field]
        if isinstance(new_value, datetime):
            new_rendered: Optional[str] = new_value.isoformat()
        else:
            new_rendered = new_value

        change_details[field] = {
            'old': previous_rendered,
            'new': new_rendered,
        }

    if not updates:
        return jsonify({'message': 'No changes detected.', 'alert': serialize_admin_alert(alert)})

    try:
        for field, value in updates.items():
            setattr(alert, field, value)

        alert.updated_at = utc_now()

        log_entry = SystemLog(
            level='INFO',
            message='Alert updated from admin interface',
            module='admin',
            details={
                'alert_id': alert.id,
                'identifier': alert.identifier,
                'changes': change_details,
                'updated_at_utc': alert.updated_at.isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        logger.info(
            "Admin updated alert %s fields: %s",
            alert.identifier,
            ', '.join(sorted(updates.keys())),
        )

        db.session.refresh(alert)
        return jsonify({'message': 'Alert updated successfully.', 'alert': serialize_admin_alert(alert)})
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to update alert %s (%s): %s", alert.identifier, alert.id, exc)
        return jsonify({'error': 'Failed to update alert.'}), 500


@app.route('/admin/mark_expired', methods=['POST'])
def mark_expired():
    """Mark expired alerts as inactive without deleting them (SAFE OPTION)"""
    try:
        now = utc_now()

        expired_alerts = CAPAlert.query.filter(
            CAPAlert.expires < now,
            CAPAlert.status != 'Expired'
        ).all()

        count = len(expired_alerts)

        if count == 0:
            return jsonify({'message': 'No alerts need to be marked as expired'})

        for alert in expired_alerts:
            alert.status = 'Expired'
            alert.updated_at = now

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Marked {count} alerts as expired (data preserved)',
            module='admin',
            details={
                'marked_at_utc': now.isoformat(),
                'marked_at_local': local_now().isoformat(),
                'count': count
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'message': f'Marked {count} alerts as expired',
            'note': 'Alert data has been preserved in the database',
            'marked_count': count
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking expired alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500


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
