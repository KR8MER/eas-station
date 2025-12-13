#!/usr/bin/env python3
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

"""
EAS Station - Complete Emergency Alert System Platform
Flask-based CAP ingestion, SAME encoding, broadcast, and verification system

Author: KR8MER Amateur Radio Emergency Communications
Description: Multi-source alert aggregation with FCC-compliant SAME encoding, PostGIS spatial intelligence,
             SDR verification, and LED signage integration
Version: 2.7.2 - Restores SDR audio monitors on-demand to eliminate 503 playback errors
"""

# =============================================================================
# IMPORTS AND DEPENDENCIES
# =============================================================================

import base64
import hmac
import io
import os
import math
import re
import secrets
import psutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from urllib.parse import quote, urljoin, urlparse
from types import SimpleNamespace

from dotenv import load_dotenv
import pytz

# Application utilities
from app_utils import (
    get_location_timezone_name,
    local_now,
    parse_nws_datetime as _parse_nws_datetime,
    set_location_timezone,
    utc_now,
)
from app_utils.assets import get_shield_logo_data
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
from app_core.eas_storage import (
    backfill_eas_message_payloads,
    backfill_manual_eas_audio,
    ensure_eas_audio_columns,
    ensure_eas_message_foreign_key,
    ensure_manual_eas_audio_columns,
    get_eas_static_prefix,
)
from app_core.system_health import get_system_health, start_health_alert_worker
from app_core.poller_debug import ensure_poll_debug_table
from app_core.radio import (
    ensure_radio_tables,
    ensure_radio_squelch_columns,
    ensure_radio_audio_sample_rate_column,
    ensure_radio_frequency_correction_column,
)
from app_core.zones import ensure_zone_catalog
from app_core.auth.roles import initialize_default_roles_and_permissions, Role
from webapp import register_routes
from webapp.admin.boundaries import (
    ensure_alert_source_columns,
    ensure_boundary_geometry_column,
    ensure_storage_zone_codes_column,
)
# Re-export manual import utilities for CLI scripts that import from ``app``.
from webapp.admin.maintenance import (
    NOAAImportError,
    format_noaa_timestamp,
    normalize_manual_import_datetime,
    retrieve_noaa_alerts,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree
from app_utils.optimized_parsing import json_loads, json_dumps, JSONDecodeError

# Flask and extensions
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    flash,
    redirect,
    url_for,
    has_app_context,
    session,
    g,
    send_file,
    abort,
)
from geoalchemy2.functions import ST_Intersects, ST_AsGeoJSON
from sqlalchemy import text, func, or_, desc
from sqlalchemy.exc import OperationalError

# Logging
import logging
import click

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
from app_core.cache import init_cache, cache
from app_core.extensions import db
from app_core.led import (
    LED_AVAILABLE,
    ensure_led_tables,
    initialise_led_controller,
    led_controller,
)
from app_core.oled import (
    OLED_AVAILABLE,
    initialise_oled_display,
    oled_controller,
)
from app_core.vfd import (
    VFD_AVAILABLE,
    ensure_vfd_tables,
    initialise_vfd_controller,
    vfd_controller,
)
from app_core.location import get_location_settings, update_location_settings
from app_core.models import (
    AdminUser,
    Boundary,
    CAPAlert,
    EASMessage,
    Intersection,
    ManualEASActivation,
    LEDMessage,
    LEDSignStatus,
    LocationSettings,
    PollDebugRecord,
    PollHistory,
    RadioReceiver,
    RadioReceiverStatus,
    SnowEmergency,
    SystemLog,
)

# Refactored modules (PR #1191)
from app_core.config.environment import parse_env_list, parse_int_env
from app_core.config.database import build_database_url
from app_core.database.connectivity import check_database_connectivity
from app_core.database.postgis import ensure_postgis_extension
from app_core.eas.file_operations import (
    get_eas_output_root,
    get_eas_static_prefix as get_eas_static_prefix_from_config,
    resolve_eas_disk_path,
    load_or_cache_audio_data,
    load_or_cache_summary_payload,
    remove_eas_files,
)
from app_core.flask.csrf import (
    generate_csrf_token,
    CSRF_SESSION_KEY,
    CSRF_HEADER_NAME,
    CSRF_PROTECTED_METHODS,
    CSRF_EXEMPT_ENDPOINTS,
    CSRF_EXEMPT_PATHS,
)
from app_core.flask.url_defaults import add_static_cache_bust
from app_core.flask.template_filters import shields_escape
from app_core.flask.context_processors import inject_global_vars
from app_core.datetime.parsing import parse_nws_datetime

