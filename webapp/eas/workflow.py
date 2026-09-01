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

"""Routes backing the EAS workflow area."""

import base64
import json
import os
import re
import shutil
import tempfile
import time
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

from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger, AuditAction
from app_core.extensions import db
from app_core.models import AdminUser, EASMessage, LocalAuthority, ManualEASActivation, SystemLog
from werkzeug.utils import secure_filename

from app_utils.eas import (
    BROADCAST_LEAD_IN_SECONDS,
    BROADCAST_LEAD_OUT_SECONDS,
    EASAudioGenerator,
    _convert_audio_to_samples,
    _wav_duration_seconds,
    load_eas_config,
    ORIGINATOR_DESCRIPTIONS,
    P_DIGIT_MEANINGS,
    PRIMARY_ORIGINATORS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    build_same_header,
    clear_broadcast_active,
    describe_same_header,
    manual_default_same_codes,
    play_broadcast_audio,
    samples_to_wav_bytes,
    set_broadcast_active,
    truncate_wav_to_max_seconds,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import (
    get_extended_same_lookup,
    get_extended_state_county_tree,
    state_index_from_tree,
)

ALLOWED_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.aac', '.flac'}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


_MDC1200_OP_CODE_LABELS = {
    'ptt_id_pre': 'PTT-ID (Pre)',
    'ptt_id_post': 'PTT-ID (Post)',
    'emergency': 'Emergency',
    'request_to_talk': 'Request to Talk',
    'remote_monitor': 'Remote Monitor',
    'call_alert': 'Call Alert',
    'selective_call': 'Selective Call',
    'custom': 'Custom (raw bytes)',
}


def _mdc1200_op_label(op_code: Optional[str]) -> str:
    if not op_code:
        return 'N/A'
    key = str(op_code).strip().lower()
    return _MDC1200_OP_CODE_LABELS.get(key, op_code)


def _format_signaling_lines(signaling: Optional[Dict[str, Any]]) -> List[str]:
    """Render the saved pre/post-alert signal metadata as plain-text lines for PDF/log output."""
    if not signaling:
        return []

    lines: List[str] = []
    for position_key, label in (('pre_chime', 'Pre-Alert Signal'), ('post_chime', 'Post-Alert Signal')):
        entry = signaling.get(position_key) or {}
        profile = (entry.get('profile') or 'none').lower()
        duration = entry.get('duration_seconds')
        used = entry.get('used')

        if profile == 'none' or not used:
            lines.append(f"{label}: None")
            continue

        detail = profile.upper()
        if duration:
            try:
                detail += f" ({float(duration):.2f}s)"
            except (TypeError, ValueError):
                pass
        lines.append(f"{label}: {detail}")

    mdc = signaling.get('mdc1200') or {}
    if mdc:
        lines.append("")
        lines.append("MDC1200 Selective Calling:")
        lines.append(f"  Source Unit ID: {mdc.get('unit_id', 'N/A')}")
        target = mdc.get('target_unit_id')
        if target:
            lines.append(f"  Target Unit ID: {target}")
        else:
            lines.append("  Target Unit ID: (none — single-packet emission)")
        lines.append(f"  Op-Code Preset: {_mdc1200_op_label(mdc.get('op_code'))}")
        if mdc.get('pre_op_code') and mdc.get('pre_op_code') != mdc.get('op_code'):
            lines.append(f"  Resolved Pre Op-Code: {_mdc1200_op_label(mdc.get('pre_op_code'))}")
        if mdc.get('post_op_code') and mdc.get('post_op_code') != mdc.get('op_code'):
            lines.append(f"  Resolved Post Op-Code: {_mdc1200_op_label(mdc.get('post_op_code'))}")
        if mdc.get('op_code_raw') is not None:
            lines.append(f"  Raw Op-Code Byte: 0x{int(mdc['op_code_raw']):02X} ({mdc['op_code_raw']})")
        if mdc.get('arg_raw') is not None:
            lines.append(f"  Raw Argument Byte: 0x{int(mdc['arg_raw']):02X} ({mdc['arg_raw']})")

    dtmf_sequence = signaling.get('dtmf_sequence')
    if dtmf_sequence:
        lines.append("")
        lines.append(f"DTMF Sequence: {dtmf_sequence}")

    qc2 = signaling.get('qc2') or {}
    if qc2:
        lines.append("")
        lines.append("QC-II Tones:")
        lines.append(f"  Tone A: {qc2.get('tone_a_freq', 'N/A')} Hz")
        lines.append(f"  Tone B: {qc2.get('tone_b_freq', 'N/A')} Hz")
        if qc2.get('long_tone_enabled'):
            lines.append(f"  Long Tone: enabled ({qc2.get('long_tone_seconds', 0)} s)")

    return lines


def _get_local_authority(user) -> Optional[LocalAuthority]:
    """Return the LocalAuthority record for a user, or None if not a local authority."""
    if not user:
        return None
    authority = getattr(user, 'local_authority', None)
    if authority and authority.is_active:
        return authority
    return None


def register_workflow_routes(bp, logger, eas_config) -> None:
    """Register HTML and API routes for the EAS workflow blueprint."""

    workflow_logger = logger.getChild('workflow')

    def _auth_redirect(json_mode: bool = False):
        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            if json_mode:
                return jsonify({'error': 'Authentication required.'}), 401
            return redirect(url_for('auth.login', next=request.url))
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

        # Use the extended tree so the Broadcast Builder picker can
        # surface marine areas (GM/AM/AN/lakes/etc.) loaded from the
        # NWS marine zone DBF, not just U.S. Census states. Falls back
        # to U.S.-only when no marine zones are loaded.
        state_tree = get_extended_state_county_tree()
        same_lookup = get_extended_same_lookup()

        # without_audio(): workflow.html reads created_at, id,
        # metadata_payload, text_filename and text_payload -- no audio.
        recent_messages: List[EASMessage] = (
            EASMessage.without_audio()
            .order_by(EASMessage.created_at.desc())
            .limit(10)
            .all()
        )

        # Detect local authority context for the current user
        local_auth = _get_local_authority(g.current_user)
        local_authority_ctx = None
        if local_auth:
            local_authority_ctx = local_auth.to_dict()

        return render_template(
            'eas/workflow.html',
            eas_event_codes=event_options,
            eas_originator_choices=originator_choices,
            eas_originator=local_auth.originator if local_auth else eas_config.get('originator', 'WXR'),
            eas_station_id=local_auth.station_id if local_auth else eas_config.get('station_id', 'EASNODES'),
            eas_attention_seconds=eas_config.get('attention_tone_seconds', 8),
            eas_sample_rate=eas_config.get('sample_rate', 16000),
            eas_max_activation_seconds=int(eas_config.get('max_activation_seconds', 300)),
            eas_default_same_codes=manual_same_defaults,
            eas_header_fields=SAME_HEADER_FIELD_DESCRIPTIONS,
            eas_p_digit_meanings=P_DIGIT_MEANINGS,
            eas_fips_states=state_tree,
            eas_fips_lookup=same_lookup,
            eas_originator_descriptions=ORIGINATOR_DESCRIPTIONS,
            eas_recent_messages=recent_messages,
            eas_web_subdir=current_app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
            local_authority=local_authority_ctx,
        )

    def _read_upload_file(file_key: str, logger) -> Optional[List[int]]:
        """Read and convert an uploaded audio file to PCM samples.

        Returns a list of 16-bit PCM samples or None when no file is present.
        """
        upload = request.files.get(file_key)
        if not upload or not upload.filename:
            return None

        filename = secure_filename(upload.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            return None

        audio_bytes = upload.read()
        if not audio_bytes:
            return None

        if len(audio_bytes) > MAX_UPLOAD_SIZE:
            logger.warning('Uploaded file %s exceeds size limit (%d bytes)', file_key, len(audio_bytes))
            return None

        mime = upload.content_type or 'application/octet-stream'
        try:
            sample_rate = int(request.form.get('sample_rate') or eas_config.get('sample_rate', 16000) or 16000)
        except (TypeError, ValueError):
            sample_rate = 16000

        samples = _convert_audio_to_samples(audio_bytes, mime, sample_rate, logger)
        if samples and logger:
            duration = round(len(samples) / sample_rate, 2)
            logger.info('Uploaded %s: %s (%s, %d samples, ~%ss)', file_key, filename, mime, len(samples), duration)
        return samples

    @bp.route('/manual/generate', methods=['POST'])
    @require_permission('eas.broadcast')
    def manual_eas_generate():
        auth_response = _auth_redirect(json_mode=True)
        if auth_response is not None:
            return auth_response

        # Support both JSON and multipart/form-data (for file uploads)
        content_type = (request.content_type or '').lower()
        if 'multipart/form-data' in content_type:
            payload = {}
            for key in request.form:
                value = request.form[key]
                # Parse boolean-like values
                if value.lower() in ('true', '1', 'on'):
                    payload[key] = True
                elif value.lower() in ('false', '0', 'off'):
                    payload[key] = False
                else:
                    payload[key] = value
            # Parse same_codes from comma-separated or JSON
            raw_same = request.form.get('same_codes', '')
            if raw_same.startswith('['):
                try:
                    payload['same_codes'] = json.loads(raw_same)
                except (json.JSONDecodeError, ValueError):
                    payload['same_codes'] = raw_same
            else:
                payload['same_codes'] = raw_same
        else:
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

        # --- Local Authority jurisdiction enforcement ---
        local_authority = _get_local_authority(g.current_user)
        if local_authority:
            # Override originator and station_id with the authority's values
            originator = local_authority.originator.upper()
            station_id = local_authority.station_id.upper()

            # Restrict FIPS codes to authorized subdivision
            auth_fips = set(str(c).zfill(6)[:6] for c in (local_authority.authorized_fips_codes or []))
            if auth_fips:
                unauthorized = [c for c in location_codes if c not in auth_fips]
                if unauthorized:
                    return _validation_error(
                        f'Your authority ({local_authority.name}) is not authorized to '
                        f'broadcast to FIPS codes: {", ".join(unauthorized)}. '
                        f'Authorized codes: {", ".join(sorted(auth_fips))}.'
                    )

            # Restrict event codes to authorized list
            auth_events = set(str(e).strip().upper() for e in (local_authority.authorized_event_codes or []))
            if auth_events and event_code not in auth_events:
                return _validation_error(
                    f'Your authority ({local_authority.name}) is not authorized to '
                    f'issue event code {event_code}. '
                    f'Authorized event codes: {", ".join(sorted(auth_events))}.'
                )

            workflow_logger.info(
                'Local authority broadcast: user=%s authority=%s station_id=%s originator=%s',
                getattr(g.current_user, 'username', 'unknown'),
                local_authority.name,
                station_id,
                originator,
            )

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

        # Reload EAS config fresh to get latest TTS settings from database
        # (TTS settings can be updated via /admin/tts while app is running)
        fresh_config = load_eas_config(current_app.root_path)
        manual_config = dict(fresh_config)
        manual_config['enabled'] = True
        manual_config['originator'] = originator[:3].upper()
        manual_config['station_id'] = station_id.upper()[:8]
        manual_config['attention_tone_seconds'] = (
            tone_seconds if tone_seconds is not None else manual_config.get('attention_tone_seconds', 8)
        )
        manual_config['sample_rate'] = sample_rate

        # Log TTS configuration status to SystemLog for debugging
        # This helps diagnose why TTS might not work in Broadcast Builder
        tts_provider_loaded = manual_config.get('tts_provider', '')
        if include_tts:
            try:
                db.session.add(
                    SystemLog(
                        level='INFO',
                        message='Broadcast Builder: TTS configuration loaded',
                        module='eas.workflow',
                        details={
                            'tts_provider': tts_provider_loaded or '(not configured)',
                            'include_tts_requested': include_tts,
                        },
                    )
                )
                db.session.commit()
            except Exception as log_exc:
                workflow_logger.debug(f'Failed to log TTS config to SystemLog: {log_exc}')
                db.session.rollback()

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

        # FCC 47 CFR §11.61(a)(1)(ii): RWT carries SAME header + EOM only —
        # no Attention Signal, no voice narration. Enforced unconditionally
        # in build_manual_components(); mirror it here so the saved record
        # reflects what was actually broadcast.
        if event_code == 'RWT':
            tone_profile = 'none'
            tone_seconds = 0.0
            include_tts = False

        # Process uploaded audio files (only present in multipart requests)
        uploaded_narration = _read_upload_file('narration_audio', workflow_logger)
        uploaded_pre_alert = _read_upload_file('pre_alert_audio', workflow_logger)
        uploaded_post_alert = _read_upload_file('post_alert_audio', workflow_logger)

        try:
            components = generator.build_manual_components(
                alert_object,
                header,
                tone_profile=tone_profile,
                tone_duration=tone_seconds,
                include_tts=include_tts,
                narration_upload_samples=uploaded_narration,
                pre_alert_samples=uploaded_pre_alert,
                post_alert_samples=uploaded_post_alert,
            )
        except Exception as exc:
            workflow_logger.error('Manual EAS generation failed: %s', exc)
            workflow_logger.exception('Manual EAS generation exception details:')
            # Log to SystemLog for visibility in UI
            try:
                db.session.add(
                    SystemLog(
                        level='ERROR',
                        message='Broadcast Builder: EAS generation failed',
                        module='eas.workflow',
                        details={
                            'identifier': identifier,
                            'event_code': event_code,
                            'error': str(exc),
                            'error_type': type(exc).__name__,
                        },
                    )
                )
                db.session.commit()
            except Exception as log_exc:
                workflow_logger.error(f'Failed to log error to SystemLog: {log_exc}')
                db.session.rollback()
            return jsonify({'error': 'Failed to generate manual EAS package.'}), 500

        if not components:
            return jsonify({'error': 'Manual EAS package contained no audio components.'}), 500

        # Log TTS warnings to SystemLog for visibility in UI
        tts_warning = components.get('tts_warning')
        tts_provider = components.get('tts_provider')
        tts_enabled = components.get('tts_enabled', include_tts)  # Actual TTS state (may differ from request if RWT)
        
        if tts_warning:
            workflow_logger.warning(f'TTS synthesis issue: {tts_warning}')
            try:
                db.session.add(
                    SystemLog(
                        level='WARNING',
                        message='Broadcast Builder: TTS synthesis failed or unavailable',
                        module='eas.workflow',
                        details={
                            'identifier': identifier,
                            'event_code': event_code,
                            'tts_provider': tts_provider,
                            'tts_warning': tts_warning,
                            'include_tts_requested': include_tts,
                            'tts_enabled': tts_enabled,
                        },
                    )
                )
                db.session.commit()
            except Exception as log_exc:
                workflow_logger.error(f'Failed to log TTS warning to SystemLog: {log_exc}')
                db.session.rollback()
        elif tts_enabled and not components.get('tts_samples'):
            # TTS was enabled but no samples were generated and no warning was set
            # Include provider info in the log message for easier debugging
            provider_info = f"provider='{tts_provider}'" if tts_provider else "provider=NOT_CONFIGURED"
            workflow_logger.warning(f'Broadcast Builder: TTS was requested but no audio was generated ({provider_info})')
            try:
                db.session.add(
                    SystemLog(
                        level='WARNING',
                        message=f'Broadcast Builder: TTS was requested but no audio was generated ({provider_info})',
                        module='eas.workflow',
                        details={
                            'identifier': identifier,
                            'event_code': event_code,
                            'tts_provider': tts_provider if tts_provider else 'not_configured',
                            'include_tts_requested': include_tts,
                            'tts_enabled': tts_enabled,
                            'message_text_length': len(components.get('message_text', '') or ''),
                        },
                    )
                )
                db.session.commit()
            except Exception as log_exc:
                workflow_logger.error(f'Failed to log TTS issue to SystemLog: {log_exc}')
                db.session.rollback()
        elif include_tts and not tts_enabled:
            # TTS was requested but was disabled (e.g., for RWT)
            workflow_logger.info(f'Broadcast Builder: TTS was requested but disabled for event_code={event_code}')

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

        state_tree = get_extended_state_county_tree()
        state_index = state_index_from_tree(state_tree)
        same_lookup = get_extended_same_lookup()
        header_detail = describe_same_header(header, lookup=same_lookup, state_index=state_index)

        same_component = _package_audio(components.get('same_samples') or [], 'same')
        attention_component = _package_audio(components.get('attention_samples') or [], 'attention')
        pre_alert_component = _package_audio(components.get('pre_alert_samples') or [], 'pre_alert')
        tts_component = _package_audio(components.get('tts_samples') or [], 'tts')
        post_alert_component = _package_audio(components.get('post_alert_samples') or [], 'post_alert')
        eom_component = _package_audio(components.get('eom_samples') or [], 'eom')
        composite_component = _package_audio(components.get('composite_samples') or [], 'full')
        pre_chime_component = _package_audio(components.get('pre_chime_samples') or [], 'pre_chime')
        post_chime_component = _package_audio(components.get('post_chime_samples') or [], 'post_chime')

        stored_components = {
            'same': same_component,
            'attention': attention_component,
            'pre_alert': pre_alert_component,
            'tts': tts_component,
            'post_alert': post_alert_component,
            'eom': eom_component,
            'composite': composite_component,
            'pre_chime': pre_chime_component,
            'post_chime': post_chime_component,
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

        db_components = {}
        for key, value in stored_components.items():
            if not value:
                continue
            entry = {
                'filename': value['filename'],
                'duration_seconds': value['duration_seconds'],
                'size_bytes': value['size_bytes'],
                'storage_subpath': value['storage_subpath'],
            }
            # Attach signal profile metadata so the print page can display it
            if key == 'pre_chime' and components.get('pre_chime_profile'):
                entry['profile'] = components['pre_chime_profile']
            elif key == 'post_chime' and components.get('post_chime_profile'):
                entry['profile'] = components['post_chime_profile']
            db_components[key] = entry

        generated_by_user = getattr(g.current_user, 'username', 'system')
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
        if ',' in client_ip:
            client_ip = client_ip.split(',')[0].strip()

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
                'local_authority_id': local_authority.id if local_authority else None,
                'local_authority_name': local_authority.name if local_authority else None,
                'local_authority_station_id': local_authority.station_id if local_authority else None,
                'signaling': components.get('signaling') or {},
            },
            composite_audio_data=composite_component.get('wav_bytes') if composite_component else None,
            same_audio_data=same_component.get('wav_bytes') if same_component else None,
            attention_audio_data=attention_component.get('wav_bytes') if attention_component else None,
            tts_audio_data=tts_component.get('wav_bytes') if tts_component else None,
            eom_audio_data=eom_component.get('wav_bytes') if eom_component else None,
            narration_upload_audio_data=tts_component.get('wav_bytes') if (tts_component and uploaded_narration) else None,
            pre_alert_audio_data=pre_alert_component.get('wav_bytes') if pre_alert_component else None,
            post_alert_audio_data=post_alert_component.get('wav_bytes') if post_alert_component else None,
            pre_chime_audio_data=pre_chime_component.get('wav_bytes') if pre_chime_component else None,
            post_chime_audio_data=post_chime_component.get('wav_bytes') if post_chime_component else None,
            created_by=generated_by_user,
            created_by_ip=client_ip,
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
                        'generated_by': generated_by_user,
                        'generated_by_ip': client_ip,
                    },
                )
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            workflow_logger.error('Failed to persist manual EAS activation: %s', exc)
            return jsonify({'error': 'Unable to persist manual activation details.'}), 500

        workflow_logger.info(
            "Manual EAS alert generated by user '%s' from %s: id=%s event_code=%s identifier=%s",
            generated_by_user,
            client_ip,
            activation_record.id,
            resolved_event_code,
            identifier,
        )

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
                # without_audio(): this listing reads no audio blob.
                ManualEASActivation.without_audio()
                .order_by(ManualEASActivation.created_at.desc())
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
                        'triggered_at': event.triggered_at.isoformat() if event.triggered_at else None,
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
                'profile': meta.get('profile'),
                'download_url': download_url,
                'stream_url': url_for('manual_eas_audio', event_id=event.id, component=component_key),
            }

        state_tree = get_extended_state_county_tree()
        state_index = state_index_from_tree(state_tree)
        same_lookup = get_extended_same_lookup()
        header_detail = describe_same_header(event.same_header, lookup=same_lookup, state_index=state_index)

        summary_url = None
        if event.summary_filename:
            summary_subpath = '/'.join(
                part for part in [event.storage_path, event.summary_filename] if part
            )
            if summary_subpath:
                web_parts = [web_prefix, summary_subpath] if web_prefix else [summary_subpath]
                summary_url = url_for('static', filename='/'.join(web_parts))

        metadata_payload = event.metadata_payload or {}
        signaling = metadata_payload.get('signaling') or {}

        return render_template(
            'manual_eas_print.html',
            event=event,
            components={
                key: _component_with_url(key, meta)
                for key, meta in components_payload.items()
            },
            header_detail=header_detail,
            summary_url=summary_url,
            signaling=signaling,
        )

    @bp.route('/manual/events/<int:event_id>/print.pdf')
    def manual_eas_print_pdf(event_id: int):
        """Generate archival PDF for manual EAS activation - server-side from database."""
        auth_response = _auth_redirect()
        if auth_response is not None:
            return auth_response

        from flask import Response
        from datetime import datetime
        from app_core.eas_storage import format_local_datetime
        from app_utils.pdf_generator import generate_pdf_document

        event = ManualEASActivation.query.get_or_404(event_id)
        components_payload = event.components_payload or {}
        metadata_payload = event.metadata_payload or {}
        signaling = metadata_payload.get('signaling') or {}

        # Build PDF sections
        sections = []

        # Event Information
        event_info = [
            f"Event Code: {event.event_code or 'N/A'}",
            f"Event Name: {event.event_name or 'N/A'}",
            f"Identifier: {event.identifier or 'N/A'}",
            f"SAME Header: {event.same_header or 'N/A'}",
            f"Created: {format_local_datetime(event.created_at, include_utc=True)}",
            f"Status: {event.status or 'N/A'} / {event.message_type or 'N/A'}",
            f"Tone Profile: {(event.tone_profile or 'none').title()} ({float(event.tone_seconds or 0):.1f} seconds)",
            f"Sample Rate: {event.sample_rate or 'N/A'} Hz",
        ]

        if event.triggered_at:
            event_info.append(f"Triggered: {format_local_datetime(event.triggered_at, include_utc=True)}")

        sections.append({
            'heading': 'Manual EAS Activation Information',
            'content': event_info,
        })

        # Pre/Post-Alert Signals (system-level chimes, MDC1200, DTMF, QC-II)
        signal_lines = _format_signaling_lines(signaling)
        if signal_lines:
            sections.append({
                'heading': 'Pre/Post-Alert Signals',
                'content': signal_lines,
            })

        # Location Information
        state_tree = get_extended_state_county_tree()
        state_index = state_index_from_tree(state_tree)
        same_lookup = get_extended_same_lookup()
        header_detail = describe_same_header(event.same_header, lookup=same_lookup, state_index=state_index)

        locations = header_detail.get('locations', [])
        if locations:
            location_lines = []
            for loc in locations:
                if isinstance(loc, dict):
                    code = loc.get('code', 'N/A')
                    desc = loc.get('description', 'N/A')
                    state_abbr = loc.get('state_abbr', '')
                    loc_line = f"{code}: {desc}"
                    if state_abbr:
                        loc_line += f" ({state_abbr})"
                    location_lines.append(loc_line)

            sections.append({
                'heading': 'Affected Locations',
                'content': location_lines,
            })

        # Audio Components
        if components_payload:
            component_lines = []
            for key, meta in components_payload.items():
                if not isinstance(meta, dict):
                    continue
                filename = meta.get('filename', 'N/A')
                duration = meta.get('duration_seconds')
                size = meta.get('size_bytes')

                comp_line = f"{key.upper()}: {filename}"
                if duration:
                    comp_line += f" (Duration: {duration:.2f}s"
                    if size:
                        comp_line += f", Size: {size:,} bytes)"
                    else:
                        comp_line += ")"
                elif size:
                    comp_line += f" (Size: {size:,} bytes)"

                component_lines.append(comp_line)

            sections.append({
                'heading': 'Audio Components',
                'content': component_lines,
            })

        # Generation Metadata
        if metadata_payload:
            try:
                metadata_str = json.dumps(metadata_payload, indent=2, default=str)
                # Split JSON into lines to preserve formatting in PDF
                metadata_lines = metadata_str.split('\n')
                sections.append({
                    'heading': 'Generation Metadata',
                    'content': metadata_lines,
                })
            except (TypeError, ValueError) as exc:
                workflow_logger.warning('Failed to serialize generation metadata: %s', exc)

        # Generate PDF
        pdf_bytes = generate_pdf_document(
            title=f"Manual EAS Activation Report",
            sections=sections,
            subtitle=f"Event ID: {event_id} | {event.event_code or 'Manual Event'}",
            footer_text="Generated by EAS Station™ — Emergency Alert System Platform"
        )

        # Return as downloadable PDF
        response = Response(pdf_bytes, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f"inline; filename=manual_eas_{event_id}_{datetime.now().strftime('%Y%m%d')}.pdf"
        )
        return response

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
    @require_permission('eas.broadcast')
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

    @bp.route('/manual/events/<int:event_id>/send', methods=['POST'])
    @require_permission('eas.broadcast')
    def manual_eas_send(event_id: int):
        """Send a previously generated manual EAS activation.

        Triggers audio playback via the configured player command and
        activates GPIO relay pins according to the hardware behavior
        matrix.  Updates the activation's ``triggered_at`` timestamp
        on success.
        """
        auth_response = _auth_redirect(json_mode=True)
        if auth_response is not None:
            return auth_response

        activation = ManualEASActivation.query.get(event_id)
        if activation is None:
            return jsonify({'error': 'Manual EAS activation not found.'}), 404

        # Retrieve composite audio (full alert) from the database record
        audio_data = activation.composite_audio_data
        if not audio_data:
            # Fall back to reading from disk
            output_root = str(
                current_app.config.get('EAS_OUTPUT_DIR') or ''
            ).strip()
            if output_root and activation.storage_path:
                components = activation.components_payload or {}
                composite_meta = components.get('composite') or {}
                filename = composite_meta.get('filename', '')
                if filename:
                    disk_path = os.path.join(
                        output_root, activation.storage_path, filename,
                    )
                    if os.path.isfile(disk_path):
                        try:
                            with open(disk_path, 'rb') as fh:
                                audio_data = fh.read()
                        except OSError as exc:
                            workflow_logger.warning(
                                'Failed to read composite audio from disk: %s', exc,
                            )

        if not audio_data:
            return jsonify({
                'error': 'No composite audio data is available for this activation.',
            }), 404

        # Load EAS configuration for audio player command
        fresh_config = load_eas_config(current_app.root_path)
        audio_player_cmd = fresh_config.get('audio_player_cmd')

        # Enforce the hard activation time limit (DASDEC-style cap).
        max_activation_seconds = int(fresh_config.get('max_activation_seconds', 300) or 300)
        original_duration = _wav_duration_seconds(audio_data)
        was_truncated = False
        # Needed unconditionally (not just when truncating) so a
        # GPIO-triggered Dump/Abort mid-broadcast can still send a compliant
        # EOM burst -- see the play_broadcast_audio() call below.
        eom_wav = activation.eom_audio_data
        # Phase breakpoints for the countdown overlay -- see
        # set_broadcast_active()'s docstring. Chime audio (when configured)
        # plays immediately before the header / after the EOM, so its
        # duration folds into those same two phases.
        header_seconds = (
            _wav_duration_seconds(activation.pre_chime_audio_data or b'')
            + _wav_duration_seconds(activation.same_audio_data or b'')
        )
        eom_seconds = (
            _wav_duration_seconds(eom_wav or b'')
            + _wav_duration_seconds(activation.post_chime_audio_data or b'')
        )
        if original_duration > max_activation_seconds:
            audio_data = truncate_wav_to_max_seconds(audio_data, eom_wav, max_activation_seconds)
            was_truncated = True
            workflow_logger.info(
                'Activation %s audio truncated from %.1fs to %ds hard limit',
                event_id, original_duration, max_activation_seconds,
            )
        playback_duration = _wav_duration_seconds(audio_data)

        # GPIO is NOT keyed here.  The eas-station-gpio subprocess owns the
        # physical relay lines and keys them off the broadcast-state marker set
        # below; the web process must not build a controller (it can't claim the
        # pins, and importing lgpio in a gevent worker stalls the event loop).

        # Write composite audio to a temporary file for playback
        tmp_file = None
        send_result = {
            'event_id': event_id,
            'identifier': activation.identifier,
            'audio_played': False,
            'gpio_activated': False,
            'playback_duration_seconds': round(playback_duration, 2),
            'max_activation_seconds': max_activation_seconds,
            'was_truncated': was_truncated,
        }

        try:
            tmp_file = tempfile.NamedTemporaryFile(
                suffix='.wav', prefix='eas_send_', delete=False,
            )
            tmp_file.write(audio_data)
            tmp_file.flush()
            tmp_path = tmp_file.name
            tmp_file.close()

            alert_id = activation.identifier
            event_code = activation.event_code

            # Set broadcast state before playout — this fires the global
            # countdown timer and stack light on every page AND is the rising
            # edge the eas-station-gpio subprocess watches to key the relay
            # (so a headless encoder still takes the airchain), regardless of
            # whether a local audio player is configured.
            from app_utils.event_codes import EVENT_CODE_REGISTRY as _ECR
            _ei = _ECR.get(event_code or '', {})
            _elabel = (
                _ei.get('name', event_code) if isinstance(_ei, dict) else event_code
            ) or 'EAS Alert'
            # gpio_activated reflects whether the airchain marker was actually
            # published (the GPIO subprocess keys the relay off it) — not an
            # unconditional True, since the marker write is best-effort.
            send_result['gpio_activated'] = set_broadcast_active(
                event_code=event_code or '',
                label=_elabel,
                duration_seconds=BROADCAST_LEAD_IN_SECONDS + playback_duration + BROADCAST_LEAD_OUT_SECONDS,
                source='manual',
                identifier=alert_id or '',
                header_seconds=header_seconds + BROADCAST_LEAD_IN_SECONDS,
                eom_seconds=eom_seconds + BROADCAST_LEAD_IN_SECONDS,
            )
            # Relay lead-in: the marker above already fired the rising edge
            # the GPIO subprocess keys off of; this sleep gives the
            # transmitter this long to stabilize before real audio starts.
            time.sleep(BROADCAST_LEAD_IN_SECONDS)

            # Inject into the live Icecast air-chain, same as every other
            # broadcast path (live auto-forward via EASBroadcaster.
            # handle_alert(), resend via inject_eas_audio -- see
            # scripts/resend_eas_broadcast.py). Manual Send used to only
            # play locally via audio_player_cmd (e.g. aplay) and key GPIO,
            # never reaching Icecast at all -- a manually-sent alert,
            # including a hand-triggered Required Weekly Test, was
            # inaudible to every stream listener. This process has no
            # AudioIngestController of its own (same reason resend can't
            # touch the queues directly), so it asks the audio-service to
            # do the injection over the Redis command channel. Best-effort:
            # a failure here must never block the relay keying or local
            # playback above/below, same as resend's identical guard.
            try:
                from app_core.audio.redis_commands import get_audio_command_publisher
                inject_resp = get_audio_command_publisher().inject_raw_eas_audio(
                    audio_data, timeout=10.0,
                )
                send_result['audio_injected'] = bool(inject_resp.get('success'))
                if send_result['audio_injected']:
                    workflow_logger.info(
                        'Manual EAS audio injected into air-chain for activation %s',
                        event_id,
                    )
                else:
                    workflow_logger.info(
                        'Manual EAS air-chain injection reported no audio for '
                        'activation %s: %s',
                        event_id, inject_resp.get('message'),
                    )
            except Exception as exc:
                send_result['audio_injected'] = False
                workflow_logger.warning(
                    'Manual EAS air-chain injection failed (non-fatal) for '
                    'activation %s: %s',
                    event_id, exc,
                )

            # Play audio via configured player command. The broadcast marker must
            # stay set for the full composite duration regardless of whether the
            # player actually blocks for that long — on hosts without an audio
            # device the player can exit immediately, which would otherwise drop
            # the relay (released by the subprocess) before the encoder finishes.
            playout_start = time.monotonic()
            if audio_player_cmd:
                try:
                    command = list(audio_player_cmd) + [tmp_path]
                    workflow_logger.info(
                        'Playing manual EAS audio: %s', ' '.join(command),
                    )
                    # Bound the player to this broadcast's own length, not the
                    # global max.  A hung player (busy/blocked audio device,
                    # stalled network sink) must never keep this worker — and
                    # therefore the asserted air chain and the on-air overlay —
                    # blocked past the broadcast itself.
                    # play_broadcast_audio() (not a bare subprocess.run()) so a
                    # GPIO-triggered Dump/Abort can find this process's PID and
                    # the isolated EOM burst -- see
                    # app_core.audio.gpio_input_actions.abort_current_broadcast.
                    play_broadcast_audio(
                        command, logger=workflow_logger, eom_wav=eom_wav,
                        timeout=float(playback_duration) + 30,
                    )
                    send_result['audio_played'] = True
                except Exception as exc:
                    workflow_logger.warning(
                        'Audio playback failed: %s', exc,
                    )
            else:
                workflow_logger.info(
                    'No audio player configured; skipping playback for '
                    'activation %s.',
                    event_id,
                )
                send_result['audio_player_configured'] = False

            remaining_playout = playback_duration - (time.monotonic() - playout_start)
            if remaining_playout > 0:
                time.sleep(remaining_playout)

        finally:
            # Relay lead-out: hold the relay this much longer past the actual
            # end of playout before releasing it.
            time.sleep(BROADCAST_LEAD_OUT_SECONDS)
            # Falling edge: clearing the broadcast marker is what the
            # eas-station-gpio subprocess watches to release the relay (it also
            # self-releases on the marker TTL as a backstop).  Pass the
            # identifier so an overlapping newer broadcast's marker isn't erased.
            clear_broadcast_active(identifier=alert_id or '')

            # Clean up temp file
            if tmp_file is not None:
                try:
                    os.unlink(tmp_file.name)
                except OSError:
                    pass

        # Record the trigger timestamp
        now = datetime.now(timezone.utc)
        triggered_by_user = getattr(g.current_user, 'username', 'system')
        trigger_ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
        if ',' in trigger_ip:
            trigger_ip = trigger_ip.split(',')[0].strip()
        try:
            activation.triggered_at = now
            activation.triggered_by = triggered_by_user
            activation.triggered_by_ip = trigger_ip
            db.session.add(
                SystemLog(
                    level='INFO',
                    message='Manual EAS activation sent',
                    module='eas.workflow',
                    details={
                        'event_id': event_id,
                        'identifier': activation.identifier,
                        'event_code': activation.event_code,
                        'audio_played': send_result['audio_played'],
                        'gpio_activated': send_result['gpio_activated'],
                        'triggered_by': triggered_by_user,
                        'triggered_by_ip': trigger_ip,
                    },
                )
            )
            db.session.commit()
        except Exception as exc:
            workflow_logger.error(
                'Failed to update triggered_at for activation %s: %s',
                event_id, exc,
            )
            db.session.rollback()

        workflow_logger.info(
            "Manual EAS activation %s (%s) sent by user '%s' from %s",
            event_id,
            activation.event_code,
            triggered_by_user,
            trigger_ip,
        )

        # Audit: a transmission is the most consequential operator action in
        # the system. Record it in the tamper-evident audit ledger (in
        # addition to the SystemLog entry above) so "who sent which alert,
        # when, from where" is captured alongside every other security event.
        AuditLogger.log(
            action=AuditAction.EAS_BROADCAST,
            resource_type='manual_eas_activation',
            resource_id=str(event_id),
            details={
                'identifier': activation.identifier,
                'event_code': activation.event_code,
                'audio_played': send_result.get('audio_played'),
                'gpio_activated': send_result.get('gpio_activated'),
                'triggered_by': triggered_by_user,
            },
        )

        send_result['triggered_at'] = now.isoformat()
        return jsonify(send_result)

    @bp.route('/manual/events/purge', methods=['POST'])
    @require_permission('eas.broadcast')
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
            query = ManualEASActivation.without_audio().filter(ManualEASActivation.id.in_(id_list))
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
            query = ManualEASActivation.without_audio().filter(ManualEASActivation.created_at < cutoff)

        # without_audio(): this purge reads only id and storage_path, but a
        # plain query loaded all ten audio blobs of every row it was about
        # to delete. Deferred columns keep the ORM objects that
        # db.session.delete() below needs, without transferring the audio.
        activations = query.all()
        if not activations:
            return jsonify({'message': 'No manual EAS activations matched the purge criteria.', 'deleted': 0})

        output_root = str(current_app.config.get('EAS_OUTPUT_DIR') or '').strip()
        deleted_ids: List[int] = [activation.id for activation in activations]

        # Fail-closed audit: deleting compliance records is irreversible, so
        # write the tamper-evident ledger entry BEFORE removing anything. If
        # the audit write fails we abort the purge entirely -- a missing audit
        # row must never accompany a real deletion. (The send path is not
        # fail-closed because by the time it audits the alert has already
        # physically aired and cannot be un-broadcast.)
        try:
            AuditLogger.log(
                action=AuditAction.ALERT_DELETED,
                resource_type='manual_eas_activation',
                details={
                    'deleted_ids': deleted_ids,
                    'deleted_count': len(deleted_ids),
                },
                raise_on_error=True,
            )
        except Exception as exc:
            workflow_logger.critical(
                'Aborting manual EAS purge: tamper-evident audit write failed: %s', exc
            )
            db.session.rollback()
            return jsonify(
                {'error': 'Audit log write failed; purge aborted to preserve the audit trail.'}
            ), 500

        for activation in activations:
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
