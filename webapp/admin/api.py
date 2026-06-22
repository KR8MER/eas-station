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

"""REST-style API routes used by the admin interface."""

import contextlib
import json
import os
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for, Response
from sqlalchemy import desc, func
from sqlalchemy.exc import SQLAlchemyError

from app_core.cache import cache
from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, EASMessage, Intersection, PollHistory, USCountyBoundary
from app_core.system_health import get_system_health
from app_utils import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_MANUAL,
    UTC_TZ,
    format_uptime,
    get_location_timezone,
    get_location_timezone_name,
    local_now,
    utc_now,
)
from app_core.eas_storage import get_eas_static_prefix, format_local_datetime
from app_utils.vtec import extract_vtec_identity, parse_vtec_display
from app_core.boundaries import (
    get_boundary_color,
    get_boundary_display_label,
    get_boundary_group,
    normalize_boundary_type,
)
from app_core.alerts import (
    get_active_alerts_query,
    get_expired_alerts_query,
    load_alert_plain_text_map,
)
from app_utils import is_alert_expired
from app_utils.pdf_generator import generate_pdf_document
from app_utils.optimized_parsing import json_loads, json_dumps

from .coverage import calculate_coverage_percentages, try_build_geometry_from_same_codes

# Create Blueprint for API routes
api_bp = Blueprint('api', __name__)


def _get_configured_fips_codes() -> List[str]:
    """Return the configured FIPS codes from LocationSettings (cached per-request)."""
    from app_core.location import get_location_settings
    settings = get_location_settings()
    return settings.get('fips_codes', []) if settings else []


def _detect_county_wide(alert) -> bool:
    """Determine whether an alert covers the configured county.

    Checks area_desc text patterns, SAME geocodes matching configured FIPS
    codes, and statewide SAME codes.  Returns True when the alert is known
    to cover the primary county.
    """
    is_county_wide = False

    # Load configured county/state so detection is not hardcoded to any
    # specific location (previously hardcoded to "Putnam County, Ohio").
    from app_core.location import get_location_settings
    settings = get_location_settings()
    configured_county_name = (settings.get('county_name', '') or '').lower().strip()
    configured_state_code = (settings.get('state_code', '') or '').lower().strip()

    # Short county name without the " county" suffix for looser matching.
    # e.g. "putnam county" → "putnam"
    county_short = configured_county_name.replace(' county', '').strip()

    # --- Text-based detection from area_desc ---
    if alert.area_desc:
        area_lower = alert.area_desc.lower().strip()

        # Exact configured county name or "entire county" phrase
        county_match = (
            (configured_county_name and configured_county_name in area_lower)
            or 'entire county' in area_lower
        )

        # Short county name appears alongside a multi-area list (e.g. "putnam; ... OH")
        # Guard: suppress this match when MULTIPLE counties from the same state are
        # listed (e.g. "Allen, OH; Putnam, OH; Van Wert, OH").  Those are multi-county
        # polygon alerts, not county-wide single-county alerts.  Detect by counting
        # how many times the pattern ", <state>" appears; more than one indicates a
        # list of counties, each with its state abbreviation.
        _multi_county_list = bool(
            configured_state_code
            and area_lower.count(f', {configured_state_code}') > 1
        )
        short_with_list = (
            county_short
            and county_short in area_lower
            and (area_lower.count(';') >= 2 or area_lower.count(',') >= 2)
            and not _multi_county_list
        )

        # Statewide text patterns (e.g. area_desc="Ohio" or "state of ohio")
        state_name_patterns = bool(
            configured_state_code
            and (
                area_lower == configured_state_code
                or f'state of {configured_state_code}' in area_lower
            )
        )

        # configured county name (short form) + state code anywhere in area_desc
        # Both must be present: checking only for "county" (as a generic word)
        # and the state code is insufficient because any alert from that state
        # containing a county name would match.  The short county name must
        # also appear in the description to avoid false positives for alerts
        # that target a *different* county in the same state.
        county_and_state = bool(
            county_short
            and configured_state_code
            and county_short in area_lower
            and 'county' in area_lower
            and configured_state_code in area_lower
        )

        is_county_wide = bool(county_match or short_with_list or state_name_patterns or county_and_state)

    # --- SAME geocode matching (statewide codes only) ---
    # Note: an exact county FIPS match (e.g. 039137) only means the alert
    # *affects* that county, not that it covers the entire county.  Only
    # statewide SAME codes (e.g. 039000) should trigger county-wide coverage.
    if not is_county_wide:
        raw_json = alert.raw_json if isinstance(alert.raw_json, dict) else {}
        same_codes = raw_json.get('properties', {}).get('geocode', {}).get('SAME', [])
        if same_codes:
            configured_fips = set(_get_configured_fips_codes())
            # Build the state-level code from each configured FIPS
            # e.g. 039137 -> 039000 (statewide Ohio)
            statewide_codes = set()
            for fips in configured_fips:
                if isinstance(fips, str) and len(fips) >= 3:
                    statewide_codes.add(fips[:3] + '000')

            for code in same_codes:
                if not isinstance(code, str):
                    continue
                # Statewide code for our state (e.g. 039000)
                if code in statewide_codes:
                    is_county_wide = True
                    break
                # Any code ending in 000 is statewide for some state;
                # check if it's our state
                if code.endswith('000') and len(code) >= 6:
                    state_prefix = code[:3]
                    if any(f.startswith(state_prefix) for f in configured_fips):
                        is_county_wide = True
                        break

    return is_county_wide

def _get_location_terms() -> tuple:
    """Return (county_short, county_name_lower, state_lower) from configured location settings.

    Used by the GeoJSON routes to determine county-wide coverage without
    hardcoding any specific location name.
    """
    from app_core.location import get_location_settings
    try:
        settings = get_location_settings() or {}
    except Exception:
        settings = {}
    county_name = (settings.get('county_name', '') or '').lower().strip()
    county_short = county_name.replace(' county', '').strip()
    state_lower = (settings.get('state_code', '') or '').lower().strip()
    return county_short, county_name, state_lower



_CPU_SAMPLE_INTERVAL_SECONDS: float = 5.0
_last_cpu_sample_timestamp: Optional[datetime] = None
_last_cpu_sample_value: float = 0.0


def _get_cpu_usage_percent() -> float:
    """Return a recently sampled CPU percentage without blocking the request."""

    global _last_cpu_sample_timestamp, _last_cpu_sample_value

    now = datetime.utcnow()
    if (
        _last_cpu_sample_timestamp is None
        or (now - _last_cpu_sample_timestamp).total_seconds() >= _CPU_SAMPLE_INTERVAL_SECONDS
    ):
        _last_cpu_sample_value = psutil.cpu_percent(interval=None)
        _last_cpu_sample_timestamp = now
    return _last_cpu_sample_value


def _get_primary_ip_address() -> Optional[str]:
    """Best-effort detection of the host's primary IPv4 address."""

    try:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
            sock.connect(("8.8.8.8", 80))
            ip_address = sock.getsockname()[0]
            if ip_address:
                return ip_address
    except OSError:
        pass

    try:
        ip_address = socket.gethostbyname(socket.gethostname())
        if ip_address:
            return ip_address
    except OSError:
        pass

    return None


def register_api_routes(app, logger):
    """Attach JSON API endpoints used by the admin UI."""
    
    # Store logger for use by routes
    api_bp.logger = logger
    
    # Register the blueprint with the app
    app.register_blueprint(api_bp)
    logger.info("API routes registered")


