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

"""Detailed audio history routes."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from flask import flash, redirect, render_template, url_for, Response

from app_core.models import CAPAlert, EASMessage
from app_core.eas_storage import get_eas_static_prefix, load_or_cache_summary_payload, format_local_datetime
from app_utils.eas import describe_same_header
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree
from app_utils.pdf_generator import generate_pdf_document


def register_detail_routes(app, logger) -> None:
    """Register routes that display detailed audio information."""

    @app.route('/audio/<int:message_id>')
    def audio_detail(message_id: int):
        try:
            message = EASMessage.query.get_or_404(message_id)
            alert = CAPAlert.query.get(message.cap_alert_id) if message.cap_alert_id else None
            metadata = dict(message.metadata_payload or {})
            segment_metadata: Dict[str, Dict[str, object]] = {}
            if isinstance(metadata.get('segments'), dict):
                segment_metadata = {
                    str(key): value
                    for key, value in metadata['segments'].items()
                    if isinstance(value, dict)
                }

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

            location_details = _build_location_details(message.same_header)

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

            component_map = {
                'same': ('same_audio_data', 'SAME Header Bursts'),
                'attention': ('attention_audio_data', 'Attention Tone'),
                'tts': ('tts_audio_data', 'Narration / TTS'),
                'buffer': ('buffer_audio_data', 'Silence Buffer'),
            }

            segment_entries = []
            for key, (attr, label) in component_map.items():
                blob = getattr(message, attr)
                if not blob:
                    continue
                metrics = segment_metadata.get(key, {})
                segment_entries.append(
                    {
                        'key': key,
                        'label': label,
                        'url': url_for('eas_message_audio', message_id=message.id, variant=key),
                        'duration_seconds': metrics.get('duration_seconds'),
                        'size_bytes': metrics.get('size_bytes'),
                    }
                )

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
                location_details=location_details,
                segment_entries=segment_entries,
            )
        except Exception as exc:
            logger.error('Error loading audio detail %s: %s', message_id, exc)
            flash('Unable to load audio detail at this time.', 'error')
            return redirect(url_for('audio_history'))

    @app.route('/audio/<int:message_id>/export.pdf')
    def audio_detail_pdf(message_id: int):
        """Generate archival PDF for audio message - server-side from database."""
        try:
            message = EASMessage.query.get_or_404(message_id)
            alert = CAPAlert.query.get(message.cap_alert_id) if message.cap_alert_id else None
            metadata = dict(message.metadata_payload or {})

            # Build PDF sections
            sections = []

            # Message Information
            event_name = (alert.event if alert and alert.event else metadata.get('event')) or 'Unknown Event'
            severity = alert.severity if alert and alert.severity else metadata.get('severity')
            status = alert.status if alert and alert.status else metadata.get('status')

            message_info = [
                f"Event: {event_name}",
                f"SAME Header: {message.same_header or 'N/A'}",
                f"Created: {format_local_datetime(message.created_at, include_utc=True)}",
            ]

            if severity:
                message_info.append(f"Severity: {severity}")
            if status:
                message_info.append(f"Status: {status}")

            sections.append({
                'heading': 'Message Information',
                'content': message_info,
            })

            # Linked Alert
            if alert:
                alert_info = [
                    f"Alert Event: {alert.event or 'N/A'}",
                    f"Alert Identifier: {alert.identifier or 'N/A'}",
                ]
                if alert.sent:
                    alert_info.append(f"Alert Sent: {format_local_datetime(alert.sent, include_utc=True)}")

                sections.append({
                    'heading': 'Linked CAP Alert',
                    'content': alert_info,
                })

            # Location Information
            location_details = _build_location_details(message.same_header)
            if location_details:
                location_lines = []
                for loc in location_details:
                    loc_line = f"{loc.get('code', 'N/A')}: {loc.get('description', 'N/A')}"
                    if loc.get('state_abbr'):
                        loc_line += f" ({loc.get('state_abbr')})"
                    if loc.get('scope'):
                        loc_line += f" - {loc.get('scope')}"
                    location_lines.append(loc_line)

                sections.append({
                    'heading': 'Affected Locations',
                    'content': location_lines,
                })

            # Audio Segments
            segment_metadata: Dict[str, Dict[str, object]] = {}
            if isinstance(metadata.get('segments'), dict):
                segment_metadata = {
                    str(key): value
                    for key, value in metadata['segments'].items()
                    if isinstance(value, dict)
                }

            component_map = {
                'same': ('same_audio_data', 'SAME Header Bursts'),
                'attention': ('attention_audio_data', 'Attention Tone'),
                'tts': ('tts_audio_data', 'Narration / TTS'),
                'buffer': ('buffer_audio_data', 'Silence Buffer'),
            }

            segment_lines = []
            for key, (attr, label) in component_map.items():
                blob = getattr(message, attr)
                if not blob:
                    continue
                metrics = segment_metadata.get(key, {})
                duration = metrics.get('duration_seconds')
                size = metrics.get('size_bytes')

                segment_line = f"{label}"
                if duration:
                    segment_line += f" (Duration: {duration:.2f}s"
                    if size:
                        segment_line += f", Size: {size:,} bytes)"
                    else:
                        segment_line += ")"
                elif size:
                    segment_line += f" (Size: {size:,} bytes)"

                segment_lines.append(segment_line)

            if segment_lines:
                sections.append({
                    'heading': 'Audio Segments',
                    'content': segment_lines,
                })

            # Generate PDF
            pdf_bytes = generate_pdf_document(
                title=f"Audio Message Detail Report - {event_name}",
                sections=sections,
                subtitle=f"Message ID: {message_id}",
                footer_text="Generated by EAS Station - Emergency Alert System Platform"
            )

            # Return as downloadable PDF
            response = Response(pdf_bytes, mimetype="application/pdf")
            response.headers["Content-Disposition"] = (
                f"inline; filename=audio_{message_id}_{datetime.now().strftime('%Y%m%d')}.pdf"
            )
            return response

        except Exception as exc:
            logger.error('Error generating audio PDF: %s', exc)
            flash(f'Error generating PDF: {exc}', 'error')
            return redirect(url_for('audio_detail', message_id=message_id))


def _static_download(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    static_prefix = get_eas_static_prefix()
    static_path = '/'.join(part for part in [static_prefix, filename] if part)
    return url_for('static', filename=static_path) if static_path else None


def _build_location_details(
    header: Optional[str],
    *,
    lookup: Optional[Dict[str, str]] = None,
    state_index: Optional[Dict[str, Dict[str, object]]] = None,
) -> List[Dict[str, str]]:
    """Return enriched location metadata for display on the detail page."""

    if not header:
        return []

    header = header.strip()
    if not header:
        return []

    lookup_map = lookup or get_same_lookup()
    if state_index is None:
        state_index = {
            str(state.get('state_fips') or '').zfill(2): {
                'abbr': (state.get('abbr') or '').strip(),
                'name': (state.get('name') or '').strip(),
            }
            for state in get_us_state_county_tree()
            if state.get('state_fips')
        }

    try:
        detail = describe_same_header(header, lookup=lookup_map, state_index=state_index)
    except Exception:
        return []

    entries: List[Dict[str, str]] = []
    for location in detail.get('locations', []):
        if not isinstance(location, dict):
            continue
        code = str(location.get('code') or '').strip()
        if not code:
            continue

        description = str(location.get('description') or '').strip() or code
        state_abbr = str(location.get('state_abbr') or '').strip()
        state_fips = str(location.get('state_fips') or '').strip()

        portion = str(location.get('p_meaning') or '').strip()
        if not portion:
            p_digit = str(location.get('p_digit') or '').strip()
            if p_digit:
                portion = f'P={p_digit}'

        scope = ''
        if location.get('is_statewide'):
            scope = 'Entire jurisdiction'
        else:
            county_fips = str(location.get('county_fips') or '').strip()
            if county_fips:
                scope = f'County FIPS {county_fips}'

        entries.append(
            {
                'code': code,
                'description': description,
                'state_abbr': state_abbr,
                'state_fips': state_fips,
                'portion': portion,
                'scope': scope,
            }
        )

    return entries
