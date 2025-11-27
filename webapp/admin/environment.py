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

from __future__ import annotations

"""Environment settings management routes."""

import json
import logging
import os
import re
from functools import wraps
from typing import Any, Dict, List
from pathlib import Path

from flask import Blueprint, flash, jsonify, redirect, render_template, request, current_app, url_for
from werkzeug.exceptions import BadRequest

from app_core.location import get_location_settings, _derive_county_zone_codes_from_fips
from app_core.auth.roles import require_permission
from app_utils.pi_pinout import ARGON_OLED_RESERVED_BCM, ARGON_OLED_RESERVED_PHYSICAL

logger = logging.getLogger(__name__)


# Create Blueprint for environment routes
environment_bp = Blueprint('environment', __name__)


def _get_domain_candidates() -> List[str]:
    """Return possible domain names to inspect for SSL material."""

    domain_value = os.environ.get('DOMAIN_NAME', 'localhost').strip()
    if not domain_value:
        return ['localhost']

    # DOMAIN_NAME may contain multiple domains separated by commas or whitespace
    candidates = [segment for segment in re.split(r'[\s,]+', domain_value) if segment]
    return candidates or ['localhost']


def _raise_reserved_pin(field: str, pin: int) -> None:
    physical = ", ".join(str(p) for p in sorted(ARGON_OLED_RESERVED_PHYSICAL))
    raise BadRequest(
        f"{field} cannot use GPIO pin {pin}; the Argon OLED enclosure reserves physical pins {physical}."
    )


def _validate_reserved_pin(field: str, value: str) -> None:
    value = (value or '').strip()
    if not value:
        return
    try:
        pin = int(value, 10)
    except ValueError:
        return
    if pin in ARGON_OLED_RESERVED_BCM:
        _raise_reserved_pin(field, pin)


def _validate_reserved_pin_collection(field: str, raw: str) -> None:
    raw = (raw or '').strip()
    if not raw:
        return
    entries = [segment.strip() for segment in re.split(r"[,\n]+", raw) if segment.strip()]
    for entry in entries:
        pin_segment = entry.split(":", 1)[0].strip()
        if not pin_segment:
            continue
        try:
            pin = int(pin_segment, 10)
        except ValueError:
            continue
        if pin in ARGON_OLED_RESERVED_BCM:
            _raise_reserved_pin(field, pin)


def _validate_behavior_matrix_reserved(raw: str) -> None:
    raw = (raw or '').strip()
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    for key in payload.keys():
        try:
            pin = int(key)
        except (TypeError, ValueError):
            continue
        if pin in ARGON_OLED_RESERVED_BCM:
            _raise_reserved_pin('GPIO_PIN_BEHAVIOR_MATRIX', pin)


def _find_ssl_material(filename: str) -> tuple[Path | None, List[Path], str | None]:
    """Search for SSL certificate/key material across supported locations."""

    search_roots = [
        Path('/etc/letsencrypt/live'),
        Path('/app-config/certs/live'),
    ]

    attempted_paths: List[Path] = []

    for domain_candidate in _get_domain_candidates():
        for root in search_roots:
            candidate = root / domain_candidate / filename
            attempted_paths.append(candidate)
            if candidate.exists():
                return candidate, attempted_paths, domain_candidate

    return None, attempted_paths, None


