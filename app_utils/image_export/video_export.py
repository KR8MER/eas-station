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

"""Animated video share-card export.

Replaces an earlier GIF export (see git history) -- Facebook (and most
other social platforms) doesn't actually serve uploaded GIFs as GIFs; it
transcodes them into a silent looping MP4 on ingest. Encoding straight to
MP4 skips that lossy round-trip, and sidesteps GIF's 256-colour palette
entirely, which was producing visible banding/dithering on real radar
reflectivity and multi-megabyte files for a ~10-frame loop.

Reuses generate_alert_image()'s full card composition once per cached
radar-loop frame timestamp (see radar_loop.build_radar_loop), swapping
only the map inset's radar time and polygon visibility between frames --
the header, info panels, and footer are identical on every frame, so the
only thing that visibly animates is the radar sweep and the moment the
warning polygon appears. Frames before the alert's own `sent` time render
without the polygon (see RADAR_LOOP_LEADIN_MINUTES in radar_loop.py) so
the loop shows the storm on approach before cutting to "and this is why a
warning was issued" -- never the reverse.

ffmpeg is already a system dependency of this project (audio pipeline,
TTS fallback) -- this reuses it rather than adding a Python video-encoding
library.
"""

import io
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from .palette import _BG
from .radar_loop import RADAR_LOOP_MAX_FRAMES, build_radar_loop
from .render import generate_alert_image

logger = logging.getLogger(__name__)

#: Frames per second of the encoded video. Matches the old GIF export's
#: 400ms-per-frame pacing -- slow enough that the lead-in frames read as
#: "storm approaching" rather than a strobe, fast enough that a full
#: ~15-frame loop still completes in a few seconds.
VIDEO_FPS = 2.5

#: The final (most-recently-issued) frame is repeated this many times so
#: it holds on screen for an extra beat before the loop restarts -- a
#: viewer glancing at a paused player is more likely to land on the
#: polygon-revealed state than mid-approach. ~1.6s at VIDEO_FPS.
VIDEO_LAST_FRAME_HOLD_COUNT = 4

#: Video frames don't benefit from supersampling the way a single
#: JPEG-recompressed share image does (there's no re-encode softening the
#: output), and it multiplies both encode time and file size by the frame
#: count -- capped lower than the PNG export's 3.0.
VIDEO_MAX_SCALE = 2.0

#: Generous but bounded -- a stuck/hung ffmpeg process must not hold the
#: gevent threadpool slot (see routes_alert_export_video.py's
#: _run_off_worker) forever.
_FFMPEG_TIMEOUT_SECONDS = 120


def generate_alert_video(
    alert: Any,
    coverage_data: Dict[str, Any],
    ipaws_data: Optional[Dict[str, Any]],
    location_settings: Optional[Dict[str, Any]],
    geom: Dict[str, Any],
    aspect_ratio: str = 'landscape',
    db_session: Any = None,
    scale: float = 1.0,
) -> bytes:
    """Render an animated MP4 (H.264) share card for a weather alert.

    Args:
        alert, coverage_data, ipaws_data, location_settings: Same as
            generate_alert_image().
        geom: The alert's geometry as a GeoJSON dict. Callers already have
            this (build_radar_loop and generate_alert_image both need it),
            so it's taken as a parameter instead of re-querying it once
            per frame.
        aspect_ratio: Same options as generate_alert_image().
        db_session: SQLAlchemy session for the per-frame renders. Video
            assembly always runs off the request greenlet on a plain
            thread (see routes_alert_export_video.py's _run_off_worker),
            so there is no implicit Flask-SQLAlchemy session to fall back
            to -- pass a session bound for that thread.
        scale: Output upscale factor, capped at VIDEO_MAX_SCALE.

    Returns:
        Raw MP4 bytes (H.264/yuv420p, no audio track, plays once -- most
        feeds that show a GIF-like card loop video automatically).

    Raises:
        ValueError: if the alert isn't eligible for a radar loop (not a
            weather alert, no `sent` time), no frames could be rendered,
            or ffmpeg isn't installed.
    """
    if shutil.which('ffmpeg') is None:
        raise ValueError('ffmpeg is not installed on this system; cannot encode video')

    loop_result = build_radar_loop(alert, geom, max_new_frames=RADAR_LOOP_MAX_FRAMES)
    if loop_result.get('error'):
        raise ValueError(loop_result['error'])
    frames_meta = loop_result['frames']
    if not frames_meta:
        raise ValueError('No radar frames available for this alert yet')

    scale = max(1.0, min(float(scale or 1.0), VIDEO_MAX_SCALE))

    rendered: List[bytes] = []
    for frame in frames_meta:
        ts = datetime.fromisoformat(frame['time'])
        png_bytes = generate_alert_image(
            alert, coverage_data, ipaws_data, location_settings,
            aspect_ratio=aspect_ratio, image_format='png',
            db_session=db_session, scale=scale,
            radar_time=ts, radar_show_polygon=frame['issued'],
        )
        # generate_alert_image()'s PNG has fully transparent rounded
        # corners (see render.py) -- flatten against the card's own
        # canvas colour rather than leaving alpha for ffmpeg's PNG
        # decoder to interpret however it sees fit.
        rgba = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
        flat = Image.new('RGB', rgba.size, _BG)
        flat.paste(rgba, mask=rgba.split()[3])
        out = io.BytesIO()
        flat.save(out, format='PNG')
        rendered.append(out.getvalue())

    frame_sequence = rendered[:-1] + [rendered[-1]] * VIDEO_LAST_FRAME_HOLD_COUNT

    with tempfile.TemporaryDirectory(prefix='eas_alert_video_') as tmp_dir:
        tmp_path = Path(tmp_dir)
        for i, png_bytes in enumerate(frame_sequence):
            (tmp_path / f'frame_{i:04d}.png').write_bytes(png_bytes)

        out_path = tmp_path / 'out.mp4'
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-framerate', str(VIDEO_FPS),
            '-i', str(tmp_path / 'frame_%04d.png'),
            # Card dimensions are already even, but scale (a user-supplied
            # float) can round to an odd width/height -- yuv420p requires
            # both dimensions even, so force it regardless of input size.
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '20',
            '-movflags', '+faststart',
            str(out_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error("ffmpeg timed out encoding alert video: %s", exc)
            raise ValueError('Video encoding timed out') from exc

        if result.returncode != 0 or not out_path.exists():
            stderr = (result.stderr or b'').decode('utf-8', 'replace')[-2000:]
            logger.error("ffmpeg failed encoding alert video (rc=%s): %s",
                        result.returncode, stderr)
            raise ValueError('Video encoding failed')

        return out_path.read_bytes()


__all__ = [
    'generate_alert_video', 'VIDEO_FPS', 'VIDEO_LAST_FRAME_HOLD_COUNT',
    'VIDEO_MAX_SCALE',
]
