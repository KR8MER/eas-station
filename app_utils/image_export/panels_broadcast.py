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

"""Narrow-column (broadcast-style) info-panel drawers.

Used by render.py instead of panels.py's wide-column stack (_draw_threats,
_draw_nws_headline, _draw_areas, _draw_coverage, _draw_compass_section)
when the info panel is narrower than layout.INFO_NARROW_MAX_W -- see
layout.py's landscape preset, which is map-dominant (~75% width) with a
narrow callout column alongside it, modeled on broadcast-style weather
graphics (RyanHallYall/WeatherWise-style warning cards).

All of these read the same already-parsed ipaws_data/alert fields the
wide-column drawers use (threat_data, storm_motion, expires) -- nothing
here parses any new CAP data, it's a different visual presentation of
data display_data.py already extracts.

Split out of panels.py (rather than added there) once it crossed ~400
lines -- same reasoning as panels_text.py, and re-exported through
panels.py the same way for compatibility.
"""

from typing import Any, Dict, Optional

from PIL import ImageDraw

from .palette import (
    WHITE, _SEVERITY, _TEXT, _TEXT_MUT, _TEXT_SEC, _THREAT_CLR, _darken,
)
from .fonts import _th, _tw
from .drawing import _draw_stat_box
from .icons import _ICON_FN
from .text import _format_countdown, _short_local_dt
from .panels_text import _wrap_text

_DAMAGE_CALLOUT_TEXT = {
    'destructive':  'DESTRUCTIVE DAMAGE EXPECTED',
    'considerable': 'CONSIDERABLE DAMAGE THREAT',
}


def _damage_callout_tier(threat_data: Dict) -> Optional[str]:
    """Return 'destructive', 'considerable', or None: the worst damage tag
    across wind/hail. Reads the *raw* NWS `threat` string rather than the
    coarser `level` bucket -- _threat_level() (display_data.py) collapses
    POSSIBLE/CONSIDERABLE/DESTRUCTIVE into a single 'possible' level, so
    `level` alone can't tell these two tiers apart from a routine tag.
    """
    tiers_seen = set()
    for key in ('wind', 'hail'):
        raw = ((threat_data.get(key) or {}).get('threat') or '').upper()
        if 'DESTRUCTIVE' in raw:
            tiers_seen.add('destructive')
        elif 'CONSIDERABLE' in raw:
            tiers_seen.add('considerable')
    if 'destructive' in tiers_seen:
        return 'destructive'
    if 'considerable' in tiers_seen:
        return 'considerable'
    return None


