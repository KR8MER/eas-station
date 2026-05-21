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

from flask import Blueprint, render_template, jsonify, request
import subprocess
import logging
import re
import os
from typing import Dict, List, Any
from app_core.config import get_all_log_services, get_eas_services
from app_core.cache import cache

logger = logging.getLogger(__name__)

logs_bp = Blueprint('logs', __name__)

# Regex pattern to strip ANSI escape codes from log messages
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*m')

# Valid patterns for journalctl --since parameter
VALID_SINCE_PATTERNS = [
    r'^today$',
    r'^yesterday$',
    r'^\d{1,3}\s+(second|minute|hour|day|week|month)s?\s+ago$',  # "1 hour ago", "30 minutes ago"
    r'^\d{4}-\d{2}-\d{2}$',  # "2025-12-10"
    r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?$',  # "2025-12-10 14:30:00"
]

def is_valid_since_param(since: str) -> bool:
    """Validate the 'since' parameter for journalctl to prevent injection."""
    if not since:
        return True
    since_lower = since.strip().lower()
    for pattern in VALID_SINCE_PATTERNS:
        if re.match(pattern, since_lower):
            return True
    return False


def get_systemd_logs(service: str, lines: int = 100, priority: str = None, since: str = None) -> Dict[str, Any]:
    """
    Fetch logs from systemd journalctl for a specific service.

    Args:
        service: Service name (e.g., 'eas-station-web.service')
        lines: Number of log lines to retrieve
        priority: Log priority filter (err, warning, info, debug)
        since: Time filter (e.g., 'today', '1 hour ago', '2025-12-10')

    Returns:
        Dictionary with logs and metadata
    """
    import shutil
    import pwd

    # Check if journalctl is available
    if not shutil.which('journalctl'):
        return {
            'success': False,
            'error': 'journalctl command not found. Install systemd to view service logs.',
            'service': service,
            'help': 'Service logs require systemd and journalctl to be installed.'
        }

    try:
        cmd = ['journalctl', '-u', service, '-n', str(lines), '--no-pager', '--output=json', '--all']

        if priority:
            cmd.extend(['-p', priority])

        if since:
            cmd.extend(['--since', since])

        logger.debug("Running journalctl command: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        logger.debug("journalctl returncode=%d, stdout_len=%d, stderr_len=%d",
                     result.returncode, len(result.stdout or ''), len(result.stderr or ''))

        # Check for common issues in stderr/stdout
        combined_output = (result.stdout or '') + (result.stderr or '')

        # Permission denied check - provide helpful fix instructions
        if 'Permission denied' in combined_output or 'Access denied' in combined_output:
            # Try to get current user for helpful message
            try:
                current_user = pwd.getpwuid(os.getuid()).pw_name
            except (KeyError, OSError):
                current_user = 'www-data'
            
            return {
                'success': False,
                'error': f'Permission denied accessing journal',
                'service': service,
                'help': f'Add web server user to systemd-journal group:\n  sudo usermod -a -G systemd-journal {current_user}\n  sudo systemctl restart eas-station-web.service'
            }

        if 'No journal files were found' in combined_output:
            return {
                'success': False,
                'error': 'Systemd journal not available',
                'service': service,
                'help': 'Journal may be disabled or not configured. Check: sudo systemctl status systemd-journald'
            }

        if result.returncode == 0:
            import json
            logs = []
            output = result.stdout.strip()
            if output and '-- No entries --' not in output:
                for line in output.split('\n'):
                    if line and not line.startswith('--'):
                        try:
                            log_entry = json.loads(line)
                            # Handle MESSAGE field - journalctl outputs byte arrays
                            # when messages contain ANSI escape codes or binary data
                            message = log_entry.get('MESSAGE', '')
                            if isinstance(message, list):
                                # MESSAGE is a list of byte values, decode to string
                                try:
                                    message = bytes(message).decode('utf-8', errors='replace')
                                except (TypeError, ValueError):
                                    message = str(message)
                            # Strip ANSI escape codes for clean display
                            message = ANSI_ESCAPE_PATTERN.sub('', message)
                            logs.append({
                                'timestamp': log_entry.get('__REALTIME_TIMESTAMP', ''),
                                'priority': log_entry.get('PRIORITY', '6'),
                                'message': message,
                                'unit': log_entry.get('_SYSTEMD_UNIT', service)
                            })
                        except json.JSONDecodeError as e:
                            logger.debug("Failed to parse JSON line: %s (error: %s)", line[:100], e)
                            continue

            logger.debug("Parsed %d log entries for %s", len(logs), service)
            return {
                'success': True,
                'service': service,
                'logs': logs,
                'count': len(logs)
            }
        else:
            error_msg = result.stderr.strip() if result.stderr else 'Failed to fetch logs'
            logger.debug("journalctl failed for %s: %s", service, error_msg)
            # journalctl returns exit code 1 when no entries are found for a unit
            if 'No entries' in error_msg or 'No entries' in (result.stdout or '') or result.returncode == 1:
                return {
                    'success': True,
                    'service': service,
                    'logs': [],
                    'count': 0
                }
            return {
                'success': False,
                'error': error_msg,
                'service': service
            }

    except FileNotFoundError:
        return {
            'success': False,
            'error': 'journalctl command not found',
            'service': service
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Timeout fetching logs',
            'service': service
        }
    except Exception as e:
        logger.error(f"Error fetching logs for {service}: {e}")
        return {
            'success': False,
            'error': str(e),
            'service': service
        }