# Route definitions

@api_bp.route('/api/alerts/<int:alert_id>/geometry')
def get_alert_geometry(alert_id):
    """Get specific alert geometry and intersecting boundaries as GeoJSON"""
    try:
        alert = db.session.query(
            CAPAlert.id,
            CAPAlert.identifier,
            CAPAlert.event,
            CAPAlert.severity,
            CAPAlert.urgency,
            CAPAlert.headline,
            CAPAlert.description,
            CAPAlert.expires,
            CAPAlert.sent,
            CAPAlert.area_desc,
            CAPAlert.status,
            CAPAlert.raw_json,
            func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
        ).filter(CAPAlert.id == alert_id).first()

        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(func.lower(Boundary.type) == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json_loads(county_geom.geometry)
        except Exception as exc:  # pragma: no cover - defensive logging
            api_bp.logger.warning("Could not get county boundary: %s", exc)

        geometry = None
        is_county_wide = False

        if alert.geometry:
            geometry = json_loads(alert.geometry)
        else:
            # Try to build geometry from SAME geocodes (multi-county IPAWS)
            try_build_geometry_from_same_codes(alert_id)
            geom_json = db.session.query(
                func.ST_AsGeoJSON(CAPAlert.geom)
            ).filter(CAPAlert.id == alert_id).scalar()
            if geom_json:
                geometry = json_loads(geom_json)

            # Fallback: use county boundary if alert is county-wide
            if not geometry and county_boundary and _detect_county_wide(alert):
                geometry = county_boundary
                is_county_wide = True

        intersecting_boundaries = []
        if geometry:
            # Fix N+1 query: fetch geometry in a single query with proper join
            intersections = db.session.query(
                Intersection,
                Boundary,
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).join(
                Boundary, Intersection.boundary_id == Boundary.id
            ).filter(Intersection.cap_alert_id == alert_id).all()

            for intersection, boundary, boundary_geom_json in intersections:
                if boundary_geom_json:
                    intersecting_boundaries.append(
                        {
                            'type': 'Feature',
                            'properties': {
                                'id': boundary.id,
                                'name': boundary.name,
                                'type': boundary.type,
                                'description': boundary.description,
                                'intersection_area': intersection.intersection_area,
                            },
                            'geometry': json_loads(boundary_geom_json),
                        }
                    )

        expires_iso = None
        if alert.expires:
            expires_dt = alert.expires.replace(tzinfo=UTC_TZ) if alert.expires.tzinfo is None else alert.expires.astimezone(UTC_TZ)
            expires_iso = expires_dt.isoformat()

        sent_iso = None
        if alert.sent:
            sent_dt = alert.sent.replace(tzinfo=UTC_TZ) if alert.sent.tzinfo is None else alert.sent.astimezone(UTC_TZ)
            sent_iso = sent_dt.isoformat()

        # Extract SAME codes so the frontend can render affected counties
        # even when PostGIS geometry building fails.
        same_codes: list = []
        if alert.raw_json and isinstance(alert.raw_json, dict):
            same_codes = (
                alert.raw_json
                .get('properties', {})
                .get('geocode', {})
                .get('SAME', [])
            ) or []

        response_data = {
            'alert': {
                'type': 'Feature',
                'properties': {
                    'id': alert.id,
                    'identifier': alert.identifier,
                    'event': alert.event,
                    'severity': alert.severity,
                    'urgency': alert.urgency,
                    'headline': alert.headline,
                    'description': alert.description,
                    'sent': sent_iso,
                    'expires': expires_iso,
                    'area_desc': alert.area_desc,
                    'status': alert.status,
                    'is_county_wide': is_county_wide,
                    'same_codes': same_codes,
                },
                # geometry may be null; the frontend handles that gracefully
                'geometry': geometry,
            },
            'intersecting_boundaries': {
                'type': 'FeatureCollection',
                'features': intersecting_boundaries,
            },
        }

        return jsonify(response_data)

    except Exception as exc:  # pragma: no cover - defensive logging
        api_bp.logger.error("Error getting alert geometry: %s", exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve alert geometry'}), 500

def _parse_event_motion(raw: str) -> Dict[str, Any]:
    """Parse an NWS eventMotionDescription parameter string.

    Format (parts separated by '...' ):
      <ISO-timestamp>...storm...<degrees>DEG...<speed>KT...<lat1>,<lon1> <lat2>,<lon2>...

    The DEG value uses the same "from" convention as wind direction: it is the
    direction FROM which the storm is approaching, not the direction it is heading.
    062DEG means the storm is coming from the ENE and moving toward the WSW.

    Track coordinates are listed oldest-to-newest (first point = earliest known
    position, last point = most recent known position).

    Returns a dict with parsed fields. Raises on bad input so callers can
    catch and discard gracefully.
    """
    parts = [p.strip() for p in raw.split('...')]

    motion: Dict[str, Any] = {'raw': raw}

    for part in parts:
        upper = part.upper()
        if upper.endswith('DEG'):
            try:
                motion['direction_deg'] = int(part[:-3])
            except ValueError:
                pass
        elif upper.endswith('KT'):
            try:
                kt = float(part[:-2])
                motion['speed_kt'] = kt
                motion['speed_mph'] = round(kt * 1.15078, 1)
            except ValueError:
                pass
        elif 'T' in part and part[0].isdigit():
            motion['timestamp'] = part
        elif ',' in part:
            # Coordinate pairs — listed oldest first, newest last.
            coords = []
            for token in part.split():
                try:
                    lat_s, lon_s = token.split(',')
                    coords.append([float(lat_s), float(lon_s)])
                except ValueError:
                    pass
            if coords:
                motion['track'] = coords

    # direction_deg is the FROM direction (where the storm originated).
    # Compute the heading (where the storm is going) = FROM + 180°.
    deg = motion.get('direction_deg')
    if deg is not None:
        dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        # compass_from: direction the storm is approaching from (NWS convention)
        from_idx = int((deg + 11.25) / 22.5) % 16
        motion['compass_from'] = dirs[from_idx]
        # compass_toward: actual direction of travel (used for compass arrow)
        toward_deg = (deg + 180) % 360
        toward_idx = int((toward_deg + 11.25) / 22.5) % 16
        motion['compass_toward'] = dirs[toward_idx]
        motion['toward_deg'] = toward_deg
        # Keep 'compass' as the from-direction for backward compatibility
        motion['compass'] = motion['compass_from']

    return motion


# VTEC parsing is handled by app_utils.vtec — parse_vtec_display imported above.


def _extract_alert_display_data(alert) -> Optional[Dict[str, Any]]:
    """Extract enriched display data from an alert for template rendering.

    Works for both IPAWS and NOAA alerts.  Parses sender details,
    parameters, geocodes, resources, and (for IPAWS) digital signature
    certificate information and audio references.
    """
    raw_json = alert.raw_json
    if not isinstance(raw_json, dict):
        return None

    props = raw_json.get('properties', {})
    source = (props.get('source') or getattr(alert, 'source', '') or '').upper()

    is_ipaws = source == 'IPAWS' or bool(raw_json.get('raw_xml'))
    is_noaa = source == 'NOAA'

    # Must be a recognised source to extract extra data
    if not is_ipaws and not is_noaa:
        return None

    data: Dict[str, Any] = {
        'is_ipaws': is_ipaws,
        'is_noaa': is_noaa,
        'source_label': 'IPAWS' if is_ipaws else 'NOAA',
    }

    # --- Sender / origin information ---
    sender = props.get('sender', '')
    if sender:
        data['sender'] = sender
    sender_name = props.get('senderName', '')
    if sender_name:
        data['sender_name'] = sender_name

    # --- Scope, response type, category ---
    scope = props.get('scope', '')
    if scope:
        data['scope'] = scope
    response_type = props.get('responseType', '')
    if response_type:
        data['response_type'] = response_type
    category = props.get('category', '')
    if category:
        data['category'] = category

    # --- Effective, onset, and ends times ---
    effective = props.get('effective', '')
    if effective:
        data['effective'] = effective
    onset = props.get('onset', '')
    if onset:
        data['onset'] = onset
    ends = props.get('ends', '')
    if ends:
        data['ends'] = ends

    # --- Language ---
    language = props.get('language', '')
    if language:
        data['language'] = language

    # --- Event codes (NWS product code + SAME event code) ---
    event_code = props.get('eventCode', {})
    if event_code and isinstance(event_code, dict):
        data['event_code'] = event_code

    # --- Affected zones (NWS zone API URLs) ---
    affected_zones = props.get('affectedZones', [])
    if affected_zones:
        # Extract just the zone ID from the URL tail (e.g. OHC003)
        data['affected_zones'] = [z.rstrip('/').split('/')[-1] for z in affected_zones if z]

    # --- References to prior alerts in this series ---
    references = props.get('references', [])
    if references and isinstance(references, list):
        data['references'] = references

    # --- Web link from the alert ---
    web = props.get('web', '')
    if web and web.lower().startswith(('http://', 'https://')):
        data['web'] = web

    # --- IPAWS fetch endpoint (provenance) ---
    fetch_endpoint = props.get('_fetch_endpoint', '')
    if fetch_endpoint:
        data['fetch_endpoint'] = fetch_endpoint
    fetch_type = props.get('_fetch_endpoint_type', '')
    if fetch_type:
        data['fetch_endpoint_type'] = fetch_type

    # --- EAS parameters with decoded labels ---
    params = props.get('parameters', {})
    if params:
        eas_org_codes = params.get('EAS-ORG', [])
        data['eas_org'] = ', '.join(eas_org_codes)
        data['eas_station_id'] = ', '.join(params.get('EAS-STN-ID', []))
        data['block_channels'] = params.get('BLOCKCHANNEL', [])

        # Decode EAS-ORG codes to human-readable names
        try:
            from app_utils.eas import ORIGINATOR_DESCRIPTIONS
            decoded_orgs = []
            for code in eas_org_codes:
                label = ORIGINATOR_DESCRIPTIONS.get(code.strip().upper(), '')
                decoded_orgs.append({'code': code, 'label': label})
            if decoded_orgs:
                data['eas_org_decoded'] = decoded_orgs
        except ImportError:
            pass

        # --- Parse eventMotionDescription ---
        motion_raw_list = params.get('eventMotionDescription', [])
        motion_raw = motion_raw_list[0] if motion_raw_list else ''
        if motion_raw:
            try:
                data['storm_motion'] = _parse_event_motion(motion_raw)
            except Exception:
                pass

        # --- Parse VTEC ---
        vtec_list = params.get('VTEC', [])
        if vtec_list:
            try:
                data['vtec_parsed'] = [parse_vtec_display(v) for v in vtec_list if v]
            except Exception:
                pass

        # --- Severe weather threat parameters ---
        def _threat_level(val: str) -> str:
            v = (val or '').upper()
            if 'OBSERVED' in v or 'CONFIRMED' in v:
                return 'observed'
            if 'RADAR' in v:
                return 'radar'
            if 'POSSIBLE' in v or 'CONSIDERABLE' in v or 'DESTRUCTIVE' in v:
                return 'possible'
            return 'none'

        def _threat_display(val: str) -> str:
            mapping = {
                'RADAR INDICATED': 'Radar',
                'OBSERVED': 'Confirmed',
                'POSSIBLE': 'Possible',
                'CONSIDERABLE': 'Considerable',
                'DESTRUCTIVE': 'Destructive!',
                'NONE': 'None',
            }
            return mapping.get((val or '').upper(), (val or '').title())

        def _hail_descriptor(size_str: str) -> str:
            try:
                size = float((size_str or '').replace('"', '').strip())
            except (ValueError, TypeError):
                return ''
            if size < 0.25:   return 'Pea'
            if size < 0.5:    return 'Marble'
            if size < 0.75:   return 'Dime'
            if size < 1.0:    return 'Quarter'
            if size < 1.25:   return 'Half Dollar'
            if size < 1.5:    return 'Ping Pong'
            if size < 1.75:   return 'Golf Ball'
            if size < 2.0:    return 'Baseball'
            if size < 2.5:    return 'Tennis Ball'
            if size < 3.0:    return 'Softball'
            return 'Grapefruit'

        wind_threat = (params.get('windThreat') or [''])[0].strip()
        max_wind    = (params.get('maxWindGust') or [''])[0].strip()
        hail_threat = (params.get('hailThreat') or [''])[0].strip()
        max_hail    = (params.get('maxHailSize') or [''])[0].strip()
        tornado_det = (params.get('tornadoDetection') or [''])[0].strip()

        threat_data: Dict[str, Any] = {}
        if wind_threat or max_wind:
            gust_parts = max_wind.split()
            gust_unit = gust_parts[-1].upper() if len(gust_parts) > 1 and gust_parts[-1].upper() in ('MPH', 'KT', 'KMH') else 'MPH'
            gust_val  = gust_parts[0] if gust_parts else max_wind
            threat_data['wind'] = {
                'threat': wind_threat, 'gust': gust_val, 'gust_unit': gust_unit,
                'display': _threat_display(wind_threat), 'level': _threat_level(wind_threat),
            }
        if hail_threat or max_hail:
            threat_data['hail'] = {
                'threat': hail_threat, 'size': max_hail,
                'descriptor': _hail_descriptor(max_hail),
                'display': _threat_display(hail_threat), 'level': _threat_level(hail_threat),
            }
        if tornado_det:
            threat_data['tornado'] = {
                'detection': tornado_det,
                'display': _threat_display(tornado_det), 'level': _threat_level(tornado_det),
            }
        if threat_data:
            data['threat_data'] = threat_data

        # NWS internal headline (ALL-CAPS, operational text — different from the public headline)
        nws_headline = (params.get('NWSheadline') or [''])[0].strip()
        if nws_headline:
            data['nws_headline'] = nws_headline

        # Expose all remaining parameters for display
        extra_params = {}
        _handled = {
            'EAS-ORG', 'EAS-STN-ID', 'BLOCKCHANNEL', 'eventMotionDescription', 'VTEC',
            'windThreat', 'maxWindGust', 'hailThreat', 'maxHailSize', 'tornadoDetection',
            'NWSheadline',
        }
        for k, v in params.items():
            if k not in _handled:
                extra_params[k] = v
        if extra_params:
            data['extra_parameters'] = extra_params

    # --- SAME geocodes with decoded location names ---
    geocodes = props.get('geocode', {})
    if geocodes:
        same_codes = geocodes.get('SAME', [])
        data['same_codes'] = same_codes

        # Decode SAME codes to location names
        try:
            from app_utils.fips_codes import get_extended_same_lookup
            fips_lookup = get_extended_same_lookup()
            decoded_same = []
            for code in same_codes:
                label = fips_lookup.get(code, '')
                decoded_same.append({'code': code, 'label': label})
            if decoded_same:
                data['same_codes_decoded'] = decoded_same
        except ImportError:
            pass

        # Include any additional geocode types (UGC, FIPS6, etc.)
        extra_geocodes = {}
        for k, v in geocodes.items():
            if k != 'SAME':
                extra_geocodes[k] = v
        if extra_geocodes:
            data['extra_geocodes'] = extra_geocodes

    # --- Resources: separate audio from web links ---
    resources = props.get('resources', [])
    web_resources = []
    audio_resources = []
    for r in resources:
        mime = (r.get('mimeType') or '').lower()
        uri = r.get('uri', '')
        desc = r.get('resourceDesc', '')
        has_deref = bool(r.get('derefUri'))

        if 'audio' in mime or 'eas broadcast' in desc.lower():
            audio_resources.append({
                'description': desc or 'Audio',
                'mime_type': r.get('mimeType', ''),
                'size': r.get('size', ''),
                'has_inline_data': has_deref,
                'url': uri if uri and uri.lower().startswith(('http://', 'https://')) else '',
            })
        elif uri and uri.lower().startswith(('http://', 'https://')):
            web_resources.append({
                'description': desc or 'Link',
                'url': uri,
                'mime_type': r.get('mimeType', ''),
            })
    if web_resources:
        data['web_resources'] = web_resources
    if audio_resources:
        data['audio_resources'] = audio_resources

    # --- Certificate info (from enrichment) ---
    cert_info = getattr(alert, 'certificate_info', None)
    if cert_info and isinstance(cert_info, dict):
        data['certificate'] = cert_info

    # --- IPAWS original audio URL (saved to disk) ---
    ipaws_audio = getattr(alert, 'ipaws_audio_url', None)
    if ipaws_audio:
        data['ipaws_audio_filename'] = ipaws_audio

    return data


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

@api_bp.route('/alerts/<int:alert_id>/export.pdf')
def alert_detail_pdf(alert_id):
    """Generate archival PDF for a specific alert - server-side from database."""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        # Build PDF sections
        sections = []

        # Alert Information Section
        alert_info = [
            f"Event: {alert.event or 'N/A'}",
            f"Severity: {alert.severity or 'N/A'}",
            f"Status: {alert.status or 'N/A'}",
            f"Message Type: {alert.message_type or 'N/A'}",
            f"Urgency: {alert.urgency or 'N/A'}",
            f"Certainty: {alert.certainty or 'N/A'}",
            f"Identifier: {alert.identifier or 'N/A'}",
        ]

        if alert.sent:
            alert_info.append(f"Sent: {format_local_datetime(alert.sent, include_utc=True)}")
        if alert.expires:
            alert_info.append(f"Expires: {format_local_datetime(alert.expires, include_utc=True)}")

        sections.append({
            'heading': 'Alert Information',
            'content': alert_info,
        })

        # Description Section
        if alert.headline:
            sections.append({
                'heading': 'Headline',
                'content': alert.headline,
            })

        if alert.description:
            sections.append({
                'heading': 'Description',
                'content': alert.description,
            })

        if alert.instruction:
            sections.append({
                'heading': 'Instructions',
                'content': alert.instruction,
            })

        # Area Information — geocode fields were removed from the model;
        # extract them from the stored raw CAP JSON payload instead.
        _props = (alert.raw_json or {}).get('properties', {}) if alert.raw_json else {}
        _geocode = _props.get('geocode', {}) or {}
        geocode_same = _geocode.get('SAME', [])
        geocode_ugc = _geocode.get('UGC', [])

        area_info = []
        if alert.area_desc:
            area_info.append(f"Area Description: {alert.area_desc}")
        if geocode_same:
            area_info.append(f"SAME Codes: {', '.join(geocode_same)}")
        if geocode_ugc:
            area_info.append(f"UGC Codes: {', '.join(geocode_ugc)}")

        if area_info:
            sections.append({
                'heading': 'Affected Areas',
                'content': area_info,
            })

        # Source Information — sender fields were removed from the model;
        # extract them from raw_json instead.
        sender_name = _props.get('senderName', '') or ''
        sender_id = _props.get('sender', '') or ''

        source_info = []
        if sender_name:
            source_info.append(f"Sender: {sender_name}")
        if sender_id:
            source_info.append(f"Sender ID: {sender_id}")
        if alert.source:
            source_info.append(f"Source: {alert.source}")

        if source_info:
            sections.append({
                'heading': 'Source Information',
                'content': source_info,
            })

        # Generate PDF
        pdf_bytes = generate_pdf_document(
            title=f"Alert Detail Report - {alert.event or 'Alert'}",
            sections=sections,
            subtitle=f"Alert ID: {alert_id}",
            footer_text="Generated by EAS Station™ — Emergency Alert System Platform"
        )

        # Return as downloadable PDF
        response = Response(pdf_bytes, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f"inline; filename=alert_{alert_id}_{datetime.now().strftime('%Y%m%d')}.pdf"
        )
        return response

    except Exception as exc:
        api_bp.logger.error('Error generating alert PDF: %s', exc, exc_info=True)
        flash('Error generating PDF. Please try again.', 'error')
        return redirect(url_for('api.alert_detail', alert_id=alert_id))


_SOCIAL_IMAGE_RATIOS  = {'landscape', 'square', 'portrait', 'story'}
_SOCIAL_IMAGE_FORMATS = {'png', 'webp'}


@api_bp.route('/alerts/<int:alert_id>/export-image.png')
def alert_detail_image(alert_id):
    """Generate a social-share image for an alert.

    Accepts three optional query arguments:

    * ``ratio`` — one of ``landscape`` (1200×630, FB/X/LinkedIn
      open-graph cards), ``square`` (1080×1080 — Instagram, Mastodon),
      ``portrait`` (1080×1350 — Instagram 4:5), or ``story``
      (1080×1920 — IG / TikTok / Snap Stories & Reels).
    * ``format`` — ``png`` (default, universal) or ``webp`` (~30%
      smaller at equivalent quality; supported by every major social
      platform).
    * ``scale`` — output upscale factor, 1–3 (default ``2``).  Social
      platforms re-encode uploads to JPEG and display them downscaled;
      a 2× upload keeps that compression from reading as grain in the
      feed.  Pass ``scale=1`` for the native canvas size.

    Unknown values quietly fall back to ``landscape`` / ``png`` / ``2``.
    The file name and Content-Type are set from the chosen format so the
    browser saves the file with the right extension.
    """
    try:
        from app_utils.image_export import generate_alert_image
        from app_core.location import get_location_settings

        alert = CAPAlert.query.get_or_404(alert_id)

        ratio = (request.args.get('ratio') or 'landscape').strip().lower()
        if ratio not in _SOCIAL_IMAGE_RATIOS:
            ratio = 'landscape'

        fmt = (request.args.get('format') or 'png').strip().lower()
        if fmt not in _SOCIAL_IMAGE_FORMATS:
            fmt = 'png'

        try:
            scale = float(request.args.get('scale', 2))
        except (TypeError, ValueError):
            scale = 2.0
        scale = max(1.0, min(scale, 3.0))

        intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        coverage_data = calculate_coverage_percentages(alert_id, intersections)
        ipaws_data    = _extract_alert_display_data(alert)

        try:
            location_settings = get_location_settings()
        except Exception:
            location_settings = {}

        image_bytes = generate_alert_image(
            alert, coverage_data, ipaws_data, location_settings,
            aspect_ratio=ratio, image_format=fmt, scale=scale,
        )

        mimetype = 'image/webp' if fmt == 'webp' else 'image/png'
        response = Response(image_bytes, mimetype=mimetype)
        safe_event = (alert.event or 'alert').replace(' ', '_').lower()
        # Include the ratio + format in the filename so saving multiple
        # variants doesn't collide on disk.
        response.headers['Content-Disposition'] = (
            f'attachment; filename=alert_{alert_id}_{safe_event}_{ratio}.{fmt}'
        )
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except Exception as exc:
        api_bp.logger.error('Error generating alert image: %s', exc, exc_info=True)
        flash('Error generating image. Please try again.', 'error')
        return redirect(url_for('api.alert_detail', alert_id=alert_id))


@api_bp.route('/alerts/<int:alert_id>/ipaws_audio')
def ipaws_original_audio(alert_id):
    """Serve the original IPAWS audio file for an alert."""
    from flask import send_file
    alert = CAPAlert.query.get_or_404(alert_id)
    filename = getattr(alert, 'ipaws_audio_url', None)
    if not filename:
        return Response('No IPAWS audio available for this alert', status=404)

    # Prevent path traversal by ensuring filename contains no path separators
    safe_filename = os.path.basename(filename)
    if not safe_filename or safe_filename != filename:
        return Response('Invalid audio filename', status=400)

    eas_output = os.getenv('EAS_OUTPUT_DIR') or os.path.join(
        os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static')),
        'eas_messages',
    )
    filepath = os.path.join(eas_output, safe_filename)
    
    # Verify the resolved path is within the output directory
    try:
        real_filepath = os.path.realpath(filepath)
        real_output = os.path.realpath(eas_output)
        if not real_filepath.startswith(real_output + os.sep):
            return Response('Invalid audio file path', status=400)
    except (OSError, ValueError):
        return Response('Invalid audio file path', status=400)
    
    if not os.path.isfile(real_filepath):
        return Response('Audio file not found on disk', status=404)

    return send_file(real_filepath, mimetype='audio/mpeg', download_name=safe_filename)


@api_bp.route('/api/alerts')
@cache.cached(timeout=30, query_string=True, key_prefix='alerts_list')
def get_alerts():
    """Get CAP alerts as GeoJSON with optional inclusion of expired alerts"""
    try:
        include_expired = request.args.get('include_expired', 'false').lower() == 'true'

        if include_expired:
            alerts_query = CAPAlert.query
            api_bp.logger.info("Including expired alerts in API response")
        else:
            alerts_query = get_active_alerts_query()
            api_bp.logger.info("Including only active alerts in API response")

        alerts = alerts_query.with_entities(
            CAPAlert.id,
            CAPAlert.identifier,
            CAPAlert.event,
            CAPAlert.severity,
            CAPAlert.urgency,
            CAPAlert.headline,
            CAPAlert.description,
            CAPAlert.expires,
            CAPAlert.area_desc,
            CAPAlert.source,
            CAPAlert.eas_forwarded,
            CAPAlert.eas_forwarding_reason,
            func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
        ).all()

        alert_ids = [alert.id for alert in alerts if alert.id]
        plain_text_map = load_alert_plain_text_map(alert_ids)
        eas_sources = {ALERT_SOURCE_IPAWS, ALERT_SOURCE_MANUAL}

        # Load configured location terms once for the whole loop so we avoid
        # per-alert database round-trips and don't hardcode any location name.
        _county_short, _county_name_lower, _state_lower = _get_location_terms()

        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(func.lower(Boundary.type) == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json_loads(county_geom.geometry)
        except Exception as exc:  # pragma: no cover - defensive logging
            api_bp.logger.warning("Could not get county boundary: %s", exc)

        features = []
        for alert in alerts:
            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json_loads(alert.geometry)
            else:
                # Try to build geometry from SAME geocodes (IPAWS alerts)
                if try_build_geometry_from_same_codes(alert.id):
                    geom_json = db.session.query(
                        func.ST_AsGeoJSON(CAPAlert.geom)
                    ).filter(CAPAlert.id == alert.id).scalar()
                    if geom_json:
                        geometry = json_loads(geom_json)

                # Fallback: use county boundary if area_desc suggests county-wide
                if not geometry and alert.area_desc and any(
                    county_term in alert.area_desc.lower()
                    for county_term in filter(None, ['county', _county_short, _state_lower])
                ):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

            if not is_county_wide and alert.area_desc:
                area_lower = alert.area_desc.lower()

                if _county_short and _county_short in area_lower:
                    separator_count = max(area_lower.count(';'), area_lower.count(','))
                    if separator_count >= 2:
                        is_county_wide = True

                county_keywords = ['county', 'entire county']
                if _county_name_lower:
                    county_keywords.append(_county_name_lower)
                if any(keyword in area_lower for keyword in county_keywords):
                    is_county_wide = True

            source_value = alert.source
            plain_text = None
            if source_value in eas_sources:
                plain_text = plain_text_map.get(alert.id)

            if geometry:
                expires_iso = None
                if alert.expires:
                    expires_dt = alert.expires.replace(tzinfo=UTC_TZ) if alert.expires.tzinfo is None else alert.expires.astimezone(UTC_TZ)
                    expires_iso = expires_dt.isoformat()

                features.append(
                    {
                        'type': 'Feature',
                        'properties': {
                            'id': alert.id,
                            'identifier': alert.identifier,
                            'event': alert.event,
                            'severity': alert.severity,
                            'urgency': alert.urgency,
                            'headline': alert.headline,
                            'description': (
                                alert.description[:500] + '...'
                                if len(alert.description) > 500
                                else alert.description
                            ),
                            'area_desc': alert.area_desc,
                            'source': source_value,
                            'plain_text': plain_text,
                            'expires_iso': expires_iso,
                            'is_county_wide': is_county_wide,
                            'is_expired': is_alert_expired(alert.expires),
                            'eas_forwarded': bool(alert.eas_forwarded),
                            'eas_forwarding_reason': alert.eas_forwarding_reason,
                        },
                        'geometry': geometry,
                    }
                )

        api_bp.logger.info('Returning %s alerts (include_expired=%s)', len(features), include_expired)

        return jsonify(
            {
                'type': 'FeatureCollection',
                'features': features,
                'metadata': {
                    'total_features': len(features),
                    'include_expired': include_expired,
                    'generated_at': utc_now().isoformat(),
                },
            }
        )

    except Exception as exc:
        api_bp.logger.error('Error getting alerts: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve alerts'}), 500

@api_bp.route('/api/alerts/historical')
@cache.cached(timeout=60, query_string=True, key_prefix='alerts_historical')
def get_historical_alerts():
    """Get historical alerts as GeoJSON with date filtering"""
    try:
        start_date = request.args.get('start_date') or request.args.get('start')
        end_date = request.args.get('end_date') or request.args.get('end')
        include_active = request.args.get('include_active', 'false').lower() == 'true'

        if include_active:
            query = CAPAlert.query
        else:
            query = get_expired_alerts_query()

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC_TZ)
            except ValueError:
                return jsonify({'error': 'Invalid start_date format. Use ISO 8601 format (e.g., 2024-01-15 or 2024-01-15T10:30:00).'}), 400
            query = query.filter(CAPAlert.sent >= start_dt)

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC_TZ)
            except ValueError:
                return jsonify({'error': 'Invalid end_date format. Use ISO 8601 format (e.g., 2024-01-15 or 2024-01-15T10:30:00).'}), 400
            query = query.filter(CAPAlert.sent <= end_dt)

        matching_ids = query.with_entities(CAPAlert.id).scalar_subquery()

        alerts = db.session.query(
            CAPAlert.id,
            CAPAlert.identifier,
            CAPAlert.event,
            CAPAlert.severity,
            CAPAlert.urgency,
            CAPAlert.headline,
            CAPAlert.description,
            CAPAlert.expires,
            CAPAlert.sent,
            CAPAlert.area_desc,
            func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
        ).filter(
            CAPAlert.id.in_(matching_ids)
        ).all()

        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(func.lower(Boundary.type) == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json_loads(county_geom.geometry)
        except Exception as exc:  # pragma: no cover - defensive logging
            api_bp.logger.warning("Could not get county boundary: %s", exc)

        # Load configured location terms once for the whole loop.
        _county_short, _county_name_lower, _state_lower = _get_location_terms()

        features = []
        for alert in alerts:
            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json_loads(alert.geometry)
            else:
                # Try to build geometry from SAME geocodes (IPAWS alerts)
                if try_build_geometry_from_same_codes(alert.id):
                    geom_json = db.session.query(
                        func.ST_AsGeoJSON(CAPAlert.geom)
                    ).filter(CAPAlert.id == alert.id).scalar()
                    if geom_json:
                        geometry = json_loads(geom_json)

                # Fallback: use county boundary if area_desc suggests county-wide
                if not geometry and alert.area_desc and any(
                    county_term in alert.area_desc.lower()
                    for county_term in filter(None, ['county', _county_short, _state_lower])
                ):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

            if geometry:
                expires_iso = None
                if alert.expires:
                    expires_dt = alert.expires.replace(tzinfo=UTC_TZ) if alert.expires.tzinfo is None else alert.expires.astimezone(UTC_TZ)
                    expires_iso = expires_dt.isoformat()

                sent_iso = None
                if alert.sent:
                    sent_dt = alert.sent.replace(tzinfo=UTC_TZ) if alert.sent.tzinfo is None else alert.sent.astimezone(UTC_TZ)
                    sent_iso = sent_dt.isoformat()

                description = alert.description or ''
                if len(description) > 500:
                    description = description[:500] + '...'

                features.append(
                    {
                        'type': 'Feature',
                        'properties': {
                            'id': alert.id,
                            'identifier': alert.identifier,
                            'event': alert.event,
                            'severity': alert.severity,
                            'urgency': alert.urgency,
                            'headline': alert.headline,
                            'description': description,
                            'sent': sent_iso,
                            'expires': expires_iso,
                            'area_desc': alert.area_desc,
                            'is_historical': True,
                            'is_county_wide': is_county_wide,
                        },
                        'geometry': geometry,
                    }
                )

        return jsonify({'type': 'FeatureCollection', 'features': features})

    except Exception as exc:
        api_bp.logger.error('Error getting historical alerts: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve historical alerts'}), 500

