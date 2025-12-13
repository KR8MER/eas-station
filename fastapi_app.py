#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System (FastAPI Version)
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
FastAPI-based CAP ingestion, SAME encoding, broadcast, and verification system

Author: KR8MER Amateur Radio Emergency Communications
Description: Multi-source alert aggregation with FCC-compliant SAME encoding, PostGIS spatial intelligence,
             SDR verification, and LED signage integration
Version: 3.0.0 - FastAPI Migration
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
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from urllib.parse import quote, urljoin, urlparse
from contextlib import asynccontextmanager

from dotenv import load_dotenv
import pytz

# FastAPI and Starlette imports
from fastapi import (
    FastAPI,
    Request,
    Response,
    HTTPException,
    Depends,
    status,
    Form,
    File,
    UploadFile,
)
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Socket.IO for WebSocket support
import socketio

# Application utilities (same imports as Flask version)
from app_utils import (
    get_location_timezone_name,
    local_now,
    parse_nws_datetime as _parse_nws_datetime,
    set_location_timezone,
    utc_now,
)
from app_utils.versioning import get_current_commit, get_current_version

# Database and models (FastAPI-compatible)
# Import using sys.path to avoid app_core/__init__.py Flask dependency
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app_core'))
from fastapi_extensions import init_db, get_engine, get_session_local, Base, get_db
sys.path.pop(0)

from app_core.config.environment import parse_env_list, parse_int_env
from app_core.config.database import build_database_url

# Other app_core imports
# Note: cache and connectivity checks will need to be refactored for FastAPI
# Temporarily skip models import to avoid Flask dependency - will need to refactor models.py
# from app_core.models import (
#     AdminUser,
#     Boundary,
#     CAPAlert,
#     EASMessage,
#     Intersection,
#     ManualEASActivation,
#     LEDMessage,
#     LEDSignStatus,
#     LocationSettings,
#     PollDebugRecord,
#     PollHistory,
#     RadioReceiver,
#     RadioReceiverStatus,
#     SnowEmergency,
#     SystemLog,
# )

# =============================================================================
# CONFIGURATION AND SETUP
# =============================================================================

# Configure logging early
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables early
# Preserve Icecast config from environment before loading .env file
_icecast_password = os.environ.get('ICECAST_SOURCE_PASSWORD')
_icecast_enabled = os.environ.get('ICECAST_ENABLED')

_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    logger.info(f"Loading environment from persistent config: {_config_path}")
    try:
        load_dotenv(_config_path, override=True)
    except (PermissionError, FileNotFoundError, OSError) as e:
        logger.warning(f"Could not load .env from {_config_path}: {e}. Using environment variables only.")
else:
    try:
        load_dotenv(override=True)
    except (PermissionError, FileNotFoundError, OSError) as e:
        logger.warning(f"Could not load .env file: {e}. Using environment variables only.")

# Restore Icecast auto-config from environment if auto-streaming is enabled
if _icecast_enabled and _icecast_enabled.lower() in ('true', '1', 'yes', 'enabled'):
    if _icecast_password:
        os.environ['ICECAST_SOURCE_PASSWORD'] = _icecast_password
        logger.debug("Preserved Icecast auto-config from environment")

# =============================================================================
# APP CONFIGURATION
# =============================================================================

_setup_mode_reasons: List[str] = []

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")
os.environ.setdefault('DATABASE_URL', DATABASE_URL)

# Session configuration
try:
    session_hours = int(os.environ.get('SESSION_LIFETIME_HOURS', '12'))
except ValueError:
    session_hours = 12

# CORS configuration
raw_origins = os.environ.get('CORS_ALLOWED_ORIGINS', '')
if raw_origins.strip():
    allowed_origins = [
        origin.strip()
        for origin in raw_origins.split(',')
        if origin.strip()
    ]
else:
    allowed_origins = ["*"]