@logs_bp.route('/api/logs/<service>')
def get_logs(service: str):
    """
    API endpoint to fetch logs for a specific service.
    
    Query parameters:
        - lines: Number of lines (default: 100, max: 1000)
        - priority: Log priority (err, warning, info, debug)
        - since: Time filter (today, 1 hour ago, etc.)
    """
    # Validate service name to prevent command injection
    allowed_services = get_all_log_services()

    if service not in allowed_services:
        return jsonify({'error': 'Invalid service name'}), 400
    
    lines = min(int(request.args.get('lines', 100)), 1000)
    priority = request.args.get('priority')
    since = request.args.get('since')

    # Validate priority
    if priority and priority not in ['emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug']:
        return jsonify({'error': 'Invalid priority'}), 400

    # Validate since parameter format
    if since and not is_valid_since_param(since):
        return jsonify({'error': 'Invalid since format. Use: today, yesterday, "N hours ago", or YYYY-MM-DD'}), 400

    result = get_systemd_logs(service, lines, priority, since)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 500


@logs_bp.route('/api/logs/all')
def get_all_logs():
    """
    Fetch logs from all EAS Station services.

    Query parameters:
        - lines: Number of lines per service (default: 50, max: 500)
        - priority: Log priority filter
        - since: Time filter
    """
    lines = min(int(request.args.get('lines', 50)), 500)
    priority = request.args.get('priority')
    since = request.args.get('since')

    # Validate since parameter format
    if since and not is_valid_since_param(since):
        return jsonify({'error': 'Invalid since format. Use: today, yesterday, "N hours ago", or YYYY-MM-DD'}), 400

    results = {}
    for service in get_eas_services():
        results[service] = get_systemd_logs(service, lines, priority, since)

    return jsonify(results)


@logs_bp.route('/api/logs/recent')
# Cached for ~5 s.  This endpoint is hit by the real-time log viewer's
# WebSocket-fallback poll (every 10 s) and ad-hoc dashboard panels.  Even at
# query-string variations the per-call cost is several DB SELECTs, so
# collapsing concurrent callers onto a single result for a few seconds keeps
# the DB pool free for actual user-driven requests.
@cache.cached(timeout=5, query_string=True, key_prefix='logs_recent')
def get_recent_logs():
    """
    Fetch recent logs from all sources for real-time display.
    Used by WebSocket fallback polling and real-time log viewer.

    Query parameters:
        - limit: Maximum number of logs to return (default: 50, max: 200)
        - since_id: Return only logs newer than this ID (for incremental updates)
    """
    from datetime import datetime, timedelta, timezone
    from app_core.models import SystemLog, AudioAlert, GPIOActivationLog, EASMessage

    limit = min(int(request.args.get('limit', 50)), 200)

    try:
        logs = []

        # Get recent system logs (most common source)
        for log in SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(limit).all():
            logs.append({
                'id': f'sys_{log.id}',
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                'level': log.level or 'INFO',
                'module': log.module or 'system',
                'message': log.message,
                'category': 'system',
                'alert_identifier': log.alert_identifier,
                'details': log.details,
            })

        # Get recent audio alerts
        for log in AudioAlert.query.order_by(AudioAlert.created_at.desc()).limit(limit // 4).all():
            logs.append({
                'id': f'audio_{log.id}',
                'timestamp': log.created_at.isoformat() if log.created_at else None,
                'level': (log.alert_level or 'INFO').upper(),
                'module': f'audio:{log.source_name}' if log.source_name else 'audio',
                'message': log.message,
                'category': 'audio',
                'alert_identifier': log.alert_identifier,
                'details': {
                    'alert_type': log.alert_type,
                    'acknowledged': log.acknowledged,
                },
            })

        # Get recent GPIO activations
        for log in GPIOActivationLog.query.order_by(GPIOActivationLog.activated_at.desc()).limit(limit // 4).all():
            logs.append({
                'id': f'gpio_{log.id}',
                'timestamp': log.activated_at.isoformat() if log.activated_at else None,
                'level': 'INFO',
                'module': f'gpio:pin{log.pin}',
                'message': f"{log.activation_type} - Duration: {log.duration_seconds or 'active'}s",
                'category': 'gpio',
                # GPIOActivationLog stores the correlation ID in its legacy
                # ``alert_id`` column rather than ``alert_identifier``.
                'alert_identifier': log.alert_id,
                'details': {
                    'pin': log.pin,
                    'activation_type': log.activation_type,
                    'operator': log.operator,
                },
            })

        # Get recent EAS messages
        for log in EASMessage.query.order_by(EASMessage.created_at.desc()).limit(limit // 4).all():
            logs.append({
                'id': f'eas_{log.id}',
                'timestamp': log.created_at.isoformat() if log.created_at else None,
                'level': 'INFO',
                'module': 'eas_generator',
                'message': f"SAME: {log.same_header}" if log.same_header else "EAS message generated",
                'category': 'eas',
                'alert_identifier': log.alert_identifier,
                'details': {
                    'same_header': log.same_header,
                    'audio_filename': log.audio_filename,
                },
            })

        # Sort all logs by timestamp (most recent first)
        logs.sort(key=lambda x: x['timestamp'] or '', reverse=True)

        # Trim to limit
        logs = logs[:limit]

        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })

    except Exception as e:
        logger.error(f"Error fetching recent logs: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'logs': [],
            'count': 0,
        }), 500