def require_permission_or_setup_mode(permission_name: str):
    """
    Decorator that requires permission OR allows access during setup mode.
    
    This is critical for environment settings to be accessible even when
    the database connection is misconfigured, allowing users to fix the
    configuration without needing to destroy and redeploy the stack.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Allow access if in setup mode (database failure, etc.)
            if current_app.config.get('SETUP_MODE', False):
                return f(*args, **kwargs)
            
            # Otherwise, use normal permission check
            return require_permission(permission_name)(f)(*args, **kwargs)
        return decorated_function
    return decorator


# Environment variable categories and their configurations
ENV_CATEGORIES = {
    'core': {
        'name': 'Core Settings',
        'icon': 'fa-cog',
        'description': 'Essential application configuration',
        'variables': [
            {
                'key': 'SECRET_KEY',
                'label': 'Secret Key',
                'type': 'password',
                'required': True,
                'description': 'Flask session security key (generate with: python -c "import secrets; print(secrets.token_hex(32))")',
                'sensitive': True,
                'minlength': 32,
                'pattern': '^[A-Za-z0-9]{32,}$',
                'title': 'SECRET_KEY must be at least 32 characters long and contain only alphanumeric characters.',
            },
            {
                'key': 'FLASK_ENV',
                'label': 'Environment',
                'type': 'select',
                'options': ['production', 'development'],
                'default': 'production',
                'description': 'Flask environment mode',
            },
            {
                'key': 'FLASK_DEBUG',
                'label': 'Debug Mode',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Enable Flask debug mode (should be false in production)',
            },
            {
                'key': 'LOG_LEVEL',
                'label': 'Log Level',
                'type': 'select',
                'options': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                'default': 'INFO',
                'description': 'Application logging level',
            },
            {
                'key': 'LOG_FILE',
                'label': 'Log File Path',
                'type': 'text',
                'default': 'logs/eas_station.log',
                'description': 'Path to application log file',
            },
            {
                'key': 'WEB_ACCESS_LOG',
                'label': 'Web Server Access Logs',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Enable web server access logs (shows all HTTP requests). Set to false to reduce log clutter and only show errors.',
            },
        ],
    },
    'https': {
        'name': 'HTTPS / SSL',
        'icon': 'fa-lock',
        'description': 'SSL/TLS certificate and HTTPS configuration',
        'variables': [
            {
                'key': 'DOMAIN_NAME',
                'label': 'Domain Name',
                'type': 'text',
                'default': 'localhost',
                'description': 'Domain name for SSL certificate (use "localhost" for testing with self-signed cert, or your actual domain for Let\'s Encrypt)',
                'placeholder': 'eas.example.com',
                'pattern': r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$|^localhost$',
                'title': 'Must be a valid domain name (e.g., eas.example.com) or "localhost"',
            },
            {
                'key': 'SSL_EMAIL',
                'label': 'SSL Certificate Email',
                'type': 'text',
                'default': 'admin@example.com',
                'description': 'Email address for Let\'s Encrypt certificate expiration notifications',
                'placeholder': 'admin@example.com',
                'pattern': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
                'title': 'Must be a valid email address',
            },
            {
                'key': 'CERTBOT_STAGING',
                'label': 'Use Staging Server',
                'type': 'select',
                'options': ['0', '1'],
                'default': '0',
                'description': 'Use Let\'s Encrypt staging server for testing (0=production, 1=staging). Use staging to avoid rate limits during testing.',
            },
        ],
    },
    'database': {
        'name': 'Database',
        'icon': 'fa-database',
        'description': 'PostgreSQL connection settings',
        'variables': [
            {
                'key': 'POSTGRES_HOST',
                'label': 'Host',
                'type': 'text',
                'required': True,
                'default': 'alerts-db',
                'description': 'Database server hostname or IP',
            },
            {
                'key': 'POSTGRES_PORT',
                'label': 'Port',
                'type': 'number',
                'default': '5432',
                'description': 'Database server port',
                'min': 1,
                'max': 65535,
            },
            {
                'key': 'POSTGRES_DB',
                'label': 'Database Name',
                'type': 'text',
                'required': True,
                'default': 'alerts',
                'description': 'PostgreSQL database name',
            },
            {
                'key': 'POSTGRES_USER',
                'label': 'Username',
                'type': 'text',
                'required': True,
                'default': 'postgres',
                'description': 'Database username',
            },
            {
                'key': 'POSTGRES_PASSWORD',
                'label': 'Password',
                'type': 'password',
                'required': True,
                'description': 'Database password',
                'sensitive': True,
            },
        ],
    },
    'redis': {
        'name': 'Redis Cache',
        'icon': 'fa-bolt',
        'description': 'Redis connection and caching configuration',
        'variables': [
            {
                'key': 'REDIS_HOST',
                'label': 'Redis Host',
                'type': 'text',
                'default': 'redis',
                'description': 'Redis server hostname (use "redis" for Docker container)',
            },
            {
                'key': 'REDIS_PORT',
                'label': 'Redis Port',
                'type': 'number',
                'default': '6379',
                'description': 'Redis server port',
                'min': 1,
                'max': 65535,
            },
            {
                'key': 'REDIS_DB',
                'label': 'Redis Database',
                'type': 'number',
                'default': '0',
                'description': 'Redis database index (0-15)',
                'min': 0,
                'max': 15,
            },
            {
                'key': 'REDIS_PASSWORD',
                'label': 'Redis Password',
                'type': 'password',
                'description': 'Redis password (leave empty if no authentication)',
                'sensitive': True,
            },
            {
                'key': 'CACHE_TYPE',
                'label': 'Cache Type',
                'type': 'select',
                'options': ['redis', 'simple', 'filesystem'],
                'default': 'redis',
                'description': 'Cache backend (Redis recommended for production)',
            },
            {
                'key': 'CACHE_DEFAULT_TIMEOUT',
                'label': 'Cache Timeout (seconds)',
                'type': 'number',
                'default': '300',
                'description': 'How long cached data remains valid',
                'min': 60,
                'max': 3600,
            },
            {
                'key': 'CACHE_REDIS_URL',
                'label': 'Redis URL',
                'type': 'text',
                'default': 'redis://redis:6379/0',
                'description': 'Full Redis connection URL. When set, takes precedence over individual REDIS_* settings above.',
                'placeholder': 'redis://[password@]host:port/db',
            },
        ],
    },
    'polling': {
        'name': 'Alert Polling',
        'icon': 'fa-satellite',
        'description': 'CAP feed polling configuration',
        'variables': [
            {
                'key': 'POLL_INTERVAL_SEC',
                'label': 'Poll Interval (seconds)',
                'type': 'number',
                'default': '180',
                'description': 'How often to check for new alerts',
                'min': 60,
                'max': 3600,
            },
            {
                'key': 'CAP_TIMEOUT',
                'label': 'Request Timeout (seconds)',
                'type': 'number',
                'default': '30',
                'description': 'HTTP timeout for CAP feed requests',
                'min': 10,
                'max': 120,
            },
            {
                'key': 'NOAA_USER_AGENT',
                'label': 'NOAA User Agent',
                'type': 'text',
                'required': True,
                'description': 'User agent string for NOAA API compliance',
            },
            {
                'key': 'CAP_ENDPOINTS',
                'label': 'CAP Feed URLs',
                'type': 'textarea',
                'description': 'Comma-separated list of custom CAP feed URLs (optional)',
                'placeholder': 'https://example.com/cap/feed1, https://example.com/cap/feed2',
            },
            {
                'key': 'IPAWS_CAP_FEED_URLS',
                'label': 'IPAWS Feed URLs',
                'type': 'textarea',
                'description': 'Comma-separated list of IPAWS CAP feed URLs (optional)',
            },
            {
                'key': 'IPAWS_DEFAULT_LOOKBACK_HOURS',
                'label': 'IPAWS Lookback Hours',
                'type': 'number',
                'default': '12',
                'description': 'Hours to look back when fetching IPAWS alerts',
                'min': 1,
                'max': 72,
            },
        ],
    },
    'location': {
        'name': 'Location',
        'icon': 'fa-map-marker-alt',
        'description': 'Default location and coverage area',
        'variables': [
            {
                'key': 'DEFAULT_TIMEZONE',
                'label': 'Timezone',
                'type': 'text',
                'default': 'America/New_York',
                'description': 'Default timezone (e.g., America/New_York)',
            },
            {
                'key': 'DEFAULT_COUNTY_NAME',
                'label': 'County Name',
                'type': 'text',
                'description': 'Primary county for alerts',
            },
            {
                'key': 'DEFAULT_STATE_CODE',
                'label': 'State Code',
                'type': 'text',
                'description': 'Two-letter state code (e.g., OH)',
                'maxlength': 2,
            },
            {
                'key': 'DEFAULT_ZONE_CODES',
                'label': 'Zone Codes',
                'type': 'textarea',
                'description': 'Comma-separated NWS zone codes (e.g., OHZ016,OHC137)',
                'placeholder': 'OHZ016,OHC137',
            },
            {
                'key': 'DEFAULT_FIPS_CODES',
                'label': 'FIPS Codes',
                'type': 'textarea',
                'description': 'Federal Information Processing Standards county codes (5-digit: 2-digit state + 3-digit county). Example: 039137 = Ohio (039) + Putnam County (137).',
                'placeholder': '039137,039003',
            },
            {
                'key': 'DEFAULT_STORAGE_ZONE_CODES',
                'label': 'Storage Zone Codes',
                'type': 'textarea',
                'description': 'Zone codes for alert storage (leave empty to use Zone Codes above)',
                'placeholder': 'OHZ003,OHC137',
            },
            {
                'key': 'DEFAULT_MAP_CENTER_LAT',
                'label': 'Map Center Latitude',
                'type': 'number',
                'step': 0.0001,
                'description': 'Default map center latitude',
            },
            {
                'key': 'DEFAULT_MAP_CENTER_LNG',
                'label': 'Map Center Longitude',
                'type': 'number',
                'step': 0.0001,
                'description': 'Default map center longitude',
            },
            {
                'key': 'DEFAULT_MAP_ZOOM',
                'label': 'Map Zoom Level',
                'type': 'number',
                'default': '9',
                'description': 'Default map zoom (1-18)',
                'min': 1,
                'max': 18,
            },
        ],
    },
    'eas': {
        'name': 'EAS Broadcast',
        'icon': 'fa-broadcast-tower',
        'description': 'SAME/EAS encoder configuration',
        'variables': [
            {
                'key': 'EAS_BROADCAST_ENABLED',
                'label': 'Enable EAS Broadcasting',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Enable SAME/EAS audio generation',
            },
            {
                'key': 'EAS_ORIGINATOR',
                'label': 'Originator Code',
                'type': 'select',
                'options': ['WXR', 'EAS', 'PEP', 'CIV'],
                'default': 'WXR',
                'description': 'EAS originator code: WXR (Weather), EAS (Broadcast), PEP (Primary Entry Point), CIV (Civil Authority)',
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_STATION_ID',
                'label': 'Station ID',
                'type': 'text',
                'default': 'EASNODES',
                'description': 'Your station callsign or identifier (8 characters max, uppercase letters/numbers/forward slash only)',
                'maxlength': 8,
                'pattern': '^[A-Z0-9/]{1,8}$',
                'title': 'Must contain only uppercase letters (A-Z), numbers (0-9), and forward slash (/). No hyphens or lowercase letters.',
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_OUTPUT_DIR',
                'label': 'Output Directory',
                'type': 'text',
                'default': 'static/eas_messages',
                'description': 'Directory for generated EAS audio files',
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_ATTENTION_TONE_SECONDS',
                'label': 'Attention Tone Duration',
                'type': 'number',
                'default': '8',
                'description': 'Attention tone length in seconds',
                'min': 1,
                'max': 60,
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_SAMPLE_RATE',
                'label': 'Audio Sample Rate',
                'type': 'select',
                'options': ['8000', '16000', '22050', '44100', '48000'],
                'default': '44100',
                'description': 'Audio sample rate in Hz',
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_AUDIO_PLAYER',
                'label': 'Audio Player Command',
                'type': 'text',
                'default': 'aplay',
                'description': 'Command to play audio files',
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_MANUAL_FIPS_CODES',
                'label': 'Authorized FIPS Codes',
                'type': 'textarea',
                'description': 'Comma-separated FIPS codes for manual broadcasts',
                'placeholder': '039137,039003',
                'category': 'eas_enabled',
            },
            {
                'key': 'EAS_MANUAL_EVENT_CODES',
                'label': 'Authorized Event Codes',
                'type': 'textarea',
                'description': 'Comma-separated event codes for manual broadcasts',
                'placeholder': 'RWT,DMO,SVR',
                'category': 'eas_enabled',
            },
        ],
    },
    'gpio': {
        'name': 'GPIO Control',
        'icon': 'fa-microchip',
        'description': 'GPIO relay activation settings',
        'variables': [
            {
                'key': 'EAS_GPIO_PIN',
                'label': 'Primary Pin (BCM GPIO Number)',
                'type': 'number',
                'description': (
                    'BCM GPIO pin number for relay control (e.g., GPIO 17 = BCM pin 17, physical pin 11). '
                    'Leave empty to disable GPIO completely. Pins 2, 3, 4, and 14 are reserved for the Argon OLED enclosure.'
                ),
                'placeholder': 'e.g., 17',
                'min': 2,
                'max': 27,
                'disallow': sorted(ARGON_OLED_RESERVED_BCM),
            },
            {
                'key': 'EAS_GPIO_ACTIVE_STATE',
                'label': 'Primary Pin Active State',
                'type': 'select',
                'options': ['HIGH', 'LOW'],
                'default': 'HIGH',
                'description': 'Electrical state when the primary pin is activated (HIGH = 3.3V, LOW = 0V)',
                'category': 'gpio_enabled',
            },
            {
                'key': 'EAS_GPIO_HOLD_SECONDS',
                'label': 'Primary Pin Hold Duration',
                'type': 'number',
                'default': '5',
                'description': 'How long to keep the primary pin activated (in seconds)',
                'min': 1,
                'max': 300,
                'category': 'gpio_enabled',
            },
            {
                'key': 'EAS_GPIO_WATCHDOG_SECONDS',
                'label': 'Primary Pin Watchdog Timeout',
                'type': 'number',
                'default': '300',
                'description': 'Maximum time the primary pin can stay active before automatic safety shutdown (in seconds)',
                'min': 5,
                'max': 3600,
                'category': 'gpio_enabled',
            },
            {
                'key': 'GPIO_ADDITIONAL_PINS',
                'label': 'Additional GPIO Pins',
                'type': 'gpio_pin_builder',
                'description': (
                    'Configure additional GPIO pins beyond the primary pin. '
                    'Click "Add Pin" to configure each additional relay or output. '
                    'Pins 2, 3, 4, and 14 are reserved for the Argon OLED enclosure and are unavailable.'
                ),
                'category': 'gpio_enabled',
            },
            {
                'key': 'GPIO_PIN_BEHAVIOR_MATRIX',
                'label': 'Pin Behavior Matrix',
                'type': 'textarea',
                'rows': 4,
                'description': (
                    'JSON object that maps BCM GPIO pin numbers to lists of behaviors. '
                    'Use the GPIO Pin Map page (System → GPIO Pin Map) to edit this value. '
                    'Example: {"17": ["duration_of_alert"], "18": ["playout"]}'
                ),
                'placeholder': '{"17": ["duration_of_alert"], "18": ["playout"]}',
                'category': 'gpio_enabled',
            },
        ],
    },
    'tts': {
        'name': 'Text-to-Speech',
        'icon': 'fa-volume-up',
        'description': 'TTS provider configuration',
        'variables': [
            {
                'key': 'EAS_TTS_PROVIDER',
                'label': 'TTS Provider',
                'type': 'select',
                'options': ['', 'azure_openai', 'azure', 'pyttsx3'],
                'default': '',
                'description': 'Text-to-speech provider (leave empty to disable)',
            },
            {
                'key': 'AZURE_OPENAI_ENDPOINT',
                'label': 'Azure OpenAI Endpoint',
                'type': 'text',
                'description': 'Azure OpenAI TTS endpoint URL',
                'category': 'azure_openai',
            },
            {
                'key': 'AZURE_OPENAI_KEY',
                'label': 'Azure OpenAI API Key',
                'type': 'password',
                'description': 'Azure OpenAI API key',
                'sensitive': True,
                'category': 'azure_openai',
            },
            {
                'key': 'AZURE_OPENAI_VOICE',
                'label': 'Azure OpenAI Voice',
                'type': 'select',
                'options': ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'],
                'default': 'alloy',
                'description': 'Voice selection for Azure OpenAI TTS',
                'category': 'azure_openai',
            },
            {
                'key': 'AZURE_OPENAI_MODEL',
                'label': 'Azure OpenAI Model',
                'type': 'select',
                'options': ['tts-1', 'tts-1-hd'],
                'default': 'tts-1-hd',
                'description': 'TTS model quality',
                'category': 'azure_openai',
            },
            {
                'key': 'AZURE_OPENAI_SPEED',
                'label': 'Speech Speed',
                'type': 'number',
                'step': 0.1,
                'default': '1.0',
                'description': 'Speech speed multiplier (0.25-4.0)',
                'min': 0.25,
                'max': 4.0,
                'category': 'azure_openai',
            },
            {
                'key': 'AZURE_SPEECH_KEY',
                'label': 'Azure Speech API Key',
                'type': 'password',
                'description': 'Azure AI Speech service key (legacy)',
                'sensitive': True,
                'category': 'azure',
            },
            {
                'key': 'AZURE_SPEECH_REGION',
                'label': 'Azure Speech Region',
                'type': 'text',
                'description': 'Azure service region (e.g., eastus)',
                'category': 'azure',
            },
        ],
    },
    'led': {
        'name': 'LED Display',
        'icon': 'fa-tv',
        'description': 'Alpha protocol LED sign',
        'variables': [
            {
                'key': 'LED_SIGN_IP',
                'label': 'LED Sign IP Address',
                'type': 'text',
                'description': 'IP address of LED sign (leave empty to disable). Disabling this will gray out other LED settings.',
                'placeholder': '192.168.1.100',
                'pattern': '^((25[0-5]|(2[0-4]|1\\d|[1-9]|)\\d)\\.?\\b){4}$',
                'title': 'Must be a valid IPv4 address (e.g., 192.168.1.100)',
            },
            {
                'key': 'LED_SIGN_PORT',
                'label': 'LED Sign Port',
                'type': 'number',
                'default': '10001',
                'description': 'TCP port for LED sign',
                'min': 1,
                'max': 65535,
                'category': 'led_enabled',
            },
            {
                'key': 'DEFAULT_LED_LINES',
                'label': 'Default LED Text',
                'type': 'textarea',
                'description': 'Comma-separated lines for idle display',
                'placeholder': 'PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY',
                'category': 'led_enabled',
            },
        ],
    },
    'vfd': {
        'name': 'VFD Display',
        'icon': 'fa-desktop',
        'description': 'Noritake GU140x32F-7000B VFD',
        'variables': [
            {
                'key': 'VFD_PORT',
                'label': 'Serial Port',
                'type': 'text',
                'description': 'Serial port for VFD (leave empty to disable). Disabling this will gray out other VFD settings.',
                'placeholder': '/dev/ttyUSB0',
            },
            {
                'key': 'VFD_BAUDRATE',
                'label': 'Baud Rate',
                'type': 'select',
                'options': ['9600', '19200', '38400', '57600', '115200'],
                'default': '38400',
                'description': 'Serial communication speed',
                'category': 'vfd_enabled',
            },
        ],
    },
    'oled': {
        'name': 'OLED Display',
        'icon': 'fa-microchip',
        'description': 'Argon Industria SSD1306 OLED module',
        'variables': [
            {
                'key': 'OLED_ENABLED',
                'label': 'Enable OLED Module',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Set to true to drive the Argon Industria OLED status display.',
            },
            {
                'key': 'OLED_I2C_BUS',
                'label': 'I2C Bus',
                'type': 'number',
                'default': '1',
                'description': 'Linux I2C bus number (use 1 for Raspberry Pi 3/4/5).',
                'min': 0,
                'max': 3,
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_I2C_ADDRESS',
                'label': 'I2C Address',
                'type': 'text',
                'default': '0x3C',
                'description': 'SSD1306 device address (hex like 0x3C or decimal).',
                'pattern': r'^(0x[0-9A-Fa-f]{2}|\d{1,3})$',
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_WIDTH',
                'label': 'Width (pixels)',
                'type': 'number',
                'default': '128',
                'description': 'Logical display width.',
                'min': 32,
                'max': 256,
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_HEIGHT',
                'label': 'Height (pixels)',
                'type': 'number',
                'default': '64',
                'description': 'Logical display height.',
                'min': 16,
                'max': 128,
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_ROTATE',
                'label': 'Rotation',
                'type': 'select',
                'options': ['0', '90', '180', '270'],
                'default': '0',
                'description': 'Rotate output to match installation orientation.',
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_DEFAULT_INVERT',
                'label': 'Invert Colours',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Draw dark text on a light background by default.',
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_FONT_PATH',
                'label': 'Font Path',
                'type': 'text',
                'description': 'Optional path to a TTF font used for OLED rendering.',
                'placeholder': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_CONTRAST',
                'label': 'Contrast',
                'type': 'number',
                'description': 'OLED display contrast (0-255). Leave empty for default.',
                'min': 0,
                'max': 255,
                'category': 'oled_enabled',
            },
            {
                'key': 'OLED_SCROLL_EFFECT',
                'label': 'Scroll Effect',
                'type': 'select',
                'options': ['scroll_left', 'scroll_right', 'none'],
                'default': 'scroll_left',
                'description': 'Animation effect for scrolling text.',
                'category': 'oled_enabled',
            },
        ],
    },
    'sdr': {
        'name': 'SDR & Radio Capture',
        'icon': 'fa-radio',
        'description': 'Software-Defined Radio and audio capture settings',
        'variables': [
            {
                'key': 'RADIO_CAPTURE_MODE',
                'label': 'Capture Mode',
                'type': 'select',
                'options': ['iq', 'pcm'],
                'default': 'pcm',
                'description': 'Audio capture format: IQ (complex samples for analysis) or PCM (audio for decoding)',
            },
            {
                'key': 'RADIO_CAPTURE_DURATION',
                'label': 'Capture Duration (seconds)',
                'type': 'number',
                'default': '30',
                'description': 'Duration to capture when SAME burst is detected',
                'min': 5,
                'max': 300,
            },
            {
                'key': 'RADIO_CAPTURE_DIR',
                'label': 'Capture Directory',
                'type': 'text',
                'default': '/app/captures',
                'description': 'Directory to store captured radio audio files',
            },
            {
                'key': 'SDR_ARGS',
                'label': 'SDR Arguments',
                'type': 'text',
                'default': 'driver=airspy',
                'description': 'SoapySDR device arguments (e.g., driver=airspy or driver=rtlsdr)',
                'placeholder': 'driver=airspy',
            },
        ],
    },
    'zigbee': {
        'name': 'Zigbee Module',
        'icon': 'fa-broadcast-tower',
        'description': 'Argon Industria V5 Zigbee Module',
        'variables': [
            {
                'key': 'ZIGBEE_ENABLED',
                'label': 'Enable Zigbee Module',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Enable the Argon Industria V5 Zigbee coordinator module.',
            },
            {
                'key': 'ZIGBEE_PORT',
                'label': 'Serial Port',
                'type': 'text',
                'description': 'Serial port for Zigbee module (UART connection). Leave empty to auto-detect.',
                'placeholder': '/dev/ttyAMA0',
                'category': 'zigbee_enabled',
            },
            {
                'key': 'ZIGBEE_BAUDRATE',
                'label': 'Baud Rate',
                'type': 'select',
                'options': ['9600', '19200', '38400', '57600', '115200'],
                'default': '115200',
                'description': 'Serial communication speed (115200 is standard for Zigbee coordinators)',
                'category': 'zigbee_enabled',
            },
            {
                'key': 'ZIGBEE_CHANNEL',
                'label': 'Zigbee Channel',
                'type': 'number',
                'default': '15',
                'min': 11,
                'max': 26,
                'description': 'Zigbee radio channel (11-26). Channel 15 is recommended to avoid WiFi interference.',
                'category': 'zigbee_enabled',
            },
            {
                'key': 'ZIGBEE_PAN_ID',
                'label': 'PAN ID',
                'type': 'text',
                'description': 'Personal Area Network ID (leave empty for auto-generated)',
                'placeholder': '0x1A62',
                'category': 'zigbee_enabled',
            },
        ],
    },
    'notifications': {
        'name': 'Notifications',
        'icon': 'fa-envelope',
        'description': 'Email and SMS alerts',
        'variables': [
            {
                'key': 'ENABLE_EMAIL_NOTIFICATIONS',
                'label': 'Enable Email Notifications',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Send email alerts for new notifications',
            },
            {
                'key': 'ENABLE_SMS_NOTIFICATIONS',
                'label': 'Enable SMS Notifications',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Send SMS alerts (requires configuration)',
            },
            {
                'key': 'MAIL_SERVER',
                'label': 'Mail Server',
                'type': 'text',
                'description': 'SMTP server hostname',
                'category': 'email',
            },
            {
                'key': 'MAIL_PORT',
                'label': 'Mail Port',
                'type': 'number',
                'default': '587',
                'description': 'SMTP server port',
                'category': 'email',
                'min': 1,
                'max': 65535,
            },
            {
                'key': 'MAIL_USE_TLS',
                'label': 'Use TLS',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'true',
                'description': 'Enable TLS encryption',
                'category': 'email',
            },
            {
                'key': 'MAIL_USERNAME',
                'label': 'Mail Username',
                'type': 'text',
                'description': 'SMTP authentication username',
                'category': 'email',
            },
            {
                'key': 'MAIL_PASSWORD',
                'label': 'Mail Password',
                'type': 'password',
                'description': 'SMTP authentication password',
                'sensitive': True,
                'category': 'email',
            },
        ],
    },
    'performance': {
        'name': 'Performance',
        'icon': 'fa-tachometer-alt',
        'description': 'Caching and worker settings',
        'variables': [
            {
                'key': 'CACHE_TIMEOUT',
                'label': 'Cache Timeout (seconds)',
                'type': 'number',
                'default': '300',
                'description': 'How long to cache API responses',
                'min': 60,
                'max': 3600,
            },
            {
                'key': 'MAX_WORKERS',
                'label': 'Gunicorn Workers',
                'type': 'number',
                'default': '2',
                'description': 'Number of Gunicorn worker processes. More workers allow handling more concurrent web requests but use more memory. Requires container restart to take effect.',
                'min': 1,
                'max': 8,
            },
            {
                'key': 'MAX_CONCURRENT_EAS_SCANS',
                'label': 'EAS Scan Threads (Per Worker)',
                'type': 'number',
                'default': '2',
                'description': 'Maximum concurrent EAS scan threads PER WORKER for decoding SAME headers. Increase if you see "Skipping EAS scan" warnings. Raspberry Pi: 2-3, Desktop: 3-5, Server: 4-8. Total threads = this value × number of Gunicorn workers.',
                'min': 1,
                'max': 8,
            },
            {
                'key': 'EAS_SCAN_INTERVAL',
                'label': 'EAS Scan Interval (seconds)',
                'type': 'number',
                'step': 0.5,
                'default': '3.0',
                'description': 'How often to scan audio buffer for SAME headers (in seconds). System auto-adjusts if scans take longer. Raspberry Pi 5: start with 5.0s, Desktop: 3.0s. Lower = more frequent scans (better detection) but higher CPU usage. Monitor logs for "Skipping EAS scan" warnings.',
                'min': 1.0,
                'max': 10.0,
            },
            {
                'key': 'UPLOAD_FOLDER',
                'label': 'Upload Directory',
                'type': 'text',
                'default': '/app/uploads',
                'description': 'Directory for file uploads',
            },
        ],
    },
    'docker': {
        'name': 'Docker/System',
        'icon': 'fa-docker',
        'description': 'Container and infrastructure settings',
        'variables': [
            {
                'key': 'TZ',
                'label': 'System Timezone',
                'type': 'text',
                'default': 'America/New_York',
                'description': 'Container timezone',
            },
            {
                'key': 'WATCHTOWER_LABEL_ENABLE',
                'label': 'Watchtower Auto-Update',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'true',
                'description': 'Enable automatic updates via Watchtower',
            },
            {
                'key': 'WATCHTOWER_MONITOR_ONLY',
                'label': 'Monitor Only Mode',
                'type': 'select',
                'options': ['false', 'true'],
                'default': 'false',
                'description': 'Only check for updates, do not apply',
            },
            {
                'key': 'ALERTS_DB_IMAGE',
                'label': 'PostgreSQL Image',
                'type': 'text',
                'default': 'postgis/postgis:17-3.4',
                'description': 'PostgreSQL+PostGIS Docker image',
            },
        ],
    },
    'icecast': {
        'name': 'Icecast Streaming',
        'icon': 'fa-podcast',
        'description': 'Icecast server configuration for audio streaming',
        'variables': [
            {
                'key': 'ICECAST_ENABLED',
                'label': 'Enable Icecast Streaming',
                'type': 'select',
                'options': ['true', 'false'],
                'default': 'true',
                'description': 'Enable automatic Icecast streaming for all audio sources',
            },
            {
                'key': 'ICECAST_SERVER',
                'label': 'Icecast Server (Internal)',
                'type': 'text',
                'default': 'icecast',
                'description': 'Internal hostname for sdr-service to connect to Icecast. Use "icecast" for Docker container name, or IP if external.',
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_HOSTNAME',
                'label': 'Icecast Hostname (Config)',
                'type': 'text',
                'description': 'Hostname in Icecast icecast.xml config (server identity). Different from PUBLIC_HOSTNAME which is for stream URLs.',
                'placeholder': 'icecast.example.com',
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_PUBLIC_HOSTNAME',
                'label': 'Public Hostname/IP',
                'type': 'text',
                'description': 'CRITICAL: Public IP or hostname for stream URLs (e.g., 207.148.11.5). Required for remote listeners to connect.',
                'placeholder': 'e.g., 207.148.11.5 or easstation.com',
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_PORT',
                'label': 'Internal Port',
                'type': 'number',
                'default': '8000',
                'description': 'Icecast internal port (container-to-container)',
                'min': 1,
                'max': 65535,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_EXTERNAL_PORT',
                'label': 'External Port',
                'type': 'number',
                'default': '8001',
                'description': 'Icecast external port (host/browser access)',
                'min': 1,
                'max': 65535,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_LOCATION',
                'label': 'Station Location',
                'type': 'text',
                'default': 'EAS Monitoring Station',
                'description': 'Location name shown in Icecast stream metadata',
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_ADMIN',
                'label': 'Admin Contact Email',
                'type': 'text',
                'default': 'admin@example.com',
                'description': 'Contact email shown in Icecast admin interface',
                'placeholder': 'admin@example.com',
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_MAX_CLIENTS',
                'label': 'Max Listeners',
                'type': 'number',
                'default': '100',
                'description': 'Maximum concurrent stream listeners',
                'min': 1,
                'max': 10000,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_MAX_SOURCES',
                'label': 'Max Sources',
                'type': 'number',
                'default': '50',
                'description': 'Maximum concurrent source connections (audio streams)',
                'min': 1,
                'max': 100,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_SOURCE_PASSWORD',
                'label': 'Source Password',
                'type': 'password',
                'default': 'eas_station_source_password',
                'description': 'Password for publishing streams to Icecast (username: "source")',
                'sensitive': True,
                'required': True,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_RELAY_PASSWORD',
                'label': 'Relay Password',
                'type': 'password',
                'default': 'changeme_relay',
                'description': 'Password for relay connections (for cascading Icecast servers)',
                'sensitive': True,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_ADMIN_USER',
                'label': 'Admin Username',
                'type': 'text',
                'default': 'admin',
                'description': 'Username for Icecast admin web interface',
                'required': True,
                'category': 'icecast_enabled',
            },
            {
                'key': 'ICECAST_ADMIN_PASSWORD',
                'label': 'Admin Password',
                'type': 'password',
                'default': 'changeme_admin',
                'description': 'Password for Icecast admin interface and metadata updates',
                'sensitive': True,
                'required': True,
                'category': 'icecast_enabled',
            },
        ],
    },
}


def get_env_file_path() -> Path:
    """Get the path to the .env file."""
    # Check if CONFIG_PATH environment variable is set (for persistent storage)
    config_path = os.environ.get('CONFIG_PATH')
    if config_path:
        return Path(config_path)

    # Fallback to .env in the project root
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent.parent
    env_path = project_root / '.env'
    return env_path


def read_env_file() -> Dict[str, str]:
    """Read all variables from .env file, or from environment if .env doesn't exist."""
    env_path = get_env_file_path()
    env_vars = {}

    if not env_path.exists():
        # If .env doesn't exist, read from current environment variables
        # Get all variables we care about from our ENV_CATEGORIES
        for cat_data in ENV_CATEGORIES.values():
            for var_config in cat_data['variables']:
                key = var_config['key']
                value = os.environ.get(key, '')
                if value:
                    env_vars[key] = value
        return env_vars

    # Read from .env file
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()

    return env_vars