# =============================================================================
# CONFIGURATION AND SETUP
# =============================================================================

# Configure logging early
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables early for local CLI usage
# Use CONFIG_PATH if set (for alternate location), otherwise use default .env location
# CRITICAL: override=True to override env vars from empty .env
# BUT: Preserve Icecast auto-config from environment (don't let persistent .env override it)
_env_icecast_password = os.environ.get('ICECAST_SOURCE_PASSWORD')
_env_icecast_enabled = os.environ.get('ICECAST_ENABLED')

_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    logger.info(f"Loading environment from persistent config: {_config_path}")
    load_dotenv(_config_path, override=True)
else:
    load_dotenv(override=True)

# Restore Icecast auto-config from environment if auto-streaming is enabled
# This prevents persistent .env from breaking auto-streaming with mismatched passwords
if _env_icecast_enabled and _env_icecast_enabled.lower() in ('true', '1', 'yes', 'enabled'):
    if _env_icecast_password:
        # Preserve Icecast password for auto-streaming
        os.environ['ICECAST_SOURCE_PASSWORD'] = _env_icecast_password
        logger.debug("Preserved Icecast auto-config from environment")

# Create Flask app
app = Flask(__name__)

# Configure JSON encoder to handle Infinity and NaN values
# Flask's default jsonify() produces non-standard JSON (Infinity, NaN)
# which JavaScript cannot parse. This ensures valid JSON output.
from flask.json.provider import DefaultJSONProvider

class SafeJSONProvider(DefaultJSONProvider):
    """JSON provider that converts inf/nan to safe values.
    
    Audio metrics use dB levels where -120dB represents silence (minimum)
    and 120dB represents maximum level. These values replace infinity/NaN
    to ensure valid JSON serialization while maintaining audio semantics.
    """
    # Audio level boundaries in dB
    MIN_AUDIO_LEVEL_DB = -120.0  # Silence threshold
    MAX_AUDIO_LEVEL_DB = 120.0   # Maximum level
    
    def default(self, obj):
        if isinstance(obj, float):
            if math.isinf(obj):
                return self.MIN_AUDIO_LEVEL_DB if obj < 0 else self.MAX_AUDIO_LEVEL_DB
            elif math.isnan(obj):
                return self.MIN_AUDIO_LEVEL_DB
        return super().default(obj)

app.json = SafeJSONProvider(app)

_setup_mode_reasons: List[str] = []

app.config['SESSION_COOKIE_HTTPONLY'] = True

# Google Search Console integration helpers
app.config['GOOGLE_SITE_VERIFICATION'] = os.environ.get('GOOGLE_SITE_VERIFICATION', '')

_sitemap_limit_default = os.environ.get('SITEMAP_ALERT_LIMIT', '50')
try:
    app.config['SITEMAP_ALERT_LIMIT'] = max(0, int(_sitemap_limit_default)) or 50
except ValueError:
    app.config['SITEMAP_ALERT_LIMIT'] = 50

raw_secure_flag = os.environ.get('SESSION_COOKIE_SECURE')
if raw_secure_flag is not None:
    session_cookie_secure = raw_secure_flag.lower() in {'1', 'true', 'yes'}
    logger.info(
        'Session cookie HTTPS requirement overridden via SESSION_COOKIE_SECURE=%s',
        session_cookie_secure,
    )
else:
    debug_env = os.environ.get('FLASK_ENV', '').lower() == 'development'
    debug_flag = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    prefer_https = os.environ.get('PREFERRED_URL_SCHEME', '').lower() == 'https'
    session_cookie_secure = prefer_https and not (debug_env or debug_flag)
    if session_cookie_secure:
        logger.info('Session cookies will require HTTPS transport.')
    else:
        logger.info(
            'Session cookies are not limited to HTTPS transport (HTTP or debug mode). '
            'Set SESSION_COOKIE_SECURE=true in production deployments.'
        )

