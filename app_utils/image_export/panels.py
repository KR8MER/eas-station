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

"""Info-panel section drawers.

One function per section of the right-hand (or lower) information panel:
threats, coverage, affected areas and the storm-motion compass.

The prose sections — headline, description and action — live in the
sibling :mod:`panels_text` module (they reason about NWS text conventions,
so they sit next to the parser in :mod:`nws_text`) and are re-exported
here so existing ``from .panels import _draw_description`` imports keep
resolving.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw

from .palette import (
    _CARD, _TEXT, _TEXT_MUT, _TEXT_SEC, _THREAT_CLR, _pct_bar_color,
)
from .fonts import (
    _th, _truncate, _tw,
)
from .drawing import (
    _card_row, _section_header,
)
from .icons import _ICON_FN
from .nws_text import compact_area_desc
from .panels_text import (  # noqa: F401  (re-exported for compatibility)
    _INSTR_ACCENT, _draw_description, _draw_instruction, _draw_labeled_segments,
    _draw_nws_headline, _wrap_text,
)


# ─── Info-panel section drawers ───────────────────────────────────────────────
def _draw_threats(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                  ix: int, iy: int, iw: int, bot: int,
                  ipaws_data: Optional[Dict]) -> int:
    """Draw graphical threat cards — one card per active hazard."""
    threat_data = (ipaws_data or {}).get('threat_data', {})
    if not threat_data:
        return iy

    # Collect present threats in display order
    active = [(k, threat_data[k]) for k in ('tornado', 'wind', 'hail')
              if threat_data.get(k)]
    if not active:
        return iy

    n       = len(active)
    gap     = 5
    card_w  = (iw - gap * (n - 1)) // n
    card_h  = 108
    # Reserve space for the section header (22px) + card height before
    # committing to drawing anything, so we never leave an orphan header.
    if iy + 22 + card_h > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'STORM THREATS')

    for i, (key, t) in enumerate(active):
        cx   = ix + i * (card_w + gap)
        cy   = iy
        ce_x = cx + card_w // 2   # card horizontal centre

        level   = t.get('level', 'none')
        lvl_clr = _THREAT_CLR.get(level, _THREAT_CLR['none'])

        # Card background: slight colour tint based on threat level
        bg = tuple(int(lvl_clr[j] * 0.18 + _CARD[j] * 0.82) for j in range(3))

        draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h),
                               radius=7, fill=bg,
                               outline=lvl_clr, width=1)

        # ── Icon (top section) ──────────────────────────────────────────────
        icon_fn = _ICON_FN.get(key)
        if icon_fn:
            icon_fn(draw, ce_x, cy + 28, lvl_clr)

        # ── Primary value (large number or short label) ─────────────────────
        if key == 'wind':
            val = t.get('gust', '')
            unit = t.get('gust_unit', 'MPH')
        elif key == 'hail':
            size = t.get('size', '')
            val  = f'{size}"' if size else ''
            unit = t.get('descriptor', '')
        else:  # tornado
            val  = t.get('display', '')
            unit = ''

        vfont = fonts['head']   # 18 pt bold
        vw    = _tw(vfont, val)
        draw.text((ce_x - vw // 2, cy + 52), val, font=vfont, fill=_TEXT)

        # ── Unit / descriptor ───────────────────────────────────────────────
        if unit:
            uw = _tw(fonts['tiny'], unit)
            draw.text((ce_x - uw // 2, cy + 73), unit,
                      font=fonts['tiny'], fill=_TEXT_SEC)

        # ── Threat level (coloured) ─────────────────────────────────────────
        disp = t.get('display', '') if key != 'tornado' else ''
        if disp and key in ('wind', 'hail'):
            dw = _tw(fonts['tiny'], disp)
            draw.text((ce_x - dw // 2, cy + 84), disp,
                      font=fonts['tiny'], fill=lvl_clr)

        # ── Category label at bottom ────────────────────────────────────────
        cat = key.upper()
        cw  = _tw(fonts['label'], cat)
        draw.text((ce_x - cw // 2, cy + 95), cat,
                  font=fonts['label'], fill=_TEXT_MUT)

    return iy + card_h + 6


def _draw_coverage(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                   ix: int, iy: int, iw: int, bot: int,
                   coverage_data: Dict, county_name: str) -> int:
    if not coverage_data:
        return iy

    # ── Decide what's worth showing ─────────────────────────────────────────
    # When the configured county is outside the affected polygon, county
    # coverage will be 0.0%.  Rendering a "0.0% (est.) of <County>" row with
    # an empty bar reads as a calculation bug; suppress the row in that
    # case.  Drop the whole section if neither the county nor any service
    # type has measurable overlap — there is nothing left to display.
    county = coverage_data.get('county', {}) or {}
    county_pct = float(county.get('coverage_percentage', 0) or 0)
    show_county_row = bool(county) and county_pct >= 0.05

    svc_parts: List[str] = []
    for stype, sdata in sorted(coverage_data.items()):
        if stype == 'county':
            continue
        affected = int(sdata.get('affected_boundaries', 0) or 0)
        total    = int(sdata.get('total_boundaries',    0) or 0)
        if total > 0 and affected > 0:
            svc_parts.append(f'{stype.title()}: {affected}/{total}')

    if not show_county_row and not svc_parts:
        return iy

    # Reserve section-header (22) + at least one row of content before
    # drawing anything — otherwise we'd leave an orphan "COVERAGE" title.
    if iy + 22 + 22 > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'COVERAGE')

    if show_county_row:
        est   = county.get('is_estimated', False)
        row_h = 32
        if iy + row_h <= bot:
            _card_row(draw, ix, iy, iw, row_h)

            # Percentage label
            tag  = ' (est.)' if est else ''
            lbl  = f'{county_pct:.1f}%{tag} of {county_name}'
            lbl  = _truncate(fonts['small'], lbl, iw - 16)
            draw.text((ix + 8, iy + 4), lbl, font=fonts['small'], fill=_TEXT)

            # Progress bar — empty track plus a fill clamped to a true
            # 0–100% width (no minimum-width fudge that would misrepresent
            # near-zero coverage as a visible sliver).
            bar_x, bar_y = ix + 8, iy + 21
            bar_w, bar_h = iw - 16, 6
            draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                   radius=3, fill=(55, 65, 88))
            fill_w = int(bar_w * min(county_pct, 100) / 100)
            if fill_w > 0:
                draw.rounded_rectangle(
                    (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
                    radius=3, fill=_pct_bar_color(county_pct),
                )
            iy += row_h + 3

    if svc_parts and iy + 22 <= bot:
        _card_row(draw, ix, iy, iw, 22)
        svc_text = _truncate(fonts['tiny'], '  ·  '.join(svc_parts), iw - 14)
        draw.text((ix + 7, iy + (22 - _th(fonts['tiny'], svc_text)) // 2),
                  svc_text, font=fonts['tiny'], fill=_TEXT_SEC)
        iy += 24

    return iy + 6


def _draw_areas(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                ix: int, iy: int, iw: int, bot: int, alert: Any) -> int:
    area_desc = (getattr(alert, 'area_desc', '') or '').strip()
    if not area_desc or iy + 30 > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'AFFECTED AREAS')

    # Factor the repeated state code out of the CAP list first — NWS sends
    # "Allen, OH; Defiance, OH; Henry, OH; …", which spends a whole extra
    # wrapped row restating the state.
    area_desc = compact_area_desc(area_desc)

    # Split on semicolons, clean up, pack segments onto as few rows as
    # possible.
    segments = [s.strip() for s in area_desc.split(';') if s.strip()]
    font = fonts['small']
    row_h = 21
    pad_v = 3
    max_w = iw - 16

    lines: List[str] = []
    current_line = ''
    for seg in segments:
        candidate = f'{current_line}; {seg}' if current_line else seg
        if _tw(font, candidate) <= max_w:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = seg
    if current_line:
        lines.append(_truncate(font, current_line, max_w))

    # Single continuous card block — see _draw_nws_headline for why the
    # per-row stripes were dropped.
    n_fit = min(len(lines), max(0, (bot - iy - pad_v * 2) // row_h))
    if n_fit <= 0:
        return iy
    block_h = n_fit * row_h + pad_v * 2
    draw.rectangle((ix, iy, ix + iw, iy + block_h), fill=_CARD)
    ty = iy + pad_v
    for ltext in lines[:n_fit]:
        draw.text((ix + 8, ty + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        ty += row_h

    return iy + block_h + 6


def _draw_compass_section(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                          ix: int, iy: int, iw: int, bot: int,
                          ipaws_data: Optional[Dict]) -> int:
    """Draw a circular compass rose with the storm motion arrow + speed/direction text."""
    storm = (ipaws_data or {}).get('storm_motion', {})
    if not storm:
        return iy

    toward_deg    = storm.get('toward_deg')
    direction_deg = storm.get('direction_deg')
    compass_toward = storm.get('compass_toward', '')
    compass_from   = storm.get('compass_from', storm.get('compass', ''))
    speed_mph      = storm.get('speed_mph', '')
    speed_kt       = storm.get('speed_kt', '')

    if toward_deg is None and not compass_toward and not speed_mph:
        return iy

    section_h = 88
    if iy + 22 + section_h + 6 > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'STORM MOTION')
    draw.rectangle((ix, iy, ix + iw, iy + section_h), fill=_CARD)

    # ── Compass rose ──────────────────────────────────────────────────────────
    r   = 30                   # ring radius
    ccx = ix + r + 16          # compass centre-x
    ccy = iy + section_h // 2  # compass centre-y

    ring_clr = _TEXT_MUT
    draw.ellipse((ccx - r, ccy - r, ccx + r, ccy + r), outline=ring_clr, width=2)

    # Cardinal ticks + labels
    for deg, lbl in [(0, 'N'), (90, 'E'), (180, 'S'), (270, 'W')]:
        ang = math.radians(deg)
        sx  =  math.sin(ang)
        sy  = -math.cos(ang)   # screen y grows downward
        # Tick mark
        draw.line([
            (ccx + int(sx * (r - 6)), ccy + int(sy * (r - 6))),
            (ccx + int(sx * r),       ccy + int(sy * r)),
        ], fill=ring_clr, width=2)
        # Label just outside the ring
        lx = ccx + int(sx * (r + 9))
        ly = ccy + int(sy * (r + 9))
        draw.text((lx - _tw(fonts['tiny'], lbl) // 2,
                   ly - _th(fonts['tiny'], lbl) // 2),
                  lbl, font=fonts['tiny'], fill=ring_clr)

    # Intermediate ticks (45°)
    for deg in [45, 135, 225, 315]:
        ang = math.radians(deg)
        sx, sy = math.sin(ang), -math.cos(ang)
        draw.line([
            (ccx + int(sx * (r - 4)), ccy + int(sy * (r - 4))),
            (ccx + int(sx * r),       ccy + int(sy * r)),
        ], fill=ring_clr, width=1)

    # Directional arrow
    if toward_deg is not None:
        ang = math.radians(toward_deg)
        dx  =  math.sin(ang)
        dy  = -math.cos(ang)

        tip_x = ccx + int(dx * (r - 7))
        tip_y = ccy + int(dy * (r - 7))
        tail_x = ccx - int(dx * int(r * 0.38))
        tail_y = ccy - int(dy * int(r * 0.38))

        draw.line([(tail_x, tail_y), (tip_x, tip_y)], fill=alr_clr, width=3)

        w_ang = 0.45
        hw    = 7
        lw_x = tip_x - int((dx * math.cos( w_ang) - dy * math.sin( w_ang)) * hw)
        lw_y = tip_y - int((dy * math.cos( w_ang) + dx * math.sin( w_ang)) * hw)
        rw_x = tip_x - int((dx * math.cos(-w_ang) - dy * math.sin(-w_ang)) * hw)
        rw_y = tip_y - int((dy * math.cos(-w_ang) + dx * math.sin(-w_ang)) * hw)
        draw.polygon([(tip_x, tip_y), (lw_x, lw_y), (rw_x, rw_y)], fill=alr_clr)

    # Centre dot
    draw.ellipse((ccx - 3, ccy - 3, ccx + 3, ccy + 3), fill=ring_clr)

    # ── Text block to the right of the compass ────────────────────────────────
    tx   = ccx + r + 18
    tw_  = iw - (tx - ix) - 8
    ty   = iy + 10
    lh   = 17

    if compass_toward:
        hstr = f'Heading {compass_toward}'
        if toward_deg is not None:
            hstr += f' ({int(toward_deg)}\u00b0)'
        draw.text((tx, ty), hstr, font=fonts['bold'], fill=_TEXT)
        ty += lh + 2

    if compass_from:
        fstr = f'From {compass_from}'
        if direction_deg is not None:
            fstr += f' ({int(direction_deg)}\u00b0)'
        draw.text((tx, ty), fstr, font=fonts['small'], fill=_TEXT_SEC)
        ty += lh

    if speed_mph:
        sstr = f'{speed_mph} MPH'
        if speed_kt:
            sstr += f'  ({speed_kt} kt)'
        draw.text((tx, ty), sstr, font=fonts['bold'], fill=_TEXT)
        ty += lh + 2

    # Storm position (newest track point)
    track = storm.get('track', [])
    if track:
        try:
            lat, lon = float(track[-1][0]), float(track[-1][1])
            pstr = f'Position: {lat:.2f}, {lon:.2f}'
            draw.text((tx, ty), _truncate(fonts['tiny'], pstr, tw_),
                      font=fonts['tiny'], fill=_TEXT_MUT)
        except (TypeError, IndexError, ValueError):
            pass

    return iy + section_h + 6