def write_env_file(env_vars: Dict[str, str]) -> None:
    """Write variables to .env file, preserving comments."""
    env_path = get_env_file_path()

    # Read existing file to preserve comments
    existing_lines = []
    if env_path.exists():
        with open(env_path, 'r') as f:
            existing_lines = f.readlines()

    # Build new content
    new_lines = []
    processed_keys = set()

    for line in existing_lines:
        stripped = line.strip()

        # Preserve comments and empty lines
        if not stripped or stripped.startswith('#'):
            new_lines.append(line)
            continue

        # Update existing variable
        if '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in env_vars:
                new_lines.append(f"{key}={env_vars[key]}\n")
                processed_keys.add(key)
            else:
                # Keep line as-is if not in update dict
                new_lines.append(line)

    # Add new variables not in original file
    for key, value in env_vars.items():
        if key not in processed_keys:
            new_lines.append(f"{key}={value}\n")

    # Write back to file
    with open(env_path, 'w') as f:
        f.writelines(new_lines)


def register_environment_routes(app, logger):
    """Register environment settings routes."""
    
    # Register the blueprint with the app
    app.register_blueprint(environment_bp)
    logger.info("Environment routes registered")


# Route definitions

@environment_bp.route('/api/environment/categories')
@require_permission_or_setup_mode('system.view_config')
def get_environment_categories():
    """Get list of environment variable categories."""
    categories = []
    for cat_id, cat_data in ENV_CATEGORIES.items():
        categories.append({
            'id': cat_id,
            'name': cat_data['name'],
            'icon': cat_data['icon'],
            'description': cat_data['description'],
            'variable_count': len(cat_data['variables']),
        })
    return jsonify(categories)

