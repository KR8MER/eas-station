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

"""Animated GIF share-card export.

Reuses generate_alert_image()'s full card composition once per cached
radar-loop frame timestamp (see radar_loop.build_radar_loop), swapping
only the map inset's radar time and polygon visibility between frames --
the header, info panels, and footer are identical on every frame, so the
only thing that visibly animates is the radar sweep and the moment the
warning polygon appears. Frames before the alert's own `sent` time render
without the polygon (see RADAR_LOOP_LEADIN_MINUTES in radar_loop.py) so
the loop shows the storm on approach before cutting to "and this is why a
warning was issued" -- never the reverse.
"""

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from PIL import Image

from .palette import _BG
from .radar_loop import RADAR_LOOP_MAX_FRAMES, build_radar_loop
from .render import generate_alert_image

logger = logging.getLogger(__name__)

#: Milliseconds each frame is shown. Slow enough that the lead-in frames
#: read as "storm approaching" rather than a strobe; fast enough that a
#: full ~15-frame loop still completes in a few seconds.
GIF_FRAME_DURATION_MS = 400

#: The final (most-recently-issued) frame holds an extra beat before the
#: loop restarts, so a viewer glancing at a paused/static preview is more
#: likely to land on the polygon-revealed state than mid-approach.
GIF_LAST_FRAME_DURATION_MS = 1600

#: GIF frames don't benefit from supersampling the way a single
#: JPEG-recompressed share image does (there's no re-encode softening the
#: output), and it multiplies both encode time and file size by the frame
#: count -- capped lower than the PNG export's 3.0.
GIF_MAX_SCALE = 2.0


def generate_alert_gif(
    alert: Any,
    coverage_data: Dict[str, Any],
    ipaws_data: Optional[Dict[str, Any]],
    location_settings: Optional[Dict[str, Any]],
    geom: Dict[str, Any],
    aspect_ratio: str = 'landscape',
    db_session: Any = None,
    scale: float = 1.0,
) -> bytes:
    """Render an animated GIF share card for a weather alert.

    Args:
        alert, coverage_data, ipaws_data, location_settings: Same as
            generate_alert_image().
        geom: The alert's geometry as a GeoJSON dict. Callers already have
            this (build_radar_loop and generate_alert_image both need it),
            so it's taken as a parameter instead of re-querying it once
            per frame.
        aspect_ratio: Same options as generate_alert_image().
        db_session: SQLAlchemy session for the per-frame renders. GIF
            assembly always runs off the request greenlet on a plain
            thread (see routes_alert_export.py's _run_off_worker), so
            there is no implicit Flask-SQLAlchemy session to fall back
            to -- pass a session bound for that thread.
        scale: Output upscale factor, capped at GIF_MAX_SCALE.

    Returns:
        Raw GIF bytes (infinite loop, one full card per radar-loop frame).

    Raises:
        ValueError: if the alert isn't eligible for a radar loop (not a
            weather alert, no `sent` time) or no frames could be rendered.
    """
    loop_result = build_radar_loop(alert, geom, max_new_frames=RADAR_LOOP_MAX_FRAMES)
    if loop_result.get('error'):
        raise ValueError(loop_result['error'])
    frames_meta = loop_result['frames']
    if not frames_meta:
        raise ValueError('No radar frames available for this alert yet')

    scale = max(1.0, min(float(scale or 1.0), GIF_MAX_SCALE))

    rendered: List[Image.Image] = []
    for frame in frames_meta:
        ts = datetime.fromisoformat(frame['time'])
        png_bytes = generate_alert_image(
            alert, coverage_data, ipaws_data, location_settings,
            aspect_ratio=aspect_ratio, image_format='png',
            db_session=db_session, scale=scale,
            radar_time=ts, radar_show_polygon=frame['issued'],
        )
        # generate_alert_image()'s PNG has fully transparent rounded
        # corners (see render.py) -- GIF has no true alpha compositing,
        # so flatten against the card's own canvas colour rather than
        # letting an implicit RGB conversion pick whatever was underneath.
        rgba = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
        flat = Image.new('RGB', rgba.size, _BG)
        flat.paste(rgba, mask=rgba.split()[3])
        rendered.append(flat)

    if len(rendered) == 1:
        quantized = [rendered[0].quantize(colors=256, method=Image.MEDIANCUT)]
    else:
        # Quantize every frame against one shared palette built from all
        # of them combined. The header/panels/footer are pixel-identical
        # across frames -- independent per-frame quantization would still
        # assign them slightly different palette entries and read as a
        # flicker on every loop cycle even though nothing there changed.
        w, h = rendered[0].size
        combined = Image.new('RGB', (w, h * len(rendered)))
        for i, frame_img in enumerate(rendered):
            combined.paste(frame_img, (0, i * h))
        shared_palette = combined.quantize(colors=256, method=Image.MEDIANCUT)
        quantized = [
            frame_img.quantize(palette=shared_palette, dither=Image.FLOYDSTEINBERG)
            for frame_img in rendered
        ]

    durations = [GIF_FRAME_DURATION_MS] * (len(quantized) - 1) + [GIF_LAST_FRAME_DURATION_MS]

    buf = io.BytesIO()
    quantized[0].save(
        buf, format='GIF', save_all=True, append_images=quantized[1:],
        duration=durations, loop=0,
    )
    return buf.getvalue()


__all__ = ['generate_alert_gif', 'GIF_FRAME_DURATION_MS', 'GIF_LAST_FRAME_DURATION_MS', 'GIF_MAX_SCALE']
