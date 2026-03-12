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

"""Text-to-Speech settings management routes."""

import base64
import logging
import struct
import wave
import io
from typing import Any, Dict

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import BadRequest

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.tts_settings import (
    get_tts_settings,
    update_tts_settings,
)

logger = logging.getLogger(__name__)

# Create Blueprint for TTS routes
tts_bp = Blueprint('tts', __name__)


# Routes are relative to blueprint's url_prefix='/admin'
# e.g., route '/tts' becomes '/admin/tts'
@tts_bp.route('/tts')
@require_permission('system.configure')
def tts_settings_page():
    """Display TTS configuration page."""
    try:
        settings = get_tts_settings()

        return render_template(
            'admin/tts.html',
            settings=settings,
        )
    except Exception as exc:
        logger.error(f"Failed to load TTS settings: {exc}")
        flash(f"Error loading TTS settings: {exc}", "error")
        return redirect(url_for('admin.index'))


@tts_bp.route('/api/tts/settings', methods=['GET'])
@require_permission('system.configure')
def get_settings():
    """Get current TTS settings."""
    try:
        settings = get_tts_settings()
        return jsonify({
            "success": True,
            "settings": settings.to_dict(),
        })
    except Exception as exc:
        logger.error(f"Failed to get TTS settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tts_bp.route('/api/tts/settings', methods=['PUT'])
@require_permission('system.configure')
def update_settings():
    """Update TTS settings."""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        # Convert boolean fields
        bool_fields = ['enabled']
        for field in bool_fields:
            if field in data:
                if isinstance(data[field], str):
                    data[field] = data[field].lower() in ('true', '1', 'yes', 'on')
                else:
                    data[field] = bool(data[field])

        # Convert float fields
        if 'azure_openai_speed' in data and data['azure_openai_speed'] is not None:
            if data['azure_openai_speed'] == '' or data['azure_openai_speed'] == 'None':
                data['azure_openai_speed'] = 1.0
            else:
                try:
                    speed = float(data['azure_openai_speed'])
                    if speed < 0.25 or speed > 4.0:
                        raise BadRequest("Speed must be between 0.25 and 4.0")
                    data['azure_openai_speed'] = speed
                except (TypeError, ValueError):
                    raise BadRequest("Invalid value for speed: must be a number")

        # Validate provider
        if 'provider' in data:
            valid_providers = ['', 'azure_openai', 'azure', 'pyttsx3']
            if data['provider'] not in valid_providers:
                raise BadRequest(f"Invalid provider. Must be one of: {', '.join(valid_providers)}")

        # Update settings
        settings = update_tts_settings(data)

        logger.info(f"TTS settings updated successfully")

        return jsonify({
            "success": True,
            "message": "TTS settings updated successfully. Changes take effect immediately.",
            "settings": settings.to_dict(),
        })

    except BadRequest as exc:
        logger.warning(f"Bad request updating TTS settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    except Exception as exc:
        logger.error(f"Failed to update TTS settings: {exc}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@tts_bp.route('/api/tts/test', methods=['POST'])
@require_permission('system.configure')
def test_tts():
    """Test TTS configuration with a sample message.
    
    This endpoint generates a test TTS audio to verify settings work correctly.
    """
    try:
        data = request.get_json() if request.is_json else {}
        test_message = data.get('message', 'This is a test of the text to speech system.')
        
        # Load current TTS settings
        settings = get_tts_settings()
        
        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "TTS is not enabled. Enable it in settings first."
            }), 400
        
        if not settings.provider:
            return jsonify({
                "success": False,
                "error": "TTS provider is not configured. Select a provider in settings."
            }), 400
        
        # Build config dict for TTSEngine
        from app_utils.eas_tts import TTSEngine
        
        config = {
            'tts_provider': settings.provider,
            'azure_openai_endpoint': settings.azure_openai_endpoint or '',
            'azure_openai_key': settings.azure_openai_key or '',
            'azure_openai_model': settings.azure_openai_model or 'tts-1',
            'azure_openai_voice': settings.azure_openai_voice or 'alloy',
            'azure_openai_speed': settings.azure_openai_speed or 1.0,
            'azure_speech_key': settings.azure_speech_key or '',
            'azure_speech_region': settings.azure_speech_region or '',
            'azure_speech_voice': settings.azure_speech_voice or 'en-US-AriaNeural',
            'azure_speech_sample_rate': settings.azure_speech_sample_rate or 24000,
        }
        
        # Create TTS engine
        tts_engine = TTSEngine(config, logger, 16000)
        
        logger.info(f"Testing TTS with provider '{settings.provider}' and message: '{test_message[:50]}...'")
        
        # Generate TTS
        samples = tts_engine.generate(test_message)
        
        if samples:
            # Success! Convert samples to WAV and encode as base64
            duration_seconds = len(samples) / 16000
            logger.info(f"TTS test successful: Generated {len(samples)} samples ({duration_seconds:.2f} seconds)")
            
            # Convert samples to WAV format for playback
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(16000)
                # Convert samples to bytes (16-bit signed integers)
                audio_bytes = struct.pack(f'<{len(samples)}h', *samples)
                wav_file.writeframes(audio_bytes)
            
            wav_buffer.seek(0)
            audio_base64 = base64.b64encode(wav_buffer.read()).decode('utf-8')
            
            return jsonify({
                "success": True,
                "message": f"TTS test successful! Generated {duration_seconds:.2f} seconds of audio.",
                "audio_data": audio_base64,
                "audio_type": "audio/wav",
                "details": {
                    "provider": settings.provider,
                    "voice": settings.azure_openai_voice if settings.provider == 'azure_openai' else 'default',
                    "samples": len(samples),
                    "duration_seconds": round(duration_seconds, 2),
                    "sample_rate": 16000
                }
            })
        else:
            # Failed - get error details
            error_msg = tts_engine.last_error or "Unknown error - no audio generated"
            logger.error(f"TTS test failed: {error_msg}")
            
            return jsonify({
                "success": False,
                "error": f"TTS test failed: {error_msg}",
                "details": {
                    "provider": settings.provider,
                    "message": "Check system logs for detailed error information"
                }
            }), 500
    
    except Exception as exc:
        logger.error(f"TTS test failed with exception: {exc}")
        logger.exception("TTS test exception details:")
        return jsonify({
            "success": False,
            "error": f"TTS test failed: {str(exc)}"
        }), 500


def register_tts_routes(app, logger):
    """Register TTS admin routes with the Flask app.
    
    Routes are registered with url_prefix='/admin', so Flask combines them:
    - Blueprint route '/tts' becomes '/admin/tts'
    - Blueprint route '/api/tts/settings' becomes '/admin/api/tts/settings'
    
    IMPORTANT: Do NOT add '/admin' prefix to route decorators above, as Flask
    will combine url_prefix with the route path, resulting in doubled paths
    like '/admin/admin/tts' which will cause 404 errors.
    """
    app.register_blueprint(tts_bp, url_prefix='/admin')
    logger.info("TTS admin routes registered")


__all__ = ['tts_bp', 'register_tts_routes']