@environment_bp.route('/api/environment/variables')
@require_permission_or_setup_mode('system.view_config')
def get_environment_variables():
    """Get all environment variables with current values."""
    # Read current values from .env or environment
    current_values = read_env_file()

    # Check if .env file exists
    env_path = get_env_file_path()
    env_file_exists = env_path.exists()

    # Build response with categories and variables
    response = {}
    for cat_id, cat_data in ENV_CATEGORIES.items():
        variables = []
        for var_config in cat_data['variables']:
            var_data = dict(var_config)
            key = var_config['key']

            # Get current value - respect explicit empty values in .env
            if key in current_values:
                # Key exists in .env file (even if empty)
                current_value = current_values[key]
            else:
                # Key not in .env, try environment variable then default
                current_value = os.environ.get(key, var_config.get('default', ''))

            # Mask sensitive values
            if var_config.get('sensitive') and current_value:
                var_data['value'] = '••••••••'
                var_data['has_value'] = True
            else:
                var_data['value'] = current_value
                # has_value is True if key exists in .env or has non-empty value
                var_data['has_value'] = (key in current_values) or bool(current_value)

            variables.append(var_data)

        response[cat_id] = {
            'name': cat_data['name'],
            'icon': cat_data['icon'],
            'description': cat_data['description'],
            'variables': variables,
        }

    # Add metadata about .env file status
    response['_meta'] = {
        'env_file_exists': env_file_exists,
        'env_file_path': str(env_path),
        'reading_from': 'env_file' if env_file_exists else 'environment',
    }

    return jsonify(response)

