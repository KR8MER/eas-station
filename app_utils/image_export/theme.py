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

"""Event theming: hazard-family themes, alert tier badges and urgency heat.

The theme drives the header gradient, accent colour and decorative particle
layer. Tier and urgency modulate that theme so a Heat Advisory does not glow
as hot as an Excessive Heat Warning.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


from .palette import (
    WHITE, _SEVERITY, _darken,
)


# ─── Event theming ───────────────────────────────────────────────────────────
# Each theme drives the header gradient, accent colour (section headers,
# polygon stroke, callouts) and the decorative particle layer painted
# behind the title. Particle styles: 'bolts' | 'snow' | 'rain' | 'sun' |
# 'embers' | 'wind' | 'haze' | 'none'.
#
# Themes are keyed off the CAP event name (lowercased substring match).
# This is intentionally data-driven so adding a new event type is one line.
_Theme = Dict[str, Any]

# Generic fallback themes derived from severity so unfamiliar events still
# get a reasonable look.  Tone-mapped from the original severity palette.
_THEME_DEFAULT: _Theme = {
    'top':       ( 25,  30,  55),
    'bottom':    ( 70,  95, 150),
    'accent':    ( 70, 130, 200),
    'particles': 'bolts',
    'particle_intensity': 0.7,
}

# Event → theme map.  Keys are lowercase substrings tested against the CAP
# event name.  Order matters — first match wins, so list specific events
# before generic ones (e.g. "winter storm" before "storm").
_THEMES: List[Tuple[str, _Theme]] = [
    # ── Convective / severe storms ──────────────────────────────────────
    ('tornado', {
        'top':       ( 70,   0,   0),
        'bottom':    (180,  25,  35),
        'accent':    (220,  53,  69),
        'particles': 'bolts',
        'particle_intensity': 1.1,
    }),
    ('severe thunderstorm', {
        'top':       ( 35,  20,  60),
        'bottom':    (220, 110,  30),
        'accent':    (253, 126,  20),
        'particles': 'bolts',
        'particle_intensity': 1.0,
    }),
    ('thunderstorm', {
        'top':       ( 30,  35,  70),
        'bottom':    ( 95, 110, 180),
        'accent':    (110, 140, 220),
        'particles': 'bolts',
        'particle_intensity': 0.95,
    }),
    # ── Wind / hurricane ────────────────────────────────────────────────
    # NOTE: 'wind chill' must be matched *before* the winter section,
    # otherwise 'cold' or 'wind' would steal it.  All wind-family keys
    # are ordered most-specific → least-specific.
    ('wind chill', {
        'top':       ( 20,  50,  85),
        'bottom':    ( 75, 125, 180),
        'accent':    (155, 200, 235),
        'particles': 'snow',
        'particle_intensity': 0.6,
    }),
    ('hurricane', {
        'top':       ( 60,   0,  60),
        'bottom':    (190,  60, 120),
        'accent':    (220,  90, 150),
        'particles': 'wind',
        'particle_intensity': 1.0,
    }),
    ('tropical', {
        'top':       ( 40,  20,  70),
        'bottom':    (160,  70, 140),
        'accent':    (200,  90, 160),
        'particles': 'wind',
        'particle_intensity': 0.9,
    }),
    ('high wind', {
        'top':       ( 30,  45,  75),
        'bottom':    (110, 135, 175),
        'accent':    (140, 170, 210),
        'particles': 'wind',
        'particle_intensity': 0.95,
    }),
    ('wind', {
        'top':       ( 35,  50,  80),
        'bottom':    (120, 150, 190),
        'accent':    (160, 190, 220),
        'particles': 'wind',
        'particle_intensity': 0.8,
    }),
    # ── Winter / cold ───────────────────────────────────────────────────
    ('blizzard', {
        'top':       ( 20,  35,  70),
        'bottom':    (100, 145, 200),
        'accent':    (170, 215, 245),
        'particles': 'snow',
        'particle_intensity': 1.2,
    }),
    ('winter', {
        'top':       ( 25,  45,  85),
        'bottom':    ( 95, 145, 200),
        'accent':    (170, 215, 245),
        'particles': 'snow',
        'particle_intensity': 1.0,
    }),
    ('ice', {
        'top':       ( 30,  55,  90),
        'bottom':    (110, 165, 210),
        'accent':    (180, 220, 245),
        'particles': 'snow',
        'particle_intensity': 0.9,
    }),
    ('snow', {
        'top':       ( 30,  55,  95),
        'bottom':    (105, 155, 205),
        'accent':    (175, 220, 245),
        'particles': 'snow',
        'particle_intensity': 1.0,
    }),
    ('freeze', {
        'top':       ( 20,  50,  90),
        'bottom':    ( 80, 130, 185),
        'accent':    (160, 210, 240),
        'particles': 'snow',
        'particle_intensity': 0.8,
    }),
    ('frost', {
        'top':       ( 25,  60,  95),
        'bottom':    ( 90, 140, 195),
        'accent':    (170, 215, 245),
        'particles': 'snow',
        'particle_intensity': 0.7,
    }),
    ('cold', {
        'top':       ( 20,  45,  80),
        'bottom':    ( 80, 130, 185),
        'accent':    (160, 210, 240),
        'particles': 'snow',
        'particle_intensity': 0.7,
    }),
    # ── Water ───────────────────────────────────────────────────────────
    ('flash flood', {
        'top':       (  5,  35,  60),
        'bottom':    ( 35, 110, 145),
        'accent':    ( 45, 165, 200),
        'particles': 'rain',
        'particle_intensity': 1.1,
    }),
    ('flood', {
        'top':       ( 10,  45,  70),
        'bottom':    ( 30, 115, 150),
        'accent':    ( 50, 170, 205),
        'particles': 'rain',
        'particle_intensity': 0.95,
    }),
    ('coastal', {
        'top':       ( 10,  50,  80),
        'bottom':    ( 35, 130, 165),
        'accent':    ( 60, 180, 215),
        'particles': 'rain',
        'particle_intensity': 0.7,
    }),
    ('marine', {
        'top':       ( 10,  50,  80),
        'bottom':    ( 35, 130, 165),
        'accent':    ( 60, 180, 215),
        'particles': 'rain',
        'particle_intensity': 0.6,
    }),
    ('rip current', {
        'top':       ( 15,  60,  90),
        'bottom':    ( 40, 145, 185),
        'accent':    ( 65, 195, 225),
        'particles': 'rain',
        'particle_intensity': 0.5,
    }),
    ('rain', {
        'top':       ( 15,  45,  70),
        'bottom':    ( 50, 120, 160),
        'accent':    ( 65, 180, 215),
        'particles': 'rain',
        'particle_intensity': 0.85,
    }),
    # ── Heat ────────────────────────────────────────────────────────────
    ('excessive heat', {
        'top':       (110,   0,   0),
        'bottom':    (245, 145,   0),
        'accent':    (255, 200,  60),
        'particles': 'sun',
        'particle_intensity': 1.1,
    }),
    ('heat', {
        'top':       (130,  20,   0),
        'bottom':    (240, 165,  20),
        'accent':    (255, 210,  80),
        'particles': 'sun',
        'particle_intensity': 1.0,
    }),
    # ── Fire ────────────────────────────────────────────────────────────
    ('red flag', {
        'top':       ( 40,   0,   0),
        'bottom':    (200,  50,  20),
        'accent':    (255, 130,  40),
        'particles': 'embers',
        'particle_intensity': 1.0,
    }),
    ('fire weather', {
        'top':       ( 30,   0,   0),
        'bottom':    (190,  40,  10),
        'accent':    (255, 120,  30),
        'particles': 'embers',
        'particle_intensity': 1.0,
    }),
    ('fire', {
        'top':       ( 30,   0,   0),
        'bottom':    (180,  35,   5),
        'accent':    (255, 115,  25),
        'particles': 'embers',
        'particle_intensity': 1.0,
    }),
    ('smoke', {
        'top':       ( 35,  30,  35),
        'bottom':    (130, 110, 100),
        'accent':    (210, 180, 140),
        'particles': 'embers',
        'particle_intensity': 0.6,
    }),
    # ── Visibility / atmosphere ─────────────────────────────────────────
    ('fog', {
        'top':       ( 55,  60,  70),
        'bottom':    (140, 150, 165),
        'accent':    (180, 200, 220),
        'particles': 'haze',
        'particle_intensity': 1.0,
    }),
    ('dense fog', {
        'top':       ( 50,  55,  65),
        'bottom':    (130, 140, 155),
        'accent':    (175, 195, 215),
        'particles': 'haze',
        'particle_intensity': 1.1,
    }),
    ('dust', {
        'top':       ( 70,  55,  35),
        'bottom':    (190, 155,  95),
        'accent':    (220, 185, 130),
        'particles': 'haze',
        'particle_intensity': 0.9,
    }),
    # ── Civil / non-weather ─────────────────────────────────────────────
    ('amber', {
        'top':       ( 90,  60,   0),
        'bottom':    (235, 175,  30),
        'accent':    (255, 205,  70),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('civil', {
        'top':       ( 50,   0,   5),
        'bottom':    (180,  40,  50),
        'accent':    (220,  70,  90),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('evacuation', {
        'top':       ( 70,   0,   0),
        'bottom':    (210,  60,  35),
        'accent':    (245, 120,  60),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('hazardous materials', {
        'top':       ( 50,  60,   0),
        'bottom':    (175, 195,  50),
        'accent':    (215, 230,  90),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('shelter', {
        'top':       ( 60,  40,   0),
        'bottom':    (200, 145,  40),
        'accent':    (240, 180,  70),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    # Catch-all storm before plain 'storm'
    ('storm', {
        'top':       ( 30,  35,  70),
        'bottom':    ( 95, 110, 180),
        'accent':    (110, 140, 220),
        'particles': 'bolts',
        'particle_intensity': 0.9,
    }),
]


def _resolve_theme(event_name: str, severity: str) -> _Theme:
    """Return the theme that best fits *event_name*; fall back to severity."""
    name = (event_name or '').lower()
    for key, theme in _THEMES:
        if key in name:
            return theme
    # Fall back: tint the default theme with the severity colour so we
    # still get event-appropriate gradients for unknown events.
    sev_clr = _SEVERITY.get((severity or '').lower(), _SEVERITY['unknown'])
    return {
        'top':       _darken(sev_clr, 0.65),
        'bottom':    sev_clr,
        'accent':    sev_clr,
        'particles': 'bolts',
        'particle_intensity': 0.6,
    }


def _theme_supports_storm_motion(theme: _Theme) -> bool:
    """Storm-motion overlay only makes sense for convective/wind events."""
    return theme.get('particles') in ('bolts', 'wind', 'rain')


# ─── Alert tier (emergency / warning / watch / advisory) colour coding ──────
# CAP event names carry the NWS action ladder in their last word —
# "… Warning" means take action now, "… Watch" means be prepared,
# "… Advisory" means be aware.  The event *theme* above colours the card
# by hazard family (heat, winter, flood, …), so two alerts that demand
# very different responses (Severe Thunderstorm WATCH vs WARNING) would
# otherwise look identical.  The tier badge restores that distinction
# with the conventional escalation palette: red → orange → amber.
_TIER_STYLES: List[Tuple[str, Dict[str, Any]]] = [
    # Order matters: "Tornado Emergency" must not fall through to a
    # generic match, and specific words are tested before generic ones.
    ('emergency', {'fill': (136,  14,  79), 'text': WHITE}),  # deep magenta
    ('warning',   {'fill': (220,  53,  69), 'text': WHITE}),  # act now
    ('watch',     {'fill': (253, 126,  20), 'text': WHITE}),  # be prepared
    ('advisory',  {'fill': (255, 193,   7), 'text': (45, 36, 3)}),  # be aware
    ('statement', {'fill': (108, 117, 125), 'text': WHITE}),  # informational
]


def _resolve_tier(event_name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return ``(tier_word, style)`` for *event_name*, or ``None``.

    Matches whole words only so e.g. "Special Weather Statement" maps to
    ``statement`` while events without a tier word (AMBER Alert, 911
    Telephone Outage) simply show no badge.
    """
    name = (event_name or '').lower()
    for key, style in _TIER_STYLES:
        if re.search(rf'\b{key}\b', name):
            return key, style
    return None