@api_bp.route('/api/boundaries')
@cache.cached(timeout=300, query_string=True, key_prefix='boundaries_list')
def get_boundaries():
    """Get all boundaries as GeoJSON"""
    try:
        # Validate pagination parameters
        page = request.args.get('page', 1, type=int)
        page = max(1, page)  # Ensure page is at least 1
        per_page = request.args.get('per_page', 1000, type=int)
        per_page = min(max(per_page, 1), 5000)  # Clamp between 1 and 5000
        boundary_type = request.args.get('type')
        search = request.args.get('search')

        query = db.session.query(
            Boundary.id,
            Boundary.name,
            Boundary.type,
            Boundary.description,
            func.ST_AsGeoJSON(Boundary.geom).label('geometry'),
        )

        if boundary_type:
            normalized_type = normalize_boundary_type(boundary_type)
            query = query.filter(func.lower(Boundary.type) == normalized_type)

        if search:
            query = query.filter(Boundary.name.ilike(f'%{search}%'))

        boundaries = query.paginate(page=page, per_page=per_page, error_out=False).items

        features = []
        for boundary in boundaries:
            if boundary.geometry:
                normalized_type = normalize_boundary_type(boundary.type)
                features.append(
                    {
                        'type': 'Feature',
                        'properties': {
                            'id': boundary.id,
                            'name': boundary.name,
                            'type': normalized_type,
                            'raw_type': boundary.type,
                            'display_type': get_boundary_display_label(boundary.type),
                            'group': get_boundary_group(boundary.type),
                            'color': get_boundary_color(boundary.type),
                            'description': boundary.description,
                        },
                        'geometry': json_loads(boundary.geometry),
                    }
                )

        # When no county-type Boundary records have been uploaded, serve the
        # configured county from the bundled us_county_boundaries (Census TIGER)
        # table so the map always shows the correct county outline without
        # requiring a manual GeoJSON upload.
        if not features and boundary_type and normalize_boundary_type(boundary_type) == 'county':
            try:
                from app_core.location import get_location_settings
                from app_core.county_boundaries import get_county_count, same_codes_to_geoids
                if get_county_count() > 0:
                    _settings = get_location_settings()
                    geoids = same_codes_to_geoids(_settings.get('fips_codes') or [])
                    if geoids:
                        ucb_rows = db.session.query(
                            USCountyBoundary.id,
                            USCountyBoundary.namelsad,
                            USCountyBoundary.name,
                            USCountyBoundary.geoid,
                            func.ST_AsGeoJSON(USCountyBoundary.geom).label('geometry'),
                        ).filter(
                            USCountyBoundary.geoid.in_(geoids),
                            USCountyBoundary.geom.isnot(None),
                        ).all()
                        for row in ucb_rows:
                            if row.geometry:
                                features.append(
                                    {
                                        'type': 'Feature',
                                        'properties': {
                                            'id': row.id,
                                            'name': row.namelsad or row.name,
                                            'type': 'county',
                                            'raw_type': 'county',
                                            'display_type': get_boundary_display_label('county'),
                                            'group': get_boundary_group('county'),
                                            'color': get_boundary_color('county'),
                                            'description': f'Census TIGER county boundary (GEOID {row.geoid})',
                                            'source': 'us_county_boundaries',
                                        },
                                        'geometry': json_loads(row.geometry),
                                    }
                                )
            except Exception as exc:
                api_bp.logger.warning(
                    'County boundary fallback to us_county_boundaries failed: %s', exc
                )

        return jsonify({'type': 'FeatureCollection', 'features': features})
    except Exception as exc:
        api_bp.logger.error('Error fetching boundaries: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve boundaries'}), 500

