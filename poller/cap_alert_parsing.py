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

"""Stateless CAP-alert parsing/geometry helpers extracted from CAPPoller.

These touch no instance state (no ``self`` references) -- pure functions
that happened to be trapped inside the class. Split out first, as motion,
before any of CAPPoller's genuinely stateful methods (the 2d technique --
see docs/development/LARGE_FILE_REFACTOR_PLAN.md Phase 4c)."""

import re
from typing import Any, Dict, List, Optional, Tuple

from app_core.models import CAPAlert
from app_utils import utc_now
from app_utils.optimized_parsing import get_element_tree_module, json_dumps, json_loads
from app_utils.vtec import is_cancellation

# Use the same optimized XML parser cap_poller.py resolves for itself
# (lxml if available, else the stdlib xml.etree.ElementTree) -- only used
# here as a type hint (ET.Element), never called at runtime.
ET = get_element_tree_module()


def _select_cap_info(info_elements: List[ET.Element], ns: Dict[str, str]) -> Optional[ET.Element]:
    if not info_elements:
        return None

    preferred_langs = ['en-US', 'en-us', 'en']
    for preferred in preferred_langs:
        for info_elem in info_elements:
            language = info_elem.findtext('cap:language', default='', namespaces=ns)
            if language and language.lower().startswith(preferred.lower()):
                return info_elem

    return info_elements[0]

def _extract_cap_event_codes(info_elem: Optional[ET.Element], ns: Dict[str, str]) -> Dict[str, List[str]]:
    """Extract <eventCode> elements from a CAP <info> block.

    Same shape as <parameter> (a <valueName>/<value> pair), and this
    used to be the one CAP <info> child _convert_cap_alert() didn't
    extract at all -- properties['eventCode'] was simply never set for
    IPAWS-sourced alerts, even when the source alert carried one.
    Reproduced live: a county gas-leak "shelter in place" alert whose
    raw CAP XML had <eventCode><valueName>SAME</valueName><value>SPW
    </value></eventCode> was stored with no eventCode in `properties`
    at all, so the event code fell through as unresolved ("UNKNOWN")
    downstream and the alert was silently dropped by the forwarding
    allowlist -- even though the allowlist itself already included
    SPW. NWS's api.weather.gov CAP-JSON feed doesn't need this (it
    already includes eventCode natively in the properties it returns);
    this only affects the IPAWS-OPEN XML path this method parses.

    Returned shape matches the geocode dict convention used elsewhere
    (and what app_utils.eas._collect_event_code_candidates() expects):
    {"SAME": ["SPW"], ...}, keyed by valueName with one list per name
    so multiple <eventCode> elements sharing a valueName all survive.
    """
    event_codes: Dict[str, List[str]] = {}
    if info_elem is None:
        return event_codes

    for code_elem in info_elem.findall('cap:eventCode', ns):
        name = code_elem.findtext('cap:valueName', default='', namespaces=ns)
        value = code_elem.findtext('cap:value', default='', namespaces=ns)
        if not name:
            continue
        name = name.strip()
        if not name:
            continue
        value = (value or '').strip()
        if not value:
            continue
        event_codes.setdefault(name, []).append(value)

    return event_codes

def _extract_cap_parameters(info_elem: Optional[ET.Element], ns: Dict[str, str]) -> Dict[str, List[str]]:
    parameters: Dict[str, List[str]] = {}
    if info_elem is None:
        return parameters

    for param in info_elem.findall('cap:parameter', ns):
        name = param.findtext('cap:valueName', default='', namespaces=ns)
        value = param.findtext('cap:value', default='', namespaces=ns)
        if not name:
            continue
        name = name.strip()
        if not name:
            continue
        value = (value or '').strip()
        parameters.setdefault(name, []).append(value)

    return parameters

def _summarise_geometry(geometry: Optional[Dict]) -> Tuple[Optional[str], Optional[int], Optional[List[List[float]]]]:
    if not geometry or not isinstance(geometry, dict):
        return None, None, None

    geom_type = geometry.get('type')
    coordinates = geometry.get('coordinates')
    polygon_count: Optional[int] = None
    preview: Optional[List[List[float]]] = None

    if geom_type == 'Polygon':
        polygon_count = 1
        rings = coordinates or []
        if rings and isinstance(rings, list) and rings[0]:
            preview = [list(point) for point in rings[0][: min(len(rings[0]), 12)]]
    elif geom_type == 'MultiPolygon':
        polygon_count = len(coordinates or []) if isinstance(coordinates, list) else 0
        if coordinates and isinstance(coordinates, list):
            first_polygon = coordinates[0] or []
            if first_polygon and isinstance(first_polygon, list) and first_polygon[0]:
                preview = [list(point) for point in first_polygon[0][: min(len(first_polygon[0]), 12)]]
    else:
        if isinstance(coordinates, list):
            polygon_count = len(coordinates)
            preview = [list(point) for point in coordinates[: min(len(coordinates), 12)]]

    return geom_type, polygon_count, preview

def _apply_cancellation_status(alert: CAPAlert) -> bool:
    """Mark *alert* as Cancelled when it is an explicit cancellation product.

    Recognises both the CAP ``msgType=Cancel`` envelope and the VTEC ``CAN``
    action code.  Sets ``status='Cancelled'`` and stamps ``cancelled_at``
    while leaving ``expires`` untouched, so the alert detail view can show
    the event was lifted early.  Returns ``True`` when the alert is (now) a
    cancellation.

    This handles the case where a cancellation arrives as an *update* to the
    same CAP identifier (the prior-product path is covered by
    ``_mark_vtec_chain_superseded``).  Air behaviour is unchanged: the
    auto-forward guard already suppresses terminal VTEC actions and any
    non-'Actual' status.
    """
    if not is_cancellation(
        getattr(alert, 'message_type', None),
        getattr(alert, 'vtec_action', None),
    ):
        return False
    if alert.status != 'Cancelled':
        alert.status = 'Cancelled'
    if getattr(alert, 'cancelled_at', None) is None:
        alert.cancelled_at = utc_now()
    return True

def _validate_ugc_code(ugc: str) -> bool:
    r"""Validate UGC code format: [A-Z]{2}[CZ]\d{3} (e.g., OHZ016, OHC137)."""
    if not ugc or not isinstance(ugc, str):
        return False
    ugc = ugc.strip().upper()
    # Valid UGC format: 2 letters, C or Z, 3 digits
    return bool(re.match(r'^[A-Z]{2}[CZ]\d{3}$', ugc))

def _normalize_same_code(value: Any) -> Optional[str]:
    digits = ''.join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    normalized = digits.zfill(6)[:6]
    return normalized if normalized.strip('0') else normalized

def _coords_equal(p1: List[float], p2: List[float], epsilon: float = 1e-7) -> bool:
    """Check if two coordinate pairs are equal within floating-point tolerance."""
    if len(p1) < 2 or len(p2) < 2:
        return False
    return abs(p1[0] - p2[0]) < epsilon and abs(p1[1] - p2[1]) < epsilon

def _safe_json_copy(value: Any) -> Any:
    try:
        return json_loads(json_dumps(value))
    except Exception:
        return value