@environment_bp.route('/api/environment/variables', methods=['PUT'])
@require_permission_or_setup_mode('system.configure')
def update_environment_variables():
    """Update environment variables."""
    try:
        data = request.get_json()
        if not data or 'variables' not in data:
            raise BadRequest('Missing variables in request')

        # Read current .env
        env_vars = read_env_file()
        
        logger.info(f'Updating environment variables: {list(data["variables"].keys())}')

        # Update variables
        updates = data['variables']
        for key, value in updates.items():
            # Validate key exists in our configuration
            found = False
            for cat_data in ENV_CATEGORIES.values():
                for var_config in cat_data['variables']:
                    if var_config['key'] == key:
                        found = True
                        logger.debug(f'Found variable {key} in category configuration')

                        # Don't update if it's a masked sensitive value
                        if var_config.get('sensitive') and value == '••••••••':
                            logger.debug(f'Skipping masked sensitive value for {key}')
                            continue

                        # Validate required fields
                        if var_config.get('required') and not value:
                            raise BadRequest(f'{key} is required')

                        break
                if found:
                    break

            if not found:
                logger.error(f'Unknown variable attempted to be updated: {key}')
                raise BadRequest(f'Unknown variable: {key}')

            if key == 'EAS_GPIO_PIN':
                _validate_reserved_pin(key, value)
            elif key == 'GPIO_ADDITIONAL_PINS':
                _validate_reserved_pin_collection(key, value)
            elif key == 'GPIO_PIN_BEHAVIOR_MATRIX':
                _validate_behavior_matrix_reserved(value)

            # Update value
            old_value = env_vars.get(key, '')
            env_vars[key] = str(value)
            logger.debug(f'Updated {key}: {len(old_value)} chars -> {len(str(value))} chars')

        # Auto-populate zone codes from FIPS codes if zone codes are empty
        fips_codes_raw = env_vars.get("EAS_MANUAL_FIPS_CODES", "").strip()
        zone_codes_raw = env_vars.get("DEFAULT_ZONE_CODES", "").strip()

        if fips_codes_raw and not zone_codes_raw:
            try:
                # Parse FIPS codes (comma-separated)
                fips_list = [code.strip() for code in fips_codes_raw.split(",") if code.strip()]

                # Derive zone codes from FIPS
                derived_zones = _derive_county_zone_codes_from_fips(fips_list)

                if derived_zones:
                    env_vars["DEFAULT_ZONE_CODES"] = ",".join(derived_zones)
                    logger.info(f"Auto-derived {len(derived_zones)} zone codes from {len(fips_list)} FIPS codes")
            except Exception as zone_exc:
                logger.warning(f"Failed to auto-derive zone codes from FIPS: {zone_exc}")

        # Write to .env file
        env_path = get_env_file_path()
        logger.info(f'Writing environment variables to {env_path}')
        write_env_file(env_vars)
        logger.info(f'Successfully updated {len(updates)} environment variables and wrote to {env_path}')

        return jsonify({
            'success': True,
            'message': f'Updated {len(updates)} environment variable(s). Restart required for changes to take effect.',
            'restart_required': True,
            'saved_variables': list(updates.keys()),
        })

    except BadRequest as e:
        logger.warning(f'Bad request updating environment variables: {e}')
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Error updating environment variables: {e}', exc_info=True)
        return jsonify({'error': f'Failed to update environment variables: {str(e)}'}), 500

