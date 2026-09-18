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

"""CAP-XML -> GeoJSON-shaped feature parsing, extracted out of CAPPoller.

Large File Refactor Plan Phase 4c continuation: these 12 methods (plus the
module-level ``_serialize_alert_for_sig`` helper) only ever touched
``self.logger`` -- a stable dependency set once in ``CAPPoller.__init__``
and never reassigned -- and each other, never ``self.db_session`` or any of
the poller's own zone/SAME-code configuration. That made them a clean,
low-risk first collaborator to pull out of the 59-method god-class, unlike
the 50 still-stateful methods (``poll_and_process``, ``fetch_cap_alerts``,
relevance matching, intersection/geometry persistence, ...) that remain.

``logger`` is threaded through explicitly as a parameter rather than a
fresh module-level ``logging.getLogger(__name__)``, to avoid the exact
hazard ``docs/development/AGENTS.md`` documents from Phase 3e: a new
per-module logger here would silently rename every log record these
functions emit from ``poller.cap_poller`` to ``poller.cap_geometry``,
breaking any journald filter or log search keyed on the old name. Callers
in ``cap_poller.py`` pass ``self.logger`` explicitly, preserving the exact
same logger identity as before the move.
"""

import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app_utils.alert_sources import ALERT_SOURCE_IPAWS, ALERT_SOURCE_NOAA, normalize_alert_source
from app_utils import parse_nws_datetime, utc_now
from app_utils.optimized_parsing import get_element_tree_module

from poller.cap_alert_parsing import (
    _coords_equal,
    _extract_cap_event_codes,
    _extract_cap_parameters,
    _select_cap_info,
)

ET = get_element_tree_module()


def _serialize_alert_for_sig(alert_elem) -> str:
    """Serialize an alert element preserving original namespace prefixes.

    XML digital signature verification requires that the stored raw_xml uses the
    same namespace prefixes as the original document (e.g. ``ds:`` for XMLdsig).
    The stdlib ElementTree mangler rewrites these as ``ns0:``, ``ns1:`` etc., which
    causes C14N canonicalization to produce bytes that differ from the signed bytes.

    This function always uses lxml when available (lxml preserves nsmap prefix names)
    and falls back to the generic ``ET`` module otherwise (signature verification will
    not succeed but the XML is still stored for display purposes).
    """
    try:
        from lxml import etree as _lxml_et
        return _lxml_et.tostring(alert_elem, encoding='unicode', with_tail=False)
    except ImportError:
        pass
    return ET.tostring(alert_elem, encoding='unicode')


def _parse_ipaws_xml_feed(xml_text: str, logger) -> List[Dict]:
    alerts: List[Dict] = []
    if not xml_text:
        return alerts

    try:
        from app_utils.optimized_parsing import parse_xml_string
        root = parse_xml_string(xml_text)
    except Exception as exc:
        logger.error(f"XML parse error in CAP feed: {exc}")
        return alerts

    ns = {
        'feed': 'http://gov.fema.ipaws.services/feed',
        'cap': 'urn:oasis:names:tc:emergency:cap:1.2',
    }

    for alert_elem in root.findall('.//cap:alert', ns):
        try:
            feature = _convert_cap_alert(alert_elem, ns, logger)
            if feature:
                alerts.append(feature)
        except Exception as exc:
            try:
                bad_id = alert_elem.findtext('cap:identifier', default='unknown', namespaces=ns)
            except Exception:
                bad_id = 'unknown'
            logger.error(
                f"Unhandled error converting CAP XML alert {bad_id!r}: {exc}",
                exc_info=True,
            )
            continue

    return alerts


