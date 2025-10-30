#!/usr/bin/env python3
"""
EAS Station - Complete Emergency Alert System Platform
Flask-based CAP ingestion, SAME encoding, broadcast, and verification system

Author: KR8MER Amateur Radio Emergency Communications
Description: Multi-source alert aggregation with FCC-compliant SAME encoding, PostGIS spatial intelligence,
             SDR verification, and LED signage integration
Version: 2.1.9 - Adds per-line LED formatting support and WYSIWYG message editing
"""

# =============================================================================
# IMPORTS AND DEPENDENCIES
# =============================================================================

import base64
import hmac
import io
import os
import json
import math
import re
import secrets
import psutil
import threading
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
from app_core.radio import ensure_radio_tables
from webapp import register_routes
from webapp.admin.boundaries import (
    ensure_alert_source_columns,
    ensure_boundary_geometry_column,
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
    Intersection,
    ManualEASActivation,
    LEDMessage,
    LEDSignStatus,
    LocationSettings,
    PollDebugRecord,
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

app.config['SESSION_COOKIE_HTTPONLY'] = True

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
        logger.warning(
            'Session cookies are not limited to HTTPS transport. '
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


def _parse_env_list(name: str) -> List[str]:
    raw_value = os.environ.get(name, '')
    if not raw_value:
        return []
    return [entry.strip() for entry in raw_value.split(',') if entry and entry.strip()]


def _parse_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default


app.config['COMPLIANCE_ALERT_EMAILS'] = _parse_env_list('COMPLIANCE_ALERT_EMAILS')
app.config['COMPLIANCE_SNMP_TARGETS'] = _parse_env_list('COMPLIANCE_SNMP_TARGETS')
app.config['COMPLIANCE_SNMP_COMMUNITY'] = os.environ.get('COMPLIANCE_SNMP_COMMUNITY', 'public')
app.config['COMPLIANCE_HEALTH_INTERVAL'] = _parse_int_env('COMPLIANCE_HEALTH_INTERVAL', 300)
app.config['RECEIVER_OFFLINE_THRESHOLD_MINUTES'] = _parse_int_env(
    'RECEIVER_OFFLINE_THRESHOLD_MINUTES', 10
)
app.config['AUDIO_PATH_ALERT_THRESHOLD_MINUTES'] = _parse_int_env(
    'AUDIO_PATH_ALERT_THRESHOLD_MINUTES', 60
)

PUBLIC_API_GET_PATHS = {
    '/api/alerts',
    '/api/alerts/historical',
    '/api/boundaries',
    '/api/system_status',
}
CSRF_SESSION_KEY = '_csrf_token'
CSRF_HEADER_NAME = 'X-CSRF-Token'
CSRF_PROTECTED_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
CSRF_EXEMPT_ENDPOINTS = {'login', 'logout', 'static'}
CSRF_EXEMPT_PATHS = {'/login', '/logout'}
app.config['CSRF_SESSION_KEY'] = CSRF_SESSION_KEY

# Require SECRET_KEY to be explicitly set (fail fast if missing or using default)
secret_key = os.environ.get('SECRET_KEY', '')
if not secret_key or secret_key == 'dev-key-change-in-production':
    raise ValueError(
        "SECRET_KEY environment variable must be set to a secure random string. "
        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
    )
app.secret_key = secret_key

# Application versioning (exposed via templates for quick deployment verification)
SYSTEM_VERSION = os.environ.get('APP_BUILD_VERSION', '2.3.0')
app.config['SYSTEM_VERSION'] = SYSTEM_VERSION


def generate_csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _build_database_url() -> str:
    """Build database URL from environment variables.

    Prioritizes DATABASE_URL if set, otherwise builds from POSTGRES_* variables.
    If POSTGRES_PASSWORD is omitted, builds a URL without credentials.
    """
    url = os.getenv('DATABASE_URL')
    if url:
        return url

    # Build from individual POSTGRES_* variables
    user = os.getenv('POSTGRES_USER', 'postgres') or 'postgres'
    password = os.getenv('POSTGRES_PASSWORD', '')
    host = os.getenv('POSTGRES_HOST', 'host.docker.internal') or 'host.docker.internal'
    port = os.getenv('POSTGRES_PORT', '5432') or '5432'
    database = os.getenv('POSTGRES_DB', user) or user

    # URL-encode credentials to handle special characters
    user_part = quote(user, safe='')
    password_part = quote(password, safe='') if password else ''

    if password_part:
        auth_segment = f"{user_part}:{password_part}"
    else:
        auth_segment = user_part

    return f"postgresql+psycopg2://{auth_segment}@{host}:{port}/{database}"


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


def _check_database_connectivity() -> bool:
    """Attempt to connect to the database and return True on success."""

    try:
        with app.app_context():
            with db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        return True
    except OperationalError as exc:
        logger.error("Database connection failed during startup: %s", exc)
    except Exception as exc:  # noqa: BLE001 - broad catch to log unexpected failures
        logger.exception("Unexpected error during database connectivity check: %s", exc)

    return False


logger.info("Checking database connectivity at startup...")
if _check_database_connectivity():
    logger.info("Database connectivity check succeeded.")
else:
    logger.error("Database connectivity check failed; application may not operate correctly.")


def ensure_postgis_extension() -> bool:
    """Ensure the PostGIS extension exists for PostgreSQL databases."""

    database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    if not database_uri.startswith('postgresql'):
        logger.debug(
            "Skipping PostGIS extension check for non-PostgreSQL database URI: %s",
            database_uri,
        )
        return True

    try:
        with db.engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    except OperationalError as exc:
        logger.error("Failed to ensure PostGIS extension: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - capture unexpected errors for logging
        logger.exception("Unexpected error ensuring PostGIS extension: %s", exc)
        return False

    logger.debug("PostGIS extension ensured for current database.")
    return True


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
start_health_alert_worker(app, logger)

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
# ADDITIONAL UTILITY ROUTES
# =============================================================================

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
        'csrf_token': generate_csrf_token(),
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

    # Allow authentication endpoints without CSRF or other checks.
    if (request.endpoint in CSRF_EXEMPT_ENDPOINTS) or (request.path in CSRF_EXEMPT_PATHS):
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
            if request.endpoint == 'login' or request.path == '/login':
                logger.info('Login CSRF token mismatch detected; refreshing session token and redirecting to login.')
                session.pop(CSRF_SESSION_KEY, None)
                session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
                flash('Your session has expired. Please sign in again.')
                return redirect(url_for('login'))
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

    protected_prefixes = ('/admin', '/logs', '/api')
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
            return redirect(url_for('login', next=next_url))


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

    # Double-checked locking pattern for thread safety
    if _db_initialized:
        return

    with _db_init_lock:
        # Check again after acquiring lock
        if _db_initialized:
            return

        try:
            postgis_helper = globals().get("ensure_postgis_extension")
            if postgis_helper is None:
                logger.warning(
                    "PostGIS helper unavailable during initialization; skipping extension check.",
                )
            elif not postgis_helper():
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
            backfill_eas_message_payloads(logger)
            backfill_manual_eas_audio(logger)
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

    # Use FLASK_DEBUG environment variable to control debug mode (defaults to False for security)
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
