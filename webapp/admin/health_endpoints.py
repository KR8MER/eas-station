"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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
Health check endpoints for separated architecture.

These endpoints properly read from Redis to show actual audio-service status,
not the empty local controller in the web application process.
"""

import logging
import os
import re
import shutil
import subprocess
import time
from typing import Dict, Any, Optional

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

# Create blueprint
health_bp = Blueprint('health', __name__)


def _read_audio_metrics_from_redis() -> Optional[Dict[str, Any]]:
    """
    Read audio metrics from Redis (published by audio-service process).

    Returns:
        Dict with audio metrics or None if unavailable
    """
    try:
        from app_core.audio.worker_coordinator_redis import read_shared_metrics
        return read_shared_metrics()
    except Exception as e:
        logger.warning(f"Failed to read audio metrics from Redis: {e}")
        return None


@health_bp.route('/api/health/audio-service', methods=['GET'])
def api_audio_service_health():
    """
    Check if audio-service process is alive and publishing metrics.

    This is the primary health check for separated architecture.

    Returns:
        200: Audio-service healthy
        503: Audio-service down or stale
        500: Error checking health
    """
    try:
        redis_metrics = _read_audio_metrics_from_redis()

        if not redis_metrics:
            return jsonify({
                'status': 'down',
                'message': 'No metrics from audio-service',
                'healthy': False,
                'redis_available': False
            }), 503

        # Check heartbeat age
        heartbeat = redis_metrics.get('_heartbeat', 0)
        age = time.time() - heartbeat

        # Stale threshold: 15 seconds
        if age > 15:
            return jsonify({
                'status': 'stale',
                'message': f'Metrics stale ({age:.1f}s old)',
                'healthy': False,
                'age_seconds': age,
                'last_heartbeat': heartbeat,
                'redis_available': True
            }), 503

        # Extract key info
        audio_controller = redis_metrics.get('audio_controller', {})
        eas_monitor = redis_metrics.get('eas_monitor', {})

        return jsonify({
            'status': 'healthy',
            'message': 'Audio-service publishing metrics',
            'healthy': True,
            'age_seconds': age,
            'last_heartbeat': heartbeat,
            'redis_available': True,
            'audio_controller': {
                'sources_count': len(audio_controller.get('sources', {})),
                'active_source': audio_controller.get('active_source'),
            },
            'eas_monitor': {
                'running': eas_monitor.get('running', False),
                'samples_processed': eas_monitor.get('samples_processed', 0),
            }
        })

    except Exception as e:
        logger.error(f"Error checking audio-service health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


@health_bp.route('/api/health/redis', methods=['GET'])
def api_redis_health():
    """
    Check Redis connection health.

    Returns:
        200: Redis healthy
        503: Redis unavailable
        500: Error checking Redis
    """
    try:
        import redis
        from app_core.config.redis_config import get_redis_host, get_redis_port, get_redis_db, get_redis_password

        redis_host = get_redis_host()
        redis_port = get_redis_port()
        redis_db = get_redis_db()
        redis_password = get_redis_password()

        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            socket_connect_timeout=2,
            socket_timeout=2
        )

        # Test connection
        start = time.time()
        r.ping()
        latency_ms = (time.time() - start) * 1000

        # Get info
        info = r.info()

        return jsonify({
            'status': 'healthy',
            'message': 'Redis connection OK',
            'healthy': True,
            'host': redis_host,
            'port': redis_port,
            'db': redis_db,
            'latency_ms': round(latency_ms, 2),
            'version': info.get('redis_version'),
            'uptime_seconds': info.get('uptime_in_seconds'),
            'connected_clients': info.get('connected_clients'),
            'used_memory_human': info.get('used_memory_human'),
        })

    except redis.ConnectionError as e:
        logger.error(f"Redis connection failed: {e}")
        return jsonify({
            'status': 'unavailable',
            'message': f'Cannot connect to Redis: {str(e)}',
            'healthy': False
        }), 503

    except Exception as e:
        logger.error(f"Error checking Redis health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


@health_bp.route('/api/health/icecast', methods=['GET'])
def api_icecast_health():
    """
    Check Icecast streaming server health.

    Returns:
        200: Icecast healthy or disabled
        503: Icecast enabled but not reachable
        500: Error checking Icecast
    """
    try:
        from app_core.system_health import collect_icecast_status
        
        icecast_status = collect_icecast_status(logger)
        
        # If disabled, return 200 with disabled status
        if not icecast_status.get('enabled'):
            return jsonify({
                'status': 'disabled',
                'message': 'Icecast streaming is disabled',
                'healthy': True,  # Disabled is considered "healthy" (not an error)
                **icecast_status
            })
        
        # If enabled but not running, return 503
        if not icecast_status.get('running'):
            return jsonify({
                'status': 'unavailable',
                'message': 'Icecast server is not reachable',
                'healthy': False,
                **icecast_status
            }), 503
        
        # If running but has issues, return degraded status
        if icecast_status.get('issues'):
            return jsonify({
                'status': 'degraded',
                'message': 'Icecast server is running but has issues',
                'healthy': True,  # Running but degraded
                **icecast_status
            })
        
        # All good
        return jsonify({
            'status': 'healthy',
            'message': 'Icecast server is running normally',
            'healthy': True,
            **icecast_status
        })

    except Exception as e:
        logger.error(f"Error checking Icecast health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


@health_bp.route('/api/health/system', methods=['GET'])
def api_system_health():
    """
    Overall system health check (app + audio-service + Redis + Icecast).

    Returns:
        200: All systems healthy
        503: One or more systems down
        500: Error checking health
    """
    try:
        from app_core.system_health import collect_icecast_status
        
        results = {
            'redis': {'healthy': False},
            'audio_service': {'healthy': False},
            'icecast': {'healthy': True, 'enabled': False},  # Default to healthy when disabled
            'app': {'healthy': True}  # If we're responding, app is up
        }

        # Check Redis
        try:
            redis_metrics = _read_audio_metrics_from_redis()
            results['redis']['healthy'] = redis_metrics is not None
            if redis_metrics:
                heartbeat = redis_metrics.get('_heartbeat', 0)
                age = time.time() - heartbeat
                results['redis']['age_seconds'] = age
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            results['redis']['error'] = str(e)

        # Check audio-service
        try:
            if results['redis']['healthy']:
                redis_metrics = _read_audio_metrics_from_redis()
                heartbeat = redis_metrics.get('_heartbeat', 0)
                age = time.time() - heartbeat
                results['audio_service']['healthy'] = age < 15
                results['audio_service']['age_seconds'] = age
            else:
                results['audio_service']['healthy'] = False
                results['audio_service']['message'] = 'Redis unavailable, cannot check'
        except Exception as e:
            logger.warning(f"Audio-service health check failed: {e}")
            results['audio_service']['error'] = str(e)

        # Check Icecast
        try:
            icecast_status = collect_icecast_status(logger)
            results['icecast'] = {
                'healthy': icecast_status.get('status') in ['ok', 'disabled'],
                'enabled': icecast_status.get('enabled', False),
                'running': icecast_status.get('running', False),
                'status': icecast_status.get('status', 'unknown'),
            }
            if icecast_status.get('server'):
                results['icecast']['server'] = icecast_status['server']
            if icecast_status.get('port'):
                results['icecast']['port'] = icecast_status['port']
            if icecast_status.get('listeners') is not None:
                results['icecast']['listeners'] = icecast_status['listeners']
            if icecast_status.get('sources') is not None:
                results['icecast']['sources'] = icecast_status['sources']
            if icecast_status.get('issues'):
                results['icecast']['issues'] = icecast_status['issues']
        except Exception as e:
            logger.warning(f"Icecast health check failed: {e}")
            results['icecast']['error'] = str(e)
            results['icecast']['healthy'] = True  # Don't fail overall health if Icecast check fails

        # Calculate overall status (Icecast doesn't affect overall health when disabled)
        critical_services = ['redis', 'audio_service', 'app']
        all_healthy = all(results[service]['healthy'] for service in critical_services)
        
        # Include Icecast in health if it's enabled
        if results['icecast'].get('enabled'):
            all_healthy = all_healthy and results['icecast']['healthy']

        status_code = 200 if all_healthy else 503

        return jsonify({
            'status': 'healthy' if all_healthy else 'degraded',
            'healthy': all_healthy,
            'services': results,
            'timestamp': time.time()
        }), status_code

    except Exception as e:
        logger.error(f"Error checking system health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


def _read_meminfo() -> Dict[str, int]:
    """Parse /proc/meminfo and return values in kB."""
    info: Dict[str, int] = {}
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    try:
                        info[key] = int(parts[1])
                    except ValueError:
                        pass
    except OSError:
        pass
    return info


def _read_cpu_stat() -> Dict[str, int]:
    """Read a single snapshot of /proc/stat cpu line."""
    try:
        with open('/proc/stat', 'r') as f:
            for line in f:
                if line.startswith('cpu '):
                    fields = line.split()[1:]
                    names = ['user', 'nice', 'system', 'idle', 'iowait',
                             'irq', 'softirq', 'steal']
                    return {names[i]: int(fields[i]) for i in range(min(len(names), len(fields)))}
    except OSError:
        pass
    return {}


def _cpu_percent(interval: float = 0.1) -> Optional[float]:
    """Measure CPU usage over a short interval using /proc/stat."""
    t1 = _read_cpu_stat()
    if not t1:
        return None
    time.sleep(interval)
    t2 = _read_cpu_stat()
    if not t2:
        return None
    idle1 = t1.get('idle', 0) + t1.get('iowait', 0)
    idle2 = t2.get('idle', 0) + t2.get('iowait', 0)
    total1 = sum(t1.values())
    total2 = sum(t2.values())
    delta_total = total2 - total1
    delta_idle = idle2 - idle1
    if delta_total == 0:
        return 0.0
    return round(100.0 * (1 - delta_idle / delta_total), 1)


@health_bp.route('/api/health/resources', methods=['GET'])
def api_resource_health():
    """
    System resource utilization: CPU, memory, disk, load average, uptime.

    Returns:
        200: Resource metrics collected successfully
        500: Error collecting metrics
    """
    try:
        result: Dict[str, Any] = {}

        # --- CPU ---
        cpu_pct = _cpu_percent()
        if cpu_pct is not None:
            result['cpu_percent'] = cpu_pct

        # --- Load average ---
        try:
            load1, load5, load15 = os.getloadavg()
            result['load_average'] = {
                '1min': round(load1, 2),
                '5min': round(load5, 2),
                '15min': round(load15, 2),
            }
        except (OSError, AttributeError):
            pass

        # --- Memory ---
        meminfo = _read_meminfo()
        if meminfo:
            mem_total_kb = meminfo.get('MemTotal', 0)
            mem_available_kb = meminfo.get('MemAvailable', 0)
            mem_used_kb = mem_total_kb - mem_available_kb
            if mem_total_kb:
                result['memory'] = {
                    'total_mb': round(mem_total_kb / 1024, 1),
                    'used_mb': round(mem_used_kb / 1024, 1),
                    'available_mb': round(mem_available_kb / 1024, 1),
                    'percent': round(100.0 * mem_used_kb / mem_total_kb, 1),
                }

        # --- Disk (root filesystem) ---
        try:
            disk = shutil.disk_usage('/')
            result['disk'] = {
                'total_gb': round(disk.total / 1024 ** 3, 2),
                'used_gb': round(disk.used / 1024 ** 3, 2),
                'free_gb': round(disk.free / 1024 ** 3, 2),
                'percent': round(100.0 * disk.used / disk.total, 1),
            }
        except OSError:
            pass

        # --- Uptime ---
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.read().split()[0])
            result['uptime_seconds'] = int(uptime_seconds)
        except (OSError, ValueError, IndexError):
            pass

        result['timestamp'] = time.time()

        return jsonify({
            'status': 'ok',
            'healthy': True,
            **result,
        })

    except Exception as e:
        logger.error(f"Error collecting resource metrics: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False,
        }), 500


def _parse_timedatectl_timesync(output: str) -> Dict[str, Any]:
    """Parse output of `timedatectl show-timesync --no-pager` into a dict."""
    result: Dict[str, Any] = {}
    for line in output.splitlines():
        if '=' in line:
            key, _, value = line.partition('=')
            result[key.strip()] = value.strip()
    return result


def _parse_chronyc_tracking(output: str) -> Dict[str, Any]:
    """Parse `chronyc tracking` output into a structured dict."""
    result: Dict[str, Any] = {}
    for line in output.splitlines():
        if ':' in line:
            key, _, value = line.partition(':')
            result[key.strip()] = value.strip()
    return result


def _get_ntp_status() -> Dict[str, Any]:
    """
    Collect NTP synchronization status using available system tools.

    Tries timedatectl show-timesync, then timedatectl status,
    then chronyc tracking, returning best-effort data.
    """
    info: Dict[str, Any] = {'method': None, 'synchronized': None}

    # --- Try timedatectl show-timesync (systemd-timesyncd) ---
    try:
        result = subprocess.run(
            ['timedatectl', 'show-timesync', '--no-pager'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parsed = _parse_timedatectl_timesync(result.stdout)
            info['method'] = 'timedatectl/timesyncd'
            info['server'] = parsed.get('ServerName') or parsed.get('FallbackNTPServers') or 'unknown'
            offset_str = parsed.get('NTPMessage', '')
            # Extract offset from NTPMessage field if present
            m = re.search(r'offset=([+-]?\d+\.?\d*)', offset_str)
            if m:
                info['offset_ms'] = round(float(m.group(1)) * 1000, 3)
            poll_str = parsed.get('Poll')
            if poll_str:
                try:
                    info['poll_interval_s'] = int(poll_str)
                except ValueError:
                    pass
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # --- Try timedatectl status (always works on systemd systems) ---
    try:
        result = subprocess.run(
            ['timedatectl', 'status', '--no-pager'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            out = result.stdout
            # "System clock synchronized: yes"
            m = re.search(r'System clock synchronized:\s+(\w+)', out)
            if m:
                info['synchronized'] = m.group(1).lower() == 'yes'
            # "NTP service: active"
            m = re.search(r'NTP service:\s+(\w+)', out)
            if m:
                info['ntp_service'] = m.group(1)
            # "NTP synchronized: yes" (older systemd)
            m = re.search(r'NTP synchronized:\s+(\w+)', out)
            if m and info.get('synchronized') is None:
                info['synchronized'] = m.group(1).lower() == 'yes'
            if info.get('method') is None:
                info['method'] = 'timedatectl/status'
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # --- Try chronyc tracking ---
    if info.get('synchronized') is None or info.get('offset_ms') is None:
        try:
            result = subprocess.run(
                ['chronyc', 'tracking'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                parsed = _parse_chronyc_tracking(result.stdout)
                if info.get('method') is None:
                    info['method'] = 'chronyc'
                    info['synchronized'] = True  # chronyc tracking only shows data when synced
                ref_id = parsed.get('Reference ID', '')
                m = re.search(r'\(([^)]+)\)', ref_id)
                if m and info.get('server') is None:
                    info['server'] = m.group(1)
                offset_raw = parsed.get('System time offset', parsed.get('Last offset', ''))
                m = re.search(r'([+-]?\d+\.?\d+(?:e[+-]?\d+)?)\s*seconds', offset_raw)
                if m:
                    info['offset_ms'] = round(float(m.group(1)) * 1000, 6)
                stratum_str = parsed.get('Stratum', '')
                m = re.match(r'(\d+)', stratum_str)
                if m:
                    info['stratum'] = int(m.group(1))
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return info


@health_bp.route('/api/health/ntp', methods=['GET'])
def api_ntp_health():
    """
    NTP synchronization status.

    Returns:
        200: NTP status collected (synchronized/not, offset, server, method)
        500: Error collecting status
    """
    try:
        ntp = _get_ntp_status()
        synced = ntp.get('synchronized')
        return jsonify({
            'status': 'ok' if synced else ('unknown' if synced is None else 'not_synced'),
            'healthy': bool(synced),
            'synchronized': synced,
            'server': ntp.get('server'),
            'offset_ms': ntp.get('offset_ms'),
            'stratum': ntp.get('stratum'),
            'poll_interval_s': ntp.get('poll_interval_s'),
            'ntp_service': ntp.get('ntp_service'),
            'method': ntp.get('method'),
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.error(f"Error collecting NTP status: {e}", exc_info=True)
        return jsonify({'status': 'error', 'healthy': False, 'message': str(e)}), 500


def register_health_routes(app):
    """Register health check routes on Flask app."""
    app.register_blueprint(health_bp)
    logger.info("✅ Health check routes registered")
