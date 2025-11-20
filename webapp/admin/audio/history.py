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

"""Audio archive listing and filtering routes."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import render_template, request, url_for
from sqlalchemy import or_

from app_core.extensions import db
from app_core.models import CAPAlert, EASMessage, ManualEASActivation
from app_core.eas_storage import get_eas_static_prefix, load_or_cache_summary_payload


def register_history_routes(app, logger) -> None:
    """Register the audio history listing route."""

    @app.route('/audio')
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

            messages: List[Dict[str, Any]] = []
            web_prefix = get_eas_static_prefix()

            for message, alert in automated_records:
                metadata = dict(message.metadata_payload or {})
                event_name = (alert.event if alert and alert.event else metadata.get('event')) or 'Unknown Event'
                severity = alert.severity if alert and alert.severity else metadata.get('severity')
                status = alert.status if alert and alert.status else metadata.get('status')
                eom_filename = metadata.get('eom_filename')
                has_eom_data = bool(message.eom_audio_data) or bool(eom_filename)

                audio_url = url_for('eas_message_audio', message_id=message.id)
                if message.text_payload:
                    text_url = url_for('eas_message_summary', message_id=message.id)
                else:
                    text_url = _manual_static_url(message.text_filename, web_prefix)

                if has_eom_data:
                    eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
                elif eom_filename:
                    eom_url = _manual_static_url(eom_filename, web_prefix)
                else:
                    eom_url = None

                summary_data = load_or_cache_summary_payload(message)

                messages.append(
                    {
                        'id': message.id,
                        'event': event_name,
                        'severity': severity,
                        'status': status,
                        'created_at': message.created_at,
                        'same_header': message.same_header,
                        'audio_url': audio_url,
                        'text_url': text_url,
                        'detail_url': url_for('audio_detail', message_id=message.id),
                        'alert_url': url_for('audio_detail', message_id=message.id),
                        'alert_identifier': alert.identifier if alert else None,
                        'eom_url': eom_url,
                        'summary_data': summary_data,
                        'source': 'automated',
                        'alert_label': 'View Alert',
                    }
                )

            manual_messages = _build_manual_message_entries(
                manual_records,
                manual_prefix=app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/'),
                web_prefix=web_prefix,
            )
            messages.extend(manual_messages)

            messages.sort(key=lambda item: _sort_key(item.get('created_at')), reverse=True)
            page_start = offset
            page_end = offset + per_page
            messages = messages[page_start:page_end]

            pagination = CombinedPagination(page, per_page, total_count)
            events, severities, statuses = _load_filter_metadata(logger)

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
                'errors/audio_history_error.html',
                error=str(exc),
            )


def _load_filter_metadata(logger) -> Tuple[List[str], List[str], List[str]]:
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
    except Exception as filter_error:  # pragma: no cover - defensive logging
        logger.warning('Unable to load audio filter metadata: %s', filter_error)
        events = []
        severities = []
        statuses = []

    return events, severities, statuses


def _manual_static_url(filename: Optional[str], web_prefix: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    parts = [web_prefix, filename] if web_prefix else [filename]
    path = '/'.join(part for part in parts if part)
    return url_for('static', filename=path) if path else None


def _build_manual_message_entries(
    manual_records: List[ManualEASActivation],
    *,
    manual_prefix: str,
    web_prefix: Optional[str],
) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []

    for event in manual_records:
        metadata = dict(event.metadata_payload or {})
        components_payload = dict(event.components_payload or {})

        web_prefix_clean = web_prefix.strip('/') if web_prefix else ''
        manual_prefix_clean = (manual_prefix or web_prefix_clean).strip('/') if (manual_prefix or web_prefix_clean) else ''
        storage_path_clean = event.storage_path.strip('/') if event.storage_path else ''

        def _manual_path(subpath: Optional[str]) -> Optional[str]:
            if not subpath:
                return None
            normalized = str(subpath).strip('/')
            if storage_path_clean and not normalized.startswith(storage_path_clean):
                normalized = '/'.join(part for part in [storage_path_clean, normalized] if part)
            parts = [manual_prefix_clean, normalized] if manual_prefix_clean else [normalized]
            return '/'.join(part for part in parts if part)

        def _component_subpath(*keys: str) -> Optional[str]:
            for key in keys:
                payload = components_payload.get(key) or {}
                storage_subpath = payload.get('storage_subpath')
                if storage_subpath:
                    return storage_subpath
                filename = payload.get('filename')
                if filename:
                    return filename
            return None

        audio_subpath = metadata.get('audio_subpath') or _component_subpath(
            'composite',
            'tts',
            'attention',
            'same',
        )
        summary_subpath = metadata.get('summary_subpath') or (
            event.summary_filename if event.summary_filename else None
        )
        eom_subpath = metadata.get('eom_subpath') or _component_subpath('eom')

        if event.composite_audio_data:
            audio_url = url_for('manual_eas_audio', event_id=event.id, component='composite')
        else:
            audio_url = (
                url_for('static', filename=_manual_path(audio_subpath))
                if audio_subpath
                else None
            )
        summary_url = (
            url_for('static', filename=_manual_path(summary_subpath))
            if summary_subpath
            else None
        )
        if event.eom_audio_data:
            eom_url = url_for('manual_eas_audio', event_id=event.id, component='eom')
        else:
            eom_url = (
                url_for('static', filename=_manual_path(eom_subpath))
                if eom_subpath
                else None
            )

        messages.append(
            {
                'id': event.id,
                'event': event.event_name or event.event_code or 'Manual Activation',
                'severity': metadata.get('severity'),
                'status': event.status,
                'created_at': event.created_at,
                'same_header': event.same_header,
                'audio_url': audio_url,
                'text_url': summary_url,
                'detail_url': url_for('eas.manual_eas_print', event_id=event.id),
                'alert_url': url_for('eas.manual_eas_print', event_id=event.id),
                'alert_identifier': event.identifier,
                'eom_url': eom_url,
                'source': 'manual',
                'alert_label': 'View Activation',
            }
        )

    return messages


def _sort_key(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class CombinedPagination:
    """Simple pagination helper matching flask-sqlalchemy's pagination API."""

    def __init__(self, page_number: int, page_size: int, total_items: int):
        self.page = page_number
        self.per_page = page_size
        self.total = total_items
        self.pages = max(1, math.ceil(total_items / page_size)) if page_size else 1
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1 if self.has_prev else None
        self.next_num = self.page + 1 if self.has_next else None

    def iter_pages(
        self,
        left_edge: int = 2,
        left_current: int = 2,
        right_current: int = 3,
        right_edge: int = 2,
    ):
        last = self.pages
        for num in range(1, last + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > last - right_edge
            ):
                yield num
            elif num == left_edge + 1 or num == self.page + right_current:
                yield None