def _convert_cap_alert(alert_elem: ET.Element, ns: Dict[str, str], logger) -> Optional[Dict]:
    def get_text(element: Optional[ET.Element], path: str, default: str = '') -> str:
        if element is None:
            return default
        value = element.findtext(path, default=default, namespaces=ns)
        return value.strip() if isinstance(value, str) else default

    identifier = get_text(alert_elem, 'cap:identifier')
    sent = get_text(alert_elem, 'cap:sent')
    info_elems = alert_elem.findall('cap:info', ns)
    info_elem = _select_cap_info(info_elems, ns)

    parameters = _extract_cap_parameters(info_elem, ns)
    event_codes = _extract_cap_event_codes(info_elem, ns)
    geometry, area_desc, geocodes = _extract_area_details(info_elem, ns, logger)
    resources = _extract_cap_resources(info_elem, ns, logger)

    properties = {
        'identifier': identifier,
        'sender': get_text(alert_elem, 'cap:sender'),
        'sent': sent,
        'status': get_text(alert_elem, 'cap:status', 'Unknown') or 'Unknown',
        'messageType': get_text(alert_elem, 'cap:msgType', 'Unknown') or 'Unknown',
        'scope': get_text(alert_elem, 'cap:scope', 'Unknown') or 'Unknown',
        # Per CAP 1.2 sec 3.3.2.3, a Cancel/Update message gets its OWN
        # unique identifier and points back at the message(s) it affects
        # via <references> (space-separated "sender,identifier,sent"
        # triples) -- it is not required to reuse the original
        # identifier. A Cancel commonly carries no <info> block at all
        # (nothing to cancel *to*, just a notice that a prior alert is
        # over), so this is the only way to know what it refers to.
        'references': get_text(alert_elem, 'cap:references'),
        'category': get_text(info_elem, 'cap:category', 'Unknown') or 'Unknown',
        'event': get_text(info_elem, 'cap:event', 'Unknown') or 'Unknown',
        'responseType': get_text(info_elem, 'cap:responseType'),
        'urgency': get_text(info_elem, 'cap:urgency', 'Unknown') or 'Unknown',
        'severity': get_text(info_elem, 'cap:severity', 'Unknown') or 'Unknown',
        'certainty': get_text(info_elem, 'cap:certainty', 'Unknown') or 'Unknown',
        'effective': get_text(info_elem, 'cap:effective'),
        'expires': get_text(info_elem, 'cap:expires'),
        'senderName': get_text(info_elem, 'cap:senderName'),
        'headline': get_text(info_elem, 'cap:headline'),
        'description': get_text(info_elem, 'cap:description'),
        'instruction': get_text(info_elem, 'cap:instruction'),
        'web': get_text(info_elem, 'cap:web'),
        'areaDesc': area_desc,
        'geocode': geocodes,
        'eventCode': event_codes,
        'parameters': parameters,
        'resources': resources,
        'source': ALERT_SOURCE_IPAWS,
    }

    if not properties['identifier']:
        fallback = f"{properties.get('event', 'Unknown')}|{properties.get('sent', '')}"
        # md5 here is a non-security deterministic dedup key; switching algorithms
        # would orphan rows already stored under the original fingerprint.
        properties['identifier'] = f"ipaws_{hashlib.md5(fallback.encode()).hexdigest()[:16]}"  # noqa: S324

    feature = {
        'type': 'Feature',
        'properties': properties,
        'geometry': geometry,
        # Serialize using lxml to preserve original namespace prefixes (e.g. ds:, capsig:).
        # This is required for XML digital signature verification: C14N of SignedInfo
        # must produce the same bytes as the original signed document.  stdlib
        # ElementTree mangles prefixes (ns0:, ns1:) which breaks C14N byte-matching.
        'raw_xml': _serialize_alert_for_sig(alert_elem),
    }

    return feature