# Secret key validation
_placeholder_secrets = {
    '',
    'dev-key-change-in-production',
    'replace-with-a-long-random-string',
}
SECRET_KEY = os.environ.get('SECRET_KEY', '')
if SECRET_KEY in _placeholder_secrets or len(SECRET_KEY) < 32:
    _setup_mode_reasons.append('secret-key')
    SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        'SECRET_KEY is missing or using a placeholder value. '
        'Using a temporary key while setup mode is active.'
    )

# Public API paths (no auth required for GET)
PUBLIC_API_GET_PATHS = {
    '/api/alerts',
    '/api/alerts/historical',
    '/api/boundaries',
    '/api/system_status',
    '/api/audio/metrics',
    '/api/audio/metrics/latest',
    '/api/audio/health',
    '/api/audio/sources',
    '/api/eas-monitor/status',
    '/api/system_health',
    '/api/monitoring/radio',
    '/api/snow_emergencies',
}

# CSRF configuration
CSRF_SESSION_KEY = '_csrf_token'
CSRF_HEADER_NAME = 'X-CSRF-Token'
CSRF_PROTECTED_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
CSRF_EXEMPT_ENDPOINTS = {'login', 'auth.login'}
CSRF_EXEMPT_PATHS = {'/login'}

# =============================================================================
# LIFESPAN CONTEXT FOR STARTUP/SHUTDOWN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI startup and shutdown events.
    Replaces Flask's before_first_request and teardown_appcontext.
    """
    # STARTUP
    logger.info("EAS Station FastAPI startup")
    logger.info(f"System Version: {get_current_version()}")

    # Initialize database
    logger.info("Initializing database...")
    try:
        init_db(DATABASE_URL)
        logger.info("Database initialized successfully.")

        # Test database connection
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connectivity check succeeded.")
    except Exception as e:
        logger.error(f"Database initialization/connectivity check failed: {e}")
        if 'database' not in _setup_mode_reasons:
            _setup_mode_reasons.append('database')

    # Start background workers
    setup_mode = bool(_setup_mode_reasons)
    if not setup_mode:
        try:
            from app_core.system_health import start_health_alert_worker
            # Note: This needs Flask app context, will need refactoring
            logger.info("Health alert worker initialization deferred to middleware")
        except Exception as e:
            logger.warning(f"Could not initialize health alert worker: {e}")

        try:
            from scripts.screen_manager import screen_manager
            logger.info("Screen manager initialization deferred to middleware")
        except Exception as e:
            logger.warning(f"Could not initialize screen manager: {e}")

        try:
            from app_core.rwt_scheduler import start_scheduler as start_rwt_scheduler
            logger.info("RWT scheduler initialization deferred to middleware")
        except Exception as e:
            logger.warning(f"Could not initialize RWT scheduler: {e}")

    yield  # Application runs here

    # SHUTDOWN
    logger.info("EAS Station FastAPI shutdown")
    # Cleanup resources here if needed

# =============================================================================
# CREATE FASTAPI APP
# =============================================================================

app = FastAPI(
    title="EAS Station",
    description="Emergency Alert System Platform",
    version=get_current_version(),
    lifespan=lifespan,
)

# Store configuration in app.state (FastAPI equivalent of app.config)
app.state.SECRET_KEY = SECRET_KEY
app.state.SETUP_MODE = bool(_setup_mode_reasons)
app.state.SETUP_MODE_REASONS = tuple(_setup_mode_reasons)
app.state.SESSION_LIFETIME_HOURS = session_hours
app.state.CORS_ALLOWED_ORIGINS = set(allowed_origins) if allowed_origins != ["*"] else {"*"}
app.state.CORS_ALLOW_CREDENTIALS = os.environ.get('CORS_ALLOW_CREDENTIALS', 'false').lower() == 'true'
app.state.SYSTEM_VERSION = get_current_version()
app.state.PUBLIC_API_GET_PATHS = PUBLIC_API_GET_PATHS

# Compliance and monitoring configuration
app.state.COMPLIANCE_ALERT_EMAILS = parse_env_list('COMPLIANCE_ALERT_EMAILS')
app.state.COMPLIANCE_SNMP_TARGETS = parse_env_list('COMPLIANCE_SNMP_TARGETS')
app.state.COMPLIANCE_SNMP_COMMUNITY = os.environ.get('COMPLIANCE_SNMP_COMMUNITY', 'public')
app.state.COMPLIANCE_HEALTH_INTERVAL = parse_int_env('COMPLIANCE_HEALTH_INTERVAL', 300)
app.state.RECEIVER_OFFLINE_THRESHOLD_MINUTES = parse_int_env('RECEIVER_OFFLINE_THRESHOLD_MINUTES', 10)
app.state.AUDIO_PATH_ALERT_THRESHOLD_MINUTES = parse_int_env('AUDIO_PATH_ALERT_THRESHOLD_MINUTES', 60)

# Google Search Console
app.state.GOOGLE_SITE_VERIFICATION = os.environ.get('GOOGLE_SITE_VERIFICATION', '')

# Sitemap configuration
_sitemap_limit_default = os.environ.get('SITEMAP_ALERT_LIMIT', '50')
try:
    app.state.SITEMAP_ALERT_LIMIT = max(0, int(_sitemap_limit_default)) or 50
except ValueError:
    app.state.SITEMAP_ALERT_LIMIT = 50

# Session cookie configuration
raw_secure_flag = os.environ.get('SESSION_COOKIE_SECURE')
if raw_secure_flag is not None:
    session_cookie_secure = raw_secure_flag.lower() in {'1', 'true', 'yes'}
    logger.info(f'Session cookie HTTPS requirement overridden via SESSION_COOKIE_SECURE={session_cookie_secure}')
else:
    debug_env = os.environ.get('FLASK_ENV', '').lower() == 'development'
    debug_flag = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    prefer_https = os.environ.get('PREFERRED_URL_SCHEME', '').lower() == 'https'
    session_cookie_secure = prefer_https and not (debug_env or debug_flag)
    if session_cookie_secure:
        logger.info('Session cookies will require HTTPS transport.')
    else:
        logger.info('Session cookies are not limited to HTTPS transport (HTTP or debug mode).')

app.state.SESSION_COOKIE_SECURE = session_cookie_secure

# =============================================================================
# MIDDLEWARE CONFIGURATION
# =============================================================================

# Session middleware (must be added first for sessions to work)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=session_hours * 3600,  # Convert hours to seconds
    same_site="lax",
    https_only=session_cookie_secure,
)

# CORS middleware
if allowed_origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER_NAME],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=app.state.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER_NAME],
    )

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# =============================================================================
# CUSTOM JSON ENCODER FOR INF/NAN
# =============================================================================

def safe_json_encoder(obj):
    """
    JSON encoder that converts inf/nan to safe values.
    Audio metrics use dB levels where -120dB represents silence (minimum)
    and 120dB represents maximum level.
    """
    MIN_AUDIO_LEVEL_DB = -120.0  # Silence threshold
    MAX_AUDIO_LEVEL_DB = 120.0   # Maximum level

    if isinstance(obj, float):
        if math.isinf(obj):
            return MIN_AUDIO_LEVEL_DB if obj < 0 else MAX_AUDIO_LEVEL_DB
        elif math.isnan(obj):
            return MIN_AUDIO_LEVEL_DB
    return obj

# =============================================================================
# TEMPLATES SETUP
# =============================================================================

templates = Jinja2Templates(directory="templates")

# Add custom template filters and globals
def shields_escape(text: str) -> str:
    """Escape text for shields.io badges"""
    from app_core.flask.template_filters import shields_escape as _shields_escape
    return _shields_escape(text)

templates.env.filters['shields_escape'] = shields_escape

# =============================================================================
# SOCKET.IO SETUP FOR WEBSOCKET
# =============================================================================

# Create Socket.IO server with ASGI support
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=False,
    engineio_logger=False,
)

# Wrap with Socket.IO's ASGI application
socket_app = socketio.ASGIApp(
    socketio_server=sio,
    other_asgi_app=app,
)

# =============================================================================
# MIDDLEWARE FOR REQUEST/RESPONSE PROCESSING
# =============================================================================

@app.middleware("http")
async def request_processing_middleware(request: Request, call_next):
    """
    Middleware to handle request processing, authentication, and CSRF validation.
    Equivalent to Flask's @app.before_request and @app.after_request
    """

    # Refresh version info
    request.app.state.SYSTEM_VERSION = get_current_version()

    # Log API requests
    if request.url.path.startswith('/api/') and request.method in ['POST', 'PUT', 'DELETE']:
        logger.info(f"{request.method} {request.url.path} from {request.client.host}")

    # Initialize request state (equivalent to Flask's g object)
    request.state.current_user = None
    request.state.admin_setup_mode = False

    setup_mode_active = request.app.state.SETUP_MODE

    # Handle setup mode
    if setup_mode_active:
        # Clear any existing session
        if 'user_id' in request.session:
            del request.session['user_id']

        # Define allowed endpoints during setup
        allowed_paths = {
            '/setup',
            '/setup/generate-secret',
            '/setup/derive-zone-codes',
            '/setup/lookup-county-fips',
            '/setup/success',
            '/setup/view-env',
            '/setup/download-env',
            '/setup/upload-env',
            '/settings/environment',
            '/api/environment/categories',
            '/api/environment/variables',
            '/api/environment/validate',
            '/api/environment/generate-secret',
            '/admin/environment/download-env',
        }

        is_allowed = (
            request.url.path in allowed_paths or
            request.url.path.startswith('/static/')
        )

        if not is_allowed:
            if request.url.path.startswith('/api/') or 'application/json' in request.headers.get('accept', ''):
                return JSONResponse({'error': 'Setup required'}, status_code=503)
            return RedirectResponse(url='/setup', status_code=302)
    else:
        # Load current user from session
        user_id = request.session.get('user_id')
        if user_id is not None:
            # TODO: Load user from database
            # This will need to be implemented with proper async database access
            pass

        # Check if this is admin setup mode (no users exist)
        try:
            # TODO: Check user count
            request.state.admin_setup_mode = False
        except Exception:
            request.state.admin_setup_mode = False

    # CSRF validation for protected methods
    if request.method in CSRF_PROTECTED_METHODS:
        # Check if endpoint is exempt
        is_exempt = (
            request.url.path in CSRF_EXEMPT_PATHS or
            (setup_mode_active and request.url.path.startswith('/setup'))
        )

        if not is_exempt:
            session_token = request.session.get(CSRF_SESSION_KEY)
            request_token = None

            # Get CSRF token from headers or form data
            request_token = request.headers.get(CSRF_HEADER_NAME)
            if not request_token:
                request_token = request.headers.get('X-CSRFToken')

            # Validate CSRF token
            if not session_token or not request_token or not hmac.compare_digest(session_token, request_token):
                if request.url.path in {'/login'} or request.url.path == '/login':
                    logger.info('Login CSRF token mismatch detected; refreshing session token.')
                    request.session.pop(CSRF_SESSION_KEY, None)
                    request.session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
                    return RedirectResponse(url='/login', status_code=302)

                if request.url.path.startswith('/api/') or 'application/json' in request.headers.get('accept', ''):
                    return JSONResponse({'error': 'Invalid or missing CSRF token'}, status_code=400)

                raise HTTPException(status_code=400, detail="Invalid or missing CSRF token")

    # Check authentication for protected paths
    if not setup_mode_active:
        protected_prefixes = ('/admin', '/logs', '/api', '/eas', '/settings')
        if any(request.url.path.startswith(prefix) for prefix in protected_prefixes):
            # Check if this is a public API GET endpoint
            normalized_path = request.url.path.rstrip('/') or '/'
            is_public_api = (
                request.method in {'GET', 'HEAD', 'OPTIONS'} and
                normalized_path in PUBLIC_API_GET_PATHS
            )

            if not is_public_api and request.state.current_user is None:
                if request.url.path.startswith('/api/'):
                    return JSONResponse({'error': 'Authentication required'}, status_code=401)

                if request.state.admin_setup_mode and request.url.path in {'/admin', '/admin/users'}:
                    if request.method == 'GET' or (request.method == 'POST' and '/users' in request.url.path):
                        pass  # Allow access
                    else:
                        next_url = str(request.url)
                        return RedirectResponse(url=f'/login?next={next_url}', status_code=302)
                else:
                    if request.method != 'GET' or 'application/json' in request.headers.get('accept', ''):
                        return JSONResponse({'error': 'Authentication required'}, status_code=401)
                    next_url = str(request.url)
                    return RedirectResponse(url=f'/login?next={next_url}', status_code=302)

    # Process request
    response = await call_next(request)

    # Add security headers to response
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'

    # Add cache-control headers for API endpoints
    if request.url.path.startswith('/api/') and request.method == 'GET' and response.status_code == 200:
        if '/api/system_status' in request.url.path or '/api/system_health' in request.url.path:
            response.headers['Cache-Control'] = 'public, max-age=10'
        elif '/api/alerts' in request.url.path:
            response.headers['Cache-Control'] = 'public, max-age=30'
        elif '/api/boundaries' in request.url.path:
            response.headers['Cache-Control'] = 'public, max-age=300'
        elif '/api/audio' in request.url.path:
            response.headers['Cache-Control'] = 'public, max-age=15'
        else:
            response.headers['Cache-Control'] = 'public, max-age=60'

    return response

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Custom 404 error page"""
    if request.url.path.startswith('/api/'):
        return JSONResponse({'error': '404 - Not Found'}, status_code=404)
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error": "404 - Page Not Found",
            "details": "The page you requested does not exist.",
        },
        status_code=404,
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    """Custom 500 error page"""
    logger.error(f"Internal server error: {exc}", exc_info=True)
    if request.url.path.startswith('/api/'):
        return JSONResponse({'error': '500 - Internal Server Error'}, status_code=500)
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error": "500 - Internal Server Error",
            "details": "Something went wrong on our end. Please try again later.",
        },
        status_code=500,
    )

