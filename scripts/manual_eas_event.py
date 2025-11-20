#!/usr/bin/env python3
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

"""Trigger manual EAS broadcasts from raw CAP XML messages."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence, Set, Tuple
from xml.etree import ElementTree

# Add repository root to Python path so 'app' module can be imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)

from app import (
    CAPAlert,
    EASMessage,
    SystemLog,
    app,
    assign_alert_geometry,
    calculate_alert_intersections,
    db,
    get_location_settings,
    logger,
    parse_nws_datetime,
    utc_now,
)
from app_utils import ALERT_SOURCE_MANUAL
from app_utils.eas import EASBroadcaster, load_eas_config
from app_utils.event_codes import (
    ALL_EVENT_CODES,
    DEFAULT_EVENT_CODES,
    EVENT_CODE_ALLOW_ALL_TOKENS,
    EVENT_CODE_PRESET_TOKENS,
    describe_event_code,
    format_event_code_list,
    normalise_event_code,
    resolve_event_code,
)
from app_utils.fips_codes import ALL_US_FIPS_CODES, US_FIPS_COUNTIES

CAP_NAMESPACE = 'urn:oasis:names:tc:emergency:cap:1.2'
NS = {'cap': CAP_NAMESPACE}
DEFAULT_FIPS_CODES = {'039137'}
FIPS_ALL_TOKENS = {'ALL', 'ANY', 'UNITED STATES', 'US', 'USA'}
EVENT_ALL_TOKENS = EVENT_CODE_ALLOW_ALL_TOKENS


class ManualCAPError(Exception):
    """Raised when the manual CAP ingest workflow encounters a fatal error."""


def _text(element: Optional[ElementTree.Element]) -> str:
    if element is None or element.text is None:
        return ''
    return element.text.strip()


def _find_text(parent: ElementTree.Element, path: str) -> str:
    node = parent.find(path, NS)
    return _text(node)


def _normalise_fips(value: str) -> Optional[str]:
    digits = ''.join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    if len(digits) < 6:
        digits = digits.zfill(6)
    else:
        digits = digits[:6]
    return digits


def _extract_geocodes(info_element: ElementTree.Element) -> Tuple[List[str], List[str]]:
    same_codes: List[str] = []
    fips_codes: List[str] = []

    geocode_nodes: List[ElementTree.Element] = list(info_element.findall('cap:geocode', NS))
    for area in info_element.findall('cap:area', NS):
        geocode_nodes += list(area.findall('cap:geocode', NS))

    for node in geocode_nodes:
        name = _find_text(node, 'cap:valueName')
        value = _find_text(node, 'cap:value')
        if not value:
            continue
        normalised = _normalise_fips(value)
        upper_name = name.upper()
        if upper_name == 'SAME' and normalised:
            same_codes.append(normalised)
        elif upper_name.startswith('FIPS') and normalised:
            fips_codes.append(normalised)
        elif not name and normalised:
            fips_codes.append(normalised)

    return same_codes, fips_codes


def _extract_event_codes(info_element: ElementTree.Element) -> List[str]:
    codes: List[str] = []

    for node in info_element.findall('cap:eventCode', NS):
        value = _find_text(node, 'cap:value')
        code = normalise_event_code(value)
        if code:
            codes.append(code)

    for param in info_element.findall('cap:parameter', NS):
        name = _find_text(param, 'cap:valueName')
        value = _find_text(param, 'cap:value')
        if not value:
            continue
        if name and name.upper() not in {'EVENT', 'EVENTCODE', 'EVENT_CODE', 'SAME'}:
            continue
        code = normalise_event_code(value)
        if code:
            codes.append(code)

    seen: Set[str] = set()
    ordered: List[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)

    return ordered


def _extract_polygons(info_element: ElementTree.Element) -> Optional[Dict[str, object]]:
    polygons: List[List[Tuple[float, float]]] = []

    for area in info_element.findall('cap:area', NS):
        for polygon_node in area.findall('cap:polygon', NS):
            text_value = _text(polygon_node)
            if not text_value:
                continue
            points: List[Tuple[float, float]] = []
            for pair in text_value.split():
                if ',' not in pair:
                    continue
                lat_str, lon_str = pair.split(',', 1)
                try:
                    lat = float(lat_str)
                    lon = float(lon_str)
                except ValueError:
                    continue
                points.append((lon, lat))
            if len(points) >= 3:
                if points[0] != points[-1]:
                    points.append(points[0])
                polygons.append(points)

    if not polygons:
        return None

    if len(polygons) == 1:
        return {'type': 'Polygon', 'coordinates': [polygons[0]]}

    return {'type': 'MultiPolygon', 'coordinates': [[poly] for poly in polygons]}


def parse_cap_xml(xml_text: str) -> Tuple[Dict[str, object], Set[str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ManualCAPError(f'Invalid CAP XML: {exc}') from exc

    if root.tag != f'{{{CAP_NAMESPACE}}}alert':
        raise ManualCAPError('The provided XML is not a CAP alert document.')

    info = root.find('cap:info', NS)
    if info is None:
        raise ManualCAPError('CAP alert does not contain an <info> block.')

    identifier = _find_text(root, 'cap:identifier')
    sent_text = _find_text(root, 'cap:sent')
    expires_text = _find_text(info, 'cap:expires') or _find_text(root, 'cap:expires')

    parsed: Dict[str, object] = {
        'identifier': identifier or f"manual_{utc_now().strftime('%Y%m%d%H%M%S')}",
        'sent': parse_nws_datetime(sent_text) if sent_text else utc_now(),
        'expires': parse_nws_datetime(expires_text) if expires_text else None,
        'status': _find_text(root, 'cap:status') or 'Unknown',
        'message_type': _find_text(root, 'cap:msgType') or 'Unknown',
        'scope': _find_text(root, 'cap:scope') or 'Unknown',
        'category': _find_text(info, 'cap:category') or 'Unknown',
        'event': _find_text(info, 'cap:event') or 'Unknown',
        'urgency': _find_text(info, 'cap:urgency') or 'Unknown',
        'severity': _find_text(info, 'cap:severity') or 'Unknown',
        'certainty': _find_text(info, 'cap:certainty') or 'Unknown',
        'area_desc': '',
        'headline': _find_text(info, 'cap:headline') or '',
        'description': _find_text(info, 'cap:description') or '',
        'instruction': _find_text(info, 'cap:instruction') or '',
    }

    area_descs: List[str] = []
    for area in info.findall('cap:area', NS):
        desc = _find_text(area, 'cap:areaDesc')
        if desc:
            area_descs.append(desc)
    if not area_descs:
        single = _find_text(info, 'cap:areaDesc')
        if single:
            area_descs.append(single)
    parsed['area_desc'] = '; '.join(area_descs)

    same_codes, fips_codes = _extract_geocodes(info)
    event_codes = _extract_event_codes(info)
    resolved_event_code = resolve_event_code(parsed['event'], event_codes)
    if resolved_event_code and resolved_event_code not in event_codes:
        event_codes.append(resolved_event_code)
    geometry = _extract_polygons(info)
    parsed['_geometry_data'] = geometry
    parsed['geocode'] = {
        'same': same_codes,
        'fips': fips_codes,
    }
    parsed['event_codes'] = event_codes
    parsed['resolved_event_code'] = resolved_event_code
    parsed['raw_json'] = {
        'source': 'manual_cap',
        'xml': xml_text,
        'properties': {
            'identifier': parsed['identifier'],
            'event': parsed['event'],
            'eventCode': resolved_event_code,
            'eventCodes': event_codes,
            'sent': sent_text,
            'expires': expires_text,
            'status': parsed['status'],
            'messageType': parsed['message_type'],
            'scope': parsed['scope'],
            'category': parsed['category'],
            'urgency': parsed['urgency'],
            'severity': parsed['severity'],
            'certainty': parsed['certainty'],
            'headline': parsed['headline'],
            'description': parsed['description'],
            'instruction': parsed['instruction'],
            'areaDesc': parsed['area_desc'],
            'geocode': {
                'SAME': same_codes,
                'FIPS': fips_codes,
            },
        },
        'geometry': geometry,
    }

    return parsed, set(same_codes + fips_codes)


def _normalise_manual_input(value: str, *, allow_all_token: bool = True) -> Optional[str]:
    token = value.strip()
    if not token:
        return None
    if allow_all_token and token.upper() in FIPS_ALL_TOKENS:
        return 'ALL'
    return _normalise_fips(token)


def _parse_event_inputs(values: Sequence[str]) -> Tuple[Set[str], bool, List[str]]:
    codes: Set[str] = set()
    allow_all = False
    invalid_tokens: List[str] = []

    for value in values:
        token = value.strip()
        if not token:
            continue
        upper = token.upper()
        if upper in EVENT_ALL_TOKENS:
            allow_all = True
            continue
        if upper in EVENT_CODE_PRESET_TOKENS:
            codes.update(EVENT_CODE_PRESET_TOKENS[upper])
            continue
        code = normalise_event_code(token)
        if code:
            codes.add(code)
            continue
        invalid_tokens.append(token)

    return codes, allow_all, invalid_tokens


def determine_allowed_event_codes(cli_codes: Sequence[str]) -> Set[str]:
    codes, allow_all_cli, invalid_cli = _parse_event_inputs(cli_codes)

    env_codes: Set[str] = set()
    allow_all_env = False
    invalid_env: List[str] = []
    env_setting = os.getenv('EAS_MANUAL_EVENT_CODES', '')
    if env_setting:
        env_values = [value for value in env_setting.split(',') if value]
        env_codes, allow_all_env, invalid_env = _parse_event_inputs(env_values)

    invalid_tokens = invalid_cli + invalid_env

    combined: Set[str] = set()
    combined.update(codes)
    combined.update(env_codes)

    if invalid_tokens:
        logger.warning('Ignoring unrecognized manual event tokens: %s', ', '.join(sorted(set(invalid_tokens))))

    invalid_codes = sorted(code for code in combined if code not in ALL_EVENT_CODES)
    if invalid_codes:
        logger.warning('Ignoring unsupported manual event codes: %s', ', '.join(invalid_codes))
        combined.difference_update(invalid_codes)

    if allow_all_cli or allow_all_env:
        return set(ALL_EVENT_CODES)

    if combined:
        return combined

    return set(DEFAULT_EVENT_CODES)


def determine_allowed_fips(cli_codes: Sequence[str]) -> Set[str]:
    allow_all = False
    codes: Set[str] = set()

    for value in cli_codes:
        processed = _normalise_manual_input(value)
        if processed == 'ALL':
            allow_all = True
            continue
        if processed:
            codes.add(processed)

    env_setting = os.getenv('EAS_MANUAL_FIPS_CODES', '')
    if env_setting:
        for item in env_setting.split(','):
            processed = _normalise_manual_input(item)
            if processed == 'ALL':
                allow_all = True
                continue
            if processed:
                codes.add(processed)

    if allow_all:
        return set(ALL_US_FIPS_CODES)

    invalid_codes = sorted(code for code in codes if code not in ALL_US_FIPS_CODES)
    if invalid_codes:
        logger.warning('Ignoring unrecognized manual FIPS codes: %s', ', '.join(invalid_codes))
        codes.difference_update(invalid_codes)

    if not codes:
        return set(DEFAULT_FIPS_CODES)

    return codes


def _format_fips_labels(codes: Sequence[str]) -> List[str]:
    formatted: List[str] = []
    for code in codes:
        description = US_FIPS_COUNTIES.get(code, 'Unknown area')
        formatted.append(f"{code} ({description})")
    return formatted


def _summarise_fips_set(codes: Sequence[str]) -> str:
    ordered = list(sorted(codes))
    if not ordered:
        return ''
    if len(ordered) > 20:
        preview = ', '.join(ordered[:20])
        return f"{preview}, ... ({len(ordered)} total)"
    return ', '.join(ordered)


def _summarise_event_codes(codes: Sequence[str]) -> str:
    ordered = list(sorted(codes))
    if not ordered:
        return ''
    labels = format_event_code_list(ordered)
    if len(labels) > 10:
        preview = ', '.join(labels[:10])
        return f"{preview}, ... ({len(labels)} total)"
    return ', '.join(labels)


def load_cap_source(args: argparse.Namespace) -> str:
    if args.cap_file:
        with open(args.cap_file, 'r', encoding='utf-8') as fh:
            return fh.read()
    data = sys.stdin.read()
    if not data.strip():
        raise ManualCAPError('No CAP XML provided via STDIN.')
    return data


def broadcast_manual_cap(
    xml_text: str,
    allowed_fips: Set[str],
    allowed_event_codes: Set[str],
    dry_run: bool = False,
) -> Tuple[str, List[str], str]:
    parsed_alert, alert_fips = parse_cap_xml(xml_text)
    matched = sorted({code for code in alert_fips if code in allowed_fips})
    unknown_targets = sorted(code for code in alert_fips if code not in ALL_US_FIPS_CODES)
    event_codes = list(parsed_alert.get('event_codes') or [])
    resolved_event_code = parsed_alert.get('resolved_event_code') or resolve_event_code(parsed_alert.get('event', ''), [])
    if resolved_event_code and resolved_event_code not in event_codes:
        event_codes.append(resolved_event_code)
    matched_events = sorted(code for code in event_codes if code in allowed_event_codes)
    broadcast_event_code = resolved_event_code
    if broadcast_event_code not in matched_events and matched_events:
        broadcast_event_code = matched_events[0]

    if unknown_targets:
        logger.warning(
            'CAP alert references FIPS codes that are not in the national registry: %s',
            ', '.join(unknown_targets),
        )

    if not matched:
        raise ManualCAPError(
            'CAP alert does not target an allowed FIPS code. '
            f"Allowed={_summarise_fips_set(allowed_fips)}, alert={_summarise_fips_set(alert_fips)}"
        )

    if not matched_events:
        raise ManualCAPError(
            'CAP alert does not use an allowed event code. '
            f"Allowed={_summarise_event_codes(allowed_event_codes)}, alert={_summarise_event_codes(event_codes)}"
        )

    if dry_run:
        return parsed_alert['identifier'], matched, broadcast_event_code

    with app.app_context():
        geometry_data = parsed_alert.get('_geometry_data')
        payload = dict(parsed_alert)
        payload.pop('_geometry_data', None)
        payload['event_code'] = broadcast_event_code
        payload['event_codes'] = event_codes
        payload['source'] = ALERT_SOURCE_MANUAL

        existing = CAPAlert.query.filter_by(identifier=payload['identifier']).first()
        action = 'created'
        if existing:
            for key, value in payload.items():
                if key != 'raw_json' and hasattr(existing, key):
                    setattr(existing, key, value)
            existing.raw_json = payload.get('raw_json')
            existing.updated_at = utc_now()
            assign_alert_geometry(existing, geometry_data)
            db.session.add(existing)
            action = 'updated'
            alert_record = existing
        else:
            alert_record = CAPAlert(**payload)
            alert_record.created_at = utc_now()
            alert_record.updated_at = utc_now()
            assign_alert_geometry(alert_record, geometry_data)
            db.session.add(alert_record)

        db.session.flush()
        if alert_record.geom:
            try:
                calculate_alert_intersections(alert_record)
                db.session.flush()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning('Intersection calculation failed for manual CAP %s: %s', alert_record.identifier, exc)
                db.session.rollback()
                db.session.add(alert_record)

        db.session.commit()

        eas_config = load_eas_config(app.root_path)
        location_settings = get_location_settings()
        broadcaster = EASBroadcaster(db.session, EASMessage, eas_config, logger, location_settings)
        try:
            broadcaster.handle_alert(alert_record, payload)
        except Exception as exc:
            logger.error('EAS broadcast failed for manual CAP %s: %s', alert_record.identifier, exc)

        try:
            log_entry = SystemLog(
                level='INFO',
                message='Manual CAP broadcast executed',
                module='manual_eas_event',
                details={
                    'identifier': alert_record.identifier,
                    'action': action,
                    'matched_fips': {code: US_FIPS_COUNTIES.get(code) for code in matched},
                    'unknown_fips': unknown_targets,
                    'event_code': broadcast_event_code,
                    'event_labels': format_event_code_list(matched_events),
                },
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as exc:
            logger.warning('Failed to record manual CAP broadcast log: %s', exc)
            db.session.rollback()

    return parsed_alert['identifier'], matched, broadcast_event_code


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Trigger a manual EAS broadcast from a raw CAP XML file.')
    parser.add_argument('cap_file', nargs='?', help='Path to the CAP XML file. Reads from STDIN when omitted.')
    parser.add_argument(
        '--fips',
        action='append',
        default=[],
        metavar='CODE',
        help='Additional FIPS/SAME codes to authorize for this broadcast (can be repeated).',
    )
    parser.add_argument(
        '--event',
        action='append',
        default=[],
        metavar='CODE',
        help='Additional SAME event codes to authorize for this broadcast (can be repeated).',
    )
    parser.add_argument('--dry-run', action='store_true', help='Validate the CAP without storing data or broadcasting audio.')
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    allowed_fips = determine_allowed_fips(args.fips)
    allowed_event_codes = determine_allowed_event_codes(args.event)

    try:
        xml_text = load_cap_source(args)
        identifier, matched, event_code = broadcast_manual_cap(
            xml_text,
            allowed_fips,
            allowed_event_codes,
            dry_run=args.dry_run,
        )
    except ManualCAPError as exc:
        logger.error('Manual CAP broadcast aborted: %s', exc)
        return 2
    except Exception as exc:
        logger.exception('Unexpected error during manual CAP broadcast: %s', exc)
        return 1

    labels = _format_fips_labels(matched)
    if args.dry_run:
        print(
            f"DRY RUN: CAP {identifier} {describe_event_code(event_code)} "
            f"would broadcast for {', '.join(labels)}"
        )
    else:
        print(
            f"Broadcast complete for CAP {identifier} {describe_event_code(event_code)} "
            f"({', '.join(labels)})"
        )

    return 0


if __name__ == '__main__':
    sys.exit(main())
