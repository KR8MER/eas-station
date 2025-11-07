"""Audio Ingest API routes for managing audio sources and monitoring."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from sqlalchemy import desc

from app_core.extensions import db
from app_core.models import AudioAlert, AudioHealthStatus, AudioSourceMetrics, AudioSourceConfigDB
from app_core.audio import AudioIngestController
from app_core.audio.ingest import AudioSourceConfig, AudioSourceType, AudioSourceStatus
from app_core.audio.sources import create_audio_source
from app_utils import utc_now

logger = logging.getLogger(__name__)

# Global audio ingest controller instance
_audio_controller: Optional[AudioIngestController] = None


def _get_audio_controller() -> AudioIngestController:
    """Get or create the global audio ingest controller."""
    global _audio_controller
    if _audio_controller is None:
        _audio_controller = AudioIngestController()
        _initialize_audio_sources(_audio_controller)
    return _audio_controller


def _initialize_audio_sources(controller: AudioIngestController) -> None:
    """Initialize audio sources from database configuration."""
    try:
        # Load ALL saved configurations from database (not just enabled ones)
        # This allows disabled sources to be manageable through the UI
        saved_configs = AudioSourceConfigDB.query.all()

        for db_config in saved_configs:
            try:
                # Parse source type
                source_type = AudioSourceType(db_config.source_type)

                # Create runtime configuration from database config
                config_params = db_config.config_params or {}
                runtime_config = AudioSourceConfig(
                    source_type=source_type,
                    name=db_config.name,
                    enabled=db_config.enabled,
                    priority=db_config.priority,
                    sample_rate=config_params.get('sample_rate', 44100),
                    channels=config_params.get('channels', 1),
                    buffer_size=config_params.get('buffer_size', 4096),
                    silence_threshold_db=config_params.get('silence_threshold_db', -60.0),
                    silence_duration_seconds=config_params.get('silence_duration_seconds', 5.0),
                    device_params=config_params.get('device_params', {}),
                )

                # Create and add adapter
                adapter = create_audio_source(runtime_config)
                controller.add_source(adapter)

                # Auto-start only if both enabled AND auto_start are True
                if db_config.enabled and db_config.auto_start:
                    controller.start_source(db_config.name)
                    logger.info('Auto-started audio source: %s', db_config.name)
                else:
                    logger.info('Loaded audio source: %s (not auto-started)', db_config.name)

            except Exception as exc:
                logger.error('Error loading audio source %s: %s', db_config.name, exc)

        logger.info('Initialized %d audio sources from database', len(saved_configs))

    except Exception as exc:
        logger.error('Error initializing audio sources from database: %s', exc)


def _sanitize_float(value: float) -> float:
    """Sanitize float values to be JSON-safe (no inf/nan, convert numpy types)."""
    import math
    import numpy as np

    # Convert numpy types to regular Python float first
    if isinstance(value, (np.floating, np.integer)):
        value = float(value)

    if math.isinf(value):
        return -120.0 if value < 0 else 120.0
    if math.isnan(value):
        return -120.0
    return value


def _sanitize_bool(value) -> bool:
    """Sanitize boolean values to be JSON-safe (convert numpy bool_ types)."""
    import numpy as np

    # Convert numpy bool_ to Python bool
    if isinstance(value, np.bool_):
        return bool(value)

    return bool(value)


def _serialize_audio_source(source_name: str, adapter: Any) -> Dict[str, Any]:
    """Serialize an audio source adapter to JSON-compatible dict."""
    config = adapter.config

    # Fetch database config for additional fields
    db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()

    return {
        'id': source_name,
        'name': config.name,
        'type': config.source_type.value,
        'status': adapter.status.value,
        'error_message': adapter.error_message,
        'enabled': _sanitize_bool(config.enabled),
        'priority': config.priority,
        'auto_start': _sanitize_bool(db_config.auto_start) if db_config else False,
        'description': db_config.description if db_config else '',
        'config': {
            'sample_rate': config.sample_rate,
            'channels': config.channels,
            'buffer_size': config.buffer_size,
            'silence_threshold_db': config.silence_threshold_db,
            'silence_duration_seconds': config.silence_duration_seconds,
            'device_params': config.device_params,
        },
        'metrics': {
            'timestamp': adapter.metrics.timestamp,
            'peak_level_db': _sanitize_float(adapter.metrics.peak_level_db),
            'rms_level_db': _sanitize_float(adapter.metrics.rms_level_db),
            'sample_rate': adapter.metrics.sample_rate,
            'channels': adapter.metrics.channels,
            'frames_captured': adapter.metrics.frames_captured,
            'silence_detected': _sanitize_bool(adapter.metrics.silence_detected),
            'buffer_utilization': _sanitize_float(adapter.metrics.buffer_utilization),
            'metadata': adapter.metrics.metadata if adapter.metrics.metadata else None,
        } if adapter.metrics else None,
    }


def register_audio_ingest_routes(app: Flask, logger_instance: Any) -> None:
    """Register audio ingest API routes."""

    global logger
    logger = logger_instance

    @app.route('/api/audio/sources', methods=['GET'])
    def api_get_audio_sources():
        """List all configured audio sources."""
        try:
            controller = _get_audio_controller()
            sources = []

            # Query DATABASE for all sources (source of truth)
            db_configs = AudioSourceConfigDB.query.all()

            for db_config in db_configs:
                # Check if source is loaded in memory
                adapter = controller._sources.get(db_config.name)

                if adapter:
                    # Source is in memory, serialize it normally
                    sources.append(_serialize_audio_source(db_config.name, adapter))
                else:
                    # Source exists in DB but not in memory - show as stopped
                    sources.append({
                        'name': db_config.name,
                        'type': db_config.source_type,
                        'status': 'stopped',
                        'enabled': db_config.enabled,
                        'priority': db_config.priority,
                        'auto_start': db_config.auto_start,
                        'description': db_config.description or '',
                        'metrics': None,
                        'error_message': 'Not loaded in memory (restart required)',
                        'in_memory': False  # Flag to indicate sync issue
                    })

            return jsonify({
                'sources': sources,
                'total': len(sources),
                'active_count': sum(1 for s in sources if s['status'] == 'running'),
                'db_only_count': sum(1 for s in sources if not s.get('in_memory', True))
            })
        except Exception as exc:
            logger.error('Error getting audio sources: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/sources', methods=['POST'])
    def api_create_audio_source():
        """Create a new audio source."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            # Validate required fields
            source_type = data.get('type')
            name = data.get('name')
            if not source_type or not name:
                return jsonify({'error': 'type and name are required'}), 400

            # Parse source type
            try:
                audio_type = AudioSourceType(source_type)
            except ValueError:
                return jsonify({'error': f'Invalid source type: {source_type}'}), 400

            # Get controller first to ensure it's initialized
            # (prevents duplicate adapter creation when controller initializes from DB)
            controller = _get_audio_controller()

            # Check if source already exists in DATABASE (source of truth)
            existing_db_config = AudioSourceConfigDB.query.filter_by(name=name).first()
            if existing_db_config:
                return jsonify({
                    'error': f'Source "{name}" already exists in database',
                    'hint': 'Use DELETE /api/audio/sources/{name} first, or use PATCH to update'
                }), 400

            # Also check if source exists in memory (shouldn't happen, but be safe)
            if name in controller._sources:
                return jsonify({
                    'error': f'Source "{name}" exists in memory but not in database (inconsistent state)',
                    'hint': 'Contact system administrator - database sync issue'
                }), 500

            # Create configuration
            config = AudioSourceConfig(
                source_type=audio_type,
                name=name,
                enabled=data.get('enabled', True),
                priority=data.get('priority', 100),
                sample_rate=data.get('sample_rate', 44100),
                channels=data.get('channels', 1),
                buffer_size=data.get('buffer_size', 4096),
                silence_threshold_db=data.get('silence_threshold_db', -60.0),
                silence_duration_seconds=data.get('silence_duration_seconds', 5.0),
                device_params=data.get('device_params', {}),
            )

            # Create adapter
            adapter = create_audio_source(config)

            # Add to controller
            controller.add_source(adapter)

            # Save to database AFTER adding to controller
            db_config = AudioSourceConfigDB(
                name=name,
                source_type=source_type,
                config_params={
                    'sample_rate': config.sample_rate,
                    'channels': config.channels,
                    'buffer_size': config.buffer_size,
                    'silence_threshold_db': config.silence_threshold_db,
                    'silence_duration_seconds': config.silence_duration_seconds,
                    'device_params': config.device_params,
                },
                priority=config.priority,
                enabled=config.enabled,
                auto_start=data.get('auto_start', False),
                description=data.get('description', ''),
            )
            db.session.add(db_config)
            try:
                db.session.commit()
            except Exception:
                # If database commit fails, remove from controller to keep state consistent
                db.session.rollback()
                controller.remove_source(name)
                raise

            logger.info('Created audio source: %s (Type: %s)', name, source_type)

            return jsonify({
                'source': _serialize_audio_source(name, adapter),
                'message': 'Audio source created successfully'
            }), 201

        except Exception as exc:
            logger.error('Error creating audio source: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/sources/<source_name>', methods=['GET'])
    def api_get_audio_source(source_name: str):
        """Get details of a specific audio source."""
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            return jsonify(_serialize_audio_source(source_name, adapter))

        except Exception as exc:
            logger.error('Error getting audio source %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/sources/<source_name>', methods=['PATCH'])
    def api_update_audio_source(source_name: str):
        """Update audio source configuration."""
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            config = adapter.config
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            # Update database configuration FIRST, before touching the in-memory config
            db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
            if db_config:
                if 'enabled' in data:
                    db_config.enabled = data['enabled']
                if 'priority' in data:
                    db_config.priority = data['priority']
                if 'auto_start' in data:
                    db_config.auto_start = data['auto_start']
                if 'description' in data:
                    db_config.description = data['description']

                # Update config params
                config_params = db_config.config_params or {}
                if 'silence_threshold_db' in data:
                    config_params['silence_threshold_db'] = data['silence_threshold_db']
                if 'silence_duration_seconds' in data:
                    config_params['silence_duration_seconds'] = data['silence_duration_seconds']
                if 'device_params' in data:
                    device_params = config_params.get('device_params', {})
                    device_params.update(data['device_params'])
                    config_params['device_params'] = device_params

                db_config.config_params = config_params
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    raise

            # Update in-memory configuration AFTER the database transaction succeeds
            # This prevents inconsistency if the commit fails
            if 'enabled' in data:
                config.enabled = data['enabled']
            if 'priority' in data:
                config.priority = data['priority']
            if 'silence_threshold_db' in data:
                config.silence_threshold_db = data['silence_threshold_db']
            if 'silence_duration_seconds' in data:
                config.silence_duration_seconds = data['silence_duration_seconds']
            if 'device_params' in data:
                config.device_params.update(data['device_params'])

            logger.info('Updated audio source: %s', source_name)

            return jsonify({
                'source': _serialize_audio_source(source_name, adapter),
                'message': 'Audio source updated successfully'
            })

        except Exception as exc:
            logger.error('Error updating audio source %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/sources/<source_name>', methods=['DELETE'])
    def api_delete_audio_source(source_name: str):
        """Delete an audio source."""
        try:
            controller = _get_audio_controller()

            # Check DATABASE first (source of truth)
            db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
            if not db_config:
                return jsonify({'error': 'Source not found in database'}), 404

            # Check if source is in memory
            adapter = controller._sources.get(source_name)

            # Stop if running (only if in memory)
            if adapter and adapter.status == AudioSourceStatus.RUNNING:
                controller.stop_source(source_name)

            # Remove from database FIRST
            db.session.delete(db_config)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise

            # Remove from controller AFTER database transaction succeeds
            # (only if it was in memory)
            if adapter:
                controller.remove_source(source_name)
                logger.info('Deleted audio source from both database and memory: %s', source_name)
            else:
                logger.info('Deleted audio source from database (was not in memory): %s', source_name)

            return jsonify({'message': 'Audio source deleted successfully'})

        except Exception as exc:
            logger.error('Error deleting audio source %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/sources/<source_name>/start', methods=['POST'])
    def api_start_audio_source(source_name: str):
        """Start audio ingestion from a source."""
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            if adapter.status == AudioSourceStatus.RUNNING:
                return jsonify({'message': 'Source is already running'}), 200

            controller.start_source(source_name)

            logger.info('Started audio source: %s', source_name)

            return jsonify({
                'message': 'Audio source started successfully',
                'status': adapter.status.value
            })

        except Exception as exc:
            logger.error('Error starting audio source %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/sources/<source_name>/stop', methods=['POST'])
    def api_stop_audio_source(source_name: str):
        """Stop audio ingestion from a source."""
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            if adapter.status == AudioSourceStatus.STOPPED:
                return jsonify({'message': 'Source is already stopped'}), 200

            controller.stop_source(source_name)

            logger.info('Stopped audio source: %s', source_name)

            return jsonify({
                'message': 'Audio source stopped successfully',
                'status': adapter.status.value
            })

        except Exception as exc:
            logger.error('Error stopping audio source %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/metrics', methods=['GET'])
    def api_get_audio_metrics():
        """Get real-time metrics for all audio sources."""
        try:
            # Get in-memory metrics from controller
            controller = _get_audio_controller()
            source_metrics = []

            for source_name, adapter in controller._sources.items():
                if adapter.metrics:
                    source_metrics.append({
                        'source_id': source_name,
                        'source_name': adapter.config.name,
                        'source_type': adapter.config.source_type.value,
                        'timestamp': adapter.metrics.timestamp,
                        'peak_level_db': _sanitize_float(adapter.metrics.peak_level_db),
                        'rms_level_db': _sanitize_float(adapter.metrics.rms_level_db),
                        'sample_rate': adapter.metrics.sample_rate,
                        'channels': adapter.metrics.channels,
                        'frames_captured': adapter.metrics.frames_captured,
                        'silence_detected': _sanitize_bool(adapter.metrics.silence_detected),
                        'buffer_utilization': _sanitize_float(adapter.metrics.buffer_utilization),
                    })

            # Also get recent database metrics
            db_metrics = (
                AudioSourceMetrics.query
                .order_by(desc(AudioSourceMetrics.timestamp))
                .limit(100)
                .all()
            )

            db_metrics_list = []
            for metric in db_metrics:
                db_metrics_list.append({
                    'id': metric.id,
                    'source_name': metric.source_name,
                    'source_type': metric.source_type,
                    'peak_level_db': _sanitize_float(metric.peak_level_db) if metric.peak_level_db is not None else -120.0,
                    'rms_level_db': _sanitize_float(metric.rms_level_db) if metric.rms_level_db is not None else -120.0,
                    'sample_rate': metric.sample_rate,
                    'channels': metric.channels,
                    'frames_captured': metric.frames_captured,
                    'silence_detected': _sanitize_bool(metric.silence_detected) if metric.silence_detected is not None else False,
                    'clipping_detected': _sanitize_bool(metric.clipping_detected) if metric.clipping_detected is not None else False,
                    'buffer_utilization': _sanitize_float(metric.buffer_utilization) if metric.buffer_utilization is not None else 0.0,
                    'timestamp': metric.timestamp.isoformat() if metric.timestamp else None,
                })

            return jsonify({
                'live_metrics': source_metrics,
                'recent_metrics': db_metrics_list,
                'total_sources': len(source_metrics),
            })

        except Exception as exc:
            logger.error('Error getting audio metrics: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/health', methods=['GET'])
    def api_get_audio_health():
        """Get audio system health status."""
        try:
            # Get recent health status from database
            health_records = (
                AudioHealthStatus.query
                .order_by(desc(AudioHealthStatus.timestamp))
                .limit(50)
                .all()
            )

            health_list = []
            for record in health_records:
                health_list.append({
                    'id': record.id,
                    'source_name': record.source_name,
                    'health_score': _sanitize_float(record.health_score) if record.health_score is not None else 0.0,
                    'is_active': _sanitize_bool(record.is_active) if record.is_active is not None else False,
                    'is_healthy': _sanitize_bool(record.is_healthy) if record.is_healthy is not None else False,
                    'silence_detected': _sanitize_bool(record.silence_detected) if record.silence_detected is not None else False,
                    'error_detected': _sanitize_bool(record.error_detected) if record.error_detected is not None else False,
                    'uptime_seconds': _sanitize_float(record.uptime_seconds) if record.uptime_seconds is not None else 0.0,
                    'silence_duration_seconds': _sanitize_float(record.silence_duration_seconds) if record.silence_duration_seconds is not None else 0.0,
                    'time_since_last_signal_seconds': _sanitize_float(record.time_since_last_signal_seconds) if record.time_since_last_signal_seconds is not None else 0.0,
                    'level_trend': record.level_trend,
                    'trend_value_db': _sanitize_float(record.trend_value_db) if record.trend_value_db is not None else 0.0,
                    'timestamp': record.timestamp.isoformat() if record.timestamp else None,
                })

            # Get controller status
            controller = _get_audio_controller()
            active_sources = sum(
                1 for adapter in controller._sources.values()
                if adapter.status == AudioSourceStatus.RUNNING
            )

            # Calculate overall health
            if health_list:
                avg_health = sum(h['health_score'] for h in health_list[:10]) / min(len(health_list), 10)
                avg_health = _sanitize_float(avg_health)
                overall_status = 'healthy' if avg_health >= 80 else 'degraded' if avg_health >= 50 else 'critical'
            else:
                avg_health = 0.0
                overall_status = 'unknown'

            return jsonify({
                'health_records': health_list,
                'overall_health_score': avg_health,
                'overall_status': overall_status,
                'active_sources': active_sources,
                'total_sources': len(controller._sources),
            })

        except Exception as exc:
            logger.error('Error getting audio health: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/alerts', methods=['GET'])
    def api_get_audio_alerts():
        """Get audio system alerts."""
        try:
            # Parse query parameters
            limit = request.args.get('limit', 50, type=int)
            limit = min(max(limit, 1), 500)  # Clamp between 1 and 500

            unresolved_only = request.args.get('unresolved_only', 'false').lower() == 'true'

            # Build query
            query = AudioAlert.query

            if unresolved_only:
                query = query.filter(AudioAlert.resolved == False)

            alerts = (
                query
                .order_by(desc(AudioAlert.created_at))
                .limit(limit)
                .all()
            )

            alerts_list = []
            for alert in alerts:
                alerts_list.append({
                    'id': alert.id,
                    'source_name': alert.source_name,
                    'alert_level': alert.alert_level,
                    'alert_type': alert.alert_type,
                    'message': alert.message,
                    'details': alert.details,
                    'threshold_value': alert.threshold_value,
                    'actual_value': alert.actual_value,
                    'acknowledged': _sanitize_bool(alert.acknowledged) if alert.acknowledged is not None else False,
                    'acknowledged_by': alert.acknowledged_by,
                    'acknowledged_at': alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                    'resolved': _sanitize_bool(alert.resolved) if alert.resolved is not None else False,
                    'resolved_by': alert.resolved_by,
                    'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                    'created_at': alert.created_at.isoformat() if alert.created_at else None,
                })

            unresolved_count = AudioAlert.query.filter(AudioAlert.resolved == False).count()

            return jsonify({
                'alerts': alerts_list,
                'total': len(alerts_list),
                'unresolved_count': unresolved_count,
            })

        except Exception as exc:
            logger.error('Error getting audio alerts: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/alerts/<int:alert_id>/acknowledge', methods=['POST'])
    def api_acknowledge_alert(alert_id: int):
        """Acknowledge an audio alert."""
        try:
            alert = AudioAlert.query.get(alert_id)
            if not alert:
                return jsonify({'error': 'Alert not found'}), 404

            data = request.get_json() or {}
            acknowledged_by = data.get('acknowledged_by', 'system')

            alert.acknowledged = True
            alert.acknowledged_by = acknowledged_by
            alert.acknowledged_at = utc_now()
            alert.updated_at = utc_now()

            db.session.commit()

            logger.info('Acknowledged alert %d by %s', alert_id, acknowledged_by)

            return jsonify({'message': 'Alert acknowledged successfully'})

        except Exception as exc:
            logger.error('Error acknowledging alert %d: %s', alert_id, exc)
            db.session.rollback()
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/alerts/<int:alert_id>/resolve', methods=['POST'])
    def api_resolve_alert(alert_id: int):
        """Resolve an audio alert."""
        try:
            alert = AudioAlert.query.get(alert_id)
            if not alert:
                return jsonify({'error': 'Alert not found'}), 404

            data = request.get_json() or {}
            resolved_by = data.get('resolved_by', 'system')
            resolution_notes = data.get('resolution_notes', '')

            alert.resolved = True
            alert.resolved_by = resolved_by
            alert.resolved_at = utc_now()
            alert.resolution_notes = resolution_notes
            alert.updated_at = utc_now()

            db.session.commit()

            logger.info('Resolved alert %d by %s', alert_id, resolved_by)

            return jsonify({'message': 'Alert resolved successfully'})

        except Exception as exc:
            logger.error('Error resolving alert %d: %s', alert_id, exc)
            db.session.rollback()
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/devices', methods=['GET'])
    def api_discover_audio_devices():
        """Discover available audio input devices."""
        try:
            devices = []

            # Try to discover ALSA devices
            try:
                import alsaaudio
                alsa_devices = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
                for idx, device_name in enumerate(alsa_devices):
                    devices.append({
                        'type': 'alsa',
                        'device_id': device_name,
                        'device_index': idx,
                        'name': device_name,
                        'description': f'ALSA Device: {device_name}',
                    })
            except ImportError:
                logger.debug('alsaaudio not available for device discovery')
            except Exception as exc:
                logger.warning('Error discovering ALSA devices: %s', exc)

            # Try to discover PulseAudio/PyAudio devices
            try:
                import pyaudio
                pa = pyaudio.PyAudio()
                for idx in range(pa.get_device_count()):
                    device_info = pa.get_device_info_by_index(idx)
                    if device_info['maxInputChannels'] > 0:
                        devices.append({
                            'type': 'pulse',
                            'device_id': str(idx),
                            'device_index': idx,
                            'name': device_info['name'],
                            'description': f"PulseAudio: {device_info['name']}",
                            'sample_rate': int(device_info['defaultSampleRate']),
                            'max_channels': device_info['maxInputChannels'],
                        })
                pa.terminate()
            except ImportError:
                logger.debug('pyaudio not available for device discovery')
            except Exception as exc:
                logger.warning('Error discovering PulseAudio devices: %s', exc)

            return jsonify({
                'devices': devices,
                'total': len(devices),
            })

        except Exception as exc:
            logger.error('Error discovering audio devices: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/waveform/<source_name>', methods=['GET'])
    def api_get_waveform(source_name: str):
        """Get waveform data for a specific audio source."""
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            # Get waveform data from adapter
            waveform_data = adapter.get_waveform_data()

            # Convert to list for JSON serialization
            waveform_list = waveform_data.tolist()

            return jsonify({
                'source_name': source_name,
                'waveform': waveform_list,
                'sample_count': len(waveform_list),
                'timestamp': time.time(),
                'status': adapter.status.value,
            })

        except Exception as exc:
            logger.error('Error getting waveform for %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/spectrogram/<source_name>')
    def api_get_spectrogram(source_name: str):
        """Get spectrogram data for a specific audio source (for waterfall display)."""
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            # Get spectrogram data from adapter
            spectrogram_data = adapter.get_spectrogram_data()

            # Convert to list for JSON serialization
            # Shape: [time_frames, frequency_bins]
            spectrogram_list = spectrogram_data.tolist()

            return jsonify({
                'source_name': source_name,
                'spectrogram': spectrogram_list,
                'time_frames': len(spectrogram_list),
                'frequency_bins': len(spectrogram_list[0]) if len(spectrogram_list) > 0 else 0,
                'sample_rate': adapter.config.sample_rate,
                'fft_size': adapter._fft_size,
                'timestamp': time.time(),
                'status': adapter.status.value,
            })

        except Exception as exc:
            logger.error('Error getting spectrogram for %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/stream/<source_name>')
    def api_stream_audio(source_name: str):
        """Stream live audio from a specific source as WAV."""
        import struct
        import io
        from flask import Response, stream_with_context

        def generate_wav_stream():
            """Generator that yields WAV-formatted audio chunks."""
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                logger.error(f'Audio source not found: {source_name}')
                return

            if adapter.status != AudioSourceStatus.RUNNING:
                logger.error(f'Audio source not running: {source_name}')
                return

            # WAV header for streaming (we'll use a placeholder for data size)
            sample_rate = adapter.config.sample_rate
            channels = adapter.config.channels
            bits_per_sample = 16  # 16-bit PCM

            # Build WAV header
            wav_header = io.BytesIO()
            wav_header.write(b'RIFF')
            wav_header.write(struct.pack('<I', 0xFFFFFFFF))  # Placeholder for file size
            wav_header.write(b'WAVE')

            # fmt chunk
            wav_header.write(b'fmt ')
            wav_header.write(struct.pack('<I', 16))  # fmt chunk size
            wav_header.write(struct.pack('<H', 1))   # PCM format
            wav_header.write(struct.pack('<H', channels))
            wav_header.write(struct.pack('<I', sample_rate))
            wav_header.write(struct.pack('<I', sample_rate * channels * bits_per_sample // 8))  # byte rate
            wav_header.write(struct.pack('<H', channels * bits_per_sample // 8))  # block align
            wav_header.write(struct.pack('<H', bits_per_sample))

            # data chunk header
            wav_header.write(b'data')
            wav_header.write(struct.pack('<I', 0xFFFFFFFF))  # Placeholder for data size

            yield wav_header.getvalue()

            # Pre-buffer audio for smooth playback (VLC-style buffering)
            logger.info(f'Pre-buffering audio for {source_name}')
            prebuffer = []
            prebuffer_target = int(sample_rate * 2)  # 2 seconds of audio
            prebuffer_samples = 0
            prebuffer_timeout = 5.0  # Max 5 seconds to fill prebuffer
            prebuffer_start = time.time()

            while prebuffer_samples < prebuffer_target:
                if time.time() - prebuffer_start > prebuffer_timeout:
                    logger.warning(f'Prebuffer timeout for {source_name}, starting with {prebuffer_samples}/{prebuffer_target} samples')
                    break

                audio_chunk = adapter.get_audio_chunk(timeout=0.2)
                if audio_chunk is not None:
                    import numpy as np
                    if not isinstance(audio_chunk, np.ndarray):
                        audio_chunk = np.array(audio_chunk, dtype=np.float32)

                    prebuffer.append(audio_chunk)
                    prebuffer_samples += len(audio_chunk)

            # Yield pre-buffered audio
            logger.info(f'Streaming {len(prebuffer)} pre-buffered chunks for {source_name}')
            for chunk in prebuffer:
                pcm_data = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
                yield pcm_data.tobytes()

            # Stream audio chunks
            logger.info(f'Starting live audio stream for {source_name}')
            chunk_count = len(prebuffer)
            max_chunks = 999999999  # Effectively unlimited - stream until client disconnects
            silence_count = 0
            max_consecutive_silence = 200  # 10 seconds of silence before stopping (increased from 1s)

            try:
                while chunk_count < max_chunks:
                    # Get audio chunk from adapter (very short timeout to keep stream responsive)
                    audio_chunk = adapter.get_audio_chunk(timeout=0.05)

                    if audio_chunk is None:
                        # No data available - yield silence to keep HTTP stream alive
                        if adapter.status != AudioSourceStatus.RUNNING:
                            logger.info(f'Audio source stopped: {source_name}')
                            break

                        # Yield a small chunk of silence (0.05 seconds worth)
                        # This keeps the HTTP connection alive and prevents browser timeout
                        silence_samples = int(sample_rate * channels * 0.05)
                        import numpy as np
                        silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                        yield silence_chunk.tobytes()

                        silence_count += 1
                        if silence_count > max_consecutive_silence:
                            logger.warning(f'Too many consecutive silent chunks for {source_name}, stopping stream')
                            break
                        continue

                    # Reset silence counter when we get real data
                    silence_count = 0

                    # Convert float32 [-1, 1] to int16 PCM
                    # Ensure we have a numpy array
                    import numpy as np
                    if not isinstance(audio_chunk, np.ndarray):
                        audio_chunk = np.array(audio_chunk, dtype=np.float32)

                    # Clip to [-1, 1] range and convert to int16
                    audio_chunk = np.clip(audio_chunk, -1.0, 1.0)
                    pcm_data = (audio_chunk * 32767).astype(np.int16)

                    # Convert to bytes and yield
                    yield pcm_data.tobytes()

                    chunk_count += 1

            except GeneratorExit:
                logger.info(f'Client disconnected from audio stream: {source_name}')
            except Exception as exc:
                logger.error(f'Error streaming audio from {source_name}: {exc}')

        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)

            if not adapter:
                return jsonify({'error': 'Source not found'}), 404

            if adapter.status != AudioSourceStatus.RUNNING:
                return jsonify({'error': 'Source not running. Please start the source first.'}), 400

            return Response(
                stream_with_context(generate_wav_stream()),
                mimetype='audio/wav',
                headers={
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0',
                    'X-Content-Type-Options': 'nosniff',
                }
            )

        except Exception as exc:
            logger.error('Error setting up audio stream for %s: %s', source_name, exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/health/dashboard', methods=['GET'])
    def api_get_health_dashboard():
        """Get comprehensive health metrics for dashboard display."""
        try:
            controller = _get_audio_controller()

            # Get all source metrics
            source_health = []
            total_restarts = 0
            healthy_count = 0
            degraded_count = 0
            failed_count = 0

            for source_name, adapter in controller._sources.items():
                metrics = adapter.metrics
                status = adapter.status

                # Categorize health
                if status.value == 'running':
                    if not metrics.silence_detected:
                        healthy_count += 1
                        health_status = 'healthy'
                    else:
                        degraded_count += 1
                        health_status = 'degraded'
                else:
                    failed_count += 1
                    health_status = 'failed'

                source_health.append({
                    'name': source_name,
                    'status': status.value,
                    'health': health_status,
                    'uptime_seconds': time.time() - adapter._start_time if hasattr(adapter, '_start_time') and adapter._start_time > 0 else 0,
                    'peak_level_db': _sanitize_float(metrics.peak_level_db),
                    'rms_level_db': _sanitize_float(metrics.rms_level_db),
                    'silence_detected': metrics.silence_detected,
                    'buffer_utilization': _sanitize_float(metrics.buffer_utilization * 100),
                })

            # Calculate overall health score (0-100)
            total_sources = len(controller._sources)
            if total_sources > 0:
                health_score = (
                    (healthy_count * 100) +
                    (degraded_count * 50) +
                    (failed_count * 0)
                ) / total_sources
            else:
                health_score = 0

            return jsonify({
                'overall_health_score': health_score,
                'total_sources': total_sources,
                'healthy_count': healthy_count,
                'degraded_count': degraded_count,
                'failed_count': failed_count,
                'source_health': source_health,
                'timestamp': time.time()
            })

        except Exception as exc:
            logger.error('Error getting health dashboard: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/health/metrics', methods=['GET'])
    def api_get_health_metrics():
        """Get real-time metrics for all sources."""
        try:
            controller = _get_audio_controller()
            metrics_list = []

            for source_name, adapter in controller._sources.items():
                metrics = adapter.metrics

                metrics_list.append({
                    'source_name': source_name,
                    'timestamp': metrics.timestamp,
                    'peak_level_db': _sanitize_float(metrics.peak_level_db),
                    'rms_level_db': _sanitize_float(metrics.rms_level_db),
                    'sample_rate': metrics.sample_rate,
                    'frames_captured': metrics.frames_captured,
                    'silence_detected': metrics.silence_detected,
                    'buffer_utilization': _sanitize_float(metrics.buffer_utilization * 100),
                })

            return jsonify({
                'metrics': metrics_list,
                'timestamp': time.time()
            })

        except Exception as exc:
            logger.error('Error getting health metrics: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/icecast/config', methods=['GET'])
    def api_get_icecast_config():
        """Get Icecast rebroadcast configuration."""
        try:
            # TODO: Load from database or config file
            return jsonify({
                'enabled': False,
                'server': 'localhost',
                'port': 8000,
                'password': '***',
                'mount': '/eas-station',
                'name': 'EAS Station Audio',
                'description': 'Emergency Alert System Audio Monitor',
                'genre': 'Emergency',
                'bitrate': 128
            })
        except Exception as exc:
            logger.error('Error getting Icecast config: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/audio/icecast/config', methods=['POST'])
    def api_update_icecast_config():
        """Update Icecast rebroadcast configuration."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            # TODO: Validate and save to database
            # TODO: Restart Icecast streamer if enabled

            return jsonify({
                'message': 'Icecast configuration updated',
                'config': data
            })

        except Exception as exc:
            logger.error('Error updating Icecast config: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/audio/health/dashboard')
    def audio_health_dashboard():
        """Render the health monitoring dashboard page."""
        return render_template('audio/health_dashboard.html')


__all__ = ['register_audio_ingest_routes']