app.config['SESSION_COOKIE_SECURE'] = session_cookie_secure
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
try:
    session_hours = int(os.environ.get('SESSION_LIFETIME_HOURS', '12'))
except ValueError:
    session_hours = 12
app.permanent_session_lifetime = timedelta(hours=session_hours)

raw_origins = os.environ.get('CORS_ALLOWED_ORIGINS', '')
if raw_origins.strip():
    allowed_origins = {
        origin.strip()
        for origin in raw_origins.split(',')
        if origin.strip()
    }
else:
    allowed_origins = set()
app.config['CORS_ALLOWED_ORIGINS'] = allowed_origins
app.config['CORS_ALLOW_CREDENTIALS'] = (
    os.environ.get('CORS_ALLOW_CREDENTIALS', 'false').lower() == 'true'
)


app.config['COMPLIANCE_ALERT_EMAILS'] = parse_env_list('COMPLIANCE_ALERT_EMAILS')
app.config['COMPLIANCE_SNMP_TARGETS'] = parse_env_list('COMPLIANCE_SNMP_TARGETS')
app.config['COMPLIANCE_SNMP_COMMUNITY'] = os.environ.get('COMPLIANCE_SNMP_COMMUNITY', 'public')
app.config['COMPLIANCE_HEALTH_INTERVAL'] = parse_int_env('COMPLIANCE_HEALTH_INTERVAL', 300)
app.config['RECEIVER_OFFLINE_THRESHOLD_MINUTES'] = parse_int_env(
    'RECEIVER_OFFLINE_THRESHOLD_MINUTES', 10
)
app.config['AUDIO_PATH_ALERT_THRESHOLD_MINUTES'] = parse_int_env(
    'AUDIO_PATH_ALERT_THRESHOLD_MINUTES', 60
)

PUBLIC_API_GET_PATHS = {
    '/api/alerts',
    '/api/alerts/historical',
    '/api/boundaries',
    '/api/system_status',
    # Display hardware endpoints (OLED/LED/VFD screens)
    '/api/audio/metrics',
    '/api/audio/metrics/latest',
    '/api/audio/health',
    '/api/audio/sources',
    '/api/eas-monitor/status',
    '/api/system_health',
    '/api/monitoring/radio',
    # Snow emergency status (public safety information)
    '/api/snow_emergencies',
    # Monitoring endpoints (for health checks and version tracking)
    '/api/health',
    '/api/release-manifest',
}
# CSRF constants are now imported from app_core.flask.csrf
app.config['CSRF_SESSION_KEY'] = CSRF_SESSION_KEY

# Require SECRET_KEY to be explicitly set (fail fast if missing or using default)
_placeholder_secrets = {
    '',
    'dev-key-change-in-production',
    'replace-with-a-long-random-string',
}
secret_key = os.environ.get('SECRET_KEY', '')
if secret_key in _placeholder_secrets or len(secret_key) < 32:
    _setup_mode_reasons.append('secret-key')
    secret_key = secrets.token_hex(32)
    logger.warning(
        'SECRET_KEY is missing or using a placeholder value. '
        'Using a temporary key while setup mode is active.'
    )
app.secret_key = secret_key

# Application versioning (exposed via templates for quick deployment verification)
from app_utils.versioning import get_current_commit, get_current_version


app.config['SYSTEM_VERSION'] = get_current_version()

_static_version_env = os.environ.get('STATIC_ASSET_VERSION')
if _static_version_env:
    app.config['STATIC_ASSET_VERSION'] = _static_version_env.strip()
else:
    app.config['STATIC_ASSET_VERSION'] = app.config['SYSTEM_VERSION']


@app.url_defaults
def _add_static_cache_bust_wrapper(endpoint: str, values: Dict[str, Any]) -> None:
    """Wrapper for add_static_cache_bust to work with app.url_defaults decorator."""
    add_static_cache_bust(app, endpoint, values)