@app.exception_handler(403)
async def forbidden_handler(request: Request, exc: HTTPException):
    """Custom 403 error page"""
    if request.url.path.startswith('/api/'):
        return JSONResponse({'error': '403 - Forbidden'}, status_code=403)
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error": "403 - Forbidden",
            "details": "You do not have permission to access this resource.",
        },
        status_code=403,
    )

@app.exception_handler(400)
async def bad_request_handler(request: Request, exc: HTTPException):
    """Custom 400 error page"""
    if request.url.path.startswith('/api/'):
        return JSONResponse({'error': '400 - Bad Request'}, status_code=400)
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error": "400 - Bad Request",
            "details": "The request was malformed or invalid.",
        },
        status_code=400,
    )

# =============================================================================
# BASIC ROUTES (More routes will be added from route modules)
# =============================================================================

@app.get("/")
async def index(request: Request):
    """Index page"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy", "version": get_current_version()}

# =============================================================================
# STATIC FILES
# =============================================================================

# Mount static files (CSS, JS, images, etc.)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# =============================================================================
# ROUTE REGISTRATION
# =============================================================================

# TODO: Import and register all route modules from webapp/
# This will be done in subsequent steps of the migration

logger.info(f"FastAPI app initialized - Version {get_current_version()}")
if app.state.SETUP_MODE:
    logger.warning(f"Setup mode enabled due to: {', '.join(app.state.SETUP_MODE_REASONS)}")

# =============================================================================
# ENTRYPOINT FOR DEVELOPMENT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_app:socket_app",  # Use socket_app to include Socket.IO
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
