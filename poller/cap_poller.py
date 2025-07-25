#!/usr/bin/env python3
"""
Enhanced NOAA CAP Alert Poller for Putnam County, OH (OHZ016/OHC137)
Includes LED sign integration for alert display
"""

import os
import sys
import time
import json
import requests
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List
import argparse
import pytz
from sqlalchemy import create_engine, text, func, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

# Configure timezone
UTC_TZ = pytz.UTC
PUTNAM_COUNTY_TZ = pytz.timezone('America/New_York')


def utc_now():
    """Get current UTC time"""
    return datetime.now(UTC_TZ)


def local_now():
    """Get current local time"""
    return datetime.now(PUTNAM_COUNTY_TZ)


def parse_nws_datetime(dt_string):
    """Parse NWS datetime string with timezone handling"""
    if not dt_string:
        return None

    try:
        # Handle different datetime formats from NWS
        for fmt in [
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ'
        ]:
            try:
                if dt_string.endswith('Z'):
                    dt_string = dt_string[:-1] + '+00:00'
                dt = datetime.strptime(dt_string, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC_TZ)
                return dt.astimezone(UTC_TZ)
            except ValueError:
                continue
    except Exception as e:
        logging.warning(f"Could not parse datetime: {dt_string} - {e}")

    return None


def format_local_datetime(dt, include_utc=True):
    """Format datetime in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    local_str = local_dt.strftime('%B %d, %Y at %I:%M %p %Z')
    if include_utc:
        utc_str = dt.astimezone(UTC_TZ).strftime('%H:%M UTC')
        return f"{local_str} ({utc_str})"
    return local_str


# Add the parent directory to the path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Try to import from existing app structure
try:
    # Import from Flask app if available
    import sys
    import os

    # Add the project root to path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root.endswith('/poller'):
        project_root = os.path.dirname(project_root)
    sys.path.insert(0, project_root)

    # Try to import the main app to get access to existing models
    from app import db, CAPAlert, SystemLog

    # Define missing models that might not be in the main app yet
    from sqlalchemy import Column, Integer, String, DateTime, Text, JSON


    class PollHistory(db.Model):
        __tablename__ = 'poll_history'

        id = Column(Integer, primary_key=True)
        timestamp = Column(DateTime, default=utc_now)
        alerts_fetched = Column(Integer, default=0)
        alerts_new = Column(Integer, default=0)
        alerts_updated = Column(Integer, default=0)
        execution_time_ms = Column(Integer)
        status = Column(String(20))
        error_message = Column(Text)


    FLASK_MODELS_AVAILABLE = True
    USE_EXISTING_DB = True

except ImportError as e:
    print(f"Warning: Could not import from main app: {e}")
    print("Will attempt to connect to existing database directly")
    FLASK_MODELS_AVAILABLE = False
    USE_EXISTING_DB = True

# Try to import LED controller
try:
    from led_sign_controller import LEDSignController

    LED_AVAILABLE = True
except ImportError:
    LED_AVAILABLE = False
    print("Warning: LED sign controller not available")

    # Fallback: Direct database connection without models
if not FLASK_MODELS_AVAILABLE:
    from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, Float, ForeignKey
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import relationship

    # Create base but don't create tables - use existing ones
    Base = declarative_base()


    class CAPAlert(Base):
        __tablename__ = 'cap_alerts'

        id = Column(Integer, primary_key=True)
        identifier = Column(String(255), unique=True, nullable=False)
        sent = Column(DateTime, nullable=False)
        expires = Column(DateTime)
        status = Column(String(50))
        message_type = Column(String(50))
        scope = Column(String(50))
        category = Column(String(50))
        event = Column(String(100))
        urgency = Column(String(50))
        severity = Column(String(50))
        certainty = Column(String(50))
        area_desc = Column(Text)
        headline = Column(Text)
        description = Column(Text)
        instruction = Column(Text)
        # Remove geometry column reference for now
        raw_json = Column(JSON)
        created_at = Column(DateTime, default=utc_now)
        updated_at = Column(DateTime, default=utc_now)


    class SystemLog(Base):
        __tablename__ = 'system_logs'

        id = Column(Integer, primary_key=True)
        timestamp = Column(DateTime, default=utc_now)
        level = Column(String(20))
        message = Column(Text)
        module = Column(String(50))
        details = Column(JSON)


    class PollHistory(Base):
        __tablename__ = 'poll_history'

        id = Column(Integer, primary_key=True)
        timestamp = Column(DateTime, default=utc_now)
        alerts_fetched = Column(Integer, default=0)
        alerts_new = Column(Integer, default=0)
        alerts_updated = Column(Integer, default=0)
        execution_time_ms = Column(Integer)
        status = Column(String(20))
        error_message = Column(Text)


class CAPPoller:
    """Enhanced CAP alert poller with LED sign integration"""

    def __init__(self, database_url: str, led_sign_ip: str = None, led_sign_port: int = 10001):
        """
        Initialize CAP poller with LED sign support

        Args:
            database_url: PostgreSQL database connection string
            led_sign_ip: IP address of the LED sign (optional)
            led_sign_port: Port for LED sign communication (default 10001)
        """
        self.database_url = database_url
        self.led_sign_ip = led_sign_ip
        self.led_sign_port = led_sign_port

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Setup database connection
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=3600)
        Session = sessionmaker(bind=self.engine)
        self.db_session = Session()

        # DON'T create tables - use existing database structure
        # Tables should already exist from the main Flask app

        # Verify required tables exist
        try:
            # Simple test query to ensure tables exist
            self.db_session.execute(text("SELECT 1 FROM cap_alerts LIMIT 1"))
            self.db_session.execute(text("SELECT 1 FROM system_logs LIMIT 1"))
            self.logger.info("Database tables verified successfully")
        except Exception as e:
            self.logger.warning(f"Database table verification failed: {e}")
            # Continue anyway - tables might be empty but exist

        # Setup HTTP session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NOAA CAP Alert System/1.0 (Putnam County, OH Emergency Management)'
        })

        # Initialize LED sign controller if IP is provided and available
        self.led_controller = None
        if led_sign_ip and LED_AVAILABLE:
            try:
                self.led_controller = LEDSignController(led_sign_ip, led_sign_port)
                self.logger.info(f"LED sign controller initialized for {led_sign_ip}:{led_sign_port}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LED controller: {e}")
        elif led_sign_ip:
            self.logger.warning("LED sign IP provided but controller not available")

        # CAP alert endpoints
        self.cap_endpoints = [
            'https://api.weather.gov/alerts/active?zone=OHZ016',  # Putnam County Zone
            'https://api.weather.gov/alerts/active?area=OHC137',  # All Ohio alerts (we'll filter)
        ]

        # Area filters for relevance checking
        self.area_filters = [
            'OHZ016',  # Putnam County forecast zone
            'OHC137',  # Putnam County FIPS code
            'PUTNAM',  # County name
            'COLUMBUS',  # Major nearby city
            'FINDLAY',  # Regional city
            'LIMA',  # Regional city
            'OTTAWA',  # County seat
            'LEIPSIC', 'PANDORA', 'GLANDORF', 'KALIDA', 'FORT JENNINGS'  # Local communities
        ]

    def fetch_cap_alerts(self, timeout: int = 30) -> List[Dict]:
        """Fetch CAP alerts from NOAA with enhanced error handling"""
        unique_alerts = []
        seen_identifiers = set()

        for endpoint in self.cap_endpoints:
            try:
                self.logger.info(f"Fetching alerts from: {endpoint}")

                response = self.session.get(endpoint, timeout=timeout)
                response.raise_for_status()

                data = response.json()
                features = data.get('features', [])

                self.logger.info(f"Retrieved {len(features)} alerts from {endpoint}")

                for alert in features:
                    props = alert.get('properties', {})
                    identifier = props.get('identifier')

                    if identifier and identifier not in seen_identifiers:
                        seen_identifiers.add(identifier)
                        unique_alerts.append(alert)
                    elif not identifier:
                        self.logger.warning("Alert has no identifier, including anyway")
                        unique_alerts.append(alert)

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Error fetching from {endpoint}: {str(e)}")
                continue
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error from {endpoint}: {str(e)}")
                continue
            except Exception as e:
                self.logger.error(f"Unexpected error fetching from {endpoint}: {str(e)}")
                continue

        self.logger.info(f"Total unique alerts collected: {len(unique_alerts)}")
        return unique_alerts

    def is_relevant_alert(self, alert_data: Dict) -> bool:
        """Enhanced relevance checking for alerts"""
        try:
            properties = alert_data.get('properties', {})

            # Check UGC codes
            geocode = properties.get('geocode', {})
            ugc_codes = geocode.get('UGC', [])

            for ugc in ugc_codes:
                if any(area in ugc.upper() for area in ['OHZ016', 'OHC137']):
                    self.logger.debug(f"Alert relevant by UGC code: {ugc}")
                    return True

            # Check area description
            area_desc = properties.get('areaDesc', '').upper()
            if any(area in area_desc for area in self.area_filters):
                self.logger.debug(f"Alert relevant by area description: {area_desc}")
                return True

            # Check event severity - always include severe alerts for nearby areas
            severity = properties.get('severity', '').upper()
            if severity in ['SEVERE', 'EXTREME']:
                # Check if it's in Ohio
                if 'OHIO' in area_desc or any(ugc.startswith('OH') for ugc in ugc_codes):
                    self.logger.debug(f"Severe alert included from Ohio: {severity}")
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking alert relevance: {str(e)}")
            return False

    def parse_cap_alert(self, alert_data: Dict):
        """Parse CAP alert data with enhanced timezone handling"""
        try:
            properties = alert_data.get('properties', {})
            geometry = alert_data.get('geometry')

            # Extract or generate identifier
            identifier = properties.get('identifier')
            if not identifier:
                event = properties.get('event', 'Unknown')
                sent = properties.get('sent', str(time.time()))
                temp_id = f"temp_{hashlib.md5((event + sent).encode()).hexdigest()[:16]}"
                identifier = temp_id
                self.logger.info(f"Generated temporary identifier: {identifier}")

            # Parse timestamps
            sent = parse_nws_datetime(properties.get('sent')) if properties.get('sent') else None
            expires = parse_nws_datetime(properties.get('expires')) if properties.get('expires') else None

            # Check if already expired
            if expires and expires < utc_now():
                self.logger.info(f"Alert {identifier} is already expired")

            # Extract area description
            area_desc = (properties.get('areaDesc') or
                         properties.get('areas') or
                         properties.get('geocode', {}).get('UGC', [''])[0] or
                         'OHZ016')

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
                # Store geometry in raw_json for now since geometry column may not exist
                'raw_json': alert_data
            }

            self.logger.info(f"Successfully parsed alert: {identifier} - {parsed_alert['event']}")
            return parsed_alert

        except Exception as e:
            self.logger.error(f"Error parsing CAP alert: {str(e)}")
            return None

    def save_cap_alert(self, alert_data: Dict):
        """Save CAP alert to database with duplicate detection"""
        try:
            # Check if alert already exists
            existing_alert = self.db_session.query(CAPAlert).filter_by(
                identifier=alert_data['identifier']
            ).first()

            if existing_alert:
                # Update existing alert
                for key, value in alert_data.items():
                    if key != 'raw_json':  # Don't overwrite raw_json unless necessary
                        setattr(existing_alert, key, value)

                existing_alert.updated_at = utc_now()
                self.db_session.commit()

                # Update LED display if this is an active alert
                if self.led_controller and not self.is_alert_expired(existing_alert):
                    self.update_led_display()

                return False, existing_alert
            else:
                # Create new alert
                new_alert = CAPAlert(**alert_data)
                new_alert.created_at = utc_now()
                new_alert.updated_at = utc_now()

                self.db_session.add(new_alert)
                self.db_session.commit()

                # Update LED display for new active alerts
                if self.led_controller and not self.is_alert_expired(new_alert):
                    self.update_led_display()

                return True, new_alert

        except SQLAlchemyError as e:
            self.logger.error(f"Database error saving alert: {str(e)}")
            self.db_session.rollback()
            return False, None
        except Exception as e:
            self.logger.error(f"Error saving CAP alert: {str(e)}")
            return False, None

    def is_alert_expired(self, alert) -> bool:
        """Check if an alert is expired"""
        if not hasattr(alert, 'expires') or not alert.expires:
            return False
        return alert.expires < utc_now()

    def update_led_display(self):
        """Update LED sign with current active alerts"""
        if not self.led_controller:
            return

        try:
            # Get active alerts ordered by severity
            active_alerts = self.db_session.query(CAPAlert).filter(
                or_(
                    CAPAlert.expires.is_(None),
                    CAPAlert.expires > utc_now()
                )
            ).order_by(
                CAPAlert.severity.desc(),
                CAPAlert.sent.desc()
            ).limit(5).all()

            if active_alerts:
                # Display alerts on LED sign
                self.led_controller.display_alerts(active_alerts)
                self.logger.info(f"Updated LED display with {len(active_alerts)} active alerts")
            else:
                # Display default message when no alerts
                self.led_controller.display_default_message()
                self.logger.info("Updated LED display with default message")

        except Exception as e:
            self.logger.error(f"Error updating LED display: {e}")

    def cleanup_old_poll_history(self):
        """Clean up old poll history records (keep alerts forever)"""
        try:
            # Skip if poll_history table doesn't exist
            try:
                # Test if poll_history table exists
                self.db_session.execute(text("SELECT 1 FROM poll_history LIMIT 1"))
            except Exception:
                self.logger.info("poll_history table not available - skipping cleanup")
                return

            # Only clean up poll history, NOT alerts - keep all alerts for historical analysis
            cutoff_date = utc_now() - timedelta(days=30)  # Keep 30 days of poll history

            old_polls_count = self.db_session.query(PollHistory).filter(
                PollHistory.timestamp < cutoff_date
            ).count()

            if old_polls_count > 100:  # Only clean if we have many records
                # Keep the most recent 100 poll records even if older than 30 days
                subquery = self.db_session.query(PollHistory.id).order_by(
                    PollHistory.timestamp.desc()
                ).limit(100).subquery()

                self.db_session.query(PollHistory).filter(
                    PollHistory.timestamp < cutoff_date,
                    ~PollHistory.id.in_(subquery)
                ).delete(synchronize_session=False)

                self.db_session.commit()
                self.logger.info(f"Cleaned up old poll history records (alerts preserved)")

        except Exception as e:
            self.logger.error(f"Error cleaning up poll history: {str(e)}")
            # Rollback any failed transaction
            try:
                self.db_session.rollback()
            except:
                pass

    def log_poll_history(self, stats):
        """Log poll statistics to database for monitoring"""
        try:
            # Skip if poll_history table doesn't exist
            try:
                # Test if poll_history table exists
                self.db_session.execute(text("SELECT 1 FROM poll_history LIMIT 1"))
            except Exception:
                self.logger.info("poll_history table not available - logging to file only")
                return

            poll_record = PollHistory(
                timestamp=utc_now(),
                alerts_fetched=stats.get('alerts_fetched', 0),
                alerts_new=stats.get('alerts_new', 0),
                alerts_updated=stats.get('alerts_updated', 0),
                execution_time_ms=stats.get('execution_time_ms', 0),
                status=stats.get('status', 'UNKNOWN'),
                error_message=stats.get('error_message')
            )
            self.db_session.add(poll_record)
            self.db_session.commit()

        except Exception as e:
            self.logger.error(f"Error logging poll history: {str(e)}")
            # Rollback any failed transaction
            try:
                self.db_session.rollback()
            except:
                pass

    def log_system_event(self, level: str, message: str, details: Dict = None):
        """Log system event to database"""
        try:
            # Skip if system_logs table doesn't exist
            try:
                # Test if system_logs table exists
                self.db_session.execute(text("SELECT 1 FROM system_logs LIMIT 1"))
            except Exception:
                self.logger.info("system_logs table not available - logging to file only")
                return

            if details is None:
                details = {}

            details.update({
                'logged_at_utc': utc_now().isoformat(),
                'logged_at_local': local_now().isoformat(),
                'timezone': str(PUTNAM_COUNTY_TZ)
            })

            log_entry = SystemLog(
                level=level,
                message=message,
                module='cap_poller',
                details=details,
                timestamp=utc_now()
            )
            self.db_session.add(log_entry)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"Error logging system event: {str(e)}")
            # Rollback any failed transaction
            try:
                self.db_session.rollback()
            except:
                pass

    def poll_and_process(self) -> Dict:
        """Main polling function with LED integration"""
        start_time = time.time()
        poll_start_utc = utc_now()
        poll_start_local = local_now()

        stats = {
            'alerts_fetched': 0,
            'alerts_new': 0,
            'alerts_updated': 0,
            'alerts_filtered': 0,
            'execution_time_ms': 0,
            'status': 'SUCCESS',
            'error_message': None,
            'zone': 'OHZ016/OHC137 (Putnam County, OH)',
            'poll_time_utc': poll_start_utc.isoformat(),
            'poll_time_local': poll_start_local.isoformat(),
            'timezone': str(PUTNAM_COUNTY_TZ),
            'led_updated': False
        }

        try:
            self.logger.info(
                f"Starting CAP alert polling cycle for Putnam County, OH at {format_local_datetime(poll_start_utc)}"
            )

            # Fetch alerts
            alerts_data = self.fetch_cap_alerts()
            stats['alerts_fetched'] = len(alerts_data)

            # Process each alert
            for alert_data in alerts_data:
                props = alert_data.get('properties', {})
                event = props.get('event', 'Unknown')
                alert_id = props.get('identifier', 'No ID')

                self.logger.info(
                    f"Processing alert: {event} (ID: {alert_id[:20] if alert_id != 'No ID' else 'No ID'}...)")

                if not self.is_relevant_alert(alert_data):
                    self.logger.info(f"Alert {event} filtered out - not relevant")
                    stats['alerts_filtered'] += 1
                    continue

                self.logger.info(f"Alert {event} passed relevance check - processing...")

                parsed_alert = self.parse_cap_alert(alert_data)
                if parsed_alert:
                    is_new, alert = self.save_cap_alert(parsed_alert)

                    if is_new:
                        stats['alerts_new'] += 1
                        if alert and hasattr(alert, 'sent') and alert.sent:
                            self.logger.info(
                                f"Saved new alert: {alert.event} - Sent: {format_local_datetime(alert.sent)}"
                            )
                        else:
                            self.logger.info(f"Saved new alert: {parsed_alert['event']}")
                        stats['led_updated'] = True
                    else:
                        stats['alerts_updated'] += 1
                        if alert and hasattr(alert, 'sent') and alert.sent:
                            self.logger.info(
                                f"Updated existing alert: {alert.event} - Sent: {format_local_datetime(alert.sent)}"
                            )
                        else:
                            self.logger.info(f"Updated existing alert: {parsed_alert['event']}")
                else:
                    self.logger.warning(f"Failed to parse alert: {event}")

            # Cleanup old poll history (but keep all alerts for historical data)
            self.cleanup_old_poll_history()

            # Log poll statistics
            self.log_poll_history(stats)

            # Update LED display
            if self.led_controller:
                self.update_led_display()
                stats['led_updated'] = True

            # Calculate execution time
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.info(
                f"Polling cycle completed: {stats['alerts_new']} new, {stats['alerts_updated']} updated, {stats['alerts_filtered']} filtered"
            )

            # Log successful poll
            self.log_system_event('INFO', f'CAP polling successful: {stats["alerts_new"]} new alerts', stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.error(f"Error in polling cycle: {str(e)}")
            self.log_system_event('ERROR', f'CAP polling failed: {str(e)}', stats)

        return stats

    def close(self):
        """Close connections"""
        if hasattr(self, 'db_session'):
            self.db_session.close()
        if hasattr(self, 'session'):
            self.session.close()
        if self.led_controller:
            self.led_controller.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='NOAA CAP Alert Poller with LED Sign Integration')
    parser.add_argument('--database-url',
                        default='postgresql://noaa_user:rkhkeq@localhost:5432/noaa_alerts',
                        help='Database connection URL')
    parser.add_argument('--led-ip',
                        help='LED sign IP address')
    parser.add_argument('--led-port',
                        type=int,
                        default=10001,
                        help='LED sign port (default: 10001)')
    parser.add_argument('--log-level',
                        default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging level')
    parser.add_argument('--continuous',
                        action='store_true',
                        help='Run continuously')
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

    startup_utc = utc_now()
    logger.info(f"Starting NOAA CAP Alert Poller with LED Integration")
    logger.info(f"Startup time: {format_local_datetime(startup_utc)}")
    if args.led_ip:
        logger.info(f"LED Sign: {args.led_ip}:{args.led_port}")

    # Create poller
    poller = CAPPoller(args.database_url, args.led_ip, args.led_port)

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
                    time.sleep(60)
        else:
            stats = poller.poll_and_process()
            print(f"Polling completed: {json.dumps(stats, indent=2)}")

    finally:
        poller.close()


if __name__ == '__main__':
    main()

    """Enhanced CAP alert poller with LED sign integration"""


    def __init__(self, database_url: str, led_sign_ip: str = None, led_sign_port: int = 10001):
        """
        Initialize CAP poller with LED sign support

        Args:
            database_url: PostgreSQL database connection string
            led_sign_ip: IP address of the LED sign (optional)
            led_sign_port: Port for LED sign communication (default 10001)
        """
        self.database_url = database_url
        self.led_sign_ip = led_sign_ip
        self.led_sign_port = led_sign_port

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Setup database connection
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=3600)
        Session = sessionmaker(bind=self.engine)
        self.db_session = Session()

        # Setup HTTP session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'NOAA CAP Alert System/1.0 (Putnam County, OH Emergency Management)'
        })

        # Initialize LED sign controller if IP is provided
        self.led_controller = None
        if led_sign_ip:
            try:
                self.led_controller = LEDSignController(led_sign_ip, led_sign_port)
                self.logger.info(f"LED sign controller initialized for {led_sign_ip}:{led_sign_port}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LED controller: {e}")

        # CAP alert endpoints
        self.cap_endpoints = [
            'https://api.weather.gov/alerts/active?zone=OHZ016',  # Putnam County Zone
            'https://api.weather.gov/alerts/active?area=OH&code=OHC137',  # Putnam County Code
        ]

        # Area filters for relevance checking
        self.area_filters = [
            'OHZ016',  # Putnam County forecast zone
            'OHC137',  # Putnam County FIPS code
            'PUTNAM',  # County name
            'COLUMBUS',  # Major nearby city
            'FINDLAY',  # Regional city
            'LIMA',  # Regional city
            'OTTAWA',  # County seat
            'LEIPSIC', 'PANDORA', 'GLANDORF', 'KALIDA', 'FORT JENNINGS'  # Local communities
        ]


    def fetch_cap_alerts(self, timeout: int = 30) -> List[Dict]:
        """Fetch CAP alerts from NOAA with enhanced error handling"""
        unique_alerts = []
        seen_identifiers = set()

        for endpoint in self.cap_endpoints:
            try:
                self.logger.info(f"Fetching alerts from: {endpoint}")

                response = self.session.get(endpoint, timeout=timeout)
                response.raise_for_status()

                data = response.json()
                features = data.get('features', [])

                self.logger.info(f"Retrieved {len(features)} alerts from {endpoint}")

                for alert in features:
                    props = alert.get('properties', {})
                    identifier = props.get('identifier')

                    if identifier and identifier not in seen_identifiers:
                        seen_identifiers.add(identifier)
                        unique_alerts.append(alert)
                    elif not identifier:
                        self.logger.warning("Alert has no identifier, including anyway")
                        unique_alerts.append(alert)

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Error fetching from {endpoint}: {str(e)}")
                continue
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error from {endpoint}: {str(e)}")
                continue
            except Exception as e:
                self.logger.error(f"Unexpected error fetching from {endpoint}: {str(e)}")
                continue

        self.logger.info(f"Total unique alerts collected: {len(unique_alerts)}")
        return unique_alerts


    def is_relevant_alert(self, alert_data: Dict) -> bool:
        """Enhanced relevance checking for alerts"""
        try:
            properties = alert_data.get('properties', {})

            # Check UGC codes
            geocode = properties.get('geocode', {})
            ugc_codes = geocode.get('UGC', [])

            for ugc in ugc_codes:
                if any(area in ugc.upper() for area in ['OHZ016', 'OHC137']):
                    self.logger.debug(f"Alert relevant by UGC code: {ugc}")
                    return True

            # Check area description
            area_desc = properties.get('areaDesc', '').upper()
            if any(area in area_desc for area in self.area_filters):
                self.logger.debug(f"Alert relevant by area description: {area_desc}")
                return True

            # Check event severity - always include severe alerts for nearby areas
            severity = properties.get('severity', '').upper()
            if severity in ['SEVERE', 'EXTREME']:
                # Check if it's in Ohio
                if 'OHIO' in area_desc or any(ugc.startswith('OH') for ugc in ugc_codes):
                    self.logger.debug(f"Severe alert included from Ohio: {severity}")
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking alert relevance: {str(e)}")
            return False


    def parse_cap_alert(self, alert_data: Dict) -> Optional[Dict]:
        """Parse CAP alert data with enhanced timezone handling"""
        try:
            properties = alert_data.get('properties', {})
            geometry = alert_data.get('geometry')

            # Extract or generate identifier
            identifier = properties.get('identifier')
            if not identifier:
                event = properties.get('event', 'Unknown')
                sent = properties.get('sent', str(time.time()))
                temp_id = f"temp_{hashlib.md5((event + sent).encode()).hexdigest()[:16]}"
                identifier = temp_id
                self.logger.info(f"Generated temporary identifier: {identifier}")

            # Parse timestamps
            sent = parse_nws_datetime(properties.get('sent')) if properties.get('sent') else None
            expires = parse_nws_datetime(properties.get('expires')) if properties.get('expires') else None

            # Check if already expired
            if expires and expires < utc_now():
                self.logger.info(f"Alert {identifier} is already expired")

            # Extract area description
            area_desc = (properties.get('areaDesc') or
                         properties.get('areas') or
                         properties.get('geocode', {}).get('UGC', [''])[0] or
                         'OHZ016')

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
        """Save CAP alert to database with duplicate detection"""
        try:
            # Check if alert already exists
            existing_alert = self.db_session.query(CAPAlert).filter_by(
                identifier=alert_data['identifier']
            ).first()

            if existing_alert:
                # Update existing alert
                for key, value in alert_data.items():
                    if key != 'raw_json':  # Don't overwrite raw_json unless necessary
                        setattr(existing_alert, key, value)

                existing_alert.updated_at = utc_now()
                self.db_session.commit()

                # Update LED display if this is an active alert
                if self.led_controller and not self.is_alert_expired(existing_alert):
                    self.update_led_display()

                return False, existing_alert
            else:
                # Create new alert
                new_alert = CAPAlert(**alert_data)
                new_alert.created_at = utc_now()
                new_alert.updated_at = utc_now()

                self.db_session.add(new_alert)
                self.db_session.commit()

                # Update LED display for new active alerts
                if self.led_controller and not self.is_alert_expired(new_alert):
                    self.update_led_display()

                return True, new_alert

        except SQLAlchemyError as e:
            self.logger.error(f"Database error saving alert: {str(e)}")
            self.db_session.rollback()
            return False, None
        except Exception as e:
            self.logger.error(f"Error saving CAP alert: {str(e)}")
            return False, None


    def is_alert_expired(self, alert: CAPAlert) -> bool:
        """Check if an alert is expired"""
        if not alert.expires:
            return False
        return alert.expires < utc_now()


    def update_led_display(self):
        """Update LED sign with current active alerts"""
        if not self.led_controller:
            return

        try:
            # Get active alerts ordered by severity
            active_alerts = self.db_session.query(CAPAlert).filter(
                or_(
                    CAPAlert.expires.is_(None),
                    CAPAlert.expires > utc_now()
                )
            ).order_by(
                CAPAlert.severity.desc(),
                CAPAlert.sent.desc()
            ).limit(5).all()

            if active_alerts:
                # Display alerts on LED sign
                self.led_controller.display_alerts(active_alerts)
                self.logger.info(f"Updated LED display with {len(active_alerts)} active alerts")
            else:
                # Display default message when no alerts
                self.led_controller.display_default_message()
                self.logger.info("Updated LED display with default message")

        except Exception as e:
            self.logger.error(f"Error updating LED display: {e}")


    def process_intersections(self, alert: CAPAlert):
        """Process alert intersections with boundaries"""
        try:
            if not alert.geometry:
                return

            # This would be implemented based on your existing intersection logic
            # from the main app.py file
            pass

        except Exception as e:
            self.logger.error(f"Error processing intersections: {str(e)}")


    def cleanup_old_poll_history(self):
        """Clean up old poll history records (keep alerts forever)"""
        try:
            # Only clean up poll history, NOT alerts - keep all alerts for historical analysis
            cutoff_date = utc_now() - timedelta(days=30)  # Keep 30 days of poll history

            from models import PollHistory
            old_polls_count = self.db_session.query(PollHistory).filter(
                PollHistory.timestamp < cutoff_date
            ).count()

            if old_polls_count > 100:  # Only clean if we have many records
                # Keep the most recent 100 poll records even if older than 30 days
                subquery = self.db_session.query(PollHistory.id).order_by(
                    PollHistory.timestamp.desc()
                ).limit(100).subquery()

                self.db_session.query(PollHistory).filter(
                    PollHistory.timestamp < cutoff_date,
                    ~PollHistory.id.in_(subquery)
                ).delete(synchronize_session=False)

                self.db_session.commit()
                self.logger.info(f"Cleaned up old poll history records (alerts preserved)")

        except Exception as e:
            self.logger.error(f"Error cleaning up poll history: {str(e)}")


    def log_poll_history(self, stats):
        """Log poll statistics to database for monitoring"""
        try:
            from models import PollHistory
            poll_record = PollHistory(
                timestamp=utc_now(),
                alerts_fetched=stats.get('alerts_fetched', 0),
                alerts_new=stats.get('alerts_new', 0),
                alerts_updated=stats.get('alerts_updated', 0),
                execution_time_ms=stats.get('execution_time_ms', 0),
                status=stats.get('status', 'UNKNOWN'),
                error_message=stats.get('error_message')
            )
            self.db_session.add(poll_record)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"Error logging poll history: {str(e)}")


    def log_system_event(self, level: str, message: str, details: Dict = None):
        """Log system event to database"""
        try:
            if details is None:
                details = {}

            details.update({
                'logged_at_utc': utc_now().isoformat(),
                'logged_at_local': local_now().isoformat(),
                'timezone': str(PUTNAM_COUNTY_TZ)
            })

            log_entry = SystemLog(
                level=level,
                message=message,
                module='cap_poller',
                details=details,
                timestamp=utc_now()
            )
            self.db_session.add(log_entry)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"Error logging system event: {str(e)}")


    def poll_and_process(self) -> Dict:
        """Main polling function with LED integration"""
        start_time = time.time()
        poll_start_utc = utc_now()
        poll_start_local = local_now()

        stats = {
            'alerts_fetched': 0,
            'alerts_new': 0,
            'alerts_updated': 0,
            'alerts_filtered': 0,
            'execution_time_ms': 0,
            'status': 'SUCCESS',
            'error_message': None,
            'zone': 'OHZ016/OHC137 (Putnam County, OH)',
            'poll_time_utc': poll_start_utc.isoformat(),
            'poll_time_local': poll_start_local.isoformat(),
            'timezone': str(PUTNAM_COUNTY_TZ),
            'led_updated': False
        }

        try:
            self.logger.info(
                f"Starting CAP alert polling cycle for Putnam County, OH at {format_local_datetime(poll_start_utc)}"
            )

            # Fetch alerts
            alerts_data = self.fetch_cap_alerts()
            stats['alerts_fetched'] = len(alerts_data)

            # Process each alert
            for alert_data in alerts_data:
                props = alert_data.get('properties', {})
                event = props.get('event', 'Unknown')
                alert_id = props.get('identifier', 'No ID')

                self.logger.info(f"Processing alert: {event} (ID: {alert_id[:20]}...)")

                if not self.is_relevant_alert(alert_data):
                    self.logger.info(f"Alert {event} filtered out - not relevant")
                    stats['alerts_filtered'] += 1
                    continue

                self.logger.info(f"Alert {event} passed relevance check - processing...")

                parsed_alert = self.parse_cap_alert(alert_data)
                if parsed_alert:
                    is_new, alert = self.save_cap_alert(parsed_alert)

                    if is_new:
                        stats['alerts_new'] += 1
                        if alert.sent:
                            self.logger.info(
                                f"Saved new alert: {alert.event} - Sent: {format_local_datetime(alert.sent)}"
                            )
                        else:
                            self.logger.info(f"Saved new alert: {alert.event}")

                        self.process_intersections(alert)
                        stats['led_updated'] = True
                    else:
                        stats['alerts_updated'] += 1
                        if alert.sent:
                            self.logger.info(
                                f"Updated existing alert: {alert.event} - Sent: {format_local_datetime(alert.sent)}"
                            )
                        else:
                            self.logger.info(f"Updated existing alert: {alert.event}")
                else:
                    self.logger.warning(f"Failed to parse alert: {event}")

            # Cleanup old poll history (but keep all alerts for historical data)
            self.cleanup_old_poll_history()

            # Log poll statistics
            self.log_poll_history(stats)

            # Update LED display
            if self.led_controller:
                self.update_led_display()
                stats['led_updated'] = True

            # Calculate execution time
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.info(
                f"Polling cycle completed: {stats['alerts_new']} new, {stats['alerts_updated']} updated, {stats['alerts_filtered']} filtered"
            )

            # Log successful poll
            self.log_system_event('INFO', f'CAP polling successful: {stats["alerts_new"]} new alerts', stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start_time) * 1000)

            self.logger.error(f"Error in polling cycle: {str(e)}")
            self.log_system_event('ERROR', f'CAP polling failed: {str(e)}', stats)

        return stats


    def close(self):
        """Close connections"""
        if hasattr(self, 'db_session'):
            self.db_session.close()
        if hasattr(self, 'session'):
            self.session.close()
        if self.led_controller:
            self.led_controller.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='NOAA CAP Alert Poller with LED Sign Integration')
    parser.add_argument('--database-url',
                        default='postgresql://noaa_user:rkhkeq@localhost:5432/noaa_alerts',
                        help='Database connection URL')
    parser.add_argument('--led-ip',
                        help='LED sign IP address')
    parser.add_argument('--led-port',
                        type=int,
                        default=10001,
                        help='LED sign port (default: 10001)')
    parser.add_argument('--log-level',
                        default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging level')
    parser.add_argument('--continuous',
                        action='store_true',
                        help='Run continuously')
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

    startup_utc = utc_now()
    logger.info(f"Starting NOAA CAP Alert Poller with LED Integration")
    logger.info(f"Startup time: {format_local_datetime(startup_utc)}")
    if args.led_ip:
        logger.info(f"LED Sign: {args.led_ip}:{args.led_port}")

    # Create poller
    poller = CAPPoller(args.database_url, args.led_ip, args.led_port)

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
                    time.sleep(60)
        else:
            stats = poller.poll_and_process()
            print(f"Polling completed: {json.dumps(stats, indent=2)}")

    finally:
        poller.close()


if __name__ == '__main__':
    main()