def _get_eas_output_root() -> Optional[str]:
    """Wrapper for backward compatibility - calls extracted function."""
    return get_eas_output_root(app)


def _get_eas_static_prefix() -> str:
    """Wrapper for backward compatibility - calls extracted function."""
    return get_eas_static_prefix_from_config(app)


def _resolve_eas_disk_path(filename: Optional[str]) -> Optional[str]:
    """Wrapper for backward compatibility - calls extracted function."""
    return resolve_eas_disk_path(app, filename)


def _load_or_cache_audio_data(message: EASMessage, *, variant: str = 'primary') -> Optional[bytes]:
    """Wrapper for backward compatibility - calls extracted function."""
    return load_or_cache_audio_data(app, db, message, variant=variant)


def _load_or_cache_summary_payload(message: EASMessage) -> Optional[Dict[str, Any]]:
    """Wrapper for backward compatibility - calls extracted function."""
    return load_or_cache_summary_payload(app, db, message)


def _remove_eas_files(message: EASMessage) -> None:
    """Wrapper for backward compatibility - calls extracted function."""
    return remove_eas_files(app, message)


# Database configuration
DATABASE_URL = build_database_url()
os.environ.setdefault('DATABASE_URL', DATABASE_URL)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Add connection timeout and pool settings to prevent startup hangs
# Pool settings optimized for robustness and performance
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {
        'connect_timeout': 10,  # 10 second timeout for initial connection
    },
    'pool_pre_ping': True,      # Verify connections before using them (detect stale connections)
    'pool_recycle': 3600,       # Recycle connections after 1 hour
    'pool_size': 10,            # Number of connections to maintain
    'max_overflow': 20,         # Additional connections when pool exhausted
    'pool_timeout': 30,         # Timeout waiting for connection from pool
    'echo_pool': False,         # Set to True for connection pool debugging
}

# Initialize database
db.init_app(app)

# Initialize caching
init_cache(app)

# Initialize WebSocket support
# CRITICAL: async_mode must match gunicorn worker class
# - gunicorn uses 'gevent' workers (see systemd service or gunicorn config)
# - Flask-SocketIO must use 'gevent' or None (auto-detect) to enable WebSocket transport
# - Using 'threading' with gevent workers causes WebSockets to FAIL SILENTLY and fall back to polling
from flask_socketio import SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')


logger.info("Checking database connectivity at startup...")
if check_database_connectivity(app, db):
    logger.info("Database connectivity check succeeded.")
else:
    logger.error("Database connectivity check failed; application may not operate correctly.")
    if 'database' not in _setup_mode_reasons:
        _setup_mode_reasons.append('database')

app.config['SETUP_MODE'] = bool(_setup_mode_reasons)
app.config['SETUP_MODE_REASONS'] = tuple(_setup_mode_reasons)
if app.config['SETUP_MODE']:
    logger.warning(
        'Setup mode enabled due to: %s. Visit /setup to complete configuration.',
        ', '.join(_setup_mode_reasons),
    )


# Configure EAS output integration
EAS_CONFIG = load_eas_config(app.root_path)
app.config['EAS_BROADCAST_ENABLED'] = bool(EAS_CONFIG.get('enabled'))
app.config['EAS_OUTPUT_DIR'] = EAS_CONFIG.get('output_dir')
app.config['EAS_OUTPUT_WEB_SUBDIR'] = EAS_CONFIG.get('web_subdir', 'eas_messages')

# Guard database schema preparation so we only attempt it once per process.
_db_initialized = False
_db_initialization_error = None
_db_init_lock = threading.Lock()
logger.info("NOAA Alerts System startup")

# Register route modules
register_routes(app, logger)

# Start background health monitoring alerts
if app.config.get('SETUP_MODE'):
    logger.info('Skipping health alert worker while setup mode is active.')
else:
    start_health_alert_worker(app, logger)

# Start screen manager for LED/VFD display rotation
try:
    from scripts.screen_manager import screen_manager
    screen_manager.init_app(app)
    if not app.config.get('SETUP_MODE'):
        screen_manager.start()
        logger.info('Screen manager started for display rotation')
