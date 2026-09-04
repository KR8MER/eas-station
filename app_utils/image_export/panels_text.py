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

"""Prose sections of the info panel: headline, description and action.

Split out of ``panels.py`` (which had grown past the module-size guidance)
so the copy-heavy drawers — the ones that have to reason about NWS text
conventions — sit next to the parser in ``nws_text.py``.  ``panels`` still
re-exports every name, so existing imports are unaffected.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw, ImageFont

from .palette import _CARD, _TEXT, _darken, _lighten
from .fonts import _th, _truncate, _tw
from .text import _humanize_caps_text
from .drawing import _section_header
from .nws_text import NWSSegment, select_share_segments, strip_urls


_EMPHASIS_RE = re.compile(
    # Two alternatives because \b can't follow a non-word literal like '"':
    # a plain unit word gets the word-boundary check, a bare inch-mark
    # doesn't need one -- the quote itself is already an unambiguous stop.
    r'\d+(?:\.\d+)?\s*(?:mph|kt|knots?|in\.?|inch(?:es)?|ft|feet|mm|cm)\b'
    r'|\d+(?:\.\d+)?"',
    re.IGNORECASE,
)


def _draw_emphasized_line(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
                          font: ImageFont.FreeTypeFont,
                          bold_font: ImageFont.FreeTypeFont,
                          color) -> None:
    """Draw *text* left-to-right, bolding numeric hazard magnitudes
    ("60 mph", '1.00"', "2 inch") so the specific, actionable numbers in a
    HAZARD/IMPACTS line are scannable without reading the full sentence.
    Falls back to a single plain draw when nothing matches.

    Wrapping (_wrap_text) measures every line at the regular weight only --
    a bold run is a few px wider than the same text at the same size, but
    matched spans are short relative to the line, so the resulting overflow
    is negligible and not worth a run-aware wrap pass for this cosmetic a
    feature.
    """
    pos = 0
    cx = x
    for m in _EMPHASIS_RE.finditer(text):
        if m.start() > pos:
            plain = text[pos:m.start()]
            draw.text((cx, y), plain, font=font, fill=color)
            cx += _tw(font, plain)
        bold = m.group(0)
        draw.text((cx, y), bold, font=bold_font, fill=color)
        cx += _tw(bold_font, bold)
        pos = m.end()
    if pos < len(text):
        draw.text((cx, y), text[pos:], font=font, fill=color)


def _wrap_text(font: ImageFont.FreeTypeFont, text: str,
               max_w: int, max_lines: int = 8) -> List[str]:
    """Word-wrap *text* into lines that fit within *max_w* pixels."""
    words = text.split()
    lines: List[str] = []
    line = ''
    for word in words:
        candidate = (line + ' ' + word).strip()
        if _tw(font, candidate) <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
                if len(lines) >= max_lines:
                    # Truncate the last line with ellipsis
                    lines[-1] = _truncate(font, lines[-1], max_w)
                    return lines
            line = word
    if line:
        if len(lines) >= max_lines:
            lines[-1] = _truncate(font, lines[-1] + ' ' + line, max_w)
        else:
            lines.append(line)
    return lines


def _draw_nws_headline(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                       ix: int, iy: int, iw: int, bot: int,
                       alert: Any, ipaws_data: Optional[Dict]) -> int:
    """Render the NWS operational headline (ALL-CAPS quote block).

    Falls back to alert.headline when nws_headline is absent.
    The alert.description is intentionally omitted — it's too long to
    truncate meaningfully in a social-media image.
    """
    nws_head = (ipaws_data or {}).get('nws_headline', '').strip()
    pub_head = (getattr(alert, 'headline', '') or '').strip()
    text     = nws_head or pub_head

    if not text or iy + 30 > bot:
        return iy

    # NWS-style headlines are often shouted; humanise before rendering.
    text = _humanize_caps_text(text)

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'HEADLINE')

    # Word-wrap (leave room for the quote bar + insets on the left)
    font  = fonts['small']
    max_w = iw - 20
    words = text.split()
    lines: List[str] = []
    line  = ''
    for word in words:
        candidate = (line + ' ' + word).strip()
        if _tw(font, candidate) <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)

    # One continuous card block instead of per-row stripes — the old
    # 1-px gaps between rows turned into shimmering scan-lines after
    # social platforms re-encoded the upload as JPEG.
    row_h = 20
    pad_v = 4
    n_fit = min(len(lines), max(0, (bot - iy - pad_v * 2) // row_h))
    if n_fit <= 0:
        return iy
    if n_fit < len(lines):
        lines[n_fit - 1] = _truncate(
            font, lines[n_fit - 1] + ' ' + lines[n_fit], max_w)

    block_h = n_fit * row_h + pad_v * 2
    draw.rectangle((ix, iy, ix + iw, iy + block_h), fill=_CARD)
    # Coloured quote bar on the left edge
    draw.rectangle((ix, iy, ix + 3, iy + block_h), fill=alr_clr)
    ty = iy + pad_v
    for ltext in lines[:n_fit]:
        draw.text((ix + 12, ty + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        ty += row_h

    return iy + block_h + 6


# Widest the label gutter is allowed to get before labels are truncated
# into it.  Past this the body column gets too narrow to wrap decently on
# the 594 px landscape info panel.
_LABEL_COL_MAX = 84


def _draw_labeled_segments(draw: ImageDraw.ImageDraw, fonts: Dict,
                           alr_clr: Tuple, ix: int, iy: int, iw: int,
                           bot: int, segments: List[NWSSegment]) -> int:
    """Render tagged NWS bullets as a label gutter plus wrapped prose.

    Each segment gets its label (WHAT / IMPACTS / DETAILS …) in the gutter
    on the left and its body hanging beside it, so the outline NWS wrote
    survives onto the card instead of dissolving into one paragraph.  A
    segment with an empty label — the untagged lede that opens severe
    warnings — spans the full width instead, reading as the opening
    paragraph it is.  Segments are laid out until the panel runs out of
    room; a segment that cannot fit one line of body is dropped rather
    than left as an orphan label.

    Returns the y coordinate after the block, or *iy* unchanged when
    nothing could be drawn.
    """
    label_font = fonts['label']
    body_font  = fonts['small']
    row_h = 19
    pad_v = 5
    gap   = 6      # vertical gap between segments

    labelled = [s.label for s in segments if s.label]
    label_col = min(
        _LABEL_COL_MAX,
        max((_tw(label_font, lbl) for lbl in labelled), default=0) + 10,
    ) if labelled else 0
    body_x     = ix + 8 + label_col
    body_max_w = iw - 16 - label_col
    full_max_w = iw - 16

    # Lay the whole block out before painting so the card background can be
    # drawn at its true height in one rectangle (per-row fills leave 1-px
    # seams that social platforms' JPEG re-encode turns into scan-lines).
    placed: List[Tuple[str, List[str]]] = []
    used_h = pad_v * 2
    for seg in segments:
        remaining = bot - iy - used_h - (gap if placed else 0)
        max_lines = remaining // row_h
        if max_lines < 1:
            break
        lines = _wrap_text(body_font, seg.body,
                           full_max_w if not seg.label else body_max_w,
                           max_lines=max_lines)
        if not lines:
            continue
        used_h += len(lines) * row_h + (gap if placed else 0)
        placed.append((seg.label, lines))

    if not placed:
        return iy

    draw.rectangle((ix, iy, ix + iw, iy + used_h), fill=_CARD)

    # Labels take a lightened accent so they read as structure without
    # competing with the body copy, and stay legible whatever hue the
    # hazard family's theme accent happens to be.
    label_clr = _lighten(alr_clr, 0.45)

    ty = iy + pad_v
    for i, (label, lines) in enumerate(placed):
        if i:
            ty += gap
        if label:
            draw.text((ix + 8, ty + (row_h - _th(label_font, label)) // 2),
                      _truncate(label_font, label, label_col - 6),
                      font=label_font, fill=label_clr)
        text_x = body_x if label else ix + 8
        bold_font = fonts.get('small_bold', body_font)
        for ltext in lines:
            _draw_emphasized_line(
                draw, text_x, ty + (row_h - _th(body_font, ltext)) // 2,
                ltext, body_font, bold_font, _TEXT,
            )
            ty += row_h

    return iy + used_h + 6


def _draw_description(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                      ix: int, iy: int, iw: int, bot: int,
                      alert: Any, *, areas_shown: bool = False,
                      timing_shown: bool = False) -> int:
    """Render the alert description, keeping its NWS outline where present.

    Modern NWS products are written as tagged bullets (WHAT / WHERE / WHEN
    / IMPACTS / ADDITIONAL DETAILS).  When those tags are found the section
    renders as labelled rows; anything else falls back to a plain wrapped
    paragraph.

    *areas_shown* and *timing_shown* tell the drawer which bullets the card
    is already covering elsewhere — the AFFECTED AREAS section and the
    footer's issued/expires stamp respectively — so WHERE and WHEN can be
    dropped instead of repeating information a reader just saw.
    """
    desc = (getattr(alert, 'description', '') or '').strip()
    if not desc or iy + 30 > bot:
        return iy

    segments = select_share_segments(desc, drop_where=areas_shown,
                                     drop_when=timing_shown)

    font = fonts['small']
    row_h = 20
    pad_v = 4
    # Reserve the 22px section header + at least one row before committing.
    if iy + 22 + row_h + pad_v * 2 > bot:
        return iy

    if segments:
        # De-shout each body independently: a legacy product may shout the
        # prose while its tags stay structural.
        segments = [
            NWSSegment(s.label, _humanize_caps_text(s.body)) for s in segments
        ]
        iy_after_header = _section_header(draw, fonts, alr_clr, ix, iy, iw,
                                          'DESCRIPTION')
        iy_end = _draw_labeled_segments(draw, fonts, alr_clr, ix,
                                        iy_after_header, iw, bot, segments)
        if iy_end > iy_after_header:
            return iy_end
        # Nothing fit under the header — fall through to the paragraph
        # path, which re-draws its own header over the same pixels.

    # Clean up NWS description formatting: collapse multiple whitespace,
    # strip leading asterisks/bullets, normalise newlines to spaces, and
    # drop bare URLs (unclickable on an image, and they wrap badly).
    desc = strip_urls(desc)
    desc = re.sub(r'\s*\n\s*', ' ', desc)
    desc = re.sub(r'\s{2,}', ' ', desc)
    desc = re.sub(r'^\*\s*', '', desc)
    desc = desc.strip()

    if not desc:
        return iy

    # De-shout NWS text — bodies of all-caps are noticeably slower to read.
    desc = _humanize_caps_text(desc)

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'DESCRIPTION')

    max_w = iw - 16
    # Fill all remaining vertical space rather than capping at an arbitrary
    # line count — long descriptions previously ended mid-sentence because
    # the cap was 6 lines regardless of how much room was left.
    avail_lines = max(1, (bot - iy - pad_v * 2) // row_h)
    lines = _wrap_text(font, desc, max_w, max_lines=avail_lines)

    # Single continuous card block — see _draw_nws_headline for why the
    # old per-row stripes (1-px gaps) were dropped.
    block_h = len(lines) * row_h + pad_v * 2
    draw.rectangle((ix, iy, ix + iw, iy + block_h), fill=_CARD)
    ty = iy + pad_v
    for ltext in lines:
        draw.text((ix + 8, ty + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        ty += row_h

    return iy + block_h + 6


_INSTR_ACCENT = (255, 193, 7)  # warning-yellow accent bar


def _draw_instruction(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                      ix: int, iy: int, iw: int, bot: int,
                      alert: Any) -> int:
    """Render safety guidance with a stronger visual treatment.

    The CAP ``instruction`` field is the one thing on a share card a
    reader can act on — "move to an interior room", "shelter in
    place", "evacuate if instructed" — so it gets a warning-yellow
    section header (visually distinct from the neutral event-coloured
    headers used for HEADLINE / DESCRIPTION) plus a thicker accent bar
    on each row.  The header reads "WHAT TO DO" -- shorter and more
    imperative than "INSTRUCTIONS", and matches the broadcast-style
    graphics this section's narrow-column treatment is modeled on.
    """
    instr = (getattr(alert, 'instruction', '') or '').strip()
    if not instr or iy + 30 > bot:
        return iy

    instr = strip_urls(instr)
    instr = re.sub(r'\s*\n\s*', ' ', instr)
    instr = re.sub(r'\s{2,}', ' ', instr)
    instr = instr.strip()

    if not instr:
        return iy

    instr = _humanize_caps_text(instr)

    font = fonts['small']
    row_h = 20
    pad_v = 4
    if iy + 22 + row_h + pad_v * 2 > bot:
        return iy

    # Warning-coloured section header so the action band reads as
    # distinct from the neutral headline / description sections.  Using
    # a deeply-darkened amber preserves WCAG-style contrast against the
    # white label text.
    iy = _section_header(
        draw, fonts, alr_clr, ix, iy, iw, 'WHAT TO DO',
        bg=_darken(_INSTR_ACCENT, 0.55),
        stripe=_INSTR_ACCENT,
    )

    accent_w = 4  # was 3 — thicker bar reads better at thumbnail size
    max_w = iw - 16 - accent_w
    # Fill remaining vertical space instead of capping at 4 lines.
    avail_lines = max(1, (bot - iy - pad_v * 2) // row_h)
    lines = _wrap_text(font, instr, max_w, max_lines=avail_lines)

    # Single continuous card block with a full-height amber bar — see
    # _draw_nws_headline for why the per-row stripes were dropped.
    block_h = len(lines) * row_h + pad_v * 2
    draw.rectangle((ix, iy, ix + iw, iy + block_h), fill=_CARD)
    draw.rectangle((ix, iy, ix + accent_w, iy + block_h), fill=_INSTR_ACCENT)
    ty = iy + pad_v
    for ltext in lines:
        draw.text((ix + accent_w + 8, ty + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        ty += row_h

    return iy + block_h + 6


__all__ = [
    '_INSTR_ACCENT', '_LABEL_COL_MAX', '_draw_description',
    '_draw_instruction', '_draw_labeled_segments', '_draw_nws_headline',
    '_wrap_text',
]