@logs_bp.route('/api/logs/debug')
def debug_logs():
    """
    Diagnostic endpoint to help troubleshoot log display issues.
    Returns information about log sources and their status.
    """
    from datetime import datetime, timezone
    from app_core.models import SystemLog, AudioAlert, GPIOActivationLog, EASMessage

    results = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'database_status': 'unknown',
        'systemd_status': 'unknown',
        'sources': {},
    }

    # Check database logs
    try:
        system_log_count = SystemLog.query.count()
        results['sources']['system_log'] = {
            'count': system_log_count,
            'status': 'ok' if system_log_count >= 0 else 'error',
        }
        if system_log_count > 0:
            latest = SystemLog.query.order_by(SystemLog.timestamp.desc()).first()
            results['sources']['system_log']['latest'] = {
                'id': latest.id,
                'timestamp': latest.timestamp.isoformat() if latest.timestamp else None,
                'level': latest.level,
                'message': latest.message[:100] if latest.message else None,
            }
        results['database_status'] = 'ok'
    except Exception as e:
        results['sources']['system_log'] = {'status': 'error', 'error': str(e)}
        results['database_status'] = 'error'

    try:
        audio_alert_count = AudioAlert.query.count()
        results['sources']['audio_alert'] = {
            'count': audio_alert_count,
            'status': 'ok',
        }
    except Exception as e:
        results['sources']['audio_alert'] = {'status': 'error', 'error': str(e)}

    try:
        gpio_count = GPIOActivationLog.query.count()
        results['sources']['gpio_log'] = {
            'count': gpio_count,
            'status': 'ok',
        }
    except Exception as e:
        results['sources']['gpio_log'] = {'status': 'error', 'error': str(e)}

    try:
        eas_count = EASMessage.query.count()
        results['sources']['eas_message'] = {
            'count': eas_count,
            'status': 'ok',
        }
    except Exception as e:
        results['sources']['eas_message'] = {'status': 'error', 'error': str(e)}

    # Check systemd logs
    try:
        services = get_eas_services()
        results['sources']['systemd'] = {
            'services_configured': services,
            'service_count': len(services),
        }

        # Try to fetch logs from the first service
        if services:
            test_service = services[0]
            test_result = get_systemd_logs(test_service, lines=5, priority=None, since='1 hour ago')
            results['sources']['systemd']['test_service'] = test_service
            results['sources']['systemd']['test_result'] = {
                'success': test_result.get('success', False),
                'log_count': len(test_result.get('logs', [])),
                'error': test_result.get('error'),
            }
            if test_result.get('logs'):
                results['sources']['systemd']['sample_log'] = test_result['logs'][0]
        results['systemd_status'] = 'ok'
    except Exception as e:
        results['sources']['systemd'] = {'status': 'error', 'error': str(e)}
        results['systemd_status'] = 'error'

    return jsonify(results)


def register(app):
    """Register logs blueprint with the Flask app."""
    app.register_blueprint(logs_bp)
    logger.info("Logs routes registered")