except Exception as screen_mgr_error:
    logger.warning('Screen manager could not be started: %s', screen_mgr_error)

# Start RWT (Required Weekly Test) scheduler
try:
    from app_core.rwt_scheduler import start_scheduler as start_rwt_scheduler
    if not app.config.get('SETUP_MODE'):
        start_rwt_scheduler(app)
        logger.info('RWT scheduler started for automatic weekly tests')
except Exception as rwt_scheduler_error:
    logger.warning('RWT scheduler could not be started: %s', rwt_scheduler_error)

# =============================================================================
# BOUNDARY TYPE METADATA
# =============================================================================

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,64}$')

# =============================================================================
# TIMEZONE AND DATETIME UTILITIES
# =============================================================================


# parse_nws_datetime is now imported from app_core.datetime.parsing



# =============================================================================
# SYSTEM MONITORING UTILITIES
# =============================================================================
# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found_error(error):
    """Enhanced 404 error page"""
    return render_template('error.html',
                         error='404 - Page Not Found',
                         details='The page you requested does not exist.'), 404


@app.errorhandler(500)
def internal_error(error):
    """Enhanced 500 error page"""
    if hasattr(db, 'session') and db.session:
        db.session.rollback()

    return render_template('error.html',
                         error='500 - Internal Server Error',
                         details='Something went wrong on our end. Please try again later.'), 500


@app.errorhandler(403)
def forbidden_error(error):
    """403 Forbidden error page"""
    return render_template('error.html',
                         error='403 - Forbidden',
                         details='You do not have permission to access this resource.'), 403


@app.errorhandler(400)
def bad_request_error(error):
    """400 Bad Request error page"""
    return render_template('error.html',
                         error='400 - Bad Request',
                         details='The request was malformed or invalid.'), 400


# =============================================================================
# ADDITIONAL UTILITY ROUTES
# =============================================================================

# =============================================================================
# CONTEXT PROCESSORS FOR TEMPLATES
# =============================================================================

@app.context_processor
def _inject_global_vars_wrapper():
    """Wrapper for inject_global_vars to work with app.context_processor decorator."""
    return inject_global_vars(app)


# =============================================================================
# JINJA2 FILTERS
# =============================================================================

@app.template_filter('shields_escape')
def shields_escape_filter(text):
    """Wrapper for shields_escape to work with app.template_filter decorator."""
    return shields_escape(text)


# =============================================================================
# REQUEST HOOKS
# =============================================================================

