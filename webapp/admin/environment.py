"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
import subprocess
from functools import wraps
from typing import Any, Dict, List
from pathlib import Path

from flask import Blueprint, flash, jsonify, redirect, render_template, request, current_app, url_for
from werkzeug.exceptions import BadRequest

from app_core.location import get_location_settings
from app_core.auth.roles import require_permission

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




def _find_ssl_material(filename: str) -> tuple[Path | None, List[Path], str | None]:
    """Search for SSL certificate/key material across supported locations."""

    search_roots = [
        Path('/etc/letsencrypt/live'),
        # For bare metal: use project directory for certs
        Path(__file__).parent.parent.parent / 'certs' / 'live',
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


# Bootstrap environment variable categories.
# Only settings that are required before the database connection is
# available are managed here.  Everything else is now configured through
# dedicated admin pages backed by database tables:
#   - Alert Polling  → /admin/poller
#   - Notifications  → /admin/notifications
#   - App Settings   → /admin/application
#   - EAS Broadcast  → /admin/eas (EASSettings table)
#   - Hardware       → /admin/hardware (HardwareSettings table)
#   - Icecast        → /admin/icecast (IcecastSettings table)
#   - TTS            → /admin/tts (TTSSettings table)
ENV_CATEGORIES = {
    'core': {
        'name': 'Core Settings',
        'icon': 'fa-cog',
        'description': 'Essential application bootstrap configuration',
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
        ],
    },
    'database': {
        'name': 'Database',
        'icon': 'fa-database',
        'description': 'PostgreSQL connection settings',
        'variables': [
            {
                'key': 'DATABASE_URL',
                'label': 'Database Connection URL',
                'type': 'text',
                'required': True,
                'description': 'Complete PostgreSQL connection URL. Format: postgresql://user:password@host:port/database',
                'placeholder': 'postgresql+psycopg2://eas_station:password@127.0.0.1:5432/alerts',
                'default': 'postgresql+psycopg2://eas_station:change-me@127.0.0.1:5432/alerts',
            },
        ],
    },
    'redis': {
        'name': 'Redis Cache',
        'icon': 'fa-bolt',
        'description': 'Redis connection and caching configuration',
        'variables': [
            {
                'key': 'CACHE_REDIS_URL',
                'label': 'Redis Connection URL',
                'type': 'text',
                'required': True,
                'default': 'redis://localhost:6379/0',
                'description': 'Complete Redis connection URL. Format: redis://[password@]host:port/db',
                'placeholder': 'redis://:password@localhost:6379/0',
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


def _unquote_env_value(value: str) -> str:
    """Remove quotes from environment variable value if present.
    
    Handles single quotes, double quotes, and unquoted values.
    This is needed because systemd EnvironmentFile requires JSON values to be quoted.
    """
    value = value.strip()
    if len(value) >= 2:
        if (value.startswith("'") and value.endswith("'")) or \
           (value.startswith('"') and value.endswith('"')):
            return value[1:-1]
    return value


def _quote_env_value(value: str) -> str:
    """Add quotes to environment variable value if needed.
    
    JSON objects and values containing special characters need to be quoted
    for systemd EnvironmentFile compatibility.
    """
    value = str(value)
    stripped_value = value.strip()
    
    # Check if value looks like JSON (starts with { or [)
    if stripped_value.startswith(('{', '[')):
        # Use single quotes to avoid escaping issues with JSON's double quotes
        return f"'{value}'"
    
    # Check if value contains spaces, quotes, or other special characters
    special_chars = (' ', '"', "'", '$', '`', '\\')
    if any(char in value for char in special_chars):
        # Prefer double quotes if value contains single quotes but no double quotes
        # Otherwise use single quotes (less escaping needed for most cases)
        if "'" in value and '"' not in value:
            return f'"{value}"'
        else:
            return f"'{value}'"
    
    return value


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
                # Unquote the value to get the actual content
                env_vars[key.strip()] = _unquote_env_value(value)

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
                # Quote the value if needed for systemd compatibility
                quoted_value = _quote_env_value(env_vars[key])
                new_lines.append(f"{key}={quoted_value}\n")
                processed_keys.add(key)
            else:
                # Keep line as-is if not in update dict
                new_lines.append(line)

    # Add new variables not in original file
    for key, value in env_vars.items():
        if key not in processed_keys:
            # Quote the value if needed for systemd compatibility
            quoted_value = _quote_env_value(value)
            new_lines.append(f"{key}={quoted_value}\n")

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
                # For JSON type with json_schema, mask individual sensitive fields
                if var_config.get('type') == 'json' and var_config.get('json_schema'):
                    try:
                        json_obj = json.loads(current_value)
                        # Mask password fields in the JSON
                        for field_key, field_def in var_config.get('json_schema', {}).items():
                            if field_def.get('type') == 'password' and json_obj.get(field_key):
                                json_obj[field_key] = '••••••••'
                        var_data['value'] = json.dumps(json_obj)
                        var_data['has_value'] = True
                    except (json.JSONDecodeError, TypeError):
                        # If JSON parsing fails, fall back to masking entire value
                        var_data['value'] = '••••••••'
                        var_data['has_value'] = True
                else:
                    # For non-JSON sensitive fields, mask the entire value
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
                        if var_config.get('sensitive'):
                            # For JSON fields with password subfields, unmask them
                            if var_config.get('type') == 'json' and var_config.get('json_schema') and value:
                                try:
                                    new_json = json.loads(value)
                                    # Get current value to preserve masked password fields
                                    current_value = env_vars.get(key, '')
                                    if current_value:
                                        try:
                                            current_json = json.loads(current_value)
                                            # Check each password field
                                            for field_key, field_def in var_config.get('json_schema', {}).items():
                                                if field_def.get('type') == 'password':
                                                    # If new value is masked, preserve current value
                                                    if new_json.get(field_key) == '••••••••' and current_json.get(field_key):
                                                        new_json[field_key] = current_json[field_key]
                                                        logger.debug(f'Preserved masked password field {field_key} in {key}')
                                            value = json.dumps(new_json)
                                        except (json.JSONDecodeError, TypeError):
                                            logger.warning(f'Could not parse current JSON value for {key}')
                                except (json.JSONDecodeError, TypeError):
                                    logger.warning(f'Could not parse new JSON value for {key}')
                            elif value == '••••••••':
                                # Non-JSON masked value - skip update
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

            # Update value
            old_value = env_vars.get(key, '')
            env_vars[key] = str(value)
            logger.debug(f'Updated {key}: {len(old_value)} chars -> {len(str(value))} chars')

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
                # Key not in .env, check environment variable, then default
                value = os.environ.get(key, var_config.get('default', ''))

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

    # Check for deprecated/migrated variables that can now be removed from .env
    deprecated_vars = [
        'PATH', 'LANG', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256',
        'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED', 'SKIP_DB_INIT',
        'EAS_OUTPUT_WEB_SUBDIR',
    ]
    migrated_vars = [
        # Polling settings → /admin/poller (poller_settings table)
        'POLL_INTERVAL_SEC', 'CAP_TIMEOUT', 'NOAA_USER_AGENT',
        'CAP_ENDPOINTS', 'IPAWS_CAP_FEED_URLS', 'IPAWS_DEFAULT_LOOKBACK_HOURS',
        # EAS broadcast settings → /admin/eas (eas_settings table)
        'EAS_BROADCAST_ENABLED', 'EAS_ORIGINATOR', 'EAS_STATION_ID',
        'EAS_OUTPUT_DIR', 'EAS_ATTENTION_TONE_SECONDS', 'EAS_SAMPLE_RATE',
        'EAS_AUDIO_PLAYER', 'EAS_MANUAL_EVENT_CODES',
        # Notification settings → /admin/notifications (notification_settings table)
        'ENABLE_EMAIL_NOTIFICATIONS', 'ENABLE_SMS_NOTIFICATIONS', 'MAIL_URL',
        'MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_USE_TLS',
        'COMPLIANCE_ALERT_EMAILS',
        # Application settings → /admin/application (application_settings table)
        'LOG_LEVEL', 'LOG_FILE', 'UPLOAD_FOLDER',
    ]

    for var in deprecated_vars:
        if var in env_vars:
            warnings.append({
                'severity': 'info',
                'variable': var,
                'message': f'{var} is deprecated and can be removed',
            })

    for var in migrated_vars:
        if var in env_vars:
            warnings.append({
                'severity': 'info',
                'variable': var,
                'message': (
                    f'{var} has been migrated to the database and can be removed from .env. '
                    'Configure it via the appropriate admin page instead.'
                ),
            })

    return jsonify({
        'valid': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
    })

@environment_bp.route('/admin/environment')
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
        'admin/environment.html',
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
        return redirect(url_for("environment.environment_settings"))

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


@environment_bp.route('/api/environment/restart-services', methods=['POST'])
@require_permission_or_setup_mode('system.configure')
def restart_services():
    """
    Restart EAS Station services after configuration changes.
    
    This endpoint allows restarting specific services or the entire stack
    without requiring CLI access.
    """
    # Whitelist of allowed service names for security
    ALLOWED_SERVICES = {
        'all': 'eas-station.target',
        'hardware': 'eas-station-hardware.service',
        'web': 'eas-station-web.service',
        'poller': 'eas-station-poller.service',
        'sdr': 'eas-station-sdr.service',
        'audio': 'eas-station-audio.service',
    }
    
    try:
        data = request.get_json() or {}
        service = data.get('service', 'all')
        
        # Validate service name against whitelist
        if service not in ALLOWED_SERVICES:
            valid_options = ', '.join(ALLOWED_SERVICES.keys())
            return jsonify({
                'success': False,
                'error': f'Invalid service: {service}. Valid options: {valid_options}'
            }), 400
        
        # Get the actual systemd service name from whitelist
        systemd_service = ALLOWED_SERVICES[service]
        services_to_restart = [systemd_service]
        
        restart_results = []
        all_successful = True
        
        for svc_name in services_to_restart:
            try:
                logger.info(f"Restarting service: {svc_name}")
                # Use list for subprocess to prevent command injection
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', svc_name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    restart_results.append({
                        'service': svc_name,
                        'success': True,
                        'message': f'Service {svc_name} restarted successfully'
                    })
                    logger.info(f"Successfully restarted {svc_name}")
                else:
                    restart_results.append({
                        'service': svc_name,
                        'success': False,
                        'message': f'Failed to restart {svc_name}',
                        'error': result.stderr
                    })
                    all_successful = False
                    logger.error(f"Failed to restart {svc_name}: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                restart_results.append({
                    'service': svc_name,
                    'success': False,
                    'message': f'Restart timeout for {svc_name}',
                    'error': 'Command timed out after 30 seconds'
                })
                all_successful = False
                logger.error(f"Restart timeout for {svc_name}")
            except Exception as svc_exc:
                restart_results.append({
                    'service': svc_name,
                    'success': False,
                    'message': f'Error restarting {svc_name}',
                    'error': str(svc_exc)
                })
                all_successful = False
                logger.error(f"Error restarting {svc_name}: {svc_exc}")
        
        return jsonify({
            'success': all_successful,
            'message': 'All services restarted successfully' if all_successful else 'Some services failed to restart',
            'results': restart_results
        })
        
    except Exception as e:
        logger.error(f"Error in restart-services endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Failed to restart services: {str(e)}'
        }), 500


__all__ = ['register_environment_routes', 'ENV_CATEGORIES']
