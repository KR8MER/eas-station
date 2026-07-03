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

"""Filter parsing, query building, and query-string helpers for the
received-alerts list view (/audio/received).

Sources and event codes accept multiple values and an include/exclude
mode, so operators can select several sources at once or hide noisy
ones (e.g. filter weekly-test events out of the list entirely).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode

from sqlalchemy import or_

from app_core.models import ReceivedEASAlert

FILTER_MODES = ('include', 'exclude')

DEFAULT_PER_PAGE = 25

_CHIP_LABELS = {
    'search': 'Search',
    'source': 'Source',
    'event': 'Event',
    'alert_source': 'Path',
    'decision': 'Decision',
    'originator': 'Originator',
    'date_from': 'From',
    'date_to': 'To',
    'min_confidence': 'Confidence',
}


def parse_filters(args) -> Dict[str, Any]:
    """Parse and sanitise received-alerts filter parameters.

    ``args`` is a werkzeug MultiDict (``request.args``); repeated keys
    (``?source=A&source=B``) become lists. Invalid values degrade to the
    unfiltered default rather than erroring.
    """

    def _multi(name: str) -> List[str]:
        seen = set()
        values: List[str] = []
        for raw in args.getlist(name):
            value = raw.strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def _mode(name: str) -> str:
        mode = (args.get(name) or 'include').strip().lower()
        return mode if mode in FILTER_MODES else 'include'

    filters: Dict[str, Any] = {
        'search': (args.get('search') or '').strip(),
        'sources': _multi('source'),
        'source_mode': _mode('source_mode'),
        'events': _multi('event'),
        'event_mode': _mode('event_mode'),
        'alert_source': (args.get('alert_source') or '').strip(),
        'decision': (args.get('decision') or '').strip(),
        'originator': (args.get('originator') or '').strip(),
        'date_from': (args.get('date_from') or '').strip(),
        'date_to': (args.get('date_to') or '').strip(),
        'min_confidence': None,
    }

    # Date inputs are YYYY-MM-DD; silently drop anything malformed.
    for key in ('date_from', 'date_to'):
        if filters[key]:
            try:
                datetime.strptime(filters[key], '%Y-%m-%d')
            except ValueError:
                filters[key] = ''

    raw_confidence = (args.get('min_confidence') or '').strip()
    if raw_confidence:
        try:
            value = float(raw_confidence)
            if 0.0 <= value <= 1.0:
                filters['min_confidence'] = value
        except ValueError:
            pass

    return filters


def apply_filters(query, filters: Dict[str, Any]):
    """Apply parsed filters to a ReceivedEASAlert query."""
    if filters['search']:
        term = f"%{filters['search']}%"
        query = query.filter(
            or_(
                ReceivedEASAlert.event_code.ilike(term),
                ReceivedEASAlert.event_name.ilike(term),
                ReceivedEASAlert.raw_same_header.ilike(term),
                ReceivedEASAlert.originator_name.ilike(term),
                ReceivedEASAlert.callsign.ilike(term),
            )
        )

    if filters['sources']:
        column = ReceivedEASAlert.source_name  # NOT NULL, no None guard needed
        if filters['source_mode'] == 'exclude':
            query = query.filter(column.notin_(filters['sources']))
        else:
            query = query.filter(column.in_(filters['sources']))

    if filters['events']:
        column = ReceivedEASAlert.event_code
        if filters['event_mode'] == 'exclude':
            # event_code is nullable and NULL NOT IN (...) evaluates to NULL
            # in SQL, which would drop code-less rows from an exclusion
            # filter; keep them visible.
            query = query.filter(or_(column.is_(None), column.notin_(filters['events'])))
        else:
            query = query.filter(column.in_(filters['events']))

    if filters['alert_source']:
        query = query.filter(ReceivedEASAlert.alert_source == filters['alert_source'])

    if filters['decision']:
        query = query.filter(ReceivedEASAlert.forwarding_decision == filters['decision'])

    if filters['originator']:
        query = query.filter(ReceivedEASAlert.originator_code == filters['originator'])

    # Date range: inputs are YYYY-MM-DD dates, treated as inclusive days.
    if filters['date_from']:
        start = datetime.strptime(filters['date_from'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        query = query.filter(ReceivedEASAlert.received_at >= start)
    if filters['date_to']:
        end = datetime.strptime(filters['date_to'], '%Y-%m-%d').replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
        )
        query = query.filter(ReceivedEASAlert.received_at <= end)

    if filters['min_confidence'] is not None:
        query = query.filter(ReceivedEASAlert.decode_confidence >= filters['min_confidence'])

    return query


def filter_params(filters: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Flatten parsed filters into (key, value) query-string pairs.

    Mode markers are only emitted when they matter (values selected and
    mode is exclude), so URLs stay canonical and shareable.
    """
    params: List[Tuple[str, str]] = []
    if filters['search']:
        params.append(('search', filters['search']))
    for source in filters['sources']:
        params.append(('source', source))
    if filters['sources'] and filters['source_mode'] == 'exclude':
        params.append(('source_mode', 'exclude'))
    for event in filters['events']:
        params.append(('event', event))
    if filters['events'] and filters['event_mode'] == 'exclude':
        params.append(('event_mode', 'exclude'))
    for key in ('alert_source', 'decision', 'originator', 'date_from', 'date_to'):
        if filters[key]:
            params.append((key, filters[key]))
    if filters['min_confidence'] is not None:
        params.append(('min_confidence', f"{filters['min_confidence']:g}"))
    return params


def build_filter_chips(filters: Dict[str, Any], per_page: int) -> List[Dict[str, str]]:
    """Build the active-filter chips with per-chip removal query strings."""
    params = filter_params(filters)
    chips: List[Dict[str, str]] = []
    for index, (key, value) in enumerate(params):
        if key in ('source_mode', 'event_mode'):
            continue

        remaining = [pair for i, pair in enumerate(params) if i != index]
        # Removing the last value of a multi-filter orphans its mode marker.
        if key == 'source' and not any(k == 'source' for k, _ in remaining):
            remaining = [pair for pair in remaining if pair[0] != 'source_mode']
        if key == 'event' and not any(k == 'event' for k, _ in remaining):
            remaining = [pair for pair in remaining if pair[0] != 'event_mode']
        if per_page != DEFAULT_PER_PAGE:
            remaining.append(('per_page', str(per_page)))

        label = _CHIP_LABELS.get(key, key)
        display = value
        if key == 'source' and filters['source_mode'] == 'exclude':
            label = 'Not source'
        elif key == 'event' and filters['event_mode'] == 'exclude':
            label = 'Not event'
        elif key == 'min_confidence':
            display = f"≥ {float(value) * 100:g}%"

        chips.append({'label': label, 'value': display, 'remove_qs': urlencode(remaining)})
    return chips


def build_pager_qs(filters: Dict[str, Any], per_page: int) -> str:
    """Query string carried through pagination links (without the page number)."""
    return urlencode(filter_params(filters) + [('per_page', str(per_page))])
