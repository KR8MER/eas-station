"""Environment settings management routes."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List
from pathlib import Path

from flask import jsonify, render_template, request
from werkzeug.exceptions import BadRequest

from app_core.location import get_location_settings, _derive_county_zone_codes_from_fips
from app_core.auth.roles import require_permission


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
                'type': 'boolean',
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
                'default': 'host.docker.internal',
                'description': 'Database server hostname or IP',
            },
            {
                'key': 'POSTGRES_PORT',
                'label': 'Port',
                'type': 'number',
                'default': '5432',
                'description': 'Database server port',
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
                'key': 'DEFAULT_AREA_TERMS',
                'label': 'Area Search Terms',
                'type': 'textarea',
                'description': 'Comma-separated location names to match in alerts',
                'placeholder': 'PUTNAM COUNTY,PUTNAM CO,OTTAWA',
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
                'type': 'boolean',
                'default': 'false',
                'description': 'Enable SAME/EAS audio generation',
            },
            {
                'key': 'EAS_ORIGINATOR',
                'label': 'Originator Code',
                'type': 'text',
                'default': 'WXR',
                'description': 'EAS originator code (e.g., WXR, EAS, PEP)',
                'maxlength': 3,
            },
            {
                'key': 'EAS_STATION_ID',
                'label': 'Station ID',
                'type': 'text',
                'default': 'EASNODES',
                'description': 'Your station callsign or identifier',
                'maxlength': 8,
            },
            {
                'key': 'EAS_OUTPUT_DIR',
                'label': 'Output Directory',
                'type': 'text',
                'default': 'static/eas_messages',
                'description': 'Directory for generated EAS audio files',
            },
            {
                'key': 'EAS_ATTENTION_TONE_SECONDS',
                'label': 'Attention Tone Duration',
                'type': 'number',
                'default': '8',
                'description': 'Attention tone length in seconds',
                'min': 1,
                'max': 60,
            },
            {
                'key': 'EAS_SAMPLE_RATE',
                'label': 'Audio Sample Rate',
                'type': 'select',
                'options': ['8000', '16000', '22050', '44100', '48000'],
                'default': '44100',
                'description': 'Audio sample rate in Hz',
            },
            {
                'key': 'EAS_AUDIO_PLAYER',
                'label': 'Audio Player Command',
                'type': 'text',
                'default': 'aplay',
                'description': 'Command to play audio files',
            },
            {
                'key': 'EAS_MANUAL_FIPS_CODES',
                'label': 'Authorized FIPS Codes',
                'type': 'textarea',
                'description': 'Comma-separated FIPS codes for manual broadcasts',
                'placeholder': '039137,039003',
            },
            {
                'key': 'EAS_MANUAL_EVENT_CODES',
                'label': 'Authorized Event Codes',
                'type': 'textarea',
                'description': 'Comma-separated event codes for manual broadcasts',
                'placeholder': 'RWT,DMO,SVR',
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
                'label': 'GPIO Pin',
                'type': 'number',
                'description': 'GPIO pin number for relay control (leave empty to disable)',
                'placeholder': 'e.g., 17',
            },
            {
                'key': 'EAS_GPIO_ACTIVE_STATE',
                'label': 'Active State',
                'type': 'select',
                'options': ['HIGH', 'LOW'],
                'default': 'HIGH',
                'description': 'GPIO active state',
            },
            {
                'key': 'EAS_GPIO_HOLD_SECONDS',
                'label': 'Hold Duration (seconds)',
                'type': 'number',
                'default': '5',
                'description': 'How long to activate GPIO relay',
                'min': 1,
                'max': 300,
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
                'description': 'IP address of LED sign (leave empty to disable)',
                'placeholder': '192.168.1.100',
            },
            {
                'key': 'LED_SIGN_PORT',
                'label': 'LED Sign Port',
                'type': 'number',
                'default': '10001',
                'description': 'TCP port for LED sign',
            },
            {
                'key': 'DEFAULT_LED_LINES',
                'label': 'Default LED Text',
                'type': 'textarea',
                'description': 'Comma-separated lines for idle display',
                'placeholder': 'PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY',
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
                'description': 'Serial port for VFD (leave empty to disable)',
                'placeholder': '/dev/ttyUSB0',
            },
            {
                'key': 'VFD_BAUDRATE',
                'label': 'Baud Rate',
                'type': 'select',
                'options': ['9600', '19200', '38400', '57600', '115200'],
                'default': '38400',
                'description': 'Serial communication speed',
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
                'type': 'boolean',
                'default': 'false',
                'description': 'Send email alerts for new notifications',
            },
            {
                'key': 'ENABLE_SMS_NOTIFICATIONS',
                'label': 'Enable SMS Notifications',
                'type': 'boolean',
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
            },
            {
                'key': 'MAIL_USE_TLS',
                'label': 'Use TLS',
                'type': 'boolean',
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
                'label': 'Max Worker Threads',
                'type': 'number',
                'default': '2',
                'description': 'Number of worker threads for background tasks',
                'min': 1,
                'max': 16,
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
                'type': 'boolean',
                'default': 'true',
                'description': 'Enable automatic updates via Watchtower',
            },
            {
                'key': 'WATCHTOWER_MONITOR_ONLY',
                'label': 'Monitor Only Mode',
                'type': 'boolean',
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
    """Register environment settings management routes."""

    @app.route('/api/environment/categories')
    @require_permission('system.view_config')
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

    @app.route('/api/environment/variables')
    @require_permission('system.view_config')
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

    @app.route('/api/environment/variables', methods=['PUT'])
    @require_permission('system.configure')
    def update_environment_variables():
        """Update environment variables."""
        try:
            data = request.get_json()
            if not data or 'variables' not in data:
                raise BadRequest('Missing variables in request')

            # Read current .env
            env_vars = read_env_file()

            # Update variables
            updates = data['variables']
            for key, value in updates.items():
                # Validate key exists in our configuration
                found = False
                for cat_data in ENV_CATEGORIES.values():
                    for var_config in cat_data['variables']:
                        if var_config['key'] == key:
                            found = True

                            # Don't update if it's a masked sensitive value
                            if var_config.get('sensitive') and value == '••••••••':
                                continue

                            # Validate required fields
                            if var_config.get('required') and not value:
                                raise BadRequest(f'{key} is required')

                            break
                    if found:
                        break

                if not found:
                    raise BadRequest(f'Unknown variable: {key}')

                # Update value
                env_vars[key] = str(value)

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
            write_env_file(env_vars)

            logger.info(f'Updated {len(updates)} environment variables')

            return jsonify({
                'success': True,
                'message': f'Updated {len(updates)} environment variable(s). Restart required for changes to take effect.',
                'restart_required': True,
            })

        except BadRequest as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f'Error updating environment variables: {e}')
            return jsonify({'error': 'Failed to update environment variables'}), 500

    @app.route('/api/environment/validate')
    @require_permission('system.view_config')
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

    @app.route('/settings/environment')
    @require_permission('system.view_config')
    def environment_settings():
        """Render environment settings management page."""
        from app_core.auth.roles import has_permission

        try:
            location_settings = get_location_settings()
            can_configure = has_permission('system.configure')
            return render_template(
                'settings/environment.html',
                location_settings=location_settings,
                can_configure=can_configure,
            )
        except Exception as exc:
            logger.error(f'Error rendering environment settings: {exc}')
            return render_template(
                'settings/environment.html',
                location_settings=None,
                can_configure=False,
            )

    @app.route('/admin/environment/download-env')
    @require_permission('system.view_config')
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


__all__ = ['register_environment_routes', 'ENV_CATEGORIES']