@app.before_request
def before_request():
    """Before request hook for logging and setup"""
    # Refresh dynamic metadata that may change between deployments.
    app.config['SYSTEM_VERSION'] = get_current_version()
    if not _static_version_env:
        app.config['STATIC_ASSET_VERSION'] = app.config['SYSTEM_VERSION']

    # Log API requests for debugging
    if request.path.startswith('/api/') and request.method in ['POST', 'PUT', 'DELETE']:
        logger.info(f"{request.method} {request.path} from {request.remote_addr}")

    setup_mode_active = app.config.get('SETUP_MODE', False)

    g.current_user = None
    g.admin_setup_mode = False

    if setup_mode_active:
        session.pop('user_id', None)
        allowed_endpoints = {
            'setup_wizard',
            'setup_generate_secret',
            'setup_derive_zone_codes',
            'setup_lookup_county_fips',
            'setup_success',
            'setup_view_env',
            'setup_download_env',
            'setup_upload_env',
            'static',
            # Environment settings - allow access during setup mode to fix database config
            'environment.get_environment_categories',
            'environment.get_environment_variables',
            'environment.update_environment_variables',
            'environment.validate_environment',
            'environment.environment_settings',
            'environment.admin_download_env',
            'environment.generate_secret_key_api',
        }
        allowed_paths = {
            '/setup',
            '/setup/generate-secret',
            '/setup/derive-zone-codes',
            '/setup/lookup-county-fips',
            '/setup/success',
            '/setup/view-env',
            '/setup/download-env',
            '/setup/upload-env',
            # Environment settings paths
            '/settings/environment',
            '/api/environment/categories',
            '/api/environment/variables',
            '/api/environment/validate',
            '/api/environment/generate-secret',
            '/admin/environment/download-env',
        }
        is_allowed_endpoint = request.endpoint in allowed_endpoints if request.endpoint else False
        is_allowed_path = request.path in allowed_paths or request.path.startswith('/static/')
        if not (is_allowed_endpoint or is_allowed_path):
            if request.path.startswith('/api/') or request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({'error': 'Setup required'}), 503
            return redirect(url_for('setup_wizard'))
    else:
        # Ensure the database schema exists before handling the request.
        if not initialize_database():
            logger.error("Database initialization failed - cannot handle request")
            if request.path.startswith('/api/') or request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({'error': 'Database initialization failed'}), 503
            return "Database initialization failed. Please check server logs.", 503

        # Load the current user from the session for downstream use.
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

    # Allow authentication endpoints without CSRF or other checks.
    if (request.endpoint in CSRF_EXEMPT_ENDPOINTS) or (request.path in CSRF_EXEMPT_PATHS):
        return

    # Exempt setup routes from CSRF validation when in setup mode
    if setup_mode_active and request.path.startswith('/setup'):
        return

    if request.method in CSRF_PROTECTED_METHODS:
        session_token = session.get(CSRF_SESSION_KEY)
        request_token = None
        if request.is_json:
            request_token = request.headers.get(CSRF_HEADER_NAME)
        else:
            request_token = request.form.get('csrf_token')
            if not request_token:
                request_token = request.headers.get(CSRF_HEADER_NAME)
            if not request_token:
                request_token = request.headers.get('X-CSRFToken')

        if not session_token or not request_token or not hmac.compare_digest(session_token, request_token):
            if request.endpoint in {'login', 'auth.login'} or request.path == '/login':
                logger.info('Login CSRF token mismatch detected; refreshing session token and redirecting to login.')
                session.pop(CSRF_SESSION_KEY, None)
                session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
                flash('Your session has expired. Please sign in again.')
                return redirect(url_for('auth.login'))
            if request.path.startswith('/api/') or request.is_json or 'application/json' in (request.headers.get('Accept', '') or ''):
                return jsonify({'error': 'Invalid or missing CSRF token'}), 400
            abort(400)

    if request.path.startswith('/api/'):
        normalized_path = request.path.rstrip('/') or '/'
        if (
            request.method in {'GET', 'HEAD', 'OPTIONS'}
            and normalized_path in PUBLIC_API_GET_PATHS
        ):
            return

    if not setup_mode_active:
        protected_prefixes = ('/admin', '/logs', '/api', '/eas', '/settings')
        if any(request.path.startswith(prefix) for prefix in protected_prefixes):
            if g.current_user is None:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Authentication required'}), 401
                if g.admin_setup_mode and request.endpoint in {'admin', 'admin_users'}:
                    if request.method == 'GET' or (request.method == 'POST' and request.endpoint == 'admin_users'):
                        return
                accept_header = request.headers.get('Accept', '')
                next_url = request.full_path if request.query_string else request.path
                if request.method != 'GET' or 'application/json' in accept_header or request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                return redirect(url_for('auth.login', next=next_url))


@app.after_request
def after_request(response):
    """After request hook for headers and cleanup"""
    # Add CORS headers for API endpoints
    if request.path.startswith('/api/'):
        allowed_origins = app.config.get('CORS_ALLOWED_ORIGINS', set())
        origin = request.headers.get('Origin')
        allow_any = '*' in allowed_origins

        if allow_any:
            response.headers['Access-Control-Allow-Origin'] = '*'
        elif origin and origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers.add('Vary', 'Origin')

        if allow_any or (origin and origin in allowed_origins):
            response.headers['Access-Control-Allow-Headers'] = (
                f'Content-Type,Authorization,{CSRF_HEADER_NAME}'
            )
            response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
            if app.config.get('CORS_ALLOW_CREDENTIALS') and not allow_any:
                response.headers['Access-Control-Allow-Credentials'] = 'true'
        
        # Add Cache-Control headers for GET requests to reduce load
        if request.method == 'GET' and response.status_code == 200:
            # Use shorter cache times for real-time data, longer for static data
            if '/api/system_status' in request.path or '/api/system_health' in request.path:
                response.headers['Cache-Control'] = 'public, max-age=10'
            elif '/api/alerts' in request.path:
                response.headers['Cache-Control'] = 'public, max-age=30'
            elif '/api/boundaries' in request.path:
                response.headers['Cache-Control'] = 'public, max-age=300'
            elif '/api/audio' in request.path:
                response.headers['Cache-Control'] = 'public, max-age=15'
            else:
                response.headers['Cache-Control'] = 'public, max-age=60'

    # Add security headers
    response.headers.add('X-Content-Type-Options', 'nosniff')
    response.headers.add('X-Frame-Options', 'SAMEORIGIN')
    response.headers.add('X-XSS-Protection', '1; mode=block')

    return response


