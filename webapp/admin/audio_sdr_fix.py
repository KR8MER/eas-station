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

"""Audio/SDR Configuration Fix - Web-based sample rate correction."""

import json
import logging
from typing import Dict, List, Any

from flask import Blueprint, jsonify, render_template, request, flash, redirect, url_for
from sqlalchemy import text

from app_core.extensions import db
from app_core.models import RadioReceiver

logger = logging.getLogger(__name__)

# Create Blueprint
audio_sdr_fix_bp = Blueprint('audio_sdr_fix', __name__)


def register_audio_sdr_fix_routes(app):
    """Register audio/SDR fix routes."""
    app.register_blueprint(audio_sdr_fix_bp)
    logger.info("Audio/SDR fix routes registered")


@audio_sdr_fix_bp.route('/admin/audio-sdr-fix')
def audio_sdr_fix_page():
    """Display the audio/SDR configuration fix page."""
    return render_template('admin/audio_sdr_fix.html')


@audio_sdr_fix_bp.route('/api/admin/audio-sdr-fix/diagnose', methods=['GET'])
def diagnose_audio_sdr():
    """Diagnose audio/SDR configuration issues."""
    try:
        issues = []
        warnings = []

        # Check SDR receivers (IQ sample rate)
        receivers = RadioReceiver.query.filter_by(enabled=True).all()

        for receiver in receivers:
            receiver_info = {
                'id': receiver.id,
                'identifier': receiver.identifier,
                'display_name': receiver.display_name,
                'driver': receiver.driver,
                'frequency_hz': receiver.frequency_hz,
                'frequency_mhz': round(receiver.frequency_hz / 1_000_000, 3) if receiver.frequency_hz else 0,
                'sample_rate': receiver.sample_rate,
                'modulation_type': receiver.modulation_type,
                'audio_output': receiver.audio_output,
                'stereo_enabled': receiver.stereo_enabled,
                'type': 'receiver'
            }

            # Check if IQ sample rate is too low
            if receiver.sample_rate < 100000:
                receiver_info['issue'] = f"IQ sample rate too low: {receiver.sample_rate} Hz (should be ~2.4 MHz)"
                receiver_info['recommended'] = 2400000
                receiver_info['severity'] = 'error'
                issues.append(receiver_info)
            else:
                receiver_info['status'] = 'ok'
                receiver_info['severity'] = 'success'

        # Check audio source configs
        result = db.session.execute(text("""
            SELECT
                id,
                name,
                source_type,
                enabled,
                auto_start,
                (config->>'sample_rate')::int as audio_sample_rate,
                (config->>'channels')::int as channels,
                config->'device_params'->>'stream_url' as stream_url,
                config->'device_params'->>'receiver_id' as receiver_id
            FROM audio_source_configs
            WHERE enabled = true
            ORDER BY source_type, name
        """))

        audio_sources = []
        for row in result:
            source_info = {
                'id': row.id,
                'name': row.name,
                'source_type': row.source_type,
                'audio_sample_rate': row.audio_sample_rate,
                'channels': row.channels,
                'stream_url': row.stream_url,
                'receiver_id': row.receiver_id,
                'type': 'audio_source'
            }

            # Check HTTP streams
            if row.source_type == 'stream' and row.audio_sample_rate < 32000:
                source_info['issue'] = f"Audio rate too low: {row.audio_sample_rate} Hz (should be 44.1-48 kHz)"
                source_info['recommended'] = 48000
                source_info['severity'] = 'error'
                issues.append(source_info)
            # Check SDR sources
            elif row.source_type == 'sdr' and row.audio_sample_rate < 20000:
                source_info['issue'] = f"Audio output rate too low: {row.audio_sample_rate} Hz (should be 24-48 kHz)"
                source_info['recommended'] = 48000
                source_info['severity'] = 'error'
                issues.append(source_info)
            else:
                source_info['status'] = 'ok'
                source_info['severity'] = 'success'
                audio_sources.append(source_info)

        # All items (issues + ok sources)
        all_items = issues + audio_sources

        return jsonify({
            'success': True,
            'issues': issues,
            'warnings': warnings,
            'all_configs': all_items,
            'summary': {
                'total_receivers': len(receivers),
                'total_audio_sources': len(audio_sources) + len([i for i in issues if i['type'] == 'audio_source']),
                'total_issues': len(issues),
                'total_warnings': len(warnings)
            }
        })

    except Exception as e:
        logger.error(f"Error diagnosing audio/SDR config: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@audio_sdr_fix_bp.route('/api/admin/audio-sdr-fix/apply', methods=['POST'])
def apply_audio_sdr_fixes():
    """Apply fixes to audio/SDR configuration."""
    try:
        data = request.get_json() or {}
        auto_fix = data.get('auto_fix', False)

        fixes_applied = []
        errors = []

        # Fix SDR receivers (IQ sample rate)
        receivers = RadioReceiver.query.filter_by(enabled=True).all()

        for receiver in receivers:
            if receiver.sample_rate < 100000:
                try:
                    old_rate = receiver.sample_rate
                    receiver.sample_rate = 2400000  # 2.4 MHz for RTL-SDR

                    fixes_applied.append({
                        'type': 'receiver',
                        'identifier': receiver.identifier,
                        'display_name': receiver.display_name,
                        'field': 'sample_rate (IQ)',
                        'old_value': old_rate,
                        'new_value': 2400000,
                        'unit': 'Hz'
                    })
                except Exception as e:
                    errors.append({
                        'type': 'receiver',
                        'identifier': receiver.identifier,
                        'error': str(e)
                    })

        # Fix audio source configs
        if auto_fix:
            # Fix HTTP streams
            db.session.execute(text("""
                UPDATE audio_source_configs
                SET config = jsonb_set(config, '{sample_rate}', '48000'::jsonb)
                WHERE source_type = 'stream'
                  AND enabled = true
                  AND (config->>'sample_rate')::int < 32000
            """))

            # Fix SDR audio sources
            db.session.execute(text("""
                UPDATE audio_source_configs
                SET config = jsonb_set(config, '{sample_rate}', '48000'::jsonb)
                WHERE source_type = 'sdr'
                  AND enabled = true
                  AND (config->>'sample_rate')::int < 20000
            """))

            fixes_applied.append({
                'type': 'audio_sources',
                'description': 'Updated all HTTP and SDR audio source sample rates to 48 kHz',
                'field': 'sample_rate (audio output)',
                'new_value': 48000,
                'unit': 'Hz'
            })

        # Commit all changes
        db.session.commit()

        return jsonify({
            'success': True,
            'fixes_applied': fixes_applied,
            'errors': errors,
            'message': f'Applied {len(fixes_applied)} fix(es) successfully'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error applying audio/SDR fixes: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@audio_sdr_fix_bp.route('/api/admin/audio-sdr-fix/restart-service', methods=['POST'])
def restart_sdr_service():
    """Request to restart SDR service (requires external action)."""
    # This endpoint just acknowledges the request
    # Actual restart needs to be done via docker compose from the host
    return jsonify({
        'success': True,
        'message': 'Please restart the SDR service manually using: sudo docker compose restart sdr-service',
        'command': 'sudo docker compose -f docker-compose.yml -f docker-compose.pi.yml restart sdr-service'
    })
