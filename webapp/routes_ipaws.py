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

"""IPAWS feed configuration routes."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, render_template, request
from werkzeug.exceptions import BadRequest

from dotenv import dotenv_values

from app_core.auth.roles import require_permission
from app_core.models import db, PollHistory
from app_utils.alert_sources import ALERT_SOURCE_IPAWS

logger = logging.getLogger(__name__)

# Create Blueprint for IPAWS routes
ipaws_bp = Blueprint('ipaws', __name__)


# IPAWS feed presets
IPAWS_FEED_TYPES = {
    'public': {
        'name': 'PUBLIC (All Alerts)',
        'description': 'All alerts including EAS, WEA, NWEM, and other valid alerts',
        'path': '/rest/public/recent/{timestamp}'
    },
    'eas': {
        'name': 'EAS Only',
        'description': 'Alerts valid for Emergency Alert System dissemination',
        'path': '/rest/eas/recent/{timestamp}'
    },
    'wea': {
        'name': 'WEA Only',
        'description': 'Alerts valid for Wireless Emergency Alerts dissemination',
        'path': '/rest/PublicWEA/recent/{timestamp}'
    },
    'nwem': {
        'name': 'NWEM Only',
        'description': 'Non-Weather Emergency Messages for NOAA Weather Radio',
        'path': '/rest/nwem/recent/{timestamp}'
    },
    'public_non_eas': {
        'name': 'PUBLIC (Non-EAS)',
        'description': 'Public alerts excluding EAS dissemination path',
        'path': '/rest/public_non_eas/recent/{timestamp}'
    }
}

IPAWS_ENVIRONMENTS = {
    'staging': {
        'name': 'Staging (TDL)',
        'description': 'Test environment for development and QA',
        'base_url': 'https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE',
        'badge': 'TEST'
    },
    'production': {
        'name': 'Production',
        'description': 'Live production environment with real alerts',
        'base_url': 'https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE',
        'badge': 'LIVE'
    }
}


def _get_config_path() -> Path:
    """Get the path to the master persistent config file.

    All services (web, NOAA poller, IPAWS poller) share the same configuration
    file for consistency. The CONFIG_PATH environment variable can override the
    default location.
    
    For bare metal installations, defaults to project directory .env file.
    For Docker/container deployments, set CONFIG_PATH=/app-config/.env.
    
    IMPORTANT: If CONFIG_PATH points to a non-existent or non-writable location,
    this function will automatically fall back to the project directory .env file
    to prevent "Read-only file system" errors.
    """
    # Get project root directory (fallback path)
    project_root = Path(__file__).parent.parent
    project_env = project_root / '.env'
    
    # Check for explicit override via CONFIG_PATH environment variable
    config_path_env = os.environ.get('CONFIG_PATH', '').strip()
    if config_path_env:
        config_path = Path(config_path_env)
        
        # Validate that the override path is actually usable
        # Check if parent directory exists and is writable
        parent_dir = config_path.parent
        
        if not parent_dir.exists():
            logger.warning(
                f"CONFIG_PATH parent directory does not exist: {parent_dir}. "
                f"Falling back to project directory: {project_env}"
            )
            return project_env
        
        if not os.access(parent_dir, os.W_OK):
            logger.warning(
                f"CONFIG_PATH parent directory is not writable: {parent_dir}. "
                f"Falling back to project directory: {project_env}"
            )
            return project_env
        
        # CONFIG_PATH is valid and writable
        logger.debug(f"Using CONFIG_PATH: {config_path}")
        return config_path

    # Default to project directory .env file (bare metal installation)
    logger.debug(f"Using default config path: {project_env}")
    return project_env


def _read_current_config() -> Dict[str, str]:
    """Read current IPAWS configuration from .env file.
    
    Configuration Priority:
    1. Runtime environment variables (highest priority - from systemd service files)
    2. .env file values (persistent configuration)
    
    When environment variables are set (e.g., in systemd service files), they take
    precedence over .env file values. This ensures the UI shows what's actually
    running, but may cause confusion when updating settings.
    
    Returns a dict with configuration values and optional '_source' metadata.
    """
    config_path = _get_config_path()
    config: Dict[str, str] = {}
    config_sources: Dict[str, str] = {}  # Track where each value came from

    # First, attempt to load from the persistent config file (if it exists)
    if config_path.exists():
        try:
            file_values = dotenv_values(config_path)
            for k, v in file_values.items():
                if v is not None:
                    config[k] = v
                    config_sources[k] = 'file'
        except Exception as exc:
            logger.error(f"Failed to read config file {config_path}: {exc}")

    # Always merge runtime environment variables so the UI reflects the
    # active configuration even if the persistent file is missing or empty.
    # Environment variables should take precedence because they are what
    # the running services are using at runtime.
    for key in (
        'IPAWS_CAP_FEED_URLS',
        'POLL_INTERVAL_SEC',
        'NOAA_USER_AGENT',
        'CAP_ENDPOINTS',
    ):
        env_value = os.environ.get(key, '').strip()
        if env_value:
            config[key] = env_value
            config_sources[key] = 'environment'
    
    # Add source metadata for debugging (prefixed with _ to avoid conflicts)
    config['_sources'] = config_sources
    config['_config_path'] = str(config_path)

    return config


def _parse_ipaws_url(url: str) -> Dict[str, Optional[str]]:
    """Parse an IPAWS URL to extract environment and feed type."""
    if not url:
        return {'environment': None, 'feed_type': None}

    # Detect environment
    if 'tdl.apps.fema.gov' in url:
        environment = 'staging'
    elif 'apps.fema.gov' in url:
        environment = 'production'
    else:
        return {'environment': None, 'feed_type': None}

    # Detect feed type
    feed_type = None
    for ft_key, ft_data in IPAWS_FEED_TYPES.items():
        path = ft_data['path'].replace('{timestamp}', '')
        if path.strip('/') in url:
            feed_type = ft_key
            break

    return {'environment': environment, 'feed_type': feed_type}


def _get_ipaws_status() -> Dict:
    """Get current IPAWS poller status and configuration."""
    config = _read_current_config()
    ipaws_url = config.get('IPAWS_CAP_FEED_URLS', '').strip()
    poll_interval = config.get('POLL_INTERVAL_SEC', '120')

    parsed = _parse_ipaws_url(ipaws_url)

    # Get last poll info from database
    last_poll = db.session.query(PollHistory).filter(
        PollHistory.data_source.contains(ALERT_SOURCE_IPAWS)
    ).order_by(PollHistory.timestamp.desc()).first()

    status = {
        'configured': bool(ipaws_url),
        'url': ipaws_url,
        'environment': parsed['environment'],
        'feed_type': parsed['feed_type'],
        'poll_interval': poll_interval,
        'last_poll': None,
        'last_poll_status': None,
        'last_poll_alerts': 0,
        'last_poll_error': None
    }

    if last_poll:
        status['last_poll'] = last_poll.timestamp
        status['last_poll_status'] = last_poll.status
        status['last_poll_alerts'] = last_poll.alerts_new or 0
        status['last_poll_error'] = last_poll.error_message

    return status


def _update_env_file(key: str, value: str) -> None:
    """Update a single key in the .env file.
    
    Raises:
        PermissionError: If the config file or directory is not writable
        IOError: If there's an error reading or writing the file
    """
    config_path = _get_config_path()

    try:
        # Ensure parent directory exists and is writable
        if not config_path.parent.exists():
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as e:
                raise PermissionError(
                    f"Cannot create config directory {config_path.parent}: {e}. "
                    f"Please ensure the directory exists and is writable, or set CONFIG_PATH environment variable."
                ) from e
        
        # Check if parent directory is writable
        if not os.access(config_path.parent, os.W_OK):
            raise PermissionError(
                f"Config directory {config_path.parent} is not writable. "
                f"Please check permissions or set CONFIG_PATH to a writable location."
            )

        if not config_path.exists():
            # Create new file
            try:
                with open(config_path, 'w') as f:
                    f.write(f"{key}={value}\n")
                logger.info(f"Created new config file at {config_path}")
                return
            except (PermissionError, OSError) as e:
                raise PermissionError(
                    f"Cannot create config file {config_path}: {e}. "
                    f"Please check permissions or set CONFIG_PATH environment variable."
                ) from e

        # Read existing content
        lines = []
        key_found = False

        try:
            with open(config_path, 'r') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(f"{key}="):
                        lines.append(f"{key}={value}\n")
                        key_found = True
                    else:
                        lines.append(line)
        except (PermissionError, OSError) as e:
            raise IOError(f"Cannot read config file {config_path}: {e}") from e

        # Add key if it wasn't found
        if not key_found:
            lines.append(f"{key}={value}\n")

        # Write back
        try:
            with open(config_path, 'w') as f:
                f.writelines(lines)
            logger.info(f"Updated {key} in config file {config_path}")
        except (PermissionError, OSError) as e:
            raise PermissionError(
                f"Cannot write to config file {config_path}: {e}. "
                f"Please check permissions or set CONFIG_PATH environment variable."
            ) from e
    except Exception as e:
        # Log the error for debugging
        logger.error(f"Error updating config file: {e}")
        raise


def _restart_ipaws_poller() -> bool:
    """Restart the ipaws-poller systemd service."""
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'eas-station-ipaws-poller.service'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            logger.info("IPAWS poller restarted successfully")
            return True
        else:
            logger.error(f"Failed to restart IPAWS poller: {result.stderr}")
            return False
    except Exception as exc:
        logger.error(f"Error restarting IPAWS poller: {exc}")
        return False


def _get_noaa_status() -> Dict:
    """Get current NOAA poller status and configuration."""
    config = _read_current_config()

    noaa_user_agent = config.get('NOAA_USER_AGENT', '').strip()
    cap_endpoints = config.get('CAP_ENDPOINTS', '').strip()
    poll_interval = config.get('POLL_INTERVAL_SEC', '120')

    # Get last poll info from database
    from app_utils.alert_sources import ALERT_SOURCE_NOAA
    last_poll = db.session.query(PollHistory).filter(
        PollHistory.data_source.contains(ALERT_SOURCE_NOAA)
    ).order_by(PollHistory.timestamp.desc()).first()

    status = {
        'configured': bool(noaa_user_agent),
        'user_agent': noaa_user_agent,
        'poll_interval': poll_interval,
        'last_poll': None,
        'last_poll_status': None,
        'last_poll_alerts': 0,
        'last_poll_error': None
    }

    if last_poll:
        status['last_poll'] = last_poll.timestamp
        status['last_poll_status'] = last_poll.status
        status['last_poll_alerts'] = last_poll.alerts_new or 0
        status['last_poll_error'] = last_poll.error_message

    return status


def _get_custom_sources_status() -> Dict:
    """Get current custom sources configuration."""
    config = _read_current_config()
    return {
        'cap_endpoints': config.get('CAP_ENDPOINTS', '').strip(),
        'poll_interval': config.get('POLL_INTERVAL_SEC', '120')
    }


@ipaws_bp.route('/admin/alert-feeds')
@require_permission('system.view_config')
def alert_feeds_settings():
    """Render consolidated alert feeds configuration page."""
    try:
        ipaws_status = _get_ipaws_status()
        noaa_status = _get_noaa_status()
        custom_status = _get_custom_sources_status()

        return render_template(
            'admin/alert_feeds.html',
            ipaws_status=ipaws_status,
            noaa_status=noaa_status,
            custom_status=custom_status,
            environments=IPAWS_ENVIRONMENTS,
            feed_types=IPAWS_FEED_TYPES
        )
    except Exception as exc:
        logger.error(f"Error rendering alert feeds settings: {exc}")
        return f"Error loading alert feeds settings: {exc}", 500


# Redirect old URLs to new unified page
@ipaws_bp.route('/settings/ipaws')
@require_permission('system.view_config')
def ipaws_settings_redirect():
    """Redirect old IPAWS settings URL to new unified page."""
    from flask import redirect, url_for
    return redirect(url_for('ipaws.alert_feeds_settings'))

@ipaws_bp.route('/settings/alert-feeds')
@require_permission('system.view_config')
def alert_feeds_settings_redirect():
    """Redirect old alert feeds URL to new admin page."""
    from flask import redirect, url_for
    return redirect(url_for('ipaws.alert_feeds_settings'))


@ipaws_bp.route('/api/ipaws/status')
@require_permission('system.view_config')
def api_ipaws_status():
    """API endpoint to get current IPAWS status."""
    try:
        status = _get_ipaws_status()
        return jsonify(status)
    except Exception as exc:
        logger.error(f"Error getting IPAWS status: {exc}")
        return jsonify({'error': str(exc)}), 500


@ipaws_bp.route('/api/ipaws/configure', methods=['POST'])
@require_permission('system.configure')
def api_ipaws_configure():
    """API endpoint to configure IPAWS feed."""
    try:
        data = request.get_json()

        if not data:
            raise BadRequest("No data provided")

        environment = data.get('environment')
        feed_type = data.get('feed_type')
        poll_interval = data.get('poll_interval', '120')

        if not environment or environment not in IPAWS_ENVIRONMENTS:
            raise BadRequest("Invalid environment")

        if not feed_type or feed_type not in IPAWS_FEED_TYPES:
            raise BadRequest("Invalid feed type")

        # Validate poll interval
        try:
            interval_int = int(poll_interval)
            if interval_int < 30:
                raise BadRequest("Poll interval must be at least 30 seconds")
        except ValueError:
            raise BadRequest("Invalid poll interval")

        # Build URL
        base_url = IPAWS_ENVIRONMENTS[environment]['base_url']
        path = IPAWS_FEED_TYPES[feed_type]['path']
        full_url = f"{base_url}{path}"

        # Update config file
        _update_env_file('IPAWS_CAP_FEED_URLS', full_url)
        _update_env_file('POLL_INTERVAL_SEC', poll_interval)

        # Restart poller
        restart_success = _restart_ipaws_poller()

        return jsonify({
            'success': True,
            'url': full_url,
            'poll_interval': poll_interval,
            'poller_restarted': restart_success,
            'message': 'IPAWS configuration updated successfully' + (
                ' and poller restarted' if restart_success else ' (manual restart required)'
            )
        })

    except BadRequest as e:
        return jsonify({'error': str(e)}), 400
    except Exception as exc:
        logger.error(f"Error configuring IPAWS: {exc}")
        return jsonify({'error': str(exc)}), 500


@ipaws_bp.route('/api/ipaws/disable', methods=['POST'])
@require_permission('system.configure')
def api_ipaws_disable():
    """API endpoint to disable IPAWS feed."""
    try:
        _update_env_file('IPAWS_CAP_FEED_URLS', '')
        restart_success = _restart_ipaws_poller()

        return jsonify({
            'success': True,
            'poller_restarted': restart_success,
            'message': 'IPAWS feed disabled' + (
                ' and poller restarted' if restart_success else ' (manual restart required)'
            )
        })
    except Exception as exc:
        logger.error(f"Error disabling IPAWS: {exc}")
        return jsonify({'error': str(exc)}), 500


@ipaws_bp.route('/api/noaa/configure', methods=['POST'])
@require_permission('system.configure')
def api_noaa_configure():
    """API endpoint to configure NOAA feed settings."""
    try:
        data = request.get_json()

        if not data:
            raise BadRequest("No data provided")

        user_agent = data.get('user_agent', '').strip()
        poll_interval = data.get('poll_interval', '120')

        if not user_agent:
            raise BadRequest("User agent is required for NOAA compliance")

        # Validate poll interval
        try:
            interval_int = int(poll_interval)
            if interval_int < 30:
                raise BadRequest("Poll interval must be at least 30 seconds")
        except ValueError:
            raise BadRequest("Invalid poll interval")

        # Update config file
        _update_env_file('NOAA_USER_AGENT', user_agent)
        _update_env_file('POLL_INTERVAL_SEC', poll_interval)

        # Restart noaa-poller
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', 'eas-station-noaa-poller.service'],
                capture_output=True,
                text=True,
                timeout=30
            )
            restart_success = result.returncode == 0
            if restart_success:
                logger.info("NOAA poller restarted successfully")
            else:
                logger.error(f"Failed to restart NOAA poller: {result.stderr}")
        except Exception as exc:
            logger.error(f"Error restarting NOAA poller: {exc}")
            restart_success = False

        return jsonify({
            'success': True,
            'user_agent': user_agent,
            'poll_interval': poll_interval,
            'poller_restarted': restart_success,
            'message': 'NOAA configuration updated successfully' + (
                ' and poller restarted' if restart_success else ' (manual restart required)'
            )
        })

    except BadRequest as e:
        return jsonify({'error': str(e)}), 400
    except Exception as exc:
        logger.error(f"Error configuring NOAA: {exc}")
        return jsonify({'error': str(exc)}), 500


@ipaws_bp.route('/api/ipaws/configure-custom-sources', methods=['POST'])
@require_permission('system.configure')
def api_configure_custom_sources():
    """Configure custom CAP alert sources."""
    try:
        data = request.get_json()
        if not data:
            raise BadRequest("No data provided")

        cap_endpoints = data.get('cap_endpoints', '').strip()
        poll_interval = data.get('poll_interval', '120')

        # Validate poll interval
        try:
            interval_int = int(poll_interval)
            if interval_int < 30:
                raise BadRequest("Poll interval must be at least 30 seconds")
        except ValueError:
            raise BadRequest("Invalid poll interval")

        # Update configuration
        _update_env_file('CAP_ENDPOINTS', cap_endpoints)
        _update_env_file('POLL_INTERVAL_SEC', poll_interval)

        # Restart the poller service (unified poller, not separate services)
        restart_success = False
        try:
            # Try to restart the unified poller service
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', 'eas-station-poller.service'],
                capture_output=True,
                text=True,
                timeout=30
            )
            restart_success = result.returncode == 0
            if restart_success:
                logger.info("Alert poller restarted successfully")
            else:
                logger.warning(f"Failed to restart poller: {result.stderr}")
                # Try legacy service names for backward compatibility
                for service in ['eas-station-noaa-poller.service', 'eas-station-ipaws-poller.service']:
                    try:
                        result = subprocess.run(
                            ['sudo', 'systemctl', 'restart', service],
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        if result.returncode == 0:
                            logger.info(f"Restarted {service}")
                            restart_success = True
                    except subprocess.SubprocessError as svc_exc:
                        logger.debug(f"Could not restart {service}: {svc_exc}")
                    except Exception as svc_exc:
                        logger.debug(f"Error attempting to restart {service}: {svc_exc}")
        except Exception as exc:
            logger.error(f"Error restarting poller: {exc}")

        return jsonify({
            'success': True,
            'cap_endpoints': cap_endpoints,
            'poll_interval': poll_interval,
            'poller_restarted': restart_success,
            'message': 'Custom alert sources updated successfully' + (
                ' and poller restarted' if restart_success else ' (manual restart required)'
            )
        })

    except BadRequest as e:
        return jsonify({'error': str(e)}), 400
    except Exception as exc:
        logger.error(f"Error configuring custom sources: {exc}")
        return jsonify({'error': str(exc)}), 500



def register(app, logger):
    """Register IPAWS routes with the Flask app."""
    app.register_blueprint(ipaws_bp)
    logger.info("IPAWS routes registered")
