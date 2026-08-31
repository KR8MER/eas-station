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

"""Lazily-generated, disk-cached *Level II* radar loops for weather alerts.

A deliberately separate feature from radar_loop.py's default loop, not a
replacement for it. maps.py's _render_map() used to always prefer a
sharper Level II render (raw per-site volume scans via Py-ART) over the
Level III WMS-T national mosaic every other radar view in this app uses --
that was reverted (see maps.py's radar-overlay comment) because it meant
the exported/looped image could look nothing like the in-app "Radar (at
time of alert)" toggle for the same alert: different resolution, a
different color ramp, sometimes present where the toggle's mosaic was too.

This module reintroduces Level II, but only behind its own explicitly
"High-Resolution" labeled UI (see templates/alert_detail.html's separate
card), never as a silent substitute for the standard loop or toggle. It
also exposes the one Level II product Level III doesn't have at all:
base velocity, for spotting rotation.

Coverage is real but not universal -- Level II only reaches ~230km from a
WSR-88D site (see radar_level2.py's _MAX_SITE_RANGE_KM), so an alert far
from every site, or one predating this feature's data window, may render
zero frames even though the standard Level III loop above it works fine.
That's a genuine coverage gap, not a bug, and the API response distinguishes
it from "not a weather alert" so the frontend can say so.

Same lazy/cached/bounded-per-call design as radar_loop.py: no background
job proactively snapshots frames, build_hires_radar_loop() renders a
bounded number of not-yet-cached frames per call, and the frontend polls
until pending reaches 0. Each frame is a real NEXRAD volume decode
(download + Py-ART), meaningfully slower than a WMS-T tile fetch, so the
per-call cap here is smaller than the standard loop's.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from . import radar_level2 as _radar_level2
from .maps import _render_map
from .radar_loop import _needed_timestamps
from .tiles import _geojson_bbox

logger = logging.getLogger(__name__)

#: Same 5-minute target grid as the standard loop (radar_loop.py) -- Level
#: II's actual volume cadence is irregular (~4-10 min depending on VCP), so
#: find_volume_key()'s nearest-within-tolerance matching (radar_level2.py)
#: is what actually decides which volume backs a given grid timestamp;
#: adjacent gridpoints landing on the same volume is expected, not a bug.
RADAR_LOOP_HIRES_CADENCE_MINUTES = 5
RADAR_LOOP_HIRES_MAX_FRAMES = 36

#: Lower than RADAR_LOOP_MAX_RENDER_PER_CALL (radar_loop.py) -- a Level II
#: frame is a full volume download (multiple MB) plus a Py-ART decode, not
#: a small WMS tile fetch, so fewer fit in one request without stalling a
#: gevent worker for too long.
RADAR_LOOP_HIRES_MAX_RENDER_PER_CALL = 1

RADAR_LOOP_HIRES_FRAME_W = 500
RADAR_LOOP_HIRES_FRAME_H = 420

VALID_FIELDS = ('reflectivity', 'velocity')


def _loop_output_dir() -> Path:
    base = os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static'))
    return Path(base) / 'radar_loops_hires'


def _frame_dir(alert_id: int, field: str) -> Path:
    return _loop_output_dir() / str(alert_id) / field


def _frame_filename(ts) -> str:
    return ts.strftime('%Y%m%dT%H%MZ') + '.png'


def build_hires_radar_loop(
    alert: Any, geom: Dict, *,
    field: str = 'reflectivity',
    max_new_frames: int = RADAR_LOOP_HIRES_MAX_RENDER_PER_CALL,
) -> Dict[str, Any]:
    """Return the current state of *alert*'s Level II radar loop for
    *field* ('reflectivity' or 'velocity'), rendering up to
    *max_new_frames* not-yet-cached frames this call.

    Args:
        alert: A CAPAlert (or anything with the same id/category/severity/
            sent/expires/cancelled_at attributes).
        geom: The alert's geometry as a GeoJSON dict.
        field: 'reflectivity' or 'velocity'.
        max_new_frames: Cap on frames rendered in this call.

    Returns:
        ``{"frames": [{"time": iso, "url": ...}, ...], "pending": int,
        "total": int}`` on success (``total`` and ``frames`` can both be 0
        for a genuine Level II coverage gap -- not an error), or
        ``{"frames": [], "pending": 0, "total": 0, "error": ...}`` if the
        alert/field isn't eligible at all.
    """
    if field not in VALID_FIELDS:
        return {'frames': [], 'pending': 0, 'total': 0, 'error': f"Unknown field {field!r}"}
    if getattr(alert, 'category', None) != 'Met':
        return {'frames': [], 'pending': 0, 'total': 0, 'error': 'Radar loop is only available for weather alerts'}
    sent = getattr(alert, 'sent', None)
    if not sent:
        return {'frames': [], 'pending': 0, 'total': 0, 'error': 'Alert has no sent time'}

    # Site range only depends on location, not time -- check once per
    # alert rather than once per frame. _render_map()/render_frame() are
    # both best-effort (return a radar-less map / None rather than raise),
    # so without this upfront check a genuine coverage gap would silently
    # cache and serve basemap-only "frames" indistinguishable from a
    # legitimate no-echo Level II frame, instead of being reported as the
    # coverage gap it actually is.
    bbox = _geojson_bbox(geom)
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        center_lat, center_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
        if _radar_level2.nearest_site(center_lat, center_lon) is None:
            return {
                'frames': [], 'pending': 0, 'total': 0,
                'error': 'No WSR-88D radar site within range of this alert -- Level II coverage gap',
            }

    now = datetime.now(timezone.utc)
    end_candidates = [c for c in (getattr(alert, 'cancelled_at', None), getattr(alert, 'expires', None)) if c]
    end = min(end_candidates) if end_candidates else now
    end = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
    end = min(end, now)  # never request radar for the future

    needed = _needed_timestamps(sent, end)
    # radar_loop.py's helper is capped at its own RADAR_LOOP_MAX_FRAMES;
    # re-cap to this module's (equal, but independent so the two can drift
    # without coupling) constant defensively.
    needed = needed[:RADAR_LOOP_HIRES_MAX_FRAMES]

    alert_id = getattr(alert, 'id')
    frame_dir = _frame_dir(alert_id, field)
    frame_dir.mkdir(parents=True, exist_ok=True)

    frames: List[Dict[str, Any]] = []
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
                    map_w=RADAR_LOOP_HIRES_FRAME_W, map_h=RADAR_LOOP_HIRES_FRAME_H,
                    radar_source='level2', radar_field=field,
                )
                img.save(path)
                rendered_this_call += 1
            except Exception as exc:
                logger.warning(
                    "Hi-res radar loop frame render failed for alert %s @ %s (%s): %s",
                    alert_id, ts, field, exc,
                )
                continue
        if path.exists():
            frames.append({
                'time': ts.isoformat(),
                'url': f'/static/radar_loops_hires/{alert_id}/{field}/{_frame_filename(ts)}',
            })

    return {
        'frames': frames,
        'pending': len(needed) - len(frames),
        'total': len(needed),
    }


__all__ = [
    'build_hires_radar_loop', 'VALID_FIELDS',
    'RADAR_LOOP_HIRES_CADENCE_MINUTES', 'RADAR_LOOP_HIRES_MAX_FRAMES',
]
