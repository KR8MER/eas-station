"""
EAS Decoder Monitor Settings Admin Page

Allows configuration of EAS decoder audio monitoring tap.
Users can listen to the actual 16 kHz resampled audio fed to the SAME decoder
to verify correct sample rate and audio quality.
"""

from flask import Blueprint, render_template, request, jsonify
from werkzeug.exceptions import BadRequest
import logging

from app_core import db
from app_core.models import EASDecoderMonitorSettings
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger

logger = logging.getLogger(__name__)

eas_decoder_monitor_bp = Blueprint('eas_decoder_monitor', __name__)


@eas_decoder_monitor_bp.route('/admin/eas_decoder_monitor')
def eas_decoder_monitor_page():
    """Render EAS decoder monitor settings page."""
    return render_template('admin/eas_decoder_monitor.html')


@eas_decoder_monitor_bp.route('/api/admin/eas_decoder_monitor/settings', methods=['GET'])
def get_eas_decoder_monitor_settings():
    """Get current EAS decoder monitor settings."""
    try:
        settings = EASDecoderMonitorSettings.query.first()
        if not settings:
            # Create default settings if none exist
            settings = EASDecoderMonitorSettings(
                enabled=False,
                stream_name='eas-decoder-monitor'
            )
            db.session.add(settings)
            db.session.commit()
        
        return jsonify(settings.to_dict())
    except Exception as exc:
        logger.error(f'Error getting EAS decoder monitor settings: {exc}')
        return jsonify({'error': str(exc)}), 500


@eas_decoder_monitor_bp.route('/api/admin/eas_decoder_monitor/settings', methods=['PUT'])
@require_permission('system.configure')
def update_eas_decoder_monitor_settings():
    """Update EAS decoder monitor settings."""
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            raise BadRequest('Invalid JSON payload')
        
        settings = EASDecoderMonitorSettings.query.first()
        if not settings:
            settings = EASDecoderMonitorSettings()
            db.session.add(settings)
        
        # Update enabled status
        if 'enabled' in data:
            settings.enabled = bool(data['enabled'])
        
        # Update stream name
        if 'stream_name' in data:
            stream_name = str(data['stream_name']).strip()
            if not stream_name:
                raise BadRequest('Stream name cannot be empty')
            settings.stream_name = stream_name
        
        db.session.commit()

        # Only record fields this handler actually processes/persists, so the
        # tamper-evident entry can't misstate what changed from raw client input.
        allowed_keys = {'enabled', 'stream_name'}
        AuditLogger.log_config_change(
            resource_type='eas_decoder_monitor_settings',
            resource_id=str(settings.id) if getattr(settings, 'id', None) is not None else None,
            details={'changed_fields': sorted(k for k in data if k in allowed_keys)},
        )

        return jsonify({
            'message': 'EAS decoder monitor settings updated',
            'settings': settings.to_dict()
        })
    except Exception as exc:
        db.session.rollback()
        logger.error(f'Error updating EAS decoder monitor settings: {exc}')
        return jsonify({'error': str(exc)}), 500


@eas_decoder_monitor_bp.route('/api/admin/eas_decoder_monitor/test_signal', methods=['POST'])
@require_permission('system.configure')
def inject_eas_test_signal():
    """Inject a SAME RWT test signal into the EAS decoder pipeline.

    Generates a standards-compliant SAME header at 16 kHz and publishes it
    directly to the EAS broadcast queue of one or all running audio sources.
    The signal flows through the UnifiedEASMonitorService decoder and through
    any active EAS ingest Icecast streams so operators can verify the full
    pipeline without needing external equipment.

    The command is routed to the audio-service process via Redis so that it
    runs against the sources that are actually RUNNING there, not the
    webapp's unstarted controller.

    Optional JSON body:
        source_name (str): Target a specific source by name.  Omit to use the
                           first running source.
    """
    try:
        data = request.get_json(silent=True) or {}
        target_source = data.get('source_name') if isinstance(data, dict) else None

        from app_core.audio.redis_commands import get_audio_command_publisher
        publisher = get_audio_command_publisher()
        result = publisher.inject_test_signal(source_name=target_source)

        if not result.get('success'):
            msg = result.get('message', 'Unknown error')
            logger.warning("EAS test signal injection failed: %s", msg)
            return jsonify({'error': msg}), 404

        used_source = (result.get('data') or {}).get('source_name', 'unknown')
        logger.info("EAS test signal injected into source '%s' via admin UI", used_source)
        return jsonify({
            'message': result.get('message', f"EAS test signal injected into source '{used_source}'"),
            'source_name': used_source,
        })
    except Exception as exc:
        logger.error('Error injecting EAS test signal: %s', exc, exc_info=True)
        return jsonify({'error': str(exc)}), 500


def register_blueprint(app):
    """Register the blueprint with the Flask app."""
    app.register_blueprint(eas_decoder_monitor_bp)