@environment_bp.route('/api/environment/validate')
@require_permission_or_setup_mode('system.view_config')
def validate_environment():
    """Validate current environment configuration."""
    env_vars = read_env_file()
    issues = []
    warnings = []

    # Check if .env file exists
    env_path = get_env_file_path()
    if not env_path.exists():
        warnings.append({
            'severity': 'warning',
            'variable': '.env file',
            'message': f'.env file does not exist at {env_path}. Reading from environment variables. Create .env file to persist changes.',
        })

    # Check required variables
    for cat_data in ENV_CATEGORIES.values():
        for var_config in cat_data['variables']:
            key = var_config['key']

            # Get value - respect explicit empty values in .env
            if key in env_vars:
                value = env_vars[key]
            else:
                # Key not in .env, check environment variable
                value = os.environ.get(key, '')

            # Required field validation
            if var_config.get('required') and not value:
                issues.append({
                    'severity': 'error',
                    'variable': key,
                    'message': f'{var_config["label"]} is required but not set',
                })

            # Check for default/insecure values
            if key == 'SECRET_KEY' and value in ['', 'dev-key-change-in-production', 'replace-with-a-long-random-string']:
                issues.append({
                    'severity': 'error',
                    'variable': key,
                    'message': 'SECRET_KEY must be changed from default value',
                })

            if key == 'POSTGRES_PASSWORD' and value in ['', 'change-me', 'postgres']:
                warnings.append({
                    'severity': 'warning',
                    'variable': key,
                    'message': 'Database password should be changed from default',
                })

    # Check for deprecated variables
    deprecated_vars = [
        'PATH', 'LANG', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256',
        'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED', 'SKIP_DB_INIT',
        'EAS_OUTPUT_WEB_SUBDIR',
    ]

    for var in deprecated_vars:
        if var in env_vars:
            warnings.append({
                'severity': 'info',
                'variable': var,
                'message': f'{var} is deprecated and can be removed',
            })

    return jsonify({
        'valid': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
    })