# Flask 3 removed the ``before_first_request`` hook in favour of
# ``before_serving``.  Older Flask releases (including the one bundled with
# this project) do not provide ``before_serving`` though, so we register the
# handler dynamically depending on which hook is available.  If neither hook is
# present we fall back to running the initialization immediately within an
# application context.

# NOTE: Radio receiver initialization is now handled by the SDR hardware service process.
# The sdr_service.py script initializes and starts receivers on container startup.
# This separation ensures proper USB device access isolation.


def initialize_database():
    """Create all database tables, logging any initialization failure."""
    global _db_initialized, _db_initialization_error

    # Double-checked locking pattern for thread safety
    if _db_initialized:
        return True

    with _db_init_lock:
        # Check again after acquiring lock
        if _db_initialized:
            return True

        try:
            postgis_helper = globals().get("ensure_postgis_extension")
            if postgis_helper is None:
                logger.warning(
                    "PostGIS helper unavailable during initialization; skipping extension check.",
                )
            elif not postgis_helper(app, db):
                _db_initialization_error = RuntimeError("PostGIS extension could not be ensured")
                return False
            db.create_all()
            if not ensure_alert_source_columns(logger):
                _db_initialization_error = RuntimeError("CAP alert source columns could not be ensured")
                return False
            ensure_boundary_geometry_column(logger)
            if not ensure_eas_audio_columns(logger):
                _db_initialization_error = RuntimeError(
                    "EAS audio columns could not be ensured"
                )
                return False
            if not ensure_eas_message_foreign_key(logger):
                _db_initialization_error = RuntimeError(
                    "EAS message foreign key constraint could not be ensured"
                )
                return False
            if not ensure_manual_eas_audio_columns(logger):
                _db_initialization_error = RuntimeError(
                    "Manual EAS audio columns could not be ensured"
                )
                return False
            if not ensure_poll_debug_table(logger):
                _db_initialization_error = RuntimeError(
                    "Poll debug table could not be ensured"
                )
                return False
            if not ensure_radio_tables(logger):
                _db_initialization_error = RuntimeError(
                    "Radio receiver tables could not be ensured"
                )
                return False
            if not ensure_radio_squelch_columns(logger):
                _db_initialization_error = RuntimeError(
                    "Radio squelch columns could not be ensured"
                )
                return False
            if not ensure_radio_audio_sample_rate_column(logger):
                _db_initialization_error = RuntimeError(
                    "Radio audio_sample_rate column could not be ensured"
                )
                return False
            if not ensure_radio_frequency_correction_column(logger):
                _db_initialization_error = RuntimeError(
                    "Radio frequency_correction_ppm column could not be ensured"
                )
                return False
            # Zone catalog is optional - app can start without it
            if not ensure_zone_catalog(logger):
                logger.warning("NWS zone catalog could not be loaded - continuing without it")
            if not ensure_storage_zone_codes_column(logger):
                _db_initialization_error = RuntimeError(
                    "Location settings storage_zone_codes column could not be ensured"
                )
                return False
            backfill_eas_message_payloads(logger)
            backfill_manual_eas_audio(logger)
            settings = get_location_settings(force_reload=True)
            timezone_name = settings.get('timezone')
            if timezone_name:
                set_location_timezone(timezone_name)
            if LED_AVAILABLE:
                initialise_led_controller(logger)
                ensure_led_tables()
            if OLED_AVAILABLE:
                initialise_oled_display(logger)
            if VFD_AVAILABLE:
                initialise_vfd_controller(logger)
                ensure_vfd_tables()
            # Initialize RBAC roles and permissions
            try:
                initialize_default_roles_and_permissions()
                logger.info("RBAC roles and permissions initialized")
            except Exception as rbac_error:
                logger.warning("Failed to initialize RBAC roles: %s", rbac_error)

            # Radio receivers are handled by the dedicated audio service
            # The web application serves the UI and reads metrics from Redis
            logger.info("Radio receiver initialization handled by audio service")

            # Initialize EAS continuous monitoring system
            try:
                from app_core.audio.startup_integration import initialize_eas_monitoring_system
                if initialize_eas_monitoring_system():
                    logger.info("EAS continuous monitoring enabled")
                else:
                    logger.warning("EAS continuous monitoring failed to start")
            except Exception as monitor_error:
                logger.warning("Failed to initialize EAS monitoring: %s", monitor_error)
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

            # Start WebSocket push service for real-time updates
            try:
                from app_core.websocket_push import start_websocket_push
                start_websocket_push(app, socketio)
                logger.info("WebSocket push service started")
            except Exception as ws_error:
                logger.warning("Failed to start WebSocket push service: %s", ws_error)

            return True