@api_bp.route('/api/system_status')
@cache.cached(timeout=10, key_prefix='system_status')
def api_system_status():
    """Get system status information using new helper functions with timezone support"""
    try:
        # Collect system metrics first (these don't require database)
        cpu = _get_cpu_usage_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        current_utc = utc_now()
        current_local = local_now()
        hostname = socket.gethostname()
        ip_address = _get_primary_ip_address()
        uptime_seconds = max(current_utc.timestamp() - psutil.boot_time(), 0.0)

        # Location settings (county/state) for display screens
        county_name = ''
        state_code = ''
        try:
            from app_core.location import get_location_settings
            loc = get_location_settings()
            county_name = loc.get('county_name', '') or ''
            state_code = loc.get('state_code', '') or ''
        except Exception:
            pass

        status = 'healthy'
        status_reasons = []

        def _record_status(level: str, message: str) -> None:
            nonlocal status
            status_reasons.append({'level': level, 'message': message})
            if level == 'critical':
                status = 'critical'
            elif level == 'warning' and status != 'critical':
                status = 'warning'

        # Database queries with proper error handling
        total_boundaries = None
        active_alerts = None
        last_poll = None
        database_status = 'unknown'

        try:
            # Rollback any existing failed transaction before new queries.
            # This is a defensive measure to recover from "current transaction is
            # aborted" errors in PostgreSQL. We silently ignore rollback failures
            # because the session may not have an active transaction, which is fine.
            try:
                db.session.rollback()
            except SQLAlchemyError:
                pass  # No active transaction to rollback, which is expected

            total_boundaries = Boundary.query.count()
            active_alerts = get_active_alerts_query().count()
            last_poll = PollHistory.query.order_by(desc(PollHistory.timestamp)).first()
            database_status = 'connected'
        except SQLAlchemyError as db_exc:
            api_bp.logger.warning('Database error in system_status: %s', db_exc)
            database_status = 'error'
            _record_status(
                'critical',
                f'Database connection error: {str(db_exc)[:100]}'
            )
            # Try to rollback to recover the session for subsequent requests.
            # Rollback failure here is logged at debug level since the session
            # may already be in an unusable state.
            try:
                db.session.rollback()
            except SQLAlchemyError as rollback_exc:
                api_bp.logger.debug('Rollback after DB error also failed: %s', rollback_exc)

        if cpu >= 90:
            _record_status(
                'critical',
                f'CPU usage is {cpu:.1f}%, exceeding the 90% critical threshold.',
            )
        elif cpu >= 75:
            _record_status(
                'warning',
                f'CPU usage is {cpu:.1f}%, above the 75% warning threshold.',
            )

        if memory.percent >= 92:
            _record_status(
                'critical',
                (
                    'Memory usage is '
                    f'{memory.percent:.1f}%, exceeding the 92% critical threshold.'
                ),
            )
        elif memory.percent >= 80:
            _record_status(
                'warning',
                (
                    'Memory usage is '
                    f'{memory.percent:.1f}%, above the 80% warning threshold.'
                ),
            )

        if disk.percent >= 95:
            _record_status(
                'critical',
                (
                    'Disk usage is '
                    f'{disk.percent:.1f}% on the root volume with '
                    f"{disk.free // (1024 * 1024 * 1024)} GB free, exceeding the "
                    '95% critical threshold.'
                ),
            )
        elif disk.percent >= 85:
            _record_status(
                'warning',
                (
                    'Disk usage is '
                    f'{disk.percent:.1f}% on the root volume with '
                    f"{disk.free // (1024 * 1024 * 1024)} GB free, above the "
                    '85% warning threshold.'
                ),
            )

        poll_snapshot = None
        location_tz = get_location_timezone()
        if last_poll:
            poll_timestamp = last_poll.timestamp
            if poll_timestamp.tzinfo is None:
                poll_timestamp = poll_timestamp.replace(tzinfo=UTC_TZ)
            poll_age_minutes = (current_utc - poll_timestamp).total_seconds() / 60.0
            poll_local_time = poll_timestamp.astimezone(location_tz)
            poll_time_display = poll_local_time.strftime('%Y-%m-%d %H:%M %Z')
            if poll_age_minutes >= 60:
                _record_status(
                    'critical',
                    (
                        'Last poll ran '
                        f'{poll_age_minutes:.0f} minutes ago '
                        f'(local time {poll_time_display}).'
                    ),
                )
            elif poll_age_minutes >= 15:
                _record_status(
                    'warning',
                    (
                        'Last poll ran '
                        f'{poll_age_minutes:.0f} minutes ago '
                        f'(local time {poll_time_display}).'
                    ),
                )

            poll_status = (last_poll.status or '').strip().lower()
            if poll_status and poll_status not in {'success', 'ok', 'completed'}:
                level = 'critical' if poll_status in {'failed', 'error'} else 'warning'
                error_detail = (last_poll.error_message or '').strip()
                detail_suffix = f" Details: {error_detail}" if error_detail else ''
                _record_status(
                    level,
                    f"Last poll reported status '{last_poll.status}'.{detail_suffix}",
                )

            poll_snapshot = {
                'timestamp': poll_timestamp.isoformat(),
                'local_timestamp': poll_timestamp.astimezone(location_tz).isoformat(),
                'status': last_poll.status,
                'alerts_fetched': last_poll.alerts_fetched or 0,
                'alerts_new': last_poll.alerts_new or 0,
                'error_message': (last_poll.error_message or '').strip() or None,
                'data_source': last_poll.data_source,
            }
        elif database_status == 'connected':
            # Only record this warning if database is connected but no polls exist.
            # When database_status is 'error' or 'unknown', we already reported a
            # critical database error above, so we skip this warning to avoid confusion.
            _record_status(
                'warning',
                'No poll activity has been recorded yet; verify the poller service is '
                'running and configured.',
            )

        status_summary = 'All systems operational.'
        if status_reasons:
            summary_source = next(
                (reason for reason in status_reasons if reason['level'] == status),
                status_reasons[0],
            )
            status_summary = summary_source['message']

        return jsonify(
            {
                'status': status,
                'status_summary': status_summary,
                'status_reasons': status_reasons,
                'timestamp': current_utc.isoformat(),
                'local_timestamp': current_local.isoformat(),
                'timezone': get_location_timezone_name(),
                'hostname': hostname,
                'ip_address': ip_address,
                'county_name': county_name,
                'state_code': state_code,
                'boundaries_count': total_boundaries,
                'active_alerts_count': active_alerts,
                'database_status': database_status,
                'last_poll': poll_snapshot,
                'system_resources': {
                    'cpu_usage_percent': cpu,
                    'memory_usage_percent': memory.percent,
                    'disk_usage_percent': disk.percent,
                    'disk_free_gb': disk.free // (1024 * 1024 * 1024),
                },
                'uptime_seconds': uptime_seconds,
                'uptime_human': format_uptime(uptime_seconds),
            }
        )
    except Exception as exc:
        api_bp.logger.error('Error getting system status: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to get system status'}), 500

