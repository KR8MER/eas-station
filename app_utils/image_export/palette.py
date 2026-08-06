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

"""Colour palette, severity/threat colour maps and colour helpers."""

from typing import Dict, Tuple


# ─── Colour palette ─────────────────────────────────────────────────────────
_BG         = (22,  27,  38)
_PANEL      = (30,  36,  51)
_CARD       = (38,  45,  63)
_SECTION_BG = (52,  60,  80)   # slate header band for info-panel sections
_STRIP      = (14,  18,  30)
_DIVIDER    = (55,  65,  88)
_TEXT       = (230, 235, 245)
_TEXT_SEC   = (155, 165, 190)
_TEXT_MUT   = ( 95, 108, 132)
WHITE       = (255, 255, 255)

_SEVERITY: Dict[str, Tuple[int, int, int]] = {
    'extreme':  (220,  53,  69),
    'severe':   (253, 126,  20),
    'moderate': (255, 193,   7),
    'minor':    ( 13, 110, 253),
    'unknown':  (108, 117, 125),
}
_THREAT_CLR: Dict[str, Tuple[int, int, int]] = {
    'observed': (220,  53,  69),
    'radar':    (255, 193,   7),
    'possible': (253, 126,  20),
    'none':     ( 80,  95, 120),
}

# ─── Colour helpers ──────────────────────────────────────────────────────────
def _darken(c: Tuple[int, int, int], f: float) -> Tuple[int, int, int]:
    return tuple(max(0, int(v * (1.0 - f))) for v in c)  # type: ignore[return-value]


def _pct_bar_color(pct: float) -> Tuple[int, int, int]:
    if pct >= 95:  return (40, 167,  69)
    if pct >= 75:  return (255, 193,   7)
    if pct >= 50:  return ( 13, 110, 253)
    return (108, 117, 125)