@environment_bp.route('/settings/environment')
@require_permission_or_setup_mode('system.view_config')
def environment_settings():
    """Render environment settings management page."""
    from app_core.auth.roles import has_permission

    try:
        location_settings = get_location_settings()
    except Exception as exc:
        logger.warning(f'Failed to load location settings (database may be unavailable): {exc}')
        location_settings = None
    
    try:
        can_configure = has_permission('system.configure')
    except Exception as exc:
        # During setup mode or database failure, allow configuration
        logger.debug(f'Permission check failed (expected during setup mode): {exc}')
        can_configure = current_app.config.get('SETUP_MODE', False)
    
    return render_template(
        'settings/environment.html',
        location_settings=location_settings,
        can_configure=can_configure,
    )

@environment_bp.route('/admin/environment/download-env')
@require_permission_or_setup_mode('system.view_config')
def admin_download_env():
    """Download the current .env file as a backup."""
    from flask import send_file
    from datetime import datetime

    env_path = get_env_file_path()

    if not env_path.exists():
        flash("No .env file exists to download.")
        return redirect(url_for("environment_settings"))

    # Create a timestamped filename for the download
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    download_name = f"eas-station-backup-{timestamp}.env"

    return send_file(
        env_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='text/plain'
    )

@environment_bp.route('/api/environment/generate-secret', methods=['POST'])
@require_permission_or_setup_mode('system.configure')
def generate_secret_key_api():
    """Generate a new secret key."""
    import secrets
    secret_key = secrets.token_hex(32)  # 64-character hex string
    return jsonify({'secret_key': secret_key})

