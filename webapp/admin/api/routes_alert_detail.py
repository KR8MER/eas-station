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

"""``/alerts/<id>`` — the alert detail page.

The largest handler in the package: it gathers the alert, its intersections and
coverage percentages, the related alerts sharing a VTEC identity, and the EAS
messages generated from it, then renders ``alert_detail.html``.
"""

import os
from typing import Any, Dict, List, Optional

from flask import flash, redirect, render_template, url_for
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, EASMessage, Intersection
from app_core.eas_storage import get_eas_static_prefix

from ..coverage import calculate_coverage_percentages, try_build_geometry_from_same_codes

from .blueprint import api_bp
from .county import _detect_county_wide
from .display_data import _extract_alert_display_data


@api_bp.route('/alerts/<int:alert_id>')
def alert_detail(alert_id):
    """Show detailed information about a specific alert with accurate coverage calculation"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        try:
            is_county_wide = _detect_county_wide(alert)
        except Exception:
            is_county_wide = False

        # Build geometry from SAME geocodes BEFORE coverage calc.
        # Uses a savepoint so failures never corrupt the session.
        try_build_geometry_from_same_codes(alert_id)

        coverage_data = calculate_coverage_percentages(alert_id, intersections)

        county_coverage = coverage_data.get('county', {}).get('coverage_percentage', 0)
        county_is_estimated = coverage_data.get('county', {}).get('is_estimated', False)
        # Only treat as county-wide when the percentage comes from the real NWS
        # polygon, not from a SAME-code union of multiple counties (which always
        # gives ~100% for any county in the broadcast area).
        is_actually_county_wide = county_coverage >= 95.0 and not county_is_estimated

        if not coverage_data and is_county_wide:
            # The fallback only applies when the boundaries table is completely
            # empty – i.e. the station has not yet had any boundary files
            # uploaded.  In that case we show an estimated 100 % for the
            # configured county so the operator sees something useful.
            #
            # If boundaries ARE present in the database but none of them
            # intersected with this alert's geometry, that means the alert
            # covers a different county (or a county for which boundaries
            # have not been uploaded).  Reporting 100 % coverage for ALL
            # boundaries in the database would be wrong – those boundaries
            # belong to a different county.  Leave coverage_data empty so
            # that the template shows 0 % / N/A correctly.
            total_boundary_count = db.session.query(
                func.count(Boundary.id)
            ).scalar() or 0

            if total_boundary_count == 0:
                # No boundaries configured at all – show estimated county-level
                # 100 % as a placeholder until boundaries are uploaded.
                coverage_data = {
                    'county': {
                        'total_boundaries': 0,
                        'affected_boundaries': 0,
                        'coverage_percentage': 100.0,
                        'total_area_sqm': None,
                        'intersected_area_sqm': None,
                        'is_estimated': True,
                    }
                }
                county_coverage = 100.0
                is_actually_county_wide = True
            # else: boundaries exist but none intersect → coverage stays 0 %

        suppress_boundary_details = is_actually_county_wide

        boundary_summary: List[Dict[str, Any]] = []
        for boundary_type, data in coverage_data.items() if coverage_data else []:
            if boundary_type == 'county':
                continue

            total_boundaries = data.get('total_boundaries')
            affected_boundaries = data.get('affected_boundaries')
            coverage_percentage = data.get('coverage_percentage', 0.0)

            is_full_coverage = False
            if total_boundaries is not None and affected_boundaries is not None:
                is_full_coverage = affected_boundaries >= total_boundaries > 0
            else:
                is_full_coverage = coverage_percentage >= 95.0

            boundary_summary.append(
                {
                    'type': boundary_type,
                    'total_boundaries': total_boundaries,
                    'affected_boundaries': affected_boundaries,
                    'coverage_percentage': coverage_percentage,
                    'is_full_coverage': is_full_coverage,
                    'is_estimated': data.get('is_estimated', False),
                }
            )

        boundary_summary.sort(key=lambda item: item['type'])

        audio_entries: List[Dict[str, Any]] = []
        static_prefix = get_eas_static_prefix()

        def _static_path(filename: Optional[str]) -> Optional[str]:
            if not filename:
                return None
            parts = [static_prefix, filename] if static_prefix else [filename]
            return '/'.join(part for part in parts if part)

        try:
            messages = (
                EASMessage.query
                .filter(EASMessage.cap_alert_id == alert_id)
                .order_by(EASMessage.created_at.desc())
                .all()
            )

            for message in messages:
                metadata = dict(message.metadata_payload or {})
                eom_filename = metadata.get('eom_filename')
                has_eom = bool(message.eom_audio_data) or bool(eom_filename)

                audio_url = url_for('eas_message_audio', message_id=message.id)
                if message.text_payload:
                    text_url = url_for('eas_message_summary', message_id=message.id)
                else:
                    text_path = _static_path(message.text_filename)
                    text_url = url_for('static', filename=text_path) if text_path else None

                if has_eom:
                    eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
                else:
                    eom_path = _static_path(eom_filename) if eom_filename else None
                    eom_url = url_for('static', filename=eom_path) if eom_path else None

                audio_entries.append(
                    {
                        'id': message.id,
                        'created_at': message.created_at,
                        'same_header': message.same_header,
                        'audio_url': audio_url,
                        'text_url': text_url,
                        'detail_url': url_for('audio_detail', message_id=message.id),
                        'metadata': metadata,
                        'eom_url': eom_url,
                    }
                )
        except Exception as audio_error:  # pragma: no cover - defensive logging
            api_bp.logger.warning(
                'Unable to load audio archive for alert %s: %s',
                alert.identifier,
                audio_error,
            )

        # Lazy audio extraction: if ipaws_audio_url is NULL but raw_json has
        # audio resources with derefUri, extract and save now.  This handles
        # alerts inserted before the audio extraction code was added.
        if not getattr(alert, 'ipaws_audio_url', None):
            raw_json = alert.raw_json if isinstance(alert.raw_json, dict) else {}
            resources = raw_json.get('properties', {}).get('resources', [])
            has_audio_data = any(
                ('audio' in (r.get('mimeType') or '').lower()
                 or 'eas broadcast' in (r.get('resourceDesc') or '').lower())
                and r.get('derefUri')
                for r in resources
            )
            if has_audio_data:
                try:
                    from app_utils.ipaws_enrichment import save_ipaws_audio
                    eas_output = os.getenv('EAS_OUTPUT_DIR') or os.path.join(
                        os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static')),
                        'eas_messages',
                    )
                    audio_filename = save_ipaws_audio(
                        raw_json, alert.identifier or str(alert.id), eas_output,
                    )
                    if audio_filename:
                        alert.ipaws_audio_url = audio_filename
                        db.session.commit()
                        api_bp.logger.info(
                            'Lazy-extracted IPAWS audio for alert %s: %s',
                            alert.identifier, audio_filename,
                        )
                except Exception as exc:
                    api_bp.logger.warning(
                        'Lazy IPAWS audio extraction failed for %s: %s',
                        alert.identifier, exc,
                    )

        # Lazy certificate extraction: if certificate_info is NULL but raw_json
        # has raw_xml, extract certificate details now.  Handles alerts ingested
        # before the enrichment code was deployed.
        if not getattr(alert, 'certificate_info', None):
            raw_json_cert = alert.raw_json if isinstance(alert.raw_json, dict) else {}
            raw_xml = raw_json_cert.get('raw_xml', '')
            if raw_xml:
                try:
                    from app_utils.ipaws_enrichment import extract_certificate_info
                    cert_info = extract_certificate_info(raw_xml)
                    if cert_info:
                        alert.certificate_info = cert_info
                        if cert_info.get('signature_verified') is not None:
                            alert.signature_verified = cert_info['signature_verified']
                        if cert_info.get('signature_status'):
                            alert.signature_status = cert_info['signature_status']
                        db.session.commit()
                        api_bp.logger.info(
                            'Lazy-extracted certificate info for alert %s: valid=%s',
                            alert.identifier, cert_info.get('is_cert_valid', '?'),
                        )
                except Exception as exc:
                    api_bp.logger.warning(
                        'Lazy certificate extraction failed for %s: %s',
                        alert.identifier, exc,
                    )

        # Extract enriched display data (works for both IPAWS and NOAA)
        ipaws_data = _extract_alert_display_data(alert)

        # Resolve the forwarded audio URL for the player.
        # Prefer the eas_message_audio route (serves from database) over a static
        # file path — the DB copy is always present even if the disk file was not
        # written or has since been cleaned up.
        eas_audio_web_url = None
        if getattr(alert, 'eas_audio_url', None):
            try:
                from app_core.models import EASMessage as _EASMsg
                linked_msg = (
                    _EASMsg.query
                    .filter(_EASMsg.cap_alert_id == alert_id)
                    .order_by(_EASMsg.created_at.desc())
                    .first()
                )
                if linked_msg:
                    eas_audio_web_url = url_for('eas_message_audio', message_id=linked_msg.id)
            except Exception as _url_exc:
                api_bp.logger.debug('Could not resolve eas_audio_url to web URL: %s', _url_exc)

        # Query all alerts that share the same VTEC event key, ordered oldest→newest.
        # This gives us the full lifecycle chain: NEW → CON → EXT → EXP, etc.
        related_alerts: List[CAPAlert] = []
        # vtec_chain: unified list including current alert, sorted chronologically.
        # Each entry is {'alert': CAPAlert, 'is_current': bool}.
        vtec_chain: List[Dict[str, Any]] = []
        if (
            alert.vtec_office
            and alert.vtec_phenomenon
            and alert.vtec_significance
            and alert.vtec_etn is not None
            and alert.vtec_year is not None
        ):
            try:
                related_alerts = (
                    CAPAlert.query
                    .filter(
                        CAPAlert.vtec_office == alert.vtec_office,
                        CAPAlert.vtec_phenomenon == alert.vtec_phenomenon,
                        CAPAlert.vtec_significance == alert.vtec_significance,
                        CAPAlert.vtec_etn == alert.vtec_etn,
                        CAPAlert.vtec_year == alert.vtec_year,
                        CAPAlert.id != alert_id,
                    )
                    .order_by(CAPAlert.sent.asc())
                    .all()
                )
                # Merge current alert into the chain and sort by sent time so
                # the timeline always runs oldest → newest regardless of which
                # alert in the chain the user is currently viewing.
                if related_alerts:
                    all_in_chain = related_alerts + [alert]
                    all_in_chain.sort(key=lambda a: a.sent)
                    vtec_chain = [
                        {'alert': a, 'is_current': a.id == alert_id}
                        for a in all_in_chain
                    ]
            except Exception as _rel_exc:
                api_bp.logger.warning(
                    'Could not load related alerts for %s: %s', alert.identifier, _rel_exc
                )

        return render_template(
            'alert_detail.html',
            alert=alert,
            intersections=intersections,
            is_county_wide=is_county_wide,
            is_actually_county_wide=is_actually_county_wide,
            coverage_data=coverage_data,
            audio_entries=audio_entries,
            boundary_summary=boundary_summary,
            suppress_boundary_details=suppress_boundary_details,
            ipaws_data=ipaws_data,
            eas_audio_web_url=eas_audio_web_url,
            related_alerts=related_alerts,
            vtec_chain=vtec_chain,
        )

    except Exception as exc:
        api_bp.logger.error('Error in alert_detail route: %s', exc, exc_info=True)
        flash('Error loading alert details. Please try again.', 'error')
        return redirect(url_for('index'))
