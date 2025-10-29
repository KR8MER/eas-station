#!/usr/bin/env python3
"""
Unified Multi-Source CAP Alert Poller
Combines NOAA Weather and IPAWS All-Hazards feeds into single polling service

Polls from:
1. NOAA Weather API (weather.gov) - Weather alerts
2. IPAWS (FEMA) - State/local emergencies, AMBER alerts, evacuations, etc.
3. [Future] SDR-received EAS broadcasts

Features:
- Deduplication across sources (same alert from NOAA and IPAWS)
- Source tagging for analytics
- Priority handling (IPAWS can override NOAA for same event)
- Unified error handling and logging
"""

import os
import sys
import time
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add parent directory to path for imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from cap_poller import CAPPoller
from ipaws_poller import IPAWSPoller


class UnifiedAlertPoller:
    """
    Unified poller for multiple CAP alert sources

    Orchestrates polling from NOAA and IPAWS with:
    - Intelligent deduplication
    - Source prioritization
    - Error isolation (one source failure doesn't affect others)
    """

    def __init__(
        self,
        database_url: str,
        noaa_enabled: bool = True,
        ipaws_enabled: bool = False,
        ipaws_config: Optional[Dict[str, Any]] = None,
        led_sign_ip: Optional[str] = None,
        led_sign_port: int = 10001,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize unified poller

        Args:
            database_url: PostgreSQL connection string
            noaa_enabled: Enable NOAA weather alerts
            ipaws_enabled: Enable IPAWS all-hazards alerts
            ipaws_config: IPAWS configuration dict (endpoint, pin, fips)
            led_sign_ip: Optional LED sign IP
            led_sign_port: LED sign port
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.database_url = database_url
        self.noaa_enabled = noaa_enabled
        self.ipaws_enabled = ipaws_enabled

        # Initialize NOAA poller
        self.noaa_poller = None
        if noaa_enabled:
            try:
                self.noaa_poller = CAPPoller(
                    database_url=database_url,
                    led_sign_ip=led_sign_ip,
                    led_sign_port=led_sign_port
                )
                self.logger.info("✓ NOAA Weather poller initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize NOAA poller: {e}")

        # Initialize IPAWS poller
        self.ipaws_poller = None
        if ipaws_enabled and ipaws_config:
            try:
                self.ipaws_poller = IPAWSPoller(
                    ipaws_endpoint=ipaws_config['endpoint'],
                    ipaws_pin=ipaws_config['pin'],
                    location_fips=ipaws_config['fips'],
                    location_state=ipaws_config['state'],
                    location_county=ipaws_config['county'],
                    logger=self.logger
                )
                self.logger.info("✓ IPAWS All-Hazards poller initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize IPAWS poller: {e}")

        # Statistics tracking
        self.stats = {
            'noaa_fetched': 0,
            'ipaws_fetched': 0,
            'duplicates_removed': 0,
            'total_saved': 0,
            'errors': 0
        }

    def poll_all_sources(self) -> Dict[str, List[Dict]]:
        """
        Poll all enabled alert sources

        Returns:
            Dict with alerts from each source:
            {
                'noaa': [...],
                'ipaws': [...]
            }
        """
        results = {
            'noaa': [],
            'ipaws': []
        }

        # Poll NOAA (weather alerts)
        if self.noaa_poller:
            try:
                self.logger.info("Polling NOAA Weather API...")
                noaa_alerts = self.noaa_poller.fetch_cap_alerts()
                results['noaa'] = noaa_alerts
                self.stats['noaa_fetched'] = len(noaa_alerts)
                self.logger.info(f"✓ NOAA: {len(noaa_alerts)} alerts fetched")
            except Exception as e:
                self.logger.error(f"NOAA polling failed: {e}", exc_info=True)
                self.stats['errors'] += 1

        # Poll IPAWS (all-hazards alerts)
        if self.ipaws_poller:
            try:
                self.logger.info("Polling IPAWS All-Hazards Feed...")
                ipaws_alerts = self.ipaws_poller.fetch_ipaws_alerts()
                results['ipaws'] = ipaws_alerts
                self.stats['ipaws_fetched'] = len(ipaws_alerts)
                self.logger.info(f"✓ IPAWS: {len(ipaws_alerts)} alerts fetched")
            except Exception as e:
                self.logger.error(f"IPAWS polling failed: {e}", exc_info=True)
                self.stats['errors'] += 1

        return results

    def deduplicate_alerts(self, alerts_by_source: Dict[str, List[Dict]]) -> List[Dict]:
        """
        Deduplicate alerts across sources

        Strategy:
        1. Collect all alerts
        2. Group by identifier
        3. If duplicate exists, prefer IPAWS (more authoritative for local events)

        Args:
            alerts_by_source: Dict of alerts by source

        Returns:
            Deduplicated list of alerts
        """
        # Flatten all alerts with source tags
        all_alerts = []
        for source, alerts in alerts_by_source.items():
            for alert in alerts:
                # Ensure source is tagged in properties
                if isinstance(alert, dict) and 'properties' in alert:
                    # This is a GeoJSON feature
                    props = alert['properties']
                    if 'source' not in props:
                        props['source'] = source
                all_alerts.append(alert)

        # Build identifier map
        alert_map = {}
        for alert in all_alerts:
            # Handle GeoJSON features
            if isinstance(alert, dict) and 'properties' in alert:
                identifier = alert['properties'].get('identifier')
                source = alert['properties'].get('source', 'unknown')
            else:
                # Direct alert dict
                identifier = alert.get('identifier')
                source = alert.get('source', 'unknown')

            if not identifier:
                continue

            if identifier in alert_map:
                # Duplicate found - apply priority
                existing_source = None
                if isinstance(alert_map[identifier], dict) and 'properties' in alert_map[identifier]:
                    existing_source = alert_map[identifier]['properties'].get('source')
                else:
                    existing_source = alert_map[identifier].get('source')

                # IPAWS takes priority over NOAA for same alert
                if source == 'ipaws' and existing_source == 'noaa':
                    self.logger.info(f"Dedup: Preferring IPAWS over NOAA for {identifier}")
                    alert_map[identifier] = alert
                    self.stats['duplicates_removed'] += 1
                elif source == 'noaa' and existing_source == 'ipaws':
                    self.logger.info(f"Dedup: Keeping IPAWS over NOAA for {identifier}")
                    self.stats['duplicates_removed'] += 1
                else:
                    self.logger.debug(f"Dedup: Keeping first occurrence for {identifier}")
            else:
                alert_map[identifier] = alert

        unique_alerts = list(alert_map.values())
        self.logger.info(
            f"Deduplication: {len(all_alerts)} total → {len(unique_alerts)} unique "
            f"({self.stats['duplicates_removed']} duplicates removed)"
        )

        return unique_alerts

    def process_and_save_alerts(self, alerts: List[Dict]) -> int:
        """
        Process and save alerts to database using existing CAPPoller logic

        Args:
            alerts: List of alerts to save

        Returns:
            Number of alerts saved
        """
        saved_count = 0

        for alert in alerts:
            try:
                # Use NOAA poller's save logic (works for both sources)
                if self.noaa_poller:
                    # Extract properties from GeoJSON feature if needed
                    if isinstance(alert, dict) and 'properties' in alert:
                        # Convert GeoJSON feature to flat alert dict
                        alert_dict = dict(alert['properties'])
                        alert_dict['_geometry_data'] = alert.get('geometry')
                    else:
                        alert_dict = alert

                    # Save alert
                    is_new, saved_alert = self.noaa_poller.save_cap_alert(alert_dict)
                    if saved_alert:
                        saved_count += 1
                        status = "NEW" if is_new else "UPDATED"
                        source = getattr(saved_alert, 'source', 'unknown')
                        self.logger.info(
                            f"✓ {status} ({source.upper()}): {saved_alert.event} - {saved_alert.identifier}"
                        )

            except Exception as e:
                self.logger.error(f"Failed to save alert: {e}", exc_info=True)
                self.stats['errors'] += 1

        self.stats['total_saved'] = saved_count
        return saved_count

    def poll_and_process(self) -> Dict[str, Any]:
        """
        Main polling workflow: fetch, deduplicate, and save

        Returns:
            Statistics dict with polling results
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting Unified Multi-Source Poll")
        self.logger.info("=" * 60)

        start_time = time.time()

        # Reset stats
        self.stats = {
            'noaa_fetched': 0,
            'ipaws_fetched': 0,
            'duplicates_removed': 0,
            'total_saved': 0,
            'errors': 0
        }

        # Poll all sources
        alerts_by_source = self.poll_all_sources()

        # Deduplicate
        unique_alerts = self.deduplicate_alerts(alerts_by_source)

        # Save to database
        saved_count = self.process_and_save_alerts(unique_alerts)

        execution_time_ms = int((time.time() - start_time) * 1000)

        self.logger.info("=" * 60)
        self.logger.info("Poll Summary:")
        self.logger.info(f"  NOAA fetched:      {self.stats['noaa_fetched']}")
        self.logger.info(f"  IPAWS fetched:     {self.stats['ipaws_fetched']}")
        self.logger.info(f"  Duplicates removed: {self.stats['duplicates_removed']}")
        self.logger.info(f"  Alerts saved:      {self.stats['total_saved']}")
        self.logger.info(f"  Errors:            {self.stats['errors']}")
        self.logger.info(f"  Execution time:    {execution_time_ms}ms")
        self.logger.info("=" * 60)

        return {
            **self.stats,
            'execution_time_ms': execution_time_ms,
            'timestamp': datetime.utcnow().isoformat()
        }


def main():
    """Main entry point for unified polling service"""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # Load configuration
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL not configured")
        sys.exit(1)

    noaa_enabled = os.getenv('NOAA_ENABLED', 'true').lower() == 'true'
    ipaws_enabled = os.getenv('IPAWS_ENABLED', 'false').lower() == 'true'

    ipaws_config = None
    if ipaws_enabled:
        ipaws_endpoint = os.getenv('IPAWS_ENDPOINT')
        ipaws_pin = os.getenv('IPAWS_PIN')
        location_fips = os.getenv('LOCATION_FIPS_CODE', '039137')
        location_state = os.getenv('DEFAULT_STATE_CODE', 'OH')
        location_county = os.getenv('DEFAULT_COUNTY_NAME', 'Putnam County')

        if not ipaws_endpoint or not ipaws_pin:
            logger.warning("IPAWS enabled but IPAWS_ENDPOINT or IPAWS_PIN not configured")
            logger.warning("Set IPAWS_ENABLED=false or configure IPAWS credentials")
            ipaws_enabled = False
        else:
            ipaws_config = {
                'endpoint': ipaws_endpoint,
                'pin': ipaws_pin,
                'fips': location_fips,
                'state': location_state,
                'county': location_county
            }

    # Initialize unified poller
    poller = UnifiedAlertPoller(
        database_url=database_url,
        noaa_enabled=noaa_enabled,
        ipaws_enabled=ipaws_enabled,
        ipaws_config=ipaws_config,
        led_sign_ip=os.getenv('LED_SIGN_IP'),
        led_sign_port=int(os.getenv('LED_SIGN_PORT', '10001')),
        logger=logger
    )

    # Run single poll or continuous loop
    poll_interval = int(os.getenv('POLL_INTERVAL_SEC', '180'))

    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        # Single poll
        poller.poll_and_process()
    else:
        # Continuous polling
        logger.info(f"Starting continuous polling (interval: {poll_interval}s)")
        logger.info("Press Ctrl+C to stop")

        while True:
            try:
                poller.poll_and_process()
                logger.info(f"Sleeping for {poll_interval} seconds...")
                time.sleep(poll_interval)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Polling loop error: {e}", exc_info=True)
                time.sleep(poll_interval)


if __name__ == '__main__':
    main()
