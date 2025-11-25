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

"""IPAWS feed configuration routes."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, render_template, request
from werkzeug.exceptions import BadRequest

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
    """Get the path to the persistent config file."""
    config_path_env = os.environ.get('CONFIG_PATH', '')
    if config_path_env:
        return Path(config_path_env)
    return Path('.env')


def _read_current_config() -> Dict[str, str]:
    """Read current IPAWS configuration from .env file."""
    config_path = _get_config_path()
    config = {}

    if not config_path.exists():
        return config

    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except Exception as exc:
        logger.error(f"Failed to read config file: {exc}")

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
        'last_poll_alerts': 0
    }

    if last_poll:
        status['last_poll'] = last_poll.timestamp.isoformat() if last_poll.timestamp else None
        status['last_poll_status'] = last_poll.status
        status['last_poll_alerts'] = last_poll.alerts_new or 0

    return status


def _update_env_file(key: str, value: str) -> None:
    """Update a single key in the .env file."""
    config_path = _get_config_path()

    if not config_path.exists():
        # Create new file
        with open(config_path, 'w') as f:
            f.write(f"{key}={value}\n")
        return

    # Read existing content
    lines = []
    key_found = False

    with open(config_path, 'r') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                lines.append(f"{key}={value}\n")
                key_found = True
            else:
                lines.append(line)

    # Add key if it wasn't found
    if not key_found:
        lines.append(f"{key}={value}\n")

    # Write back
    with open(config_path, 'w') as f:
        f.writelines(lines)


def _restart_ipaws_poller() -> bool:
    """Restart the ipaws-poller Docker container."""
    try:
        result = subprocess.run(
            ['docker', 'compose', 'restart', 'ipaws-poller'],
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


@ipaws_bp.route('/settings/ipaws')
@require_permission('settings.view')
def ipaws_settings():
    """Render IPAWS configuration page."""
    try:
        status = _get_ipaws_status()

        return render_template(
            'settings/ipaws.html',
            status=status,
            environments=IPAWS_ENVIRONMENTS,
            feed_types=IPAWS_FEED_TYPES
        )
    except Exception as exc:
        logger.error(f"Error rendering IPAWS settings: {exc}")
        return f"Error loading IPAWS settings: {exc}", 500


@ipaws_bp.route('/api/ipaws/status')
@require_permission('settings.view')
def api_ipaws_status():
    """API endpoint to get current IPAWS status."""
    try:
        status = _get_ipaws_status()
        return jsonify(status)
    except Exception as exc:
        logger.error(f"Error getting IPAWS status: {exc}")
        return jsonify({'error': str(exc)}), 500


@ipaws_bp.route('/api/ipaws/configure', methods=['POST'])
@require_permission('settings.edit')
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
@require_permission('settings.edit')
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


def register(app, logger):
    """Register IPAWS routes with the Flask app."""
    app.register_blueprint(ipaws_bp)
    logger.info("IPAWS routes registered")
