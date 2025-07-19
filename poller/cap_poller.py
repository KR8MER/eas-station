#!/usr/bin/env python3
"""
NOAA CAP Alert Poller Service
Fetches CAP alerts from NOAA API for OHZ016 zone and processes them
"""

import requests
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from geoalchemy2.functions import ST_GeomFromGeoJSON, ST_Intersects, ST_Area
import time
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import CAPAlert, Boundary, SystemLog, Intersection, db


class CAPPoller:
    """NOAA CAP Alert Polling Service for OHZ016 zone (Putnam County, OH)"""

    def __init__(self, database_url=None):
        self.logger = logging.getLogger(__name__)

        # Configure requests session
        self.session = requests.Session()
        self.session.timeout = 30
        self.session.headers.update({
            'User-Agent': 'NOAA-CAP-Alert-System/1.0 (Emergency Management System)'
        })

        # Database setup
        if database_url:
            self.engine = create_engine(database_url)
            Session = sessionmaker(bind=self.engine)
            self.db_session = Session()
        else:
            # Use Flask app context
            from app import app
            self.app = app
            self.db_session = db.session

    def is_relevant_alert(self, alert_data: Dict) -> bool:
        """Check if alert is relevant to Putnam County, Ohio"""
        try:
            properties = alert_data.get('properties', {})

            # Safe extraction of data
            area_desc = str(properties.get('areaDesc') or '').upper()
            geocode = properties.get('geocode', {})
            ugc_codes = geocode.get('UGC', []) or []
            event = str(properties.get('event') or '').lower()

            self.logger.debug(f"Checking alert: {event}")
            self.logger.debug(f"  UGC codes: {ugc_codes}")
            self.logger.debug(f"  Area contains PUTNAM: {'PUTNAM' in area_desc}")

            # Check for our specific zones
            our_zones = ['OHZ016', 'OHC137']
            for zone in our_zones:
                if zone in ugc_codes:
                    self.logger.info(f"Alert {event} affects our zone {zone}")
                    return True

            # Check area description for Putnam County
            if 'PUTNAM' in area_desc:
                self.logger.info(f"Alert {event} mentions Putnam County")
                return True

            # Check for our zones in area description
            for zone in our_zones:
                if zone in area_desc:
                    self.logger.info(f"Alert {event} mentions zone {zone}")
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error in is_relevant_alert: {e}")
            return True  # Include on error to be safe

    def fetch_cap_alerts(self) -> List[Dict]:
        """Fetch CAP alerts from NOAA API for OHZ016 and related zones"""
        all_alerts = []

        # Multiple endpoints to check
        endpoints = [
            "https://api.weather.gov/alerts/active?zone=OHZ016",  # Putnam County Zone
            "https://api.weather.gov/alerts/active?zone=OHC137",  # Putnam County Code
        ]

        for endpoint in endpoints:
            try:
                self.logger.info(f"Fetching CAP alerts from: {endpoint}")

                response = self.session.get(endpoint)
                response.raise_for_status()

                alerts_data = response.json()
                features = alerts_data.get('features', [])

                self.logger.info(f"Retrieved {len(features)} alerts from endpoint")

                # Add all features, we'll filter them later
                all_alerts.extend(features)

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Error fetching CAP alerts from {endpoint}: {str(e)}")
                continue
            except json.JSONDecodeError as e:
                self.logger.error(f"Error parsing CAP alerts JSON from {endpoint}: {str(e)}")
                continue

        # Remove duplicates based on identifier - handle None identifiers
        seen_ids = set()
        unique_alerts = []
        for alert in all_alerts:
            alert_id = alert.get('properties', {}).get('identifier')
            if alert_id:  # Only check for duplicates if identifier exists
                if alert_id not in seen_ids:
                    seen_ids.add(alert_id)
                    unique_alerts.append(alert)
                else:
                    self.logger.debug(f"Skipping duplicate alert: {alert_id}")
            else:
                # If no identifier, include the alert anyway
                self.logger.warning(f"Alert has no identifier, including anyway")
                unique_alerts.append(alert)

        self.logger.info(f"Total unique alerts collected: {len(unique_alerts)}")

        # Debug: log what we collected
        for alert in unique_alerts:
            props = alert.get('properties', {})
            event = props.get('event', 'Unknown')
            alert_id = props.get('identifier', 'No ID')
            self.logger.info(f"Collected alert: {event} (ID: {alert_id[:20] if alert_id != 'No ID' else 'No ID'}...)")

        return unique_alerts

    def parse_cap_alert(self, alert_data: Dict) -> Optional[Dict]:
        """Parse CAP alert data into database format"""
        try:
            properties = alert_data.get('properties', {})
            geometry = alert_data.get('geometry')

            # Extract identifier - generate one if missing
            identifier = properties.get('identifier')
            if not identifier:
                # Generate a temporary identifier for alerts without one
                import hashlib
                import time
                event = properties.get('event', 'Unknown')
                sent = properties.get('sent', str(time.time()))
                temp_id = f"temp_{hashlib.md5((event + sent).encode()).hexdigest()[:16]}"
                identifier = temp_id
                self.logger.info(f"Generated temporary identifier for {event}: {identifier}")

            # Parse datetime fields
            sent_str = properties.get('sent')
            expires_str = properties.get('expires')

            sent = None
            expires = None

            if sent_str:
                try:
                    # Handle different datetime formats
                    if sent_str.endswith('Z'):
                        sent = datetime.fromisoformat(sent_str.replace('Z', '+00:00'))
                    else:
                        sent = datetime.fromisoformat(sent_str)
                except ValueError as e:
                    self.logger.warning(f"Invalid sent timestamp: {sent_str} - {e}")

            if expires_str:
                try:
                    # Handle different datetime formats
                    if expires_str.endswith('Z'):
                        expires = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                    else:
                        expires = datetime.fromisoformat(expires_str)
                except ValueError as e:
                    self.logger.warning(f"Invalid expires timestamp: {expires_str} - {e}")

            # Extract area description from multiple possible fields
            area_desc = (properties.get('areaDesc') or
                         properties.get('areas') or
                         properties.get('geocode', {}).get('UGC', [''])[0] or
                         'OHZ016')

            # Build parsed alert data
            parsed_alert = {
                'identifier': identifier,
                'sent': sent,
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
                'geometry': geometry,
                'raw_json': alert_data
            }

            self.logger.info(f"Successfully parsed alert: {identifier} - {parsed_alert['event']}")
            return parsed_alert

        except Exception as e:
            self.logger.error(f"Error parsing CAP alert: {str(e)}")
            return None

    def save_cap_alert(self, alert_data: Dict) -> Tuple[bool, Optional[CAPAlert]]:
        """Save CAP alert to database - handles null geometry"""
        try:
            # Check if alert already exists
            existing = self.db_session.query(CAPAlert).filter_by(
                identifier=alert_data['identifier']
            ).first()

            if existing:
                # Update existing alert
                for key, value in alert_data.items():
                    if key != 'geometry':
                        setattr(existing, key, value)

                # Update geometry if provided and not null
                if alert_data.get('geometry'):
                    existing.geom = ST_GeomFromGeoJSON(json.dumps(alert_data['geometry']))
                else:
                    # For null geometry, set to None
                    existing.geom = None

                self.db_session.commit()
                self.logger.debug(f"Updated existing alert: {existing.identifier}")
                return False, existing

            else:
                # Create new alert
                new_alert = CAPAlert(**{k: v for k, v in alert_data.items() if k != 'geometry'})

                # Add geometry if provided and not null
                if alert_data.get('geometry'):
                    new_alert.geom = ST_GeomFromGeoJSON(json.dumps(alert_data['geometry']))
                else:
                    # For null geometry, leave as None
                    new_alert.geom = None

                self.db_session.add(new_alert)
                self.db_session.commit()
                self.logger.info(f"Saved new alert: {new_alert.identifier} - {new_alert.event}")
                return True, new_alert

        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Error saving CAP alert: {str(e)}")
            raise

    def process_intersections(self, alert: CAPAlert):
        """Process intersections between alert and boundaries"""
        try:
            if not alert.geom:
                self.logger.info(
                    f"Alert {alert.identifier} ({alert.event}) has no geometry - using zone-based intersection")

                # For alerts without geometry (like Special Weather Statements),
                # create intersections based on zone codes
                if alert.event and ('special weather statement' in alert.event.lower() or
                                    'advisory' in alert.event.lower() or
                                    'warning' in alert.event.lower()):

                    # Find all boundaries in Putnam County for general intersection
                    county_boundaries = self.db_session.query(Boundary).filter(
                        Boundary.name.ilike('%putnam%')
                    ).all()

                    for boundary in county_boundaries:
                        # Check if intersection already exists
                        existing = self.db_session.query(Intersection).filter_by(
                            cap_alert_id=alert.id,
                            boundary_id=boundary.id
                        ).first()

                        if not existing:
                            intersection = Intersection(
                                cap_alert_id=alert.id,
                                boundary_id=boundary.id,
                                intersection_area=0  # No area calculation for zone-based
                            )
                            self.db_session.add(intersection)
                            self.logger.info(
                                f"Created zone-based intersection: {alert.event} -> {boundary.type} '{boundary.name}'")

                self.db_session.commit()
                return

            # Normal geometry-based intersection processing
            intersecting_boundaries = self.db_session.query(Boundary).filter(
                ST_Intersects(Boundary.geom, alert.geom)
            ).all()

            self.logger.info(f"Alert {alert.identifier} intersects with {len(intersecting_boundaries)} boundaries")

            for boundary in intersecting_boundaries:
                # Check if intersection already exists
                existing_intersection = self.db_session.query(Intersection).filter_by(
                    cap_alert_id=alert.id,
                    boundary_id=boundary.id
                ).first()

                if existing_intersection:
                    continue

                # Calculate intersection area (optional)
                try:
                    intersection_area = self.db_session.scalar(
                        text("""
                             SELECT ST_Area(ST_Intersection(
                                     ST_Transform(b.geom, 3857),
                                     ST_Transform(a.geom, 3857)
                                            )) as area
                             FROM boundaries b,
                                  cap_alerts a
                             WHERE b.id = :boundary_id
                               AND a.id = :alert_id
                             """),
                        {'boundary_id': boundary.id, 'alert_id': alert.id}
                    )
                except Exception as e:
                    self.logger.warning(f"Could not calculate intersection area: {e}")
                    intersection_area = 0

                # Save intersection record
                intersection = Intersection(
                    cap_alert_id=alert.id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_area or 0
                )

                self.db_session.add(intersection)

                self.logger.info(f"Alert {alert.identifier} intersects with {boundary.type} boundary '{boundary.name}'")

            self.db_session.commit()

        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Error processing intersections: {str(e)}")

    def cleanup_expired_alerts(self):
        """Remove expired alerts from database"""
        try:
            now = datetime.utcnow()

            # Find expired alerts
            expired_alerts = self.db_session.query(CAPAlert).filter(
                CAPAlert.expires < now
            ).all()

            count = len(expired_alerts)
            if count > 0:
                # Delete expired alerts (intersections will be deleted via cascade)
                for alert in expired_alerts:
                    self.db_session.delete(alert)

                self.db_session.commit()
                self.logger.info(f"Cleaned up {count} expired alerts")

        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Error cleaning up expired alerts: {str(e)}")

    def log_system_event(self, level: str, message: str, details: Dict = None):
        """Log system event to database"""
        try:
            log_entry = SystemLog(
                level=level,
                message=message,
                module='cap_poller',
                details=details
            )
            self.db_session.add(log_entry)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"Error logging system event: {str(e)}")

    def poll_and_process(self) -> Dict:
        """Main polling and processing function"""
        start_time = time.time()
        stats = {
            'alerts_fetched': 0,
            'alerts_new': 0,
            'alerts_updated': 0,
            'alerts_filtered': 0,
            'execution_time_ms': 0,
            'status': 'SUCCESS',
            'error_message': None,
            'zone': 'OHZ016/OHC137 (Putnam County, OH)'
        }

        try:
            self.logger.info("Starting CAP alert polling cycle for Putnam County, OH (OHZ016/OHC137)")

            # Fetch alerts from NOAA for OHZ016 and OHC137
            alerts_data = self.fetch_cap_alerts()
            stats['alerts_fetched'] = len(alerts_data)

            # Process each alert
            for alert_data in alerts_data:
                props = alert_data.get('properties', {})
                event = props.get('event', 'Unknown')
                alert_id = props.get('identifier', 'No ID')

                self.logger.info(
                    f"Processing alert: {event} (ID: {alert_id[:20] if alert_id != 'No ID' else 'No ID'}...)")

                # Check if alert is relevant to our area
                if not self.is_relevant_alert(alert_data):
                    self.logger.info(f"Alert {event} filtered out - not relevant to our area")
                    stats['alerts_filtered'] += 1
                    continue

                self.logger.info(f"Alert {event} passed relevance check - processing...")

                parsed_alert = self.parse_cap_alert(alert_data)
                if parsed_alert:
                    is_new, alert = self.save_cap_alert(parsed_alert)

                    if is_new:
                        stats['alerts_new'] += 1
                        self.logger.info(f"Saved new alert: {alert.event}")
                        # Process intersections for new alerts
                        self.process_intersections(alert)
                    else:
                        stats['alerts_updated'] += 1
                        self.logger.info(f"Updated existing alert: {alert.event}")
                else:
                    self.logger.warning(f"Failed to parse alert: {event}")

            # Cleanup expired alerts
            self.cleanup_expired_alerts()

            # Calculate execution time
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.info(
                f"Putnam County polling cycle completed: {stats['alerts_new']} new, {stats['alerts_updated']} updated, {stats['alerts_filtered']} filtered")

            # Log successful poll
            self.log_system_event('INFO', f'CAP polling successful: {stats["alerts_new"]} new alerts', stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.error(f"Error in Putnam County polling cycle: {str(e)}")
            self.log_system_event('ERROR', f'CAP polling failed: {str(e)}', stats)

        return stats

    def close(self):
        """Close database connections"""
        if hasattr(self, 'db_session') and hasattr(self.db_session, 'close'):
            self.db_session.close()
        if hasattr(self, 'session'):
            self.session.close()


def main():
    """Main entry point for running poller standalone"""
    import argparse

    # Setup argument parser
    parser = argparse.ArgumentParser(description='NOAA CAP Alert Poller for Putnam County, OH (OHZ016/OHC137)')
    parser.add_argument('--database-url',
                        default='postgresql://noaa_user:rkhkeq@localhost:5432/noaa_alerts',
                        help='Database connection URL')
    parser.add_argument('--log-level',
                        default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging level')
    parser.add_argument('--continuous',
                        action='store_true',
                        help='Run continuously every 5 minutes')
    parser.add_argument('--interval',
                        type=int,
                        default=300,
                        help='Polling interval in seconds (default: 300)')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/home/pi/noaa_alerts_system/logs/cap_poller.log')
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Starting NOAA CAP Alert Poller for Putnam County, OH (OHZ016/OHC137)")

    # Create poller
    poller = CAPPoller(args.database_url)

    try:
        if args.continuous:
            logger.info(f"Running continuously with {args.interval} second intervals")
            while True:
                try:
                    stats = poller.poll_and_process()
                    logger.info(f"Poll completed: {json.dumps(stats, indent=2)}")
                    time.sleep(args.interval)
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal, shutting down")
                    break
                except Exception as e:
                    logger.error(f"Error in continuous polling: {e}")
                    time.sleep(60)  # Wait 1 minute before retrying
        else:
            # Single poll
            stats = poller.poll_and_process()
            print(f"Polling completed: {json.dumps(stats, indent=2)}")

    finally:
        poller.close()


if __name__ == '__main__':
    main()