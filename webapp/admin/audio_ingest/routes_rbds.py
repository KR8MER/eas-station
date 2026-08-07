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

"""RBDS history endpoint."""

import logging
from datetime import timedelta
from typing import Any, Dict, List
from flask import jsonify, request
from app_core.extensions import db
from app_core.models import (
    AudioSourceMetrics,
)
from app_utils import utc_now

from .blueprint import audio_ingest_bp

logger = logging.getLogger(__name__)


# RBDS metadata fields whose snapshot-to-snapshot changes are surfaced as
# history events.  (key, human label) — ordering controls event ordering
# when several fields change in the same snapshot.
_RBDS_EVENT_FIELDS = (
    ('rbds_lock_state', 'Lock'),
    ('rbds_pi_code', 'PI'),
    ('rbds_call_sign', 'Call sign'),
    ('rbds_ps_name', 'PS'),
    ('rbds_radio_text', 'RadioText'),
    ('rbds_program_type_name', 'PTY'),
    ('rbds_ta', 'TA'),
    ('rbds_ews_channel', 'EWS channel'),
)


# Keep the BLER series small enough to chart comfortably; snapshots are
# written about once a second, so an hour is ~3600 raw rows.
_RBDS_HISTORY_MAX_POINTS = 480


_RBDS_HISTORY_MAX_EVENTS = 300


@audio_ingest_bp.route('/api/audio/sources/<path:source_name>/rbds/history', methods=['GET'])
def api_get_rbds_history(source_name: str):
    """Historical RBDS telemetry for one audio source.

    Derives two views from the ``audio_source_metrics`` snapshots that the
    audio service already persists (the UI previously only ever showed the
    latest snapshot):

    - ``points``: downsampled raw/net BLER (and glitch counter) series for
      trend charts.
    - ``events``: field-change log (PS / RadioText / TA / PI / PTY / lock
      transitions), i.e. the things an operator wants to scroll back
      through after the fact.

    Query string: ``minutes`` (default 60, clamped 5..1440).
    """
    try:
        minutes = int(request.args.get('minutes', 60))
    except (TypeError, ValueError):
        minutes = 60
    minutes = max(5, min(minutes, 1440))
    cutoff = utc_now() - timedelta(minutes=minutes)

    try:
        rows = (
            db.session.query(
                AudioSourceMetrics.timestamp,
                AudioSourceMetrics.source_metadata,
            )
            .filter(
                AudioSourceMetrics.source_name == source_name,
                AudioSourceMetrics.timestamp >= cutoff,
            )
            .order_by(AudioSourceMetrics.timestamp.asc())
            .limit(90000)
            .all()
        )
    except Exception as exc:
        logger.error('Error querying RBDS history for %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

    raw_points: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    prev_values: Dict[str, Any] = {}

    for ts, md in rows:
        md = md or {}
        if 'rbds_lock_state' not in md and 'rbds_blocks_total' not in md:
            continue
        iso_ts = ts.isoformat() if ts is not None else None

        raw_points.append({
            't': iso_ts,
            'raw_bler': md.get('rbds_raw_bler'),
            'net_bler': md.get('rbds_net_bler'),
            'glitches': md.get('rbds_glitches_rejected'),
        })

        for key, label in _RBDS_EVENT_FIELDS:
            cur = md.get(key)
            # Missing keys mean the publisher omitted the field for this
            # snapshot, not that the value reverted — keep the previous
            # value so partial snapshots don't fabricate flap events.
            if cur is None or cur == '':
                continue
            if key in prev_values and prev_values[key] != cur:
                events.append({
                    't': iso_ts,
                    'field': label,
                    'from': prev_values[key],
                    'to': cur,
                })
            prev_values[key] = cur

    sample_count = len(raw_points)
    if sample_count > _RBDS_HISTORY_MAX_POINTS:
        stride = -(-sample_count // _RBDS_HISTORY_MAX_POINTS)  # ceil div
        raw_points = raw_points[::stride]

    return jsonify({
        'source': source_name,
        'minutes': minutes,
        'sample_count': sample_count,
        'points': raw_points,
        'events': events[-_RBDS_HISTORY_MAX_EVENTS:],
    })
