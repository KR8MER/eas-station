#!/usr/bin/env python3
"""
Standalone Radio/SDR Manager Service

This service manages SDR receivers and handles capture requests.
Runs independently of the CAP poller.
"""
import os
import sys
import time
import logging

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import RadioReceiver
from app_core.radio import RadioManager, ensure_radio_tables

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('radio_manager')


def get_database_url():
    """Build database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    
    from urllib.parse import quote
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "alerts-db")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "alerts")
    
    user_part = quote(user, safe="")
    password_part = quote(password, safe="") if password else ""
    auth = f"{user_part}:{password_part}" if password_part else user_part
    
    return f"postgresql+psycopg2://{auth}@{host}:{port}/{database}"


def main():
    logger.info("Starting Radio/SDR Manager Service")
    
    # Check if radio capture is enabled
    if not os.getenv('ENABLE_RADIO_MANAGER', '').lower() in {'1', 'true', 'yes'}:
        logger.info("Radio manager is disabled (set ENABLE_RADIO_MANAGER=1 to enable)")
        logger.info("Service will exit")
        return
    
    # Connect to database
    database_url = get_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    
    # Ensure radio tables exist
    try:
        ensure_radio_tables(engine)
        logger.info("Radio database tables verified")
    except Exception as e:
        logger.error(f"Failed to verify radio tables: {e}")
        sys.exit(1)
    
    # Initialize radio manager
    try:
        manager = RadioManager()
        logger.info("Radio Manager initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize radio manager: {e}")
        sys.exit(1)
    
    # Configure receivers from database
    refresh_interval = int(os.getenv('RADIO_CONFIG_REFRESH_INTERVAL', '300'))  # 5 minutes
    last_refresh_time = 0
    
    logger.info(f"Radio configuration will refresh every {refresh_interval} seconds")
    
    while True:
        try:
            current_time = time.time()
            
            # Refresh configuration periodically
            if current_time - last_refresh_time >= refresh_interval:
                logger.info("Refreshing radio receiver configuration from database")
                
                try:
                    receivers = db_session.query(RadioReceiver).order_by(RadioReceiver.identifier).all()
                    
                    configs = []
                    for receiver in receivers:
                        if not receiver.identifier:
                            continue
                        try:
                            configs.append(receiver.to_receiver_config())
                        except Exception as e:
                            logger.error(f"Invalid receiver {receiver.identifier}: {e}")
                    
                    if configs:
                        manager.configure_receivers(configs)
                        manager.start_all()
                        logger.info(f"Configured {len(configs)} radio receivers")
                    else:
                        logger.info("No radio receivers configured in database")
                    
                    last_refresh_time = current_time
                    
                except Exception as e:
                    logger.error(f"Failed to refresh radio configuration: {e}")
            
            # The radio manager runs SDR threads in the background
            # This service just needs to stay alive and refresh config periodically
            time.sleep(10)
            
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down")
            break
        except Exception as e:
            logger.error(f"Error in radio manager loop: {e}", exc_info=True)
            time.sleep(10)
    
    # Cleanup
    try:
        manager.stop_all()
    except:
        pass
    
    db_session.close()
    logger.info("Radio/SDR Manager Service stopped")


if __name__ == '__main__':
    main()