def _initialize_database_with_error_check():
    """Wrapper to ensure database initialization errors are handled properly"""
    if not initialize_database():
        logger.critical("Database initialization failed! Application cannot start. Check logs for details.")
        raise RuntimeError("Database initialization failed - application cannot continue")

if hasattr(app, "before_serving"):
    app.before_serving(_initialize_database_with_error_check)
elif hasattr(app, "before_first_request"):
    app.before_first_request(_initialize_database_with_error_check)
else:
    # Skip initialization if running migrations
    # This prevents the chicken-and-egg problem where migrations need to add
    # columns that the initialization code tries to query
    if not os.environ.get("SKIP_DB_INIT"):
        with app.app_context():
            if not initialize_database():
                logger.critical("Database initialization failed! Application cannot start. Check logs for details.")
                raise RuntimeError("Database initialization failed - application cannot continue")


# =============================================================================
# CLI COMMANDS (for future use with Flask CLI)
# =============================================================================

@app.cli.command()
def init_db():
    """Initialize the database tables"""
    if not initialize_database():
        logger.critical("Database initialization failed!")
        raise click.ClickException("Database initialization failed - check logs for details")
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
    if not initialize_database():
        logger.critical("Database initialization failed!")
        raise click.ClickException("Database initialization failed - check logs for details")

    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        raise click.ClickException('Usernames must be 3-64 characters and may include letters, numbers, dots, underscores, and hyphens.')

    if len(password) < 8:
        raise click.ClickException('Password must be at least 8 characters long.')

    existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
    if existing:
        raise click.ClickException('That username already exists.')

    # Get the admin role to assign to the new user
    admin_role = Role.query.filter_by(name='admin').first()
    if not admin_role:
        raise click.ClickException('Admin role not found. Database may not be properly initialized.')

    user = AdminUser(username=username)
    user.set_password(password)
    user.role_id = admin_role.id
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

    # Skip initialization if running migrations
    # This prevents the chicken-and-egg problem where migrations need to add
    # columns that the initialization code tries to query
    if not os.environ.get("SKIP_DB_INIT"):
        with app.app_context():
            if not initialize_database():
                logger.critical("Database initialization failed! Application cannot start. Check logs for details.")
                raise RuntimeError("Database initialization failed - application cannot continue")

    return app


# =============================================================================
# APPLICATION STARTUP
# =============================================================================

if __name__ == '__main__':
    with app.app_context():
        if not initialize_database():
            logger.critical("Database initialization failed! Application cannot start. Check logs for details.")
            import sys
            sys.exit(1)

    # Use FLASK_DEBUG environment variable to control debug mode (defaults to False for security)
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
