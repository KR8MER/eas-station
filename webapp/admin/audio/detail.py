"""Detailed audio history routes."""

from __future__ import annotations

from typing import Optional

from flask import flash, redirect, render_template, url_for

from app_core.models import CAPAlert, EASMessage
from app_core.eas_storage import get_eas_static_prefix, load_or_cache_summary_payload


def register_detail_routes(app, logger) -> None:
    """Register routes that display detailed audio information."""

    @app.route('/audio/<int:message_id>')
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
                text_url = _static_download(message.text_filename)

            if has_eom_data:
                eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
            elif eom_filename:
                eom_url = _static_download(eom_filename)
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


def _static_download(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    static_prefix = get_eas_static_prefix()
    static_path = '/'.join(part for part in [static_prefix, filename] if part)
    return url_for('static', filename=static_path) if static_path else None
