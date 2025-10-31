"""Download endpoints for generated audio assets."""

from __future__ import annotations

import io
import json

from flask import abort, jsonify, request, send_file

from app_core.models import CAPAlert, EASMessage, ManualEASActivation
from app_core.eas_storage import load_or_cache_audio_data, load_or_cache_summary_payload


def register_file_routes(app, logger) -> None:
    """Register routes responsible for serving generated files."""

    @app.route('/eas_messages/<int:message_id>/audio', methods=['GET'])
    def eas_message_audio(message_id: int):
        variant = (request.args.get('variant') or 'primary').strip().lower()
        if variant not in {'primary', 'eom', 'same', 'attention', 'tts', 'buffer'}:
            abort(400, description='Unsupported audio variant.')

        message = EASMessage.query.get_or_404(message_id)
        data = load_or_cache_audio_data(message, variant=variant)
        if not data:
            abort(404, description='Audio not available.')

        download = request.args.get('download', '').strip().lower()
        as_attachment = download in {'1', 'true', 'yes', 'download'}

        metadata = message.metadata_payload or {}
        if variant == 'eom':
            filename = metadata.get('eom_filename') if isinstance(metadata, dict) else None
            if not filename:
                filename = f'eas_message_{message.id}_eom.wav'
        elif variant == 'primary':
            filename = message.audio_filename or f'eas_message_{message.id}.wav'
        else:
            filename = f'eas_message_{message.id}_{variant}.wav'

        file_obj = io.BytesIO(data)
        file_obj.seek(0)
        response = send_file(
            file_obj,
            mimetype='audio/wav',
            as_attachment=as_attachment,
            download_name=filename,
            max_age=0,
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @app.route('/eas_messages/<int:message_id>/summary', methods=['GET'])
    def eas_message_summary(message_id: int):
        message = EASMessage.query.get_or_404(message_id)
        data = load_or_cache_summary_payload(message)

        if not data:
            abort(404, description='Summary not available.')

        if request.args.get('format') == 'json':
            return jsonify(data)

        alert = CAPAlert.query.get(message.cap_alert_id) if message.cap_alert_id else None
        content = json.dumps(
            {
                'message': message.identifier,
                'alert': alert.identifier if alert else None,
                'summary': data,
            },
            indent=2,
            sort_keys=True,
        )

        file_obj = io.BytesIO(content.encode('utf-8'))
        file_obj.seek(0)
        filename = message.text_filename or f'eas_message_{message.id}.json'
        return send_file(
            file_obj,
            mimetype='application/json',
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )

    @app.route('/manual_eas/<int:event_id>/audio/<string:component>', methods=['GET'])
    def manual_eas_audio(event_id: int, component: str):
        component_key = (component or '').strip().lower()
        component_map = {
            'composite': 'composite_audio_data',
            'full': 'composite_audio_data',
            'primary': 'composite_audio_data',
            'same': 'same_audio_data',
            'attention': 'attention_audio_data',
            'tts': 'tts_audio_data',
            'narration': 'tts_audio_data',
            'eom': 'eom_audio_data',
        }

        attr_name = component_map.get(component_key)
        if not attr_name:
            abort(404, description='Unsupported manual audio component.')

        activation = ManualEASActivation.query.get_or_404(event_id)
        blob = getattr(activation, attr_name)
        if not blob:
            abort(404, description='Audio not available for this component.')

        download_flag = (request.args.get('download') or '').strip().lower()
        as_attachment = download_flag in {'1', 'true', 'yes', 'download'}

        filename = f'manual_eas_{activation.id}_{component_key or "audio"}.wav'

        file_obj = io.BytesIO(blob)
        file_obj.seek(0)
        response = send_file(
            file_obj,
            mimetype='audio/wav',
            as_attachment=as_attachment,
            download_name=filename,
            max_age=0,
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