def _extract_cap_resources(info_elem: Optional[ET.Element], ns: Dict[str, str], logger) -> List[Dict[str, str]]:
    """Extract resource elements from CAP info block.

    CAP 1.2 alerts can contain <resource> elements with embedded or linked content,
    including audio files. IPAWS alerts often include pre-recorded audio messages.

    Returns:
        List of resource dicts with keys: resourceDesc, mimeType, uri, derefUri, digest
    """
    resources: List[Dict[str, str]] = []
    if info_elem is None:
        return resources

    for resource in info_elem.findall('cap:resource', ns):
        resource_dict: Dict[str, str] = {}

        # Required fields
        resource_desc = resource.findtext('cap:resourceDesc', default='', namespaces=ns)
        if resource_desc:
            resource_dict['resourceDesc'] = resource_desc.strip()

        mime_type = resource.findtext('cap:mimeType', default='', namespaces=ns)
        if mime_type:
            resource_dict['mimeType'] = mime_type.strip()

        # Optional fields - URI for external resource
        uri = resource.findtext('cap:uri', default='', namespaces=ns)
        if uri:
            resource_dict['uri'] = uri.strip()

        # Optional fields - derefUri for base64-encoded inline content
        deref_uri = resource.findtext('cap:derefUri', default='', namespaces=ns)
        if deref_uri:
            resource_dict['derefUri'] = deref_uri.strip()

        # Optional fields - digest for integrity verification
        digest = resource.findtext('cap:digest', default='', namespaces=ns)
        if digest:
            resource_dict['digest'] = digest.strip()

        # Size in bytes (optional)
        size = resource.findtext('cap:size', default='', namespaces=ns)
        if size:
            resource_dict['size'] = size.strip()

        # Only include if we have at least a description or URI
        if resource_dict.get('resourceDesc') or resource_dict.get('uri') or resource_dict.get('derefUri'):
            resources.append(resource_dict)

            # Log audio resources for debugging
            if mime_type and 'audio' in mime_type.lower():
                logger.info(
                    f"Found audio resource in CAP alert: {resource_desc or 'unnamed'} "
                    f"(type: {mime_type}, uri: {uri[:50] + '...' if uri and len(uri) > 50 else uri or 'embedded'})"
                )

    return resources


def _extract_area_details(
    info_elem: Optional[ET.Element], ns: Dict[str, str], logger
) -> Tuple[Optional[Dict], str, Dict[str, List[str]]]:
    if info_elem is None:
        return None, '', {}

    polygons: List[List[List[float]]] = []
    area_descs: List[str] = []
    geocodes: Dict[str, List[str]] = {}

    for area in info_elem.findall('cap:area', ns):
        desc = area.findtext('cap:areaDesc', default='', namespaces=ns)
        if desc:
            desc = desc.strip()
            if desc and desc not in area_descs:
                area_descs.append(desc)

        for polygon in area.findall('cap:polygon', ns):
            coords = _parse_cap_polygon(polygon.text, logger)
            if coords:
                polygons.append(coords)

        for circle in area.findall('cap:circle', ns):
            coords = _parse_cap_circle(circle.text, logger)
            if coords:
                polygons.append(coords)

        for geocode in area.findall('cap:geocode', ns):
            name = geocode.findtext('cap:valueName', default='', namespaces=ns)
            value = geocode.findtext('cap:value', default='', namespaces=ns)
            if not name or not value:
                continue
            name = name.strip().upper()
            value = value.strip()
            if not name or not value:
                continue
            geocodes.setdefault(name, []).append(value)

    geometry: Optional[Dict] = None
    if polygons:
        if len(polygons) == 1:
            geometry = {'type': 'Polygon', 'coordinates': [polygons[0]]}
        else:
            geometry = {'type': 'MultiPolygon', 'coordinates': [[coords] for coords in polygons]}

    area_desc = '; '.join(area_descs)
    return geometry, area_desc, geocodes


def _parse_cap_polygon(polygon_text: Optional[str], logger) -> Optional[List[List[float]]]:
    if not polygon_text:
        return None

    coords: List[List[float]] = []
    for pair in polygon_text.strip().split():
        if ',' not in pair:
            continue
        try:
            lat_str, lon_str = pair.split(',', 1)
            lat = float(lat_str)
            lon = float(lon_str)

            # Validate coordinate ranges
            if not (-90 <= lat <= 90):
                logger.warning(f"Invalid latitude {lat} in polygon, skipping coordinate")
                continue
            if not (-180 <= lon <= 180):
                logger.warning(f"Invalid longitude {lon} in polygon, skipping coordinate")
                continue

            coords.append([lon, lat])
        except ValueError:
            continue

    if len(coords) < 3:
        return None

    # Use epsilon tolerance for coordinate comparison to handle floating-point precision
    if not _coords_equal(coords[0], coords[-1]):
        coords.append(coords[0])

    return coords