@api_bp.route('/api/system_health')
@cache.cached(timeout=10, key_prefix='system_health')
def api_system_health():
    """Get comprehensive system health information via API"""
    try:
        health_data = get_system_health()
        return jsonify(health_data)
    except Exception as exc:
        api_bp.logger.error('Error getting system health via API: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to get system health'}), 500


_HISTORY_RANGE_HOURS = {
    '1h': 1,
    '6h': 6,
    '12h': 12,
    '24h': 24,
    '3d': 72,
    '7d': 168,
    '30d': 720,
}


def _system_health_history_cache_key():
    return f"system_health_history:{request.query_string.decode('utf-8')}"


@api_bp.route('/api/system_health/history')
@cache.cached(timeout=15, key_prefix=_system_health_history_cache_key)
def api_system_health_history():
    """Return persisted system-health samples for sparklines and trend chart.

    Query parameters:
    - range: time window — one of 1h, 6h, 12h, 24h, 3d, 7d, 30d (default 24h)
    - points: max number of points to return (default 300, capped at 2000).
      The series is uniformly downsampled to at most this many points so
      the front-end can render long windows without shipping every raw row.
    """
    from datetime import timedelta as _td

    from app_core.analytics.models import SystemMetricSample

    range_key = (request.args.get('range') or '24h').lower()
    hours = _HISTORY_RANGE_HOURS.get(range_key, 24)

    try:
        max_points = int(request.args.get('points', 300))
    except (TypeError, ValueError):
        max_points = 300
    max_points = max(10, min(max_points, 2000))

    cutoff = utc_now() - _td(hours=hours)

    try:
        rows = (
            SystemMetricSample.query
            .filter(SystemMetricSample.recorded_at >= cutoff)
            .order_by(SystemMetricSample.recorded_at.asc())
            .all()
        )
    except SQLAlchemyError as exc:
        api_bp.logger.error('Failed to load system metric samples: %s', exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': 'Failed to load history'}), 500

    # Uniform downsampling — pick every Nth row so a 30-day @ 30s window
    # (~86k rows) collapses to a chart-friendly 300 points.
    total = len(rows)
    if total > max_points:
        step = total / max_points
        sampled = [rows[int(i * step)] for i in range(max_points)]
        # Always include the most recent row so the live tail lines up.
        if sampled[-1] is not rows[-1]:
            sampled.append(rows[-1])
        rows = sampled

    series = {
        'timestamps': [],
        'cpu': [],
        'memory': [],
        'swap': [],
        'load_1m': [],
        'load_5m': [],
        'load_15m': [],
        'storage': [],
        'temperature': [],
        'net_rx_bytes': [],
        'net_tx_bytes': [],
    }
    for row in rows:
        series['timestamps'].append(row.recorded_at.isoformat() if row.recorded_at else None)
        series['cpu'].append(row.cpu_percent)
        series['memory'].append(row.memory_percent)
        series['swap'].append(row.swap_percent)
        series['load_1m'].append(row.load_1m)
        series['load_5m'].append(row.load_5m)
        series['load_15m'].append(row.load_15m)
        series['storage'].append(row.storage_percent)
        series['temperature'].append(row.temperature_c)
        series['net_rx_bytes'].append(row.net_rx_bytes)
        series['net_tx_bytes'].append(row.net_tx_bytes)

    return jsonify({
        'range': range_key,
        'hours': hours,
        'count': len(rows),
        'total_raw_samples': total,
        'series': series,
    })


@api_bp.route('/api/smart_diag')
def api_smart_diag():
    """Diagnostic endpoint: shows raw smartctl JSON output for debugging."""
    import shutil
    import subprocess as _sp

    from app_utils.system import _nvme_controller_path

    smartctl_path = shutil.which("smartctl") or "/usr/sbin/smartctl"

    # ── Gather smartctl version ──
    smartctl_version = None
    try:
        ver = _sp.run(
            ["sudo", "-n", smartctl_path, "--version"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        first_line = (ver.stdout or "").split("\n", 1)[0].strip()
        if first_line:
            smartctl_version = first_line
    except Exception:
        pass

    # ── Discover disks via lsblk ──
    try:
        lsblk = _sp.run(
            ["lsblk", "--json", "--output", "NAME,PATH,TYPE,TRAN"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        lsblk_data = json.loads(lsblk.stdout or "{}")
    except Exception as exc:
        return jsonify({"error": f"lsblk failed: {exc}"})

    block_devs = lsblk_data.get("blockdevices") or []

    def _find_disks(entries):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if (entry.get("type") or "").lower() == "disk":
                name = entry.get("name") or ""
                if not name.startswith(("ram", "loop", "zram")):
                    yield entry
            for child in entry.get("children") or []:
                yield from _find_disks([child])

    def _run_smartctl(cmd):
        """Run a smartctl command and return a diagnostic dict."""
        attempt: dict = {"command": " ".join(cmd)}
        try:
            result = _sp.run(cmd, capture_output=True, text=True, check=False, timeout=15)
            attempt["exit_code"] = result.returncode
            attempt["stderr"] = (result.stderr or "").strip()[:500]
            raw = (result.stdout or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    attempt["json_keys"] = sorted(parsed.keys())
                    attempt["has_nvme_health_log"] = "nvme_smart_health_information_log" in parsed
                    attempt["has_temperature"] = "temperature" in parsed
                    attempt["has_smart_status"] = "smart_status" in parsed
                    # Surface smartctl messages (error/warning reasons)
                    sc = parsed.get("smartctl")
                    if isinstance(sc, dict):
                        msgs = sc.get("messages")
                        if msgs:
                            attempt["smartctl_messages"] = msgs
                    nvme_log = parsed.get("nvme_smart_health_information_log")
                    if isinstance(nvme_log, dict):
                        attempt["nvme_log_keys"] = sorted(nvme_log.keys())
                        attempt["nvme_log_sample"] = {
                            k: nvme_log.get(k)
                            for k in [
                                "temperature", "power_on_hours", "percentage_used",
                                "available_spare", "data_units_written", "power_cycles",
                            ]
                            if k in nvme_log
                        }
                except json.JSONDecodeError:
                    attempt["raw_output_start"] = raw[:500]
            else:
                attempt["raw_output_start"] = "(empty)"
        except Exception as exc:
            attempt["error"] = str(exc)
        return attempt

    devices_output: list = []

    for disk in _find_disks(block_devs):
        path = disk.get("path") or f"/dev/{disk.get('name')}"
        name = disk.get("name") or ""
        tran = (disk.get("tran") or "").lower()
        is_nvme = "nvme" in name or tran == "nvme"

        diag: dict = {
            "path": path,
            "name": name,
            "transport": tran,
            "is_nvme": is_nvme,
        }

        if is_nvme:
            # NVMe devices: try multiple strategies to find what works.
            # Different smartctl versions / kernels / platforms need
            # different path + flag combinations.
            controller_path = _nvme_controller_path(path)
            strategies = [
                (path,            "nvme"),   # namespace + -d nvme
                (controller_path, "nvme"),   # controller + -d nvme
                (path,            "auto"),   # namespace + -d auto
                (path,            None),     # namespace, no -d flag
            ]
            # Deduplicate when controller == namespace
            seen = set()
            diag["attempts"] = []
            for dev_path, d_flag in strategies:
                key = (dev_path, d_flag)
                if key in seen:
                    continue
                seen.add(key)
                cmd = ["sudo", "-n", smartctl_path]
                if d_flag:
                    cmd.extend(["-d", d_flag])
                cmd.extend(["--json", "-a", dev_path])
                diag["attempts"].append(_run_smartctl(cmd))
        else:
            cmd = ["sudo", "-n", smartctl_path, "-d", "auto", "--json", "-a", path]
            diag["attempts"] = [_run_smartctl(cmd)]

        devices_output.append(diag)

    return jsonify({
        "smartctl_version": smartctl_version,
        "devices": devices_output,
    })


__all__ = ['register_api_routes']
