"""Audio archive and manual EAS management routes."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from sqlalchemy import or_

from app_core.extensions import db
from app_core.models import AdminUser, CAPAlert, EASMessage, ManualEASActivation, SystemLog
from app_core.eas_storage import (
    get_eas_static_prefix,
    load_or_cache_audio_data,
    load_or_cache_summary_payload,
    remove_eas_files,
)
from app_utils import utc_now
from app_utils.eas import (
    EASAudioGenerator,
    PRIMARY_ORIGINATORS,
    build_same_header,
    describe_same_header,
    samples_to_wav_bytes,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree


# Create Blueprint for audio routes
audio_bp = Blueprint('audio', __name__)


def register_audio_routes(app, logger, eas_config):
    """Register audio archive and manual EAS endpoints."""
    
    # Store eas_config for use by routes
    audio_bp.eas_config = eas_config
    
    # Register the blueprint with the app
    app.register_blueprint(audio_bp)
    logger.info("Audio routes registered")


# Route definitions

@audio_bp.route('/audio')
def audio_history():
    try:
        eas_enabled = app.config.get('EAS_BROADCAST_ENABLED', False)
        # Validate pagination parameters
        page = request.args.get('page', 1, type=int)
        page = max(1, page)  # Ensure page is at least 1
        per_page = request.args.get('per_page', 25, type=int)
        per_page = min(max(per_page, 10), 100)  # Clamp between 10 and 100

        search = request.args.get('search', '').strip()
        event_filter = request.args.get('event', '').strip()
        severity_filter = request.args.get('severity', '').strip()
        status_filter = request.args.get('status', '').strip()

        base_query = db.session.query(EASMessage, CAPAlert).outerjoin(
            CAPAlert, EASMessage.cap_alert_id == CAPAlert.id
        )

        if search:
            search_term = f'%{search}%'
            base_query = base_query.filter(
                or_(
                    CAPAlert.event.ilike(search_term),
                    CAPAlert.headline.ilike(search_term),
                    CAPAlert.identifier.ilike(search_term),
                    EASMessage.same_header.ilike(search_term),
                )
            )

        if event_filter:
            base_query = base_query.filter(CAPAlert.event == event_filter)
        if severity_filter:
            base_query = base_query.filter(CAPAlert.severity == severity_filter)
        if status_filter:
            base_query = base_query.filter(CAPAlert.status == status_filter)

        query = base_query.order_by(EASMessage.created_at.desc())

        manual_query = ManualEASActivation.query
        include_manual = True

        if search:
            search_term = f'%{search}%'
            manual_query = manual_query.filter(
                or_(
                    ManualEASActivation.event_name.ilike(search_term),
                    ManualEASActivation.event_code.ilike(search_term),
                    ManualEASActivation.identifier.ilike(search_term),
                    ManualEASActivation.same_header.ilike(search_term),
                )
            )
        if event_filter:
            manual_query = manual_query.filter(
                or_(
                    ManualEASActivation.event_name == event_filter,
                    ManualEASActivation.event_code == event_filter,
                )
            )
        if status_filter:
            manual_query = manual_query.filter(ManualEASActivation.status == status_filter)
        if severity_filter:
            include_manual = False

        if include_manual:
            manual_query = manual_query.order_by(ManualEASActivation.created_at.desc())

        automated_total = query.order_by(None).count()
        manual_total = manual_query.order_by(None).count() if include_manual else 0
        total_count = automated_total + manual_total

        total_pages = max(1, math.ceil(total_count / per_page)) if per_page else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page
        fetch_limit = offset + per_page

        automated_records = query.limit(fetch_limit).all() if fetch_limit else []
        manual_records: List[ManualEASActivation] = []
        if include_manual and fetch_limit:
            manual_records = manual_query.limit(fetch_limit).all()

        web_prefix = get_eas_static_prefix()

        def _static_path(filename: Optional[str]) -> Optional[str]:
            if not filename:
                return None
            parts = [web_prefix, filename] if web_prefix else [filename]
            return '/'.join(part for part in parts if part)

        def _manual_web_path(subpath: Optional[str], *, fallback_prefix: Optional[str] = None) -> Optional[str]:
            if not subpath:
                return None
            effective_prefix = fallback_prefix if fallback_prefix is not None else web_prefix
            parts = [effective_prefix, subpath] if effective_prefix else [subpath]
            return '/'.join(part for part in parts if part)

        def _sort_key(value: Optional[datetime]) -> datetime:
            if value is None:
                return datetime.min.replace(tzinfo=timezone.utc)
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        messages: List[Dict[str, Any]] = []
        for message, alert in automated_records:
            metadata = dict(message.metadata_payload or {})
            event_name = (alert.event if alert and alert.event else metadata.get('event')) or 'Unknown Event'
            severity = alert.severity if alert and alert.severity else metadata.get('severity')
            status = alert.status if alert and alert.status else metadata.get('status')
            eom_filename = metadata.get('eom_filename')
            has_eom_data = bool(message.eom_audio_data) or bool(eom_filename)

            audio_url = url_for('eas_message_audio', message_id=message.id) if message.id else None
            if message.text_payload:
                text_url = url_for('eas_message_summary', message_id=message.id)
            else:
                text_path = _static_path(message.text_filename)
                text_url = url_for('static', filename=text_path) if text_path else None

            if has_eom_data:
                eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
            else:
                eom_path = _static_path(eom_filename) if eom_filename else None
                eom_url = url_for('static', filename=eom_path) if eom_path else None

            messages.append({
                'id': message.id,
                'event': event_name,
                'severity': severity,
                'status': status,
                'created_at': message.created_at,
                'same_header': message.same_header,
                'audio_url': audio_url,
                'text_url': text_url,
                'detail_url': url_for('audio_detail', message_id=message.id),
                'alert_url': url_for('alert_detail', alert_id=alert.id) if alert else None,
                'alert_identifier': alert.identifier if alert else None,
                'eom_url': eom_url,
                'source': 'automated',
                'alert_label': 'View Alert',
            })

        if include_manual and manual_records:
            for event in manual_records:
                metadata = dict(event.metadata_payload or {})
                components_payload = event.components_payload or {}
                manual_prefix = metadata.get('web_prefix', web_prefix)

                composite_component = components_payload.get('composite')
                audio_component = (
                    composite_component
                    or components_payload.get('tts')
                    or components_payload.get('attention')
                    or components_payload.get('same')
                )
                eom_component = components_payload.get('eom')

                audio_subpath = audio_component.get('storage_subpath') if audio_component else None
                audio_url = (
                    url_for(
                        'static',
                        filename=_manual_web_path(
                            audio_subpath,
                            fallback_prefix=manual_prefix,
                        ),
                    )
                    if audio_subpath
                    else None
                )

                summary_subpath = metadata.get('summary_subpath') or (
                    '/'.join(part for part in [event.storage_path, event.summary_filename] if part)
                    if event.summary_filename
                    else None
                )
                summary_url = (
                    url_for(
                        'static',
                        filename=_manual_web_path(
                            summary_subpath,
                            fallback_prefix=manual_prefix,
                        ),
                    )
                    if summary_subpath
                    else None
                )

                eom_subpath = eom_component.get('storage_subpath') if eom_component else None
                eom_url = (
                    url_for(
                        'static',
                        filename=_manual_web_path(
                            eom_subpath,
                            fallback_prefix=manual_prefix,
                        ),
                    )
                    if eom_subpath
                    else None
                )

                messages.append({
                    'id': event.id,
                    'event': event.event_name or event.event_code or 'Manual Activation',
                    'severity': metadata.get('severity'),
                    'status': event.status,
                    'created_at': event.created_at,
                    'same_header': event.same_header,
                    'audio_url': audio_url,
                    'text_url': summary_url,
                    'detail_url': url_for('manual_eas_print', event_id=event.id),
                    'alert_url': url_for('manual_eas_print', event_id=event.id),
                    'alert_identifier': event.identifier,
                    'eom_url': eom_url,
                    'source': 'manual',
                    'alert_label': 'View Activation',
                })

        messages.sort(key=lambda item: _sort_key(item.get('created_at')), reverse=True)
        page_start = offset
        page_end = offset + per_page
        messages = messages[page_start:page_end]

        class CombinedPagination:
            def __init__(self, page_number: int, page_size: int, total_items: int):
                self.page = page_number
                self.per_page = page_size
                self.total = total_items
                self.pages = max(1, math.ceil(total_items / page_size)) if page_size else 1
                self.has_prev = self.page > 1
                self.has_next = self.page < self.pages
                self.prev_num = self.page - 1 if self.has_prev else None
                self.next_num = self.page + 1 if self.has_next else None

            def iter_pages(self, left_edge: int = 2, left_current: int = 2, right_current: int = 3, right_edge: int = 2):
                last = self.pages
                for num in range(1, last + 1):
                    if num <= left_edge or (
                        self.page - left_current - 1 < num < self.page + right_current
                    ) or num > last - right_edge:
                        yield num
                    elif num == left_edge + 1 or num == self.page + right_current:
                        yield None

        pagination = CombinedPagination(page, per_page, total_count)

        try:
            cap_events = [
                row[0]
                for row in db.session.query(CAPAlert.event)
                .join(EASMessage, EASMessage.cap_alert_id == CAPAlert.id)
                .filter(CAPAlert.event.isnot(None))
                .distinct()
                .order_by(CAPAlert.event)
                .all()
            ]

            cap_severities = [
                row[0]
                for row in db.session.query(CAPAlert.severity)
                .join(EASMessage, EASMessage.cap_alert_id == CAPAlert.id)
                .filter(CAPAlert.severity.isnot(None))
                .distinct()
                .order_by(CAPAlert.severity)
                .all()
            ]

            cap_statuses = [
                row[0]
                for row in db.session.query(CAPAlert.status)
                .join(EASMessage, EASMessage.cap_alert_id == CAPAlert.id)
                .filter(CAPAlert.status.isnot(None))
                .distinct()
                .order_by(CAPAlert.status)
                .all()
            ]

            manual_event_names = [
                row[0]
                for row in db.session.query(ManualEASActivation.event_name)
                .filter(ManualEASActivation.event_name.isnot(None))
                .distinct()
                .order_by(ManualEASActivation.event_name)
                .all()
            ]

            manual_statuses = [
                row[0]
                for row in db.session.query(ManualEASActivation.status)
                .filter(ManualEASActivation.status.isnot(None))
                .distinct()
                .order_by(ManualEASActivation.status)
                .all()
            ]

            events = sorted({value for value in cap_events + manual_event_names if value})
            severities = sorted({value for value in cap_severities if value})
            statuses = sorted({value for value in cap_statuses + manual_statuses if value})
        except Exception as filter_error:
            logger.warning('Unable to load audio filter metadata: %s', filter_error)
            events = []
            severities = []
            statuses = []

        current_filters = {
            'search': search,
            'event': event_filter,
            'severity': severity_filter,
            'status': status_filter,
            'per_page': per_page,
        }

        total_messages = EASMessage.query.count() + ManualEASActivation.query.count()

        return render_template(
            'audio_history.html',
            messages=messages,
            pagination=pagination,
            events=events,
            severities=severities,
            statuses=statuses,
            current_filters=current_filters,
            total_messages=total_messages,
            eas_enabled=eas_enabled,
        )

    except Exception as exc:
        logger.error('Error loading audio archive: %s', exc)
        return render_template(
            'errors/audio_archive_error.html',
            error=str(exc),
        )

@audio_bp.route('/audio/<int:message_id>')
def audio_detail(message_id: int):
    try:
        message = EASMessage.query.get_or_404(message_id)
        alert = CAPAlert.query.get(message.cap_alert_id) if message.cap_alert_id else None
        metadata = dict(message.metadata_payload or {})
        event_name = (alert.event if alert and alert.event else metadata.get('event')) or 'Unknown Event'
        severity = alert.severity if alert and alert.severity else metadata.get('severity')
        status = alert.status if alert and alert.status else metadata.get('status')
        same_locations = metadata.get('locations')
        if isinstance(same_locations, list):
            locations = same_locations
        elif same_locations is None:
            locations = []
        else:
            locations = [str(same_locations)]

        eom_filename = metadata.get('eom_filename')
        has_eom_data = bool(message.eom_audio_data) or bool(eom_filename)

        audio_url = url_for('eas_message_audio', message_id=message.id)
        if message.text_payload:
            text_url = url_for('eas_message_summary', message_id=message.id)
        else:
            static_prefix = get_eas_static_prefix()
            text_url = None
            if message.text_filename:
                static_path = '/'.join(part for part in [static_prefix, message.text_filename] if part)
                text_url = url_for('static', filename=static_path) if static_path else None

        if has_eom_data:
            eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
        elif eom_filename:
            eom_path = '/'.join(part for part in [get_eas_static_prefix(), eom_filename] if part)
            eom_url = url_for('static', filename=eom_path) if eom_path else None
        else:
            eom_url = None

        summary_data = load_or_cache_summary_payload(message)

        return render_template(
            'audio_detail.html',
            message=message,
            alert=alert,
            metadata=metadata,
            summary_data=summary_data,
            audio_url=audio_url,
            text_url=text_url,
            eom_url=eom_url,
            event_name=event_name,
            severity=severity,
            status=status,
            locations=locations,
        )

    except Exception as exc:
        logger.error('Error loading audio detail %s: %s', message_id, exc)
        flash('Unable to load audio detail at this time.', 'error')
        return redirect(url_for('audio_history'))

@audio_bp.route('/eas_messages/<int:message_id>/audio', methods=['GET'])
def eas_message_audio(message_id: int):
    variant = (request.args.get('variant') or 'primary').strip().lower()
    if variant not in {'primary', 'eom'}:
        abort(400, description='Unsupported audio variant.')

    message = EASMessage.query.get_or_404(message_id)
    data = load_or_cache_audio_data(message, variant=variant)
    if not data:
        abort(404, description='Audio not available.')

    download = request.args.get('download', '').strip().lower()
    as_attachment = download in {'1', 'true', 'yes', 'download'}

    if variant == 'eom':
        filename = (message.metadata_payload or {}).get('eom_filename') if message.metadata_payload else None
        if not filename:
            filename = f'eas_message_{message.id}_eom.wav'
    else:
        filename = message.audio_filename or f'eas_message_{message.id}.wav'

    file_obj = io.BytesIO(data)
    file_obj.seek(0)
    response = send_file(
        file_obj,
        mimetype='audio/wav',
        as_attachment=as_attachment,
        download_name=filename,
        max_age=0,
        conditional=False,
    )
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@audio_bp.route('/eas_messages/<int:message_id>/summary', methods=['GET'])
def eas_message_summary(message_id: int):
    message = EASMessage.query.get_or_404(message_id)
    payload = load_or_cache_summary_payload(message)
    if payload is None:
        abort(404, description='Summary not available.')

    body = json.dumps(payload, indent=2, ensure_ascii=False)
    response = app.response_class(body, mimetype='application/json')
    filename = message.text_filename or f'eas_message_{message.id}_summary.json'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@audio_bp.route('/admin/eas_messages', methods=['GET'])
def admin_eas_messages():
    eas_enabled = app.config.get('EAS_BROADCAST_ENABLED', False)

    try:
        limit = request.args.get('limit', type=int) or 50
        limit = min(max(limit, 1), 500)
        base_query = EASMessage.query.order_by(EASMessage.created_at.desc())
        messages = base_query.limit(limit).all()
        total = base_query.count()

        items = []
        for message in messages:
            data = message.to_dict()
            audio_url = url_for('eas_message_audio', message_id=message.id)
            if message.text_payload:
                text_url = url_for('eas_message_summary', message_id=message.id)
            else:
                static_prefix = get_eas_static_prefix()
                text_path = '/'.join(part for part in [static_prefix, message.text_filename] if part)
                text_url = url_for('static', filename=text_path) if text_path else None
            items.append({
                **data,
                'audio_url': audio_url,
                'text_url': text_url,
                'detail_url': url_for('audio_detail', message_id=message.id),
            })

        return jsonify({'messages': items, 'total': total, 'eas_enabled': eas_enabled})
    except Exception as exc:
        logger.error(f"Failed to list EAS messages: {exc}")
        return jsonify({'error': 'Unable to load EAS messages'}), 500

@audio_bp.route('/admin/eas_messages/<int:message_id>', methods=['DELETE'])
def admin_delete_eas_message(message_id: int):
    message = EASMessage.query.get_or_404(message_id)

    try:
        remove_eas_files(message)
        db.session.delete(message)
        db.session.add(SystemLog(
            level='WARNING',
            message='EAS message deleted',
            module='eas',
            details={
                'message_id': message_id,
                'deleted_by': getattr(g.current_user, 'username', None),
            },
        ))
        db.session.commit()
    except Exception as exc:
        logger.error(f"Failed to delete EAS message {message_id}: {exc}")
        db.session.rollback()
        return jsonify({'error': 'Failed to delete EAS message.'}), 500

    return jsonify({'message': 'EAS message deleted.', 'id': message_id})

@audio_bp.route('/admin/eas_messages/purge', methods=['POST'])
def admin_purge_eas_messages():
    if g.current_user is None:
        return jsonify({'error': 'Authentication required.'}), 401

    payload = request.get_json(silent=True) or {}

    ids = payload.get('ids')
    cutoff: Optional[datetime] = None

    if ids:
        try:
            id_list = [int(item) for item in ids if item is not None]
        except (TypeError, ValueError):
            return jsonify({'error': 'ids must be a list of integers.'}), 400
        query = EASMessage.query.filter(EASMessage.id.in_(id_list))
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
            cutoff = utc_now() - timedelta(days=days)
        else:
            return jsonify({'error': 'Provide ids, before, or older_than_days to select messages to purge.'}), 400

        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        query = EASMessage.query.filter(EASMessage.created_at < cutoff)

    messages = query.all()
    if not messages:
        return jsonify({'message': 'No EAS messages matched the purge criteria.', 'deleted': 0})

    deleted_ids: List[int] = []
    for message in messages:
        deleted_ids.append(message.id)
        remove_eas_files(message)
        db.session.delete(message)

    try:
        db.session.add(SystemLog(
            level='WARNING',
            message='EAS messages purged',
            module='eas',
            details={
                'deleted_ids': deleted_ids,
                'deleted_by': getattr(g.current_user, 'username', None),
            },
        ))
        db.session.commit()
    except Exception as exc:
        logger.error(f"Failed to purge EAS messages: {exc}")
        db.session.rollback()
        return jsonify({'error': 'Failed to purge EAS messages.'}), 500

    return jsonify({'message': f'Deleted {len(deleted_ids)} EAS messages.', 'deleted': len(deleted_ids), 'ids': deleted_ids})

@audio_bp.route('/admin/eas/manual_generate', methods=['POST'])
def admin_manual_eas_generate():
    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return jsonify({'error': 'Authentication required.'}), 401

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
    for code in raw_codes:
        digits = ''.join(ch for ch in str(code) if ch.isdigit())
        if not digits:
            continue
        location_codes.append(digits.zfill(6)[:6])

    if not location_codes:
        return _validation_error('At least one SAME/FIPS location code is required.')

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
    originator = (payload.get('originator') or audio_bp.eas_config.get('originator', 'WXR')).strip().upper() or 'WXR'
    if originator not in allowed_originators:
        return _validation_error('Originator must be one of the authorised SAME senders.')

    station_id = (payload.get('station_id') or audio_bp.eas_config.get('station_id', 'EASNODES')).strip() or 'EASNODES'

    status = (payload.get('status') or 'Actual').strip() or 'Actual'
    message_type = (payload.get('message_type') or 'Alert').strip() or 'Alert'

    try:
        sample_rate = int(payload.get('sample_rate') or audio_bp.eas_config.get('sample_rate', 16000) or 16000)
    except (TypeError, ValueError):
        return _validation_error('Sample rate must be an integer value.')
    if sample_rate < 8000 or sample_rate > 48000:
        return _validation_error('Sample rate must be between 8000 and 48000 Hz.')

    sent_dt = datetime.now(timezone.utc)
    expires_dt = sent_dt + timedelta(minutes=duration_minutes)

    manual_config = dict(audio_bp.eas_config)
    manual_config['enabled'] = True
    manual_config['originator'] = originator[:3].upper()
    manual_config['station_id'] = station_id.upper().ljust(8)[:8]
    manual_config['attention_tone_seconds'] = tone_seconds if tone_seconds is not None else manual_config.get('attention_tone_seconds', 8)
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
        generator = EASAudioGenerator(manual_config, logger)
        components = generator.build_manual_components(
            alert_object,
            header,
            repeats=3,
            tone_profile=tone_profile,
            tone_duration=tone_seconds,
            include_tts=include_tts,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to build manual EAS package: {exc}")
        return jsonify({'error': 'Unable to generate EAS audio components.'}), 500

    def _safe_base(value: str) -> str:
        cleaned = re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_')
        return cleaned or 'manual_eas'

    base_name = _safe_base(identifier)
    sample_rate = components.get('sample_rate', sample_rate)

    output_root = str(manual_config.get('output_dir') or app.config.get('EAS_OUTPUT_DIR') or '').strip()
    if not output_root:
        logger.error('Manual EAS output directory is not configured.')
        return jsonify({'error': 'Manual EAS output directory is not configured.'}), 500

    manual_root = os.path.join(output_root, 'manual')
    os.makedirs(manual_root, exist_ok=True)

    timestamp_tag = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    slug = f"{base_name}_{timestamp_tag}"
    event_dir = os.path.join(manual_root, slug)
    os.makedirs(event_dir, exist_ok=True)
    storage_root = '/'.join(part for part in ['manual', slug] if part)
    web_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')

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
        'components': stored_components,
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
    )

    try:
        db.session.add(activation_record)
        db.session.flush()
        db.session.add(SystemLog(
            level='INFO',
            message='Manual EAS package generated',
            module='admin',
            details={
                'identifier': identifier,
                'event_code': resolved_event_code,
                'location_count': len(formatted_locations),
                'tone_profile': response_payload['tone_profile'],
                'tts_included': bool(tts_component),
                'manual_activation_id': activation_record.id,
            },
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('Failed to persist manual EAS activation: %s', exc)
        return jsonify({'error': 'Unable to persist manual activation details.'}), 500

    response_payload['activation'] = {
        'id': activation_record.id,
        'created_at': activation_record.created_at.isoformat() if activation_record.created_at else None,
        'print_url': url_for('manual_eas_print', event_id=activation_record.id),
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

    return jsonify(response_payload)

@audio_bp.route('/admin/eas/manual_events', methods=['GET'])
def admin_manual_eas_events():
    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return jsonify({'error': 'Authentication required.'}), 401

    try:
        limit = request.args.get('limit', type=int) or 100
        limit = min(max(limit, 1), 500)
        total = ManualEASActivation.query.count()
        events = (
            ManualEASActivation.query.order_by(ManualEASActivation.created_at.desc())
            .limit(limit)
            .all()
        )

        web_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')
        items = []

        for event in events:
            components_payload = event.components_payload or {}

            def _component_with_url(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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
                }

            summary_subpath = None
            if event.summary_filename:
                summary_subpath = '/'.join(
                    part for part in [event.storage_path, event.summary_filename] if part
                )
            export_url = (
                url_for('manual_eas_export', event_id=event.id)
                if summary_subpath
                else None
            )

            items.append({
                'id': event.id,
                'identifier': event.identifier,
                'event_code': event.event_code,
                'event_name': event.event_name,
                'status': event.status,
                'message_type': event.message_type,
                'same_header': event.same_header,
                'created_at': event.created_at.isoformat() if event.created_at else None,
                'archived_at': event.archived_at.isoformat() if event.archived_at else None,
                'print_url': url_for('manual_eas_print', event_id=event.id),
                'export_url': export_url,
                'components': {
                    key: _component_with_url(meta)
                    for key, meta in components_payload.items()
                },
            })

        return jsonify({'events': items, 'total': total})
    except Exception as exc:
        logger.error('Failed to list manual EAS activations: %s', exc)
        return jsonify({'error': 'Unable to load manual activations.'}), 500

@audio_bp.route('/manual_eas/<int:event_id>/audio/<string:component>', methods=['GET'])
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
    blob = getattr(activation, attr_name, None)
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

@audio_bp.route('/admin/eas/manual_events/<int:event_id>/print')
def manual_eas_print(event_id: int):
    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return redirect(url_for('login'))

    event = ManualEASActivation.query.get_or_404(event_id)
    components_payload = event.components_payload or {}
    web_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')

    def _component_with_url(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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
            'download_url': download_url,
        }

    components: Dict[str, Dict[str, Any]] = {}
    for key, meta in components_payload.items():
        component_value = _component_with_url(meta)
        if component_value:
            components[key] = component_value

    state_tree = get_us_state_county_tree()
    state_index = {
        state.get('state_fips'): {'abbr': state.get('abbr'), 'name': state.get('name')}
        for state in state_tree
        if state.get('state_fips')
    }
    same_lookup = get_same_lookup()
    header_detail = describe_same_header(event.same_header, lookup=same_lookup, state_index=state_index)

    return render_template(
        'manual_eas_print.html',
        event=event,
        components=components,
        header_detail=header_detail,
        summary_url=url_for('manual_eas_export', event_id=event.id)
        if event.summary_filename
        else None,
    )

@audio_bp.route('/admin/eas/manual_events/<int:event_id>/export')
def manual_eas_export(event_id: int):
    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return abort(401)

    event = ManualEASActivation.query.get_or_404(event_id)
    if not event.summary_filename:
        return abort(404)

    output_root = str(app.config.get('EAS_OUTPUT_DIR') or '').strip()
    if not output_root:
        return abort(404)

    file_path = os.path.join(output_root, event.storage_path or '', event.summary_filename)
    if not os.path.exists(file_path):
        return abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=event.summary_filename,
        mimetype='application/json',
    )


__all__ = ['register_audio_routes']