def _parse_cap_circle(circle_text: Optional[str], logger, points: int = 36) -> Optional[List[List[float]]]:
    """Parse CAP circle element into polygon coordinates.

    Args:
        circle_text: CAP circle string format "lat,lon radius_km"
        points: Number of points to approximate circle (default 36)

    Returns:
        List of [lon, lat] coordinate pairs, or None if invalid
    """
    if not circle_text:
        return None

    parts = circle_text.strip().split()
    if not parts:
        logger.debug("Empty circle text after stripping whitespace")
        return None

    try:
        if ',' not in parts[0]:
            logger.warning(f"Invalid circle format (missing comma): '{circle_text[:50]}'")
            return None

        lat_str, lon_str = parts[0].split(',', 1)
        lat = float(lat_str)
        lon = float(lon_str)

        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            logger.warning(f"Circle latitude out of range: {lat} (must be -90 to 90)")
            return None
        if not (-180 <= lon <= 180):
            logger.warning(f"Circle longitude out of range: {lon} (must be -180 to 180)")
            return None

    except ValueError as e:
        logger.warning(f"Invalid circle coordinates: '{parts[0]}' - {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing circle coordinates: {e}")
        return None

    radius_km = 0.0
    if len(parts) > 1:
        try:
            radius_km = float(parts[1])
        except ValueError as e:
            logger.warning(f"Invalid circle radius: '{parts[1]}' - {e}")
            radius_km = 0.0

    if radius_km <= 0:
        logger.warning(f"Circle radius must be positive: {radius_km} km")
        return None

    if radius_km > 20000:  # Earth's half-circumference
        logger.warning(f"Circle radius unreasonably large: {radius_km} km (max 20000 km)")
        return None

    return _approximate_circle_polygon(lat, lon, radius_km, points, logger)


