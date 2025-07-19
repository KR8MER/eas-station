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
    """NOAA CAP Alert Polling Service for OHZ016 zone"""

    def __init__(self, database_url=None):
        self.logger = logging.getLogger(__name__)
        
        # Configure requests session
        self.session = requests.Session()
        self.session.timeout = 30
        self.session.headers.update({
            'User-Agent': 'NOAA-CAP-Alert-System/1.0 (Emergency Management System)'
        })

        # API endpoint for OHZ016 (your specific zone)
        self.api_url = "https://api.weather.gov/alerts/active?zone=OHZ013"
        
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

    def fetch_cap_alerts(self) -> List[Dict]:
        """Fetch CAP alerts from NOAA API for OHZ016 zone"""
        try:
            self.logger.info(f"Fetching CAP alerts from: {self.api_url}")

            response = self.session.get(self.api_url)
            response.raise_for_status()

            alerts_data = response.json()
            features = alerts_data.get('features', [])

            self.logger.info(f"Retrieved {len(features)} alerts for OHZ016 zone")
            return features

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching CAP alerts: {str(e)}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing CAP alerts JSON: {str(e)}")
            raise

    def parse_cap_alert(self, alert_data: Dict) -> Optional[Dict]:
        """Parse CAP alert data into database format"""
        try:
            properties = alert_data.get('properties', {})
            geometry = alert_data.get('geometry')

            # Extract required fields
            identifier = properties.get('identifier')
            if not identifier:
                self.logger.warning("Alert missing identifier, skipping")
                return None

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

            self.logger.debug(f"Parsed alert: {identifier} - {parsed_alert['event']}")
            return parsed_alert

        except Exception as e:
            self.logger.error(f"Error parsing CAP alert: {str(e)}")
            return None

    def save_cap_alert(self, alert_data: Dict) -> Tuple[bool, Optional[CAPAlert]]:
        """Save CAP alert to database"""
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

                # Update geometry if provided
                if alert_data.get('geometry'):
                    existing.geom = ST_GeomFromGeoJSON(json.dumps(alert_data['geometry']))

                self.db_session.commit()
                self.logger.debug(f"Updated existing alert: {existing.identifier}")
                return False, existing  # Updated, not new

            else:
                # Create new alert
                new_alert = CAPAlert(**{k: v for k, v in alert_data.items() if k != 'geometry'})

                # Add geometry if provided
                if alert_data.get('geometry'):
                    new_alert.geom = ST_GeomFromGeoJSON(json.dumps(alert_data['geometry']))

                self.db_session.add(new_alert)
                self.db_session.commit()
                self.logger.info(f"Saved new alert: {new_alert.identifier} - {new_alert.event}")
                return True, new_alert  # New alert

        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Error saving CAP alert: {str(e)}")
            raise

    def process_intersections(self, alert: CAPAlert):
        """Process intersections between alert and boundaries"""
        try:
            if not alert.geom:
                self.logger.debug(f"Alert {alert.identifier} has no geometry, skipping intersections")
                return

            # Find intersecting boundaries
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
            'execution_time_ms': 0,
            'status': 'SUCCESS',
            'error_message': None,
            'zone': 'OHZ016'
        }

        try:
            self.logger.info("Starting CAP alert polling cycle for OHZ016")

            # Fetch alerts from NOAA for OHZ016
            alerts_data = self.fetch_cap_alerts()
            stats['alerts_fetched'] = len(alerts_data)

            # Process each alert
            for alert_data in alerts_data:
                parsed_alert = self.parse_cap_alert(alert_data)
                if parsed_alert:
                    is_new, alert = self.save_cap_alert(parsed_alert)

                    if is_new:
                        stats['alerts_new'] += 1
                        # Process intersections for new alerts
                        self.process_intersections(alert)
                    else:
                        stats['alerts_updated'] += 1

            # Cleanup expired alerts
            self.cleanup_expired_alerts()

            # Calculate execution time
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.info(f"OHZ016 polling cycle completed: {stats['alerts_new']} new, {stats['alerts_updated']} updated")

            # Log successful poll
            self.log_system_event('INFO', f'CAP polling successful: {stats["alerts_new"]} new alerts', stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.error(f"Error in OHZ016 polling cycle: {str(e)}")
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
    parser = argparse.ArgumentParser(description='NOAA CAP Alert Poller for OHZ016')
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
    logger.info(f"Starting NOAA CAP Alert Poller for zone OHZ016")

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