@environment_bp.route('/admin/environment/download-ssl-cert')
@require_permission('system.view_config')
def admin_download_ssl_cert():
    """Download the SSL certificate file (fullchain.pem) for use in Portainer or other deployments.
    
    WARNING: This exposes the SSL certificate, which while public, should be handled carefully.
    """
    from flask import send_file
    from datetime import datetime

    cert_path, attempted_paths, resolved_domain = _find_ssl_material('fullchain.pem')

    if not cert_path:
        logger.warning('SSL certificate not found at expected locations', extra={
            'attempted_paths': [str(path) for path in attempted_paths],
        })

        domain_candidates = _get_domain_candidates()
        domain_hint = domain_candidates[0]
        if domain_hint == 'localhost':
            guidance = (
                'The system is configured for localhost. SSL certificates are only available '
                'when using a real domain with Let\'s Encrypt.'
            )
        else:
            guidance = 'Please ensure certbot has successfully obtained a certificate for your domain.'

        detail_lines = '\n'.join(str(path) for path in attempted_paths)
        error_message = (
            'SSL certificate could not be located.\n'
            'Checked the following locations:\n'
            f'{detail_lines}\n'
            f'{guidance}'
        )

        return render_template(
            'error.html',
            error='SSL Certificate Not Found',
            details=error_message,
        ), 404

    # Create a timestamped filename for the download
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    domain_label = resolved_domain or _get_domain_candidates()[0]
    download_name = f"{domain_label}-fullchain-{timestamp}.pem"

    logger.info('Downloading SSL certificate', extra={'domain': domain_label, 'path': str(cert_path)})

    return send_file(
        cert_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/x-pem-file'
    )

@environment_bp.route('/admin/environment/download-ssl-key')
@require_permission('system.view_config')
def admin_download_ssl_key():
    """Download the SSL private key file (privkey.pem) for use in Portainer or other deployments.
    
    WARNING: This is a SECURITY SENSITIVE operation. The private key should be kept secure
    and only downloaded when absolutely necessary for deployment purposes.
    """
    from flask import send_file
    from datetime import datetime

    key_path, attempted_paths, resolved_domain = _find_ssl_material('privkey.pem')

    if not key_path:
        logger.warning('SSL private key not found at expected locations', extra={
            'attempted_paths': [str(path) for path in attempted_paths],
        })

        domain_candidates = _get_domain_candidates()
        domain_hint = domain_candidates[0]
        if domain_hint == 'localhost':
            guidance = (
                'The system is configured for localhost. SSL certificates and keys are only available '
                'when using a real domain with Let\'s Encrypt.'
            )
        else:
            guidance = 'Please ensure certbot has successfully obtained a certificate for your domain.'

        detail_lines = '\n'.join(str(path) for path in attempted_paths)
        error_message = (
            'SSL private key could not be located.\n'
            'Checked the following locations:\n'
            f'{detail_lines}\n'
            f'{guidance}'
        )

        return render_template(
            'error.html',
            error='SSL Private Key Not Found',
            details=error_message,
        ), 404

    # Create a timestamped filename for the download
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    domain_label = resolved_domain or _get_domain_candidates()[0]
    download_name = f"{domain_label}-privkey-{timestamp}.pem"

    logger.warning('SECURITY: SSL private key downloaded', extra={'domain': domain_label, 'path': str(key_path)})

    return send_file(
        key_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/x-pem-file'
    )


__all__ = ['register_environment_routes', 'ENV_CATEGORIES']