def _approximate_circle_polygon(lat: float, lon: float, radius_km: float, points: int, logger) -> List[List[float]]:
    """Approximate a circle as a polygon using haversine formula.

    Args:
        lat: Center latitude in degrees
        lon: Center longitude in degrees
        radius_km: Radius in kilometers
        points: Number of points to use for approximation

    Returns:
        List of [lon, lat] coordinate pairs forming a closed ring

    Raises:
        ValueError: If inputs are invalid
    """
    import math

    coords: List[List[float]] = []

    # Validate inputs
    if not (-90 <= lat <= 90):
        raise ValueError(f"Latitude must be -90 to 90, got {lat}")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Longitude must be -180 to 180, got {lon}")
    if radius_km <= 0:
        raise ValueError(f"Radius must be positive, got {radius_km}")
    if points < 3:
        raise ValueError(f"Need at least 3 points for polygon, got {points}")

    # Handle edge case: circles at or near poles
    if abs(lat) > 89.5:
        logger.warning(
            f"Circle center at extreme latitude ({lat:.2f}°) - using simplified rectangular approximation. "
            f"Haversine formula unreliable near poles."
        )
        # For near-pole circles, use a simplified square approximation
        offset = radius_km / 111.0  # Rough km to degrees conversion
        coords = [
            [lon - offset, min(89.9, lat + offset)],
            [lon + offset, min(89.9, lat + offset)],
            [lon + offset, max(-89.9, lat - offset)],
            [lon - offset, max(-89.9, lat - offset)],
            [lon - offset, min(89.9, lat + offset)],  # Close ring
        ]
        return coords

    # Handle edge case: very large radius
    if radius_km > 10000:
        logger.warning(
            f"Circle radius very large ({radius_km:.0f} km) - may produce distorted geometry"
        )

    try:
        radius_ratio = radius_km / 6371.0  # Earth radius in km
        center_lat = math.radians(lat)
        center_lon = math.radians(lon)

        for step in range(points):
            bearing = 2 * math.pi * (step / points)
            sin_lat = math.sin(center_lat)
            cos_lat = math.cos(center_lat)
            sin_radius = math.sin(radius_ratio)
            cos_radius = math.cos(radius_ratio)

            # Haversine formula for point on great circle
            lat_rad = math.asin(
                sin_lat * cos_radius + cos_lat * sin_radius * math.cos(bearing)
            )

            # Handle potential division by zero when cos_lat is very small
            if abs(cos_lat) < 1e-10:
                logger.warning(f"cos_lat near zero at {lat}°, using center longitude")
                lon_rad = center_lon
            else:
                lon_rad = center_lon + math.atan2(
                    math.sin(bearing) * sin_radius * cos_lat,
                    cos_radius - sin_lat * math.sin(lat_rad)
                )

            # Convert to degrees and validate
            lon_deg = math.degrees(lon_rad)
            lat_deg = math.degrees(lat_rad)

            # Normalize longitude to -180 to 180
            while lon_deg > 180:
                lon_deg -= 360
            while lon_deg < -180:
                lon_deg += 360

            # Clamp latitude to valid range
            lat_deg = max(-90, min(90, lat_deg))

            coords.append([lon_deg, lat_deg])

    except (ValueError, OverflowError) as e:
        logger.error(
            f"Math error approximating circle at ({lat}, {lon}) radius {radius_km}km: {e}. "
            f"Falling back to simple square."
        )
        # Fallback to simple square on math error
        offset = radius_km / 111.0
        coords = [
            [lon - offset, min(89.9, lat + offset)],
            [lon + offset, min(89.9, lat + offset)],
            [lon + offset, max(-89.9, lat - offset)],
            [lon - offset, max(-89.9, lat - offset)],
            [lon - offset, min(89.9, lat + offset)],
        ]
        return coords

    # Use epsilon tolerance for ring closure
    if coords and not _coords_equal(coords[0], coords[-1]):
        coords.append(coords[0])

    return coords


MESSAGE_TYPE_PRIORITIES = {
    'CANCEL': 4,
    'UPDATE': 3,
    'ALERT': 2,
    'ACK': 1,
}


def _message_type_priority(message_type: Optional[str]) -> int:
    if not message_type:
        return 0
    return MESSAGE_TYPE_PRIORITIES.get(str(message_type).strip().upper(), 0)


def _alert_sort_key(alert: Dict) -> Tuple[datetime, int]:
    from pytz import UTC as UTC_TZ

    properties = alert.get('properties', {})
    sent_raw = properties.get('sent')
    sent_dt = parse_nws_datetime(sent_raw) if sent_raw else None
    if not sent_dt:
        sent_dt = datetime.min.replace(tzinfo=UTC_TZ)
    message_type_priority = _message_type_priority(properties.get('messageType'))
    return sent_dt, message_type_priority


def _should_replace_alert(existing_alert: Dict, candidate_alert: Dict) -> bool:
    """Determine if candidate alert should replace existing alert.

    CANCEL messages always supersede other message types for the same identifier,
    regardless of timestamp, as they represent authoritative cancellations.
    """
    existing_props = existing_alert.get('properties', {})
    candidate_props = candidate_alert.get('properties', {})

    existing_msg_type = (existing_props.get('messageType') or '').strip().upper()
    candidate_msg_type = (candidate_props.get('messageType') or '').strip().upper()

    # CANCEL always wins over non-CANCEL
    if candidate_msg_type == 'CANCEL' and existing_msg_type != 'CANCEL':
        return True
    if existing_msg_type == 'CANCEL' and candidate_msg_type != 'CANCEL':
        return False

    # Otherwise use timestamp and priority-based logic
    existing_sent, existing_priority = _alert_sort_key(existing_alert)
    candidate_sent, candidate_priority = _alert_sort_key(candidate_alert)

    if candidate_sent > existing_sent:
        return True
    if candidate_sent < existing_sent:
        return False
    if candidate_priority > existing_priority:
        return True
    if candidate_priority < existing_priority:
        return False

    # Prefer alerts with geometry over those without
    existing_geometry = existing_alert.get('geometry')
    candidate_geometry = candidate_alert.get('geometry')
    if candidate_geometry and not existing_geometry:
        return True

    return False


