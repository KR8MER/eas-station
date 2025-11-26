#!/usr/bin/env python3
"""
Standalone EAS Broadcaster Service

This service monitors the database for new/updated alerts and triggers
EAS audio broadcasts. Runs independently of the CAP poller.
"""
import os
import sys
import time
import logging
from datetime import datetime, timezone

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app import CAPAlert, EASMessage
from app_utils.eas import EASBroadcaster, load_eas_config
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('eas_broadcaster')


def get_database_url():
    """Build database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    
    from urllib.parse import quote
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "host.docker.internal")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "alerts")
    
    user_part = quote(user, safe="")
    password_part = quote(password, safe="") if password else ""
    auth = f"{user_part}:{password_part}" if password_part else user_part
    
    return f"postgresql+psycopg2://{auth}@{host}:{port}/{database}"


def main():
    logger.info("Starting EAS Broadcaster Service")
    
    # Connect to database
    database_url = get_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    
    # Load location settings from database
    from app import LocationSettings
    try:
        settings_record = db_session.query(LocationSettings).order_by(LocationSettings.id).first()
        if settings_record:
            location_settings = settings_record.to_dict()
            logger.info(f"Loaded location settings: {location_settings.get('county_name')}, {location_settings.get('state_code')}")
        else:
            location_settings = DEFAULT_LOCATION_SETTINGS
            logger.warning("No location settings in database, using defaults")
    except Exception as e:
        logger.error(f"Failed to load location settings: {e}")
        location_settings = DEFAULT_LOCATION_SETTINGS
    
    # Initialize EAS broadcaster
    try:
        eas_config = load_eas_config(project_root)
        broadcaster = EASBroadcaster(
            db_session, EASMessage, eas_config, logger, location_settings
        )
        logger.info("EAS Broadcaster initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize EAS broadcaster: {e}")
        sys.exit(1)
    
    # Track which alerts we've already processed
    processed_alerts = set()
    
    # Monitor for new/updated alerts
    check_interval = int(os.getenv('EAS_BROADCAST_CHECK_INTERVAL', '5'))  # seconds
    logger.info(f"Monitoring for alerts every {check_interval} seconds")
    
    while True:
        try:
            # Find unprocessed alerts that need broadcasting
            # This queries for alerts that haven't been broadcast yet
            alerts = db_session.query(CAPAlert).filter(
                CAPAlert.id.notin_(processed_alerts) if processed_alerts else True
            ).order_by(CAPAlert.sent.desc()).limit(100).all()
            
            for alert in alerts:
                if alert.id in processed_alerts:
                    continue
                
                try:
                    # Load full alert data (raw_json)
                    alert_data = alert.raw_json if hasattr(alert, 'raw_json') else {}
                    
                    # Trigger broadcast
                    logger.info(f"Processing alert for broadcast: {alert.identifier}")
                    broadcast_result = broadcaster.handle_alert(alert, alert_data)
                    
                    if broadcast_result and broadcast_result.get("same_triggered"):
                        logger.info(f"EAS broadcast triggered for {alert.event}")
                    
                    # Mark as processed
                    processed_alerts.add(alert.id)
                    
                except Exception as e:
                    logger.error(f"Error broadcasting alert {alert.identifier}: {e}")
            
            # Cleanup old processed IDs (keep last 1000)
            if len(processed_alerts) > 1000:
                # Keep only most recent 1000
                recent_alert_ids = [a.id for a in alerts[:1000]]
                processed_alerts = set(recent_alert_ids)
            
            time.sleep(check_interval)
            
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down")
            break
        except Exception as e:
            logger.error(f"Error in broadcast monitoring loop: {e}", exc_info=True)
            time.sleep(check_interval)
    
    db_session.close()
    logger.info("EAS Broadcaster Service stopped")


if __name__ == '__main__':
    main()
