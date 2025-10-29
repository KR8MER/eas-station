#!/usr/bin/env python3
"""
IPAWS (Integrated Public Alert & Warning System) Alert Poller
Polls FEMA IPAWS All-Hazards Information Feed for state/local emergency alerts

Provides alerts beyond NOAA weather:
- State/local emergency management
- AMBER/Blue alerts
- Evacuation orders
- Civil emergencies
- Hazmat incidents
"""

import os
import sys
import logging
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime

# Add parent directory to path for imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app_utils.ipaws_parser import IPAWSXMLParser


class IPAWSPoller:
    """
    Poll FEMA IPAWS All-Hazards Information Feed for emergency alerts

    Requires:
    - IPAWS PIN (provided by FEMA after MOA approval)
    - IPAWS endpoint URL (provided by FEMA)
    - FIPS code for jurisdiction filtering
    """

    def __init__(
        self,
        ipaws_endpoint: str,
        ipaws_pin: str,
        location_fips: str,
        location_state: str,
        location_county: str,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize IPAWS poller

        Args:
            ipaws_endpoint: FEMA IPAWS feed URL
            ipaws_pin: Authentication PIN from FEMA
            location_fips: FIPS code for filtering (e.g., '039137' for Putnam County, OH)
            location_state: State code for filtering (e.g., 'OH')
            location_county: County name for filtering (e.g., 'Putnam County')
            logger: Optional logger instance
        """
        self.ipaws_endpoint = ipaws_endpoint
        self.ipaws_pin = ipaws_pin
        self.location_fips = location_fips
        self.location_state = location_state.upper()
        self.location_county = location_county.upper()
        self.logger = logger or logging.getLogger(__name__)

        # Initialize XML parser
        self.parser = IPAWSXMLParser()

        # HTTP session for requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'KR8MER-NOAA-Alerts/2.0 IPAWS-Client',
            'Accept': 'application/xml, text/xml'
        })

        self.logger.info(
            f"IPAWS Poller initialized for {location_county}, {location_state} (FIPS: {location_fips})"
        )

    def fetch_ipaws_alerts(self, timeout: int = 30) -> List[Dict[str, Any]]:
        """
        Fetch alerts from IPAWS feed

        Args:
            timeout: Request timeout in seconds

        Returns:
            List of parsed CAP alerts in normalized format
        """
        try:
            self.logger.info(f"Fetching IPAWS alerts from: {self.ipaws_endpoint}")

            # Make request with PIN authentication
            response = self.session.get(
                self.ipaws_endpoint,
                params={'pin': self.ipaws_pin},
                timeout=timeout
            )
            response.raise_for_status()

            # Parse XML response
            xml_content = response.text
            self.logger.debug(f"Received {len(xml_content)} bytes of XML from IPAWS")

            # Parse alerts
            all_alerts = self.parser.parse_ipaws_feed(xml_content)
            self.logger.info(f"Parsed {len(all_alerts)} alerts from IPAWS feed")

            # Filter for relevant alerts
            relevant_alerts = [
                alert for alert in all_alerts
                if self._is_relevant_alert(alert)
            ]

            self.logger.info(
                f"Filtered to {len(relevant_alerts)} relevant alerts for {self.location_county}"
            )

            # Convert to GeoJSON features for compatibility with existing processing
            features = [
                self.parser.normalize_to_geojson_feature(alert)
                for alert in relevant_alerts
            ]

            return features

        except requests.exceptions.Timeout:
            self.logger.error(f"IPAWS request timed out after {timeout}s")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                self.logger.error("IPAWS authentication failed - check IPAWS_PIN")
            elif e.response.status_code == 403:
                self.logger.error("IPAWS access forbidden - verify MOA approval status")
            else:
                self.logger.error(f"IPAWS HTTP error {e.response.status_code}: {e}")
            return []
        except requests.exceptions.RequestException as e:
            self.logger.error(f"IPAWS request failed: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching IPAWS alerts: {e}", exc_info=True)
            return []

    def _is_relevant_alert(self, alert: Dict[str, Any]) -> bool:
        """
        Filter alerts for jurisdiction relevance

        Checks:
        - FIPS code matching (exact match)
        - State-level alerts
        - County name in area description
        - Nationwide alerts (Presidential/EAN)

        Args:
            alert: Parsed alert dictionary

        Returns:
            True if alert is relevant to configured jurisdiction
        """
        try:
            event = alert.get('event', 'Unknown')
            fips_codes = alert.get('fips_codes', [])
            ugc_codes = alert.get('ugc_codes', [])
            area_desc = (alert.get('area_desc') or '').upper()
            scope = alert.get('scope', '').upper()
            category = alert.get('category', '').upper()

            # Priority 1: Nationwide alerts (Presidential/EAN)
            if scope == 'NATIONAL' or event == 'Emergency Action Notification':
                self.logger.info(f"✓ IPAWS ALERT ACCEPTED (nationwide): {event}")
                return True

            # Priority 2: Exact FIPS code match
            for fips in fips_codes:
                # Handle both 5-digit and 6-digit FIPS codes
                # 039137 = Putnam County, OH (state 39, county 137)
                if fips == self.location_fips or fips.endswith(self.location_fips[-5:]):
                    self.logger.info(f"✓ IPAWS ALERT ACCEPTED (FIPS {fips}): {event}")
                    return True

            # Priority 3: UGC code match (for weather-related IPAWS alerts)
            # This handles alerts that might come through both NOAA and IPAWS
            for ugc in ugc_codes:
                ugc_upper = str(ugc).upper()
                # UGC format: StateZZnnn or StateCnnn
                # e.g., OHC137 for Putnam County, OH
                county_code = self.location_fips[-3:]  # Last 3 digits = county code
                if ugc_upper.startswith(self.location_state) and county_code in ugc_upper:
                    self.logger.info(f"✓ IPAWS ALERT ACCEPTED (UGC {ugc}): {event}")
                    return True

            # Priority 4: State-level alerts
            if self.location_state in area_desc:
                # Only accept if it's a significant state-level alert
                significant_events = {
                    'AMBER', 'BLUE', 'EVACUATION', 'SHELTER', 'HAZMAT',
                    'RADIOLOGICAL', 'NUCLEAR', 'LAW ENFORCEMENT'
                }
                if any(sig_event in event.upper() for sig_event in significant_events):
                    self.logger.info(f"✓ IPAWS ALERT ACCEPTED (state-level {event}): {area_desc[:50]}")
                    return True

            # Priority 5: County name match in area description
            if self.location_county in area_desc:
                self.logger.info(f"✓ IPAWS ALERT ACCEPTED (county match): {event}")
                return True

            # Reject: Not relevant to jurisdiction
            self.logger.debug(
                f"✗ IPAWS ALERT REJECTED: {event} - "
                f"FIPS: {fips_codes}, Area: {area_desc[:50]}"
            )
            return False

        except Exception as e:
            self.logger.error(f"Error checking alert relevance: {e}")
            return False


def test_ipaws_connection():
    """Test IPAWS connection and parsing (for debugging)"""
    from dotenv import load_dotenv

    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    ipaws_endpoint = os.getenv('IPAWS_ENDPOINT')
    ipaws_pin = os.getenv('IPAWS_PIN')
    location_fips = os.getenv('LOCATION_FIPS_CODE', '039137')
    location_state = os.getenv('DEFAULT_STATE_CODE', 'OH')
    location_county = os.getenv('DEFAULT_COUNTY_NAME', 'Putnam County')

    if not ipaws_endpoint or not ipaws_pin:
        print("ERROR: IPAWS_ENDPOINT and IPAWS_PIN must be set in .env")
        print("Set IPAWS_ENABLED=false to disable IPAWS polling")
        return

    poller = IPAWSPoller(
        ipaws_endpoint=ipaws_endpoint,
        ipaws_pin=ipaws_pin,
        location_fips=location_fips,
        location_state=location_state,
        location_county=location_county
    )

    print("\n" + "=" * 60)
    print("Testing IPAWS Connection")
    print("=" * 60)
    print(f"Endpoint: {ipaws_endpoint}")
    print(f"Location: {location_county}, {location_state} (FIPS: {location_fips})")
    print("=" * 60 + "\n")

    alerts = poller.fetch_ipaws_alerts()

    print(f"\n{'=' * 60}")
    print(f"Retrieved {len(alerts)} relevant IPAWS alerts")
    print("=" * 60)

    for i, alert in enumerate(alerts, 1):
        props = alert.get('properties', {})
        print(f"\n{i}. {props.get('event', 'Unknown')}")
        print(f"   ID: {props.get('identifier')}")
        print(f"   Severity: {props.get('severity')} / Urgency: {props.get('urgency')}")
        print(f"   Area: {props.get('areaDesc', 'N/A')[:60]}")
        print(f"   Headline: {props.get('headline', 'N/A')[:80]}")


if __name__ == '__main__':
    test_ipaws_connection()
