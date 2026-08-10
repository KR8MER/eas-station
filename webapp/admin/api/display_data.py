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

"""One alert flattened into the dict the detail views render.

``_extract_alert_display_data`` is the single reader of the CAP ``parameters``
blob: VTEC identity, storm motion, the tornado/thunderstorm damage tags, and
the IPAWS extras all come out of here. The detail page, the PDF export and the
social-share image render from the same dict, which is why this is a module
rather than a helper owned by any one of them.

See ``docs/reference/NWS_ALERT_PARAMETERS.md`` for the parameter catalogue.
"""

from typing import Any, Dict, Optional

from app_utils.vtec import parse_vtec_display

from .motion import _parse_event_motion


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
