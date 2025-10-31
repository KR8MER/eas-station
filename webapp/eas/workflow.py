"""Routes backing the EAS workflow area."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from flask import (
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app_core.extensions import db
from app_core.models import AdminUser, EASMessage, ManualEASActivation, SystemLog
from app_utils.eas import (
    EASAudioGenerator,
    ORIGINATOR_DESCRIPTIONS,
    P_DIGIT_MEANINGS,
    PRIMARY_ORIGINATORS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    build_same_header,
    describe_same_header,
    manual_default_same_codes,
    samples_to_wav_bytes,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree


def register_workflow_routes(bp, logger, eas_config) -> None:
    """Register HTML and API routes for the EAS workflow blueprint."""

    workflow_logger = logger.getChild('workflow')

    def _auth_redirect(json_mode: bool = False):
        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            if json_mode:
                return jsonify({'error': 'Authentication required.'}), 401
            return redirect(url_for('login', next=request.url))
        return None

    @bp.route('/')
    def workflow_home():
        """Render the consolidated EAS workflow console."""

        auth_response = _auth_redirect()
        if auth_response is not None:
            return auth_response

        manual_same_defaults = manual_default_same_codes()

        event_options = [
            {'code': code, 'name': entry.get('name', code)}
            for code, entry in EVENT_CODE_REGISTRY.items()
            if '?' not in code
        ]
        event_options.sort(key=lambda option: option['code'])

        originator_choices = [
            {
                'code': code,
                'description': ORIGINATOR_DESCRIPTIONS.get(code, ''),
            }
            for code in PRIMARY_ORIGINATORS
        ]

        state_tree = get_us_state_county_tree()
        same_lookup = get_same_lookup()

        recent_messages: List[EASMessage] = (
            EASMessage.query.order_by(EASMessage.created_at.desc()).limit(10).all()
        )

        return render_template(
            'eas/workflow.html',
            eas_event_codes=event_options,
            eas_originator_choices=originator_choices,
            eas_originator=eas_config.get('originator', 'WXR'),
            eas_station_id=eas_config.get('station_id', 'EASNODES'),
            eas_attention_seconds=eas_config.get('attention_tone_seconds', 8),
            eas_sample_rate=eas_config.get('sample_rate', 16000),
            eas_default_same_codes=manual_same_defaults,
            eas_header_fields=SAME_HEADER_FIELD_DESCRIPTIONS,
            eas_p_digit_meanings=P_DIGIT_MEANINGS,
            eas_fips_states=state_tree,
            eas_fips_lookup=same_lookup,
            eas_originator_descriptions=ORIGINATOR_DESCRIPTIONS,
            eas_recent_messages=recent_messages,
            eas_web_subdir=current_app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
        )

    @bp.route('/manual/generate', methods=['POST'])
    def manual_eas_generate():
        auth_response = _auth_redirect(json_mode=True)
        if auth_response is not None:
            return auth_response

        payload = request.get_json(silent=True) or {}

        def _validation_error(message: str, status: int = 400):
            return jsonify({'error': message}), status

        identifier = (payload.get('identifier') or '').strip()[:120]
        if not identifier:
            identifier = f"MANUAL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        event_code = (payload.get('event_code') or '').strip().upper()
        if not event_code or len(event_code) != 3 or not event_code.isalnum():
            return _validation_error('Event code must be a three-character SAME identifier.')
        if event_code not in EVENT_CODE_REGISTRY or '?' in event_code:
            return _validation_error('Select a recognised SAME event code.')

        event_name = (payload.get('event_name') or '').strip()
        if not event_name:
            registry_entry = EVENT_CODE_REGISTRY.get(event_code)
            event_name = registry_entry.get('name', event_code) if registry_entry else event_code

        same_input = payload.get('same_codes')
        if isinstance(same_input, str):
            raw_codes = re.split(r'[^0-9]+', same_input)
        elif isinstance(same_input, list):
            raw_codes = []
            for item in same_input:
                if item is None:
                    continue
                raw_codes.extend(re.split(r'[^0-9]+', str(item)))
        else:
            raw_codes = []

        location_codes: List[str] = []
        seen_codes = set()
        for code in raw_codes:
            digits = ''.join(ch for ch in str(code) if ch.isdigit())
            if not digits:
                continue
            normalized = digits.zfill(6)[:6]
            if normalized in seen_codes:
                continue
            seen_codes.add(normalized)
            location_codes.append(normalized)

        if not location_codes:
            return _validation_error('At least one SAME/FIPS location code is required.')

        if len(location_codes) > 31:
            return _validation_error('The SAME specification allows at most 31 location codes per activation.')

        try:
            duration_minutes = float(payload.get('duration_minutes', 15) or 15)
        except (TypeError, ValueError):
            return _validation_error('Duration must be a numeric value representing minutes.')
        if duration_minutes <= 0:
            return _validation_error('Duration must be greater than zero minutes.')

        tone_seconds_raw = payload.get('tone_seconds')
        if tone_seconds_raw in (None, '', 'null'):
            tone_seconds = None
        else:
            try:
                tone_seconds = float(tone_seconds_raw)
            except (TypeError, ValueError):
                return _validation_error('Tone duration must be numeric.')

        tone_profile_raw = (payload.get('tone_profile') or 'attention').strip().lower()
        if tone_profile_raw in {'none', 'omit', 'off', 'disabled'}:
            tone_profile = 'none'
        elif tone_profile_raw in {'1050', '1050hz', 'single'}:
            tone_profile = '1050hz'
        else:
            tone_profile = 'attention'

        if tone_profile == 'none':
            tone_seconds = 0.0
        elif tone_seconds is not None and tone_seconds <= 0:
            return _validation_error('Tone duration must be greater than zero seconds when a signal is included.')

        include_tts = bool(payload.get('include_tts', True))

        allowed_originators = set(PRIMARY_ORIGINATORS)
        originator = (payload.get('originator') or eas_config.get('originator', 'WXR')).strip().upper() or 'WXR'
        if originator not in allowed_originators:
            return _validation_error('Originator must be one of the authorised SAME senders.')

        station_id = (payload.get('station_id') or eas_config.get('station_id', 'EASNODES')).strip() or 'EASNODES'

        status = (payload.get('status') or 'Actual').strip() or 'Actual'
        message_type = (payload.get('message_type') or 'Alert').strip() or 'Alert'

        try:
            sample_rate = int(payload.get('sample_rate') or eas_config.get('sample_rate', 16000) or 16000)
        except (TypeError, ValueError):
            return _validation_error('Sample rate must be an integer value.')
        if sample_rate < 8000 or sample_rate > 48000:
            return _validation_error('Sample rate must be between 8000 and 48000 Hz.')

        sent_dt = datetime.now(timezone.utc)
        expires_dt = sent_dt + timedelta(minutes=duration_minutes)

        manual_config = dict(eas_config)
        manual_config['enabled'] = True
        manual_config['originator'] = originator[:3].upper()
        manual_config['station_id'] = station_id.upper().ljust(8)[:8]
        manual_config['attention_tone_seconds'] = (
            tone_seconds if tone_seconds is not None else manual_config.get('attention_tone_seconds', 8)
        )
        manual_config['sample_rate'] = sample_rate

        alert_object = SimpleNamespace(
            identifier=identifier,
            event=event_name or event_code,
            headline=(payload.get('headline') or '').strip(),
            description=(payload.get('message') or '').strip(),
            instruction=(payload.get('instruction') or '').strip(),
            sent=sent_dt,
            expires=expires_dt,
            status=status,
            message_type=message_type,
        )

        payload_wrapper: Dict[str, Any] = {
            'identifier': identifier,
            'sent': sent_dt,
            'expires': expires_dt,
            'status': status,
            'message_type': message_type,
            'raw_json': {
                'properties': {
                    'geocode': {
                        'SAME': location_codes,
                    }
                }
            },
        }

        try:
            header, formatted_locations, resolved_event_code = build_same_header(
                alert_object,
                payload_wrapper,
                manual_config,
                location_settings=None,
            )
        except Exception as exc:
            workflow_logger.error('Failed to build manual SAME header: %s', exc)
            return jsonify({'error': 'Unable to build SAME header.'}), 500

        generator = EASAudioGenerator(manual_config, logger=workflow_logger)

        try:
            components = generator.build_manual_components(
                alert_object,
                header,
                tone_profile=tone_profile,
                tone_duration=tone_seconds,
                include_tts=include_tts,
            )
        except Exception as exc:
            workflow_logger.error('Manual EAS generation failed: %s', exc)
            return jsonify({'error': 'Failed to generate manual EAS package.'}), 500

        if not components:
            return jsonify({'error': 'Manual EAS package contained no audio components.'}), 500

        def _safe_base(value: str) -> str:
            cleaned = re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_')
            return cleaned or 'manual_eas'

        base_name = _safe_base(identifier)
        sample_rate = components.get('sample_rate', sample_rate)

        output_root = str(manual_config.get('output_dir') or current_app.config.get('EAS_OUTPUT_DIR') or '').strip()
        if not output_root:
            workflow_logger.error('Manual EAS output directory is not configured.')
            return jsonify({'error': 'Manual EAS output directory is not configured.'}), 500

        manual_root = os.path.join(output_root, 'manual')
        os.makedirs(manual_root, exist_ok=True)

        timestamp_tag = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        slug = f"{base_name}_{timestamp_tag}"
        event_dir = os.path.join(manual_root, slug)
        os.makedirs(event_dir, exist_ok=True)
        storage_root = '/'.join(part for part in ['manual', slug] if part)
        web_prefix = current_app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')

        def _package_audio(samples: List[int], suffix: str) -> Optional[Dict[str, Any]]:
            if not samples:
                return None
            wav_bytes = samples_to_wav_bytes(samples, sample_rate)
            duration = round(len(samples) / sample_rate, 3)
            filename = f"{slug}_{suffix}.wav"
            file_path = os.path.join(event_dir, filename)
            with open(file_path, 'wb') as handle:
                handle.write(wav_bytes)

            storage_subpath = '/'.join(part for part in [storage_root, filename] if part)
            web_parts = [web_prefix, storage_subpath] if web_prefix else [storage_subpath]
            web_path = '/'.join(part for part in web_parts if part)
            download_url = url_for('static', filename=web_path)
            data_url = f"data:audio/wav;base64,{base64.b64encode(wav_bytes).decode('ascii')}"
            return {
                'filename': filename,
                'data_url': data_url,
                'download_url': download_url,
                'storage_subpath': storage_subpath,
                'duration_seconds': duration,
                'size_bytes': len(wav_bytes),
                'wav_bytes': wav_bytes,
            }

        state_tree = get_us_state_county_tree()
        state_index = {
            state.get('state_fips'): {'abbr': state.get('abbr'), 'name': state.get('name')}
            for state in state_tree
            if state.get('state_fips')
        }
        same_lookup = get_same_lookup()
        header_detail = describe_same_header(header, lookup=same_lookup, state_index=state_index)

        same_component = _package_audio(components.get('same_samples') or [], 'same')
        attention_component = _package_audio(components.get('attention_samples') or [], 'attention')
        tts_component = _package_audio(components.get('tts_samples') or [], 'tts')
        eom_component = _package_audio(components.get('eom_samples') or [], 'eom')
        composite_component = _package_audio(components.get('composite_samples') or [], 'full')

        stored_components = {
            'same': same_component,
            'attention': attention_component,
            'tts': tts_component,
            'eom': eom_component,
            'composite': composite_component,
        }

        response_components = {
            key: {k: v for k, v in value.items() if k != 'wav_bytes'}
            for key, value in stored_components.items()
            if value
        }

        response_payload: Dict[str, Any] = {
            'identifier': identifier,
            'event_code': resolved_event_code,
            'event_name': event_name,
            'same_header': header,
            'same_locations': formatted_locations,
            'eom_header': components.get('eom_header'),
            'tone_profile': components.get('tone_profile'),
            'tone_seconds': components.get('tone_seconds'),
            'message_text': components.get('message_text'),
            'tts_warning': components.get('tts_warning'),
            'tts_provider': components.get('tts_provider'),
            'duration_minutes': duration_minutes,
            'sent_at': sent_dt.isoformat(),
            'expires_at': expires_dt.isoformat(),
            'components': response_components,
            'sample_rate': sample_rate,
            'same_header_detail': header_detail,
            'storage_path': storage_root,
        }

        summary_filename = f"{slug}_summary.json"
        summary_path = os.path.join(event_dir, summary_filename)

        summary_components = {
            key: {
                'filename': value['filename'],
                'duration_seconds': value['duration_seconds'],
                'size_bytes': value['size_bytes'],
                'storage_subpath': value['storage_subpath'],
            }
            for key, value in stored_components.items()
            if value
        }

        summary_payload = {
            'identifier': identifier,
            'event_code': resolved_event_code,
            'event_name': event_name,
            'same_header': header,
            'same_locations': formatted_locations,
            'tone_profile': components.get('tone_profile'),
            'tone_seconds': components.get('tone_seconds'),
            'duration_minutes': duration_minutes,
            'sample_rate': sample_rate,
            'status': status,
            'message_type': message_type,
            'sent_at': sent_dt.isoformat(),
            'expires_at': expires_dt.isoformat(),
            'headline': alert_object.headline,
            'message_text': components.get('message_text'),
            'instruction_text': alert_object.instruction,
            'components': summary_components,
        }

        with open(summary_path, 'w', encoding='utf-8') as handle:
            json.dump(summary_payload, handle, indent=2)

        summary_subpath = '/'.join(part for part in [storage_root, summary_filename] if part)
        summary_parts = [web_prefix, summary_subpath] if web_prefix else [summary_subpath]
        summary_web_path = '/'.join(part for part in summary_parts if part)
        summary_url = url_for('static', filename=summary_web_path)

        response_payload['export_url'] = summary_url

        archive_time = datetime.now(timezone.utc)
        ManualEASActivation.query.filter(ManualEASActivation.archived_at.is_(None)).update(
            {'archived_at': archive_time}, synchronize_session=False
        )

        db_components = {
            key: {
                'filename': value['filename'],
                'duration_seconds': value['duration_seconds'],
                'size_bytes': value['size_bytes'],
                'storage_subpath': value['storage_subpath'],
            }
            for key, value in stored_components.items()
            if value
        }

        activation_record = ManualEASActivation(
            identifier=identifier,
            event_code=resolved_event_code,
            event_name=event_name or resolved_event_code,
            status=status,
            message_type=message_type,
            same_header=header,
            same_locations=formatted_locations,
            tone_profile=components.get('tone_profile') or 'attention',
            tone_seconds=components.get('tone_seconds'),
            sample_rate=sample_rate,
            includes_tts=bool(tts_component),
            tts_warning=components.get('tts_warning'),
            sent_at=sent_dt,
            expires_at=expires_dt,
            headline=alert_object.headline,
            message_text=components.get('message_text'),
            instruction_text=alert_object.instruction,
            duration_minutes=duration_minutes,
            storage_path=storage_root,
            summary_filename=summary_filename,
            components_payload=db_components,
            metadata_payload={
                'summary_subpath': summary_subpath,
                'web_prefix': web_prefix,
                'includes_tts': bool(tts_component),
            },
            composite_audio_data=composite_component.get('wav_bytes') if composite_component else None,
            same_audio_data=same_component.get('wav_bytes') if same_component else None,
            attention_audio_data=attention_component.get('wav_bytes') if attention_component else None,
            tts_audio_data=tts_component.get('wav_bytes') if tts_component else None,
            eom_audio_data=eom_component.get('wav_bytes') if eom_component else None,
        )

        try:
            db.session.add(activation_record)
            db.session.flush()
            db.session.add(
                SystemLog(
                    level='INFO',
                    message='Manual EAS package generated',
                    module='eas',
                    details={
                        'identifier': identifier,
                        'event_code': resolved_event_code,
                        'location_count': len(formatted_locations),
                        'tone_profile': response_payload['tone_profile'],
                        'tts_included': bool(tts_component),
                        'manual_activation_id': activation_record.id,
                        'generated_by': getattr(g.current_user, 'username', 'system'),
                    },
                )
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            workflow_logger.error('Failed to persist manual EAS activation: %s', exc)
            return jsonify({'error': 'Unable to persist manual activation details.'}), 500

        response_payload['activation'] = {
            'id': activation_record.id,
            'created_at': activation_record.created_at.isoformat() if activation_record.created_at else None,
            'print_url': url_for('eas.manual_eas_print', event_id=activation_record.id),
            'export_url': summary_url,
            'components': {
                key: {
                    'download_url': value['download_url'],
                    'filename': value['filename'],
                }
                for key, value in stored_components.items()
                if value
            },
        }

        for key, value in stored_components.items():
            if not value:
                continue
            stream_url = url_for('manual_eas_audio', event_id=activation_record.id, component=key)
            activation_component = response_payload['activation']['components'].get(key)
            if activation_component is not None:
                activation_component['stream_url'] = stream_url
            component_payload = response_payload['components'].get(key)
            if component_payload is not None:
                component_payload['stream_url'] = stream_url

        return jsonify(response_payload)

    @bp.route('/manual/events', methods=['GET'])
    def manual_eas_events():
        auth_response = _auth_redirect(json_mode=True)
        if auth_response is not None:
            return auth_response

        try:
            limit = request.args.get('limit', type=int) or 100
            limit = min(max(limit, 1), 500)
            total = ManualEASActivation.query.count()
            events = (
                ManualEASActivation.query.order_by(ManualEASActivation.created_at.desc())
                .limit(limit)
                .all()
            )

            web_prefix = current_app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')
            items = []

            for event in events:
                components_payload = event.components_payload or {}

                def _component_with_url(component_key: str, meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
                    if not meta:
                        return None
                    storage_subpath = meta.get('storage_subpath')
                    web_parts = [web_prefix, storage_subpath] if storage_subpath else []
                    web_path = '/'.join(part for part in web_parts if part)
                    download_url = url_for('static', filename=web_path) if storage_subpath else None
                    return {
                        'filename': meta.get('filename'),
                        'duration_seconds': meta.get('duration_seconds'),
                        'size_bytes': meta.get('size_bytes'),
                        'storage_subpath': storage_subpath,
                        'download_url': download_url,
                        'stream_url': url_for('manual_eas_audio', event_id=event.id, component=component_key),
                    }

                summary_subpath = None
                if event.summary_filename:
                    summary_subpath = '/'.join(
                        part for part in [event.storage_path, event.summary_filename] if part
                    )
                export_url = (
                    url_for('eas.manual_eas_export', event_id=event.id)
                    if summary_subpath
                    else None
                )

                items.append(
                    {
                        'id': event.id,
                        'identifier': event.identifier,
                        'event_code': event.event_code,
                        'event_name': event.event_name,
                        'status': event.status,
                        'message_type': event.message_type,
                        'same_header': event.same_header,
                        'created_at': event.created_at.isoformat() if event.created_at else None,
                        'archived_at': event.archived_at.isoformat() if event.archived_at else None,
                        'print_url': url_for('eas.manual_eas_print', event_id=event.id),
                        'export_url': export_url,
                        'components': {
                            key: _component_with_url(key, meta)
                            for key, meta in components_payload.items()
                        },
                    }
                )

            return jsonify({'events': items, 'total': total})
        except Exception as exc:
            workflow_logger.error('Failed to list manual EAS activations: %s', exc)
            return jsonify({'error': 'Unable to load manual activations.'}), 500

    @bp.route('/manual/events/<int:event_id>/print')
    def manual_eas_print(event_id: int):
        auth_response = _auth_redirect()
        if auth_response is not None:
            return auth_response

        event = ManualEASActivation.query.get_or_404(event_id)
        components_payload = event.components_payload or {}
        web_prefix = current_app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')

        def _component_with_url(component_key: str, meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not meta:
                return None
            storage_subpath = meta.get('storage_subpath')
            web_parts = [web_prefix, storage_subpath] if storage_subpath else []
            web_path = '/'.join(part for part in web_parts if part)
            download_url = url_for('static', filename=web_path) if storage_subpath else None
            return {
                'filename': meta.get('filename'),
                'duration_seconds': meta.get('duration_seconds'),
                'size_bytes': meta.get('size_bytes'),
                'storage_subpath': storage_subpath,
                'download_url': download_url,
                'stream_url': url_for('manual_eas_audio', event_id=event.id, component=component_key),
            }

        state_tree = get_us_state_county_tree()
        state_index = {
            state.get('state_fips'): {'abbr': state.get('abbr'), 'name': state.get('name')}
            for state in state_tree
            if state.get('state_fips')
        }
        same_lookup = get_same_lookup()
        header_detail = describe_same_header(event.same_header, lookup=same_lookup, state_index=state_index)

        summary_url = None
        if event.summary_filename:
            summary_subpath = '/'.join(
                part for part in [event.storage_path, event.summary_filename] if part
            )
            if summary_subpath:
                web_parts = [web_prefix, summary_subpath] if web_prefix else [summary_subpath]
                summary_url = url_for('static', filename='/'.join(web_parts))

        return render_template(
            'manual_eas_print.html',
            event=event,
            components={
                key: _component_with_url(key, meta)
                for key, meta in components_payload.items()
            },
            header_detail=header_detail,
            summary_url=summary_url,
        )

    @bp.route('/manual/events/<int:event_id>/export')
    def manual_eas_export(event_id: int):
        auth_response = _auth_redirect()
        if auth_response is not None:
            return auth_response

        event = ManualEASActivation.query.get_or_404(event_id)
        if not event.summary_filename:
            return jsonify({'error': 'No export summary is available for this activation.'}), 404

        output_root = str(current_app.config.get('EAS_OUTPUT_DIR') or '').strip()
        if not output_root:
            return jsonify({'error': 'EAS output directory is not configured.'}), 500

        file_path = os.path.join(output_root, event.storage_path or '', event.summary_filename)
        if not os.path.exists(file_path):
            return jsonify({'error': 'The export file is no longer available on disk.'}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=event.summary_filename,
            mimetype='application/json',
        )

    @bp.route('/manual/events/<int:event_id>', methods=['DELETE'])
    def manual_eas_delete(event_id: int):
        auth_response = _auth_redirect(json_mode=True)
        if auth_response is not None:
            return auth_response

        activation = ManualEASActivation.query.get_or_404(event_id)
        output_root = str(current_app.config.get('EAS_OUTPUT_DIR') or '').strip()

        try:
            if output_root:
                _remove_manual_eas_files(activation, output_root, workflow_logger)

            db.session.delete(activation)
            db.session.add(
                SystemLog(
                    level='WARNING',
                    message='Manual EAS activation deleted',
                    module='eas',
                    details={
                        'event_id': event_id,
                        'identifier': activation.identifier,
                        'deleted_by': getattr(g.current_user, 'username', None),
                    },
                )
            )
            db.session.commit()
        except Exception as exc:
            workflow_logger.error('Failed to delete manual EAS activation %s: %s', event_id, exc)
            db.session.rollback()
            return jsonify({'error': 'Failed to delete manual EAS activation.'}), 500

        return jsonify({'message': 'Manual EAS activation deleted.', 'id': event_id})

    @bp.route('/manual/events/purge', methods=['POST'])
    def manual_eas_purge():
        auth_response = _auth_redirect(json_mode=True)
        if auth_response is not None:
            return auth_response

        payload = request.get_json(silent=True) or {}
        ids = payload.get('ids')
        cutoff: Optional[datetime] = None

        if ids:
            try:
                id_list = [int(item) for item in ids if item is not None]
            except (TypeError, ValueError):
                return jsonify({'error': 'ids must be a list of integers.'}), 400
            query = ManualEASActivation.query.filter(ManualEASActivation.id.in_(id_list))
        else:
            before_text = payload.get('before')
            older_than_days = payload.get('older_than_days')

            if before_text:
                normalised = before_text.strip().replace('Z', '+00:00')
                try:
                    cutoff = datetime.fromisoformat(normalised)
                except ValueError:
                    return jsonify({'error': 'Unable to parse the provided cutoff timestamp.'}), 400
            elif older_than_days is not None:
                try:
                    days = int(older_than_days)
                except (TypeError, ValueError):
                    return jsonify({'error': 'older_than_days must be an integer.'}), 400
                if days < 0:
                    return jsonify({'error': 'older_than_days must be non-negative.'}), 400
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            else:
                return jsonify(
                    {'error': 'Provide ids, before, or older_than_days to select activations to purge.'},
                    400,
                )

            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            query = ManualEASActivation.query.filter(ManualEASActivation.created_at < cutoff)

        activations = query.all()
        if not activations:
            return jsonify({'message': 'No manual EAS activations matched the purge criteria.', 'deleted': 0})

        output_root = str(current_app.config.get('EAS_OUTPUT_DIR') or '').strip()
        deleted_ids: List[int] = []

        for activation in activations:
            deleted_ids.append(activation.id)
            if output_root:
                _remove_manual_eas_files(activation, output_root, workflow_logger)
            db.session.delete(activation)

        try:
            db.session.add(
                SystemLog(
                    level='WARNING',
                    message='Manual EAS activations purged',
                    module='eas',
                    details={
                        'deleted_ids': deleted_ids,
                        'deleted_by': getattr(g.current_user, 'username', None),
                    },
                )
            )
            db.session.commit()
        except Exception as exc:
            workflow_logger.error('Failed to purge manual EAS activations: %s', exc)
            db.session.rollback()
            return jsonify({'error': 'Failed to purge manual EAS activations.'}), 500

        return jsonify(
            {
                'message': f'Deleted {len(deleted_ids)} manual EAS activations.',
                'deleted': len(deleted_ids),
                'ids': deleted_ids,
            }
        )


def _remove_manual_eas_files(activation: ManualEASActivation, output_root: str, logger) -> None:
    """Delete manual EAS directory and contained files from disk."""

    if not activation.storage_path:
        return

    try:
        full_path = os.path.join(output_root, activation.storage_path)
        if os.path.exists(full_path) and os.path.isdir(full_path):
            shutil.rmtree(full_path)
            logger.debug('Deleted manual EAS directory: %s', full_path)
    except OSError as exc:
        logger.warning('Failed to delete manual EAS directory %s: %s', full_path, exc)