# ─── Urgency "heat" for the header gradient ─────────────────────────────────
# The hazard-family themes are tuned for their most dangerous product, so
# a Heat ADVISORY header glowed exactly as red-hot as an Excessive Heat
# WARNING and the two cards were indistinguishable at a glance.  Heat maps
# the tier / severity ladders onto a 0–1 factor; below 1.0 the gradient is
# progressively desaturated and dimmed (hue stays event-coded, intensity
# codes urgency) and the particle layer calms down with it.
_TIER_HEAT: Dict[str, float] = {
    'emergency': 1.0,
    'warning':   1.0,
    'watch':     0.7,
    'advisory':  0.5,
    'statement': 0.35,
}
_SEVERITY_HEAT: Dict[str, float] = {
    'extreme':  1.0,
    'severe':   0.9,
    'moderate': 0.65,
    'minor':    0.5,
    'unknown':  0.8,
}


def _urgency_heat(tier_word: Optional[str], severity: str) -> float:
    """Combined 0–1 heat — the calmer of the tier and severity ladders."""
    t = _TIER_HEAT.get(tier_word or '', 0.85)
    s = _SEVERITY_HEAT.get((severity or '').lower(), 0.8)
    return min(t, s)


def _soften(c: Tuple[int, int, int], heat: float) -> Tuple[int, int, int]:
    """Desaturate + dim *c* as *heat* drops below 1.0."""
    r, g, b = c
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    desat = (1.0 - heat) * 0.65   # heat 0 → 65% toward grey
    dim   = 1.0 - (1.0 - heat) * 0.30   # heat 0 → 30% darker
    return tuple(max(0, min(255, int((v + (luma - v) * desat) * dim)))
                 for v in (r, g, b))  # type: ignore[return-value]


def _apply_urgency_to_theme(theme: _Theme, heat: float) -> _Theme:
    """Return a copy of *theme* with the gradient cooled to *heat*."""
    if heat >= 0.999:
        return theme
    out = dict(theme)
    out['top']    = _soften(tuple(theme['top']), heat)
    out['bottom'] = _soften(tuple(theme['bottom']), heat)
    out['particle_intensity'] = (
        float(theme.get('particle_intensity', 1.0)) * (0.55 + 0.45 * heat)
    )
    return out
