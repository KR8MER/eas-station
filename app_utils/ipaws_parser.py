"""
IPAWS CAP v1.2 XML Parser
Parses FEMA IPAWS All-Hazards Information Feed XML into normalized CAP alert format
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# CAP v1.2 XML Namespace
CAP_NS = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}


class IPAWSXMLParser:
    """Parser for IPAWS CAP XML feeds"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_ipaws_feed(self, xml_content: str) -> List[Dict[str, Any]]:
        """
        Parse IPAWS XML feed into list of normalized CAP alerts

        Args:
            xml_content: Raw XML string from IPAWS feed

        Returns:
            List of CAP alert dictionaries in normalized format
        """
        alerts = []

        try:
            # Handle both single <alert> and <feed> with multiple <alert> elements
            root = ET.fromstring(xml_content)

            # Check if root is a feed or single alert
            if root.tag.endswith('feed') or root.tag.endswith('alerts'):
                # Multiple alerts in a feed
                alert_elements = root.findall('.//cap:alert', CAP_NS)
            elif root.tag.endswith('alert'):
                # Single alert
                alert_elements = [root]
            else:
                # Try to find any alert elements
                alert_elements = root.findall('.//cap:alert', CAP_NS)
                if not alert_elements:
                    self.logger.warning(f"No alerts found in XML. Root tag: {root.tag}")
                    return []

            self.logger.info(f"Found {len(alert_elements)} alert(s) in IPAWS feed")

            for alert_elem in alert_elements:
                try:
                    parsed_alert = self._parse_single_alert(alert_elem)
                    if parsed_alert:
                        alerts.append(parsed_alert)
                except Exception as e:
                    self.logger.error(f"Failed to parse individual alert: {e}", exc_info=True)

        except ET.ParseError as e:
            self.logger.error(f"XML parse error: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error parsing IPAWS feed: {e}", exc_info=True)

        return alerts

    def _parse_single_alert(self, alert_elem: ET.Element) -> Optional[Dict[str, Any]]:
        """
        Parse a single <alert> element into normalized CAP format

        CAP XML Structure:
        <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
          <identifier>...</identifier>
          <sender>...</sender>
          <sent>...</sent>
          <status>Actual</status>
          <msgType>Alert</msgType>
          <scope>Public</scope>
          <info>
            <event>Evacuation Order</event>
            <urgency>Immediate</urgency>
            <severity>Severe</severity>
            <certainty>Observed</certainty>
            <headline>...</headline>
            <description>...</description>
            <instruction>...</instruction>
            <expires>...</expires>
            <area>
              <areaDesc>Putnam County</areaDesc>
              <geocode>
                <valueName>FIPS6</valueName>
                <value>039137</value>
              </geocode>
              <polygon>lat1,lon1 lat2,lon2 ...</polygon>
            </area>
          </info>
        </alert>
        """
        # Parse alert-level fields
        identifier = self._get_text(alert_elem, 'cap:identifier', CAP_NS)
        sender = self._get_text(alert_elem, 'cap:sender', CAP_NS)
        sent = self._get_text(alert_elem, 'cap:sent', CAP_NS)
        status = self._get_text(alert_elem, 'cap:status', CAP_NS) or 'Unknown'
        msg_type = self._get_text(alert_elem, 'cap:msgType', CAP_NS) or 'Unknown'
        scope = self._get_text(alert_elem, 'cap:scope', CAP_NS) or 'Unknown'

        if not identifier:
            self.logger.warning("Alert missing identifier, skipping")
            return None

        # Parse <info> block (can be multiple for multi-lingual alerts - use first)
        info_elem = alert_elem.find('cap:info', CAP_NS)
        if info_elem is None:
            self.logger.warning(f"Alert {identifier} missing <info> block, skipping")
            return None

        # Parse info fields
        category = self._get_text(info_elem, 'cap:category', CAP_NS) or 'Unknown'
        event = self._get_text(info_elem, 'cap:event', CAP_NS) or 'Unknown'
        urgency = self._get_text(info_elem, 'cap:urgency', CAP_NS)
        severity = self._get_text(info_elem, 'cap:severity', CAP_NS)
        certainty = self._get_text(info_elem, 'cap:certainty', CAP_NS)
        headline = self._get_text(info_elem, 'cap:headline', CAP_NS)
        description = self._get_text(info_elem, 'cap:description', CAP_NS)
        instruction = self._get_text(info_elem, 'cap:instruction', CAP_NS)
        expires = self._get_text(info_elem, 'cap:expires', CAP_NS)

        # Parse area information
        area_elem = info_elem.find('cap:area', CAP_NS)
        area_desc = None
        fips_codes = []
        ugc_codes = []
        polygon = None

        if area_elem is not None:
            area_desc = self._get_text(area_elem, 'cap:areaDesc', CAP_NS)

            # Extract FIPS and UGC codes from geocode elements
            for geocode in area_elem.findall('cap:geocode', CAP_NS):
                value_name = self._get_text(geocode, 'cap:valueName', CAP_NS)
                value = self._get_text(geocode, 'cap:value', CAP_NS)

                if value_name == 'FIPS6' and value:
                    fips_codes.append(value)
                elif value_name == 'UGC' and value:
                    ugc_codes.append(value)

            # Extract polygon geometry
            polygon_text = self._get_text(area_elem, 'cap:polygon', CAP_NS)
            if polygon_text:
                polygon = self._parse_cap_polygon(polygon_text)

        # Build normalized alert dictionary (matches NOAA format for compatibility)
        parsed_alert = {
            'identifier': identifier,
            'sender': sender,
            'sent': sent,
            'status': status,
            'message_type': msg_type,
            'scope': scope,
            'category': category,
            'event': event,
            'urgency': urgency,
            'severity': severity,
            'certainty': certainty,
            'area_desc': area_desc,
            'headline': headline,
            'description': description,
            'instruction': instruction,
            'expires': expires,
            'fips_codes': fips_codes,
            'ugc_codes': ugc_codes,
            'polygon': polygon,
            'source': 'ipaws',  # Tag as IPAWS source
        }

        self.logger.debug(f"Parsed IPAWS alert: {identifier} - {event}")
        return parsed_alert

    def _get_text(self, element: ET.Element, tag: str, namespace: Dict[str, str]) -> Optional[str]:
        """Safely extract text from XML element"""
        child = element.find(tag, namespace)
        if child is not None and child.text:
            return child.text.strip()
        return None

    def _parse_cap_polygon(self, polygon_str: str) -> Optional[List[List[float]]]:
        """
        Parse CAP polygon string to coordinate list

        CAP Format: "lat1,lon1 lat2,lon2 lat3,lon3"
        Returns: [[lon1, lat1], [lon2, lat2], ...] (GeoJSON order: [longitude, latitude])
        """
        try:
            coords = []
            for pair in polygon_str.strip().split():
                if ',' in pair:
                    lat, lon = map(float, pair.split(','))
                    coords.append([lon, lat])  # GeoJSON uses [lon, lat]

            # Ensure polygon is closed (first point == last point)
            if coords and coords[0] != coords[-1]:
                coords.append(coords[0])

            return coords if len(coords) >= 4 else None  # Polygons need at least 3 unique points + closing point

        except (ValueError, AttributeError) as e:
            self.logger.warning(f"Failed to parse polygon: {polygon_str[:100]}... Error: {e}")
            return None

    def normalize_to_geojson_feature(self, parsed_alert: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert parsed IPAWS alert to GeoJSON Feature format
        (matches format expected by existing alert processing code)

        Returns:
            GeoJSON Feature with properties and geometry
        """
        properties = {
            'identifier': parsed_alert.get('identifier'),
            'sender': parsed_alert.get('sender'),
            'sent': parsed_alert.get('sent'),
            'status': parsed_alert.get('status'),
            'messageType': parsed_alert.get('message_type'),
            'scope': parsed_alert.get('scope'),
            'category': parsed_alert.get('category'),
            'event': parsed_alert.get('event'),
            'urgency': parsed_alert.get('urgency'),
            'severity': parsed_alert.get('severity'),
            'certainty': parsed_alert.get('certainty'),
            'areaDesc': parsed_alert.get('area_desc'),
            'headline': parsed_alert.get('headline'),
            'description': parsed_alert.get('description'),
            'instruction': parsed_alert.get('instruction'),
            'expires': parsed_alert.get('expires'),
        }

        # Build geocode object
        geocode = {}
        if parsed_alert.get('fips_codes'):
            geocode['FIPS6'] = parsed_alert['fips_codes']
        if parsed_alert.get('ugc_codes'):
            geocode['UGC'] = parsed_alert['ugc_codes']

        if geocode:
            properties['geocode'] = geocode

        # Build geometry from polygon
        geometry = None
        if parsed_alert.get('polygon'):
            geometry = {
                'type': 'Polygon',
                'coordinates': [parsed_alert['polygon']]  # Polygon coordinates are nested
            }

        feature = {
            'type': 'Feature',
            'properties': properties,
            'geometry': geometry
        }

        return feature