def parse_cap_alert(alert_data: Dict, logger) -> Optional[Dict]:
    try:
        properties = alert_data.get('properties', {})
        geometry = alert_data.get('geometry')
        # NOAA API uses 'id' field, IPAWS/CAP uses 'identifier' - check both
        identifier = properties.get('identifier') or properties.get('id')
        if not identifier:
            event = properties.get('event', 'Unknown')
            sent = properties.get('sent', str(time.time()))
            # md5 here is a non-security deterministic dedup key; switching algorithms
            # would orphan rows already stored under the original fingerprint.
            identifier = f"temp_{hashlib.md5((event + sent).encode()).hexdigest()[:16]}"  # noqa: S324

        sent = parse_nws_datetime(properties.get('sent'), logger=logger) if properties.get('sent') else None
        expires = parse_nws_datetime(properties.get('expires'), logger=logger) if properties.get('expires') else None

        area_desc = properties.get('areaDesc', '')
        if isinstance(area_desc, list):
            area_desc = '; '.join(area_desc)

        source_value = properties.get('source')
        if not source_value and alert_data.get('raw_xml') is not None:
            source_value = ALERT_SOURCE_IPAWS
        elif not source_value:
            source_value = ALERT_SOURCE_NOAA
        source_value = normalize_alert_source(source_value)

        parsed = {
            'identifier': identifier,
            'sent': sent or utc_now(),
            'expires': expires,
            'status': properties.get('status', 'Unknown'),
            'message_type': properties.get('messageType', 'Unknown'),
            'scope': properties.get('scope', 'Unknown'),
            'category': properties.get('category', 'Unknown'),
            'event': properties.get('event', 'Unknown'),
            'urgency': properties.get('urgency', 'Unknown'),
            'severity': properties.get('severity', 'Unknown'),
            'certainty': properties.get('certainty', 'Unknown'),
            'area_desc': area_desc,
            'headline': properties.get('headline', ''),
            'description': properties.get('description', ''),
            'instruction': properties.get('instruction', ''),
            'raw_json': alert_data,
            'source': source_value,
            '_geometry_data': geometry,
        }
        logger.info(f"Parsed alert: {identifier} - {parsed['event']}")
        return parsed
    except Exception as e:
        logger.error(f"Error parsing CAP alert: {e}")
        return None


def _count_vertices(coords, logger, depth: int = 0) -> int:
    """Recursively count vertices in nested coordinate arrays."""
    if depth > 10:  # Prevent infinite recursion on malformed data
        logger.warning("Maximum geometry nesting depth exceeded")
        return 0

    if not isinstance(coords, list):
        return 0

    # Check if this is a coordinate pair [lon, lat]
    if coords and len(coords) >= 2 and isinstance(coords[0], (int, float)):
        return 1

    # Otherwise recursively count nested arrays
    return sum(_count_vertices(item, logger, depth + 1) for item in coords)


__all__ = [
    "MESSAGE_TYPE_PRIORITIES",
    "_alert_sort_key",
    "_approximate_circle_polygon",
    "_convert_cap_alert",
    "_count_vertices",
    "_extract_area_details",
    "_extract_cap_resources",
    "_message_type_priority",
    "_parse_cap_circle",
    "_parse_cap_polygon",
    "_parse_ipaws_xml_feed",
    "_serialize_alert_for_sig",
    "_should_replace_alert",
    "parse_cap_alert",
]
