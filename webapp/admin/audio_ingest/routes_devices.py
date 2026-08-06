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

from __future__ import annotations

"""Device discovery, waveform, spectrogram and live stream endpoints."""

import logging
import json
import time
from flask import Blueprint, Flask, jsonify, render_template, request, current_app, Response, stream_with_context

from .blueprint import audio_ingest_bp

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/devices', methods=['GET'])
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


@audio_ingest_bp.route('/api/audio/waveform/<path:source_name>', methods=['GET'])
def api_get_waveform(source_name: str):
    """Get waveform data for a specific audio source.

    Reads waveform data from Redis, published by the audio-service.
    """
    try:
        from app_core.redis_client import get_redis_client
        
        # Get waveform data from Redis
        r = get_redis_client()
        waveform_key = f"eas:waveform:{source_name}"
        waveform_json = r.get(waveform_key)
        
        if not waveform_json:
            # No waveform data available - source may not be running
            return jsonify({
                'source_name': source_name,
                'waveform': [],
                'sample_count': 0,
                'timestamp': time.time(),
                'status': 'no_data',
                'message': 'No waveform data available - source may not be running'
            }), 200
        
        # Parse and return waveform data
        waveform_data = json.loads(waveform_json)
        return jsonify(waveform_data), 200

    except Exception as exc:
        logger.error('Error getting waveform for %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/spectrogram/<path:source_name>')
def api_get_spectrogram(source_name: str):
    """Spectrogram computation is disabled to reduce CPU usage."""
    return jsonify({
        'source_name': source_name,
        'spectrogram': [],
        'time_frames': 0,
        'frequency_bins': 0,
        'timestamp': time.time(),
        'status': 'disabled',
        'message': 'Spectrogram disabled to reduce CPU usage'
    }), 200


@audio_ingest_bp.route('/api/audio/stream/<path:source_name>')
def api_stream_audio(source_name: str):
    """Audio streaming endpoint - DEPRECATED.
    
    Audio streams are now handled DIRECTLY by nginx, which proxies to audio-service:5002.
    This endpoint should never be called - nginx intercepts /api/audio/stream/ requests.
    
    If you're seeing this, it means:
    1. Nginx configuration is not properly routing audio streams, OR
    2. You're accessing the app directly without going through nginx
    
    Solution: Always access the app through nginx (typically on port 443/HTTPS or 8888/HTTP).
    """
    logger.warning(
        f'Audio stream endpoint called directly for {source_name}. '
        f'This should be handled by nginx. Check your nginx configuration.'
    )
    
    return jsonify({
        'error': 'Audio streaming should be handled by nginx',
        'message': 'Nginx should proxy /api/audio/stream/ directly to audio-service:5002',
        'solution': 'Access the application through nginx (port 443 or 8888), not directly'
    }), 503
