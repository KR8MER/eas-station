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

"""Lazily-generated, disk-cached radar reflectivity loops for weather alerts.

No background job proactively snapshots frames while an alert is active.
IEM's WMS-T radar archive (see app_utils.image_export.maps) holds every
5-minute frame back to 2011-02-16, independent of when we ask -- so instead
this renders an alert's loop the first time someone actually views it, and
caches each frame to disk permanently (a frame for a given past timestamp
never changes, since an alert's sent/expires/cancelled_at window is fixed
once set). This also means it works retroactively for any weather alert
already in the database, not just ones ingested after this feature shipped.

build_radar_loop() renders a bounded number of not-yet-cached frames per
call rather than the whole loop at once (a long severe-weather episode
could need dozens of WMS fetches, too slow for one request) and reports how
many are still pending -- the API route this backs is designed to be
polled by the frontend until `pending` reaches 0.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .maps import _render_map

logger = logging.getLogger(__name__)

#: Matches the WMS-T service's own PT5M cadence (see maps.py's
#: _floor_to_5min) -- requesting anything finer would just get the same
#: frame back repeatedly.
RADAR_LOOP_CADENCE_MINUTES = 5

#: Cap on total frames per alert. A Tornado/Severe Thunderstorm Warning
#: (30-60 min) is nowhere near this; a multi-day Flood Watch would be
#: hundreds of frames uncapped, so long-duration alerts get their first
#: ~3 hours rather than unbounded storage/render-time growth.
RADAR_LOOP_MAX_FRAMES = 36

#: How many not-yet-cached frames one build_radar_loop() call will render.
#: Bounds a single request to a few seconds (each frame is one WMS fetch +
#: cached-after-first-frame basemap tiles) rather than up to a minute for a
#: full 36-frame loop rendered in one shot.
RADAR_LOOP_MAX_RENDER_PER_CALL = 6

RADAR_LOOP_FRAME_W = 500
RADAR_LOOP_FRAME_H = 420


def _loop_output_dir() -> Path:
    base = os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static'))
    return Path(base) / 'radar_loops'


def _frame_dir(alert_id: int) -> Path:
    return _loop_output_dir() / str(alert_id)


def _frame_filename(ts: datetime) -> str:
    return ts.strftime('%Y%m%dT%H%MZ') + '.png'


def _floor_to_cadence(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    minute = (dt.minute // RADAR_LOOP_CADENCE_MINUTES) * RADAR_LOOP_CADENCE_MINUTES
    return dt.replace(minute=minute, second=0, microsecond=0)


def _needed_timestamps(sent: datetime, end: datetime) -> List[datetime]:
    """5-minute-cadence timestamps from *sent* through *end* (inclusive),
    capped at RADAR_LOOP_MAX_FRAMES from the start of the window."""
    start = _floor_to_cadence(sent)
    stop = _floor_to_cadence(end)
    out: List[datetime] = []
    t = start
    while t <= stop and len(out) < RADAR_LOOP_MAX_FRAMES:
        out.append(t)
        t += timedelta(minutes=RADAR_LOOP_CADENCE_MINUTES)
    return out


def build_radar_loop(alert: Any, geom: Dict, *, max_new_frames: int = RADAR_LOOP_MAX_RENDER_PER_CALL) -> Dict[str, Any]:
    """Return the current state of *alert*'s radar loop, rendering up to
    *max_new_frames* not-yet-cached frames this call.

    Args:
        alert: A CAPAlert (or anything with the same id/category/severity/
            sent/expires/cancelled_at attributes).
        geom: The alert's geometry as a GeoJSON dict.
        max_new_frames: Cap on frames rendered in this call.

    Returns:
        ``{"frames": [{"time": iso, "url": ...}, ...], "pending": int,
        "total": int}`` on success, or ``{"frames": [], "pending": 0,
        "total": 0, "error": ...}`` if the alert isn't eligible.
    """
    if getattr(alert, 'category', None) != 'Met':
        return {'frames': [], 'pending': 0, 'total': 0, 'error': 'Radar loop is only available for weather alerts'}
    sent = getattr(alert, 'sent', None)
    if not sent:
        return {'frames': [], 'pending': 0, 'total': 0, 'error': 'Alert has no sent time'}

    now = datetime.now(timezone.utc)
    end_candidates = [c for c in (getattr(alert, 'cancelled_at', None), getattr(alert, 'expires', None)) if c]
    end = min(end_candidates) if end_candidates else now
    end = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
    end = min(end, now)  # never request radar for the future

    needed = _needed_timestamps(sent, end)
    alert_id = getattr(alert, 'id')
    frame_dir = _frame_dir(alert_id)
    frame_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    rendered_this_call = 0
    for ts in needed:
        path = frame_dir / _frame_filename(ts)
        if not path.exists():
            if rendered_this_call >= max_new_frames:
                continue  # still pending -- a later call picks it up
            try:
                img = _render_map(
                    geom, getattr(alert, 'severity', None) or 'Moderate',
                    category='Met', sent=ts,
                    map_w=RADAR_LOOP_FRAME_W, map_h=RADAR_LOOP_FRAME_H,
                )
                img.save(path)
                rendered_this_call += 1
            except Exception as exc:
                logger.warning(
                    "Radar loop frame render failed for alert %s @ %s: %s",
                    alert_id, ts, exc,
                )
                continue
        if path.exists():
            frames.append({
                'time': ts.isoformat(),
                'url': f'/static/radar_loops/{alert_id}/{_frame_filename(ts)}',
            })

    return {
        'frames': frames,
        'pending': len(needed) - len(frames),
        'total': len(needed),
    }


__all__ = ['build_radar_loop', 'RADAR_LOOP_CADENCE_MINUTES', 'RADAR_LOOP_MAX_FRAMES']