def _draw_damage_callout(draw: ImageDraw.ImageDraw, fonts: Dict,
                         ix: int, iy: int, iw: int, bot: int,
                         ipaws_data: Optional[Dict]) -> int:
    """Bold bordered callout for a Considerable/Destructive damage tag --
    the highest tier of NWS's Impact Based Warning system for severe
    thunderstorms, and the first thing a broadcast-style graphic leads
    with. A plain Possible/Radar/Observed tag (no elevated damage threat)
    stays on the stat boxes below instead -- this callout is reserved for
    the two tiers that mean "worse than a routine warning."
    """
    threat_data = (ipaws_data or {}).get('threat_data', {})
    tier = _damage_callout_tier(threat_data)
    if tier is None:
        return iy

    text = _DAMAGE_CALLOUT_TEXT[tier]
    color = _SEVERITY['extreme'] if tier == 'destructive' else _SEVERITY['moderate']
    font = fonts['bold']
    lines = _wrap_text(font, text, iw - 24, max_lines=3)
    line_h = _th(font, 'Mg') + 4
    pad = 10
    box_h = len(lines) * line_h + pad * 2
    if iy + box_h > bot:
        return iy

    draw.rounded_rectangle((ix, iy, ix + iw, iy + box_h), radius=8,
                           outline=color, width=2, fill=_darken(color, 0.82))
    ty = iy + pad
    for line in lines:
        lw = _tw(font, line)
        draw.text((ix + (iw - lw) // 2, ty), line, font=font, fill=WHITE)
        ty += line_h

    return iy + box_h + 8


def _draw_expires_block(draw: ImageDraw.ImageDraw, fonts: Dict,
                        ix: int, iy: int, iw: int, bot: int,
                        alert: Any) -> int:
    """Hero-styled absolute EXPIRES time for the narrow column. The
    footer already carries a small relative countdown pill (see
    render.py's footer section) -- this is the same underlying data
    (_format_countdown) at broadcast-graphic prominence instead.
    """
    expires = getattr(alert, 'expires', None)
    if not expires:
        return iy

    countdown = _format_countdown(expires)
    urgency = countdown[1] if countdown else 'normal'
    color = {
        'critical': _SEVERITY['extreme'],
        'soon':     _SEVERITY['severe'],
        'normal':   _TEXT,
        'expired':  _TEXT_MUT,
    }[urgency]

    label = 'EXPIRES'
    time_str = _short_local_dt(expires, ref=getattr(alert, 'sent', None))
    if not time_str:
        return iy

    lfont = fonts['label']
    vfont = fonts['title']
    box_h = _th(lfont, label) + 4 + _th(vfont, time_str) + 10
    if iy + box_h > bot:
        return iy

    draw.text((ix, iy), label, font=lfont, fill=_TEXT_MUT)
    ty = iy + _th(lfont, label) + 4
    draw.text((ix, ty), time_str, font=vfont, fill=color)

    return ty + _th(vfont, time_str) + 10


def _draw_hazard_stat_boxes(draw: ImageDraw.ImageDraw, fonts: Dict,
                            ix: int, iy: int, iw: int, bot: int,
                            ipaws_data: Optional[Dict]) -> int:
    """Vertically stacked wind/hail stat tiles -- the narrow-column
    counterpart to panels.py's _draw_threats side-by-side gauge cards,
    which need more width per card than a narrow column has. Tornado
    detection has no continuous magnitude to put in a stat box; it gets a
    pill instead (drawn directly in render.py).
    """
    threat_data = (ipaws_data or {}).get('threat_data', {})
    active = [(k, threat_data[k]) for k in ('wind', 'hail') if threat_data.get(k)]
    if not active:
        return iy

    box_h = 88
    gap = 6
    for key, t in active:
        if iy + box_h > bot:
            break

        if key == 'wind':
            value = t.get('gust', '')
            unit = t.get('gust_unit', 'MPH')
            label = 'WIND GUST'
        else:
            size = t.get('size', '')
            value = f'{size}"' if size else ''
            unit = t.get('descriptor', '')
            label = 'HAIL SIZE'
        if not value:
            continue

        level = t.get('level', 'none')
        color = _THREAT_CLR.get(level, _THREAT_CLR['none'])
        _draw_stat_box(draw, fonts, ix, iy, iw, box_h,
                      icon_fn=_ICON_FN[key], value=value, unit=unit,
                      label=label, color=color)
        iy += box_h + gap

    return iy


def _draw_storm_motion_line(draw: ImageDraw.ImageDraw, fonts: Dict,
                            ix: int, iy: int, iw: int, bot: int,
                            ipaws_data: Optional[Dict]) -> int:
    """Compact one-line storm-motion readout for the narrow column -- same
    ipaws_data['storm_motion'] fields panels.py's _draw_compass_section
    full compass rose uses, without the width a rose needs.
    """
    storm = (ipaws_data or {}).get('storm_motion', {})
    compass_toward = storm.get('compass_toward', '')
    speed_mph = storm.get('speed_mph', '')
    if not compass_toward or not speed_mph:
        return iy

    text = f'MOVING {compass_toward} AT {speed_mph} MPH'
    font = fonts['label']
    text_h = _th(font, text)
    if iy + text_h + 8 > bot:
        return iy

    draw.text((ix, iy), text, font=font, fill=_TEXT_SEC)
    return iy + text_h + 8
