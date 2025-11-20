"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""
EAS Monitoring Startup Integration

Wires together the complete data flow:
Audio Sources → Controller → Adapter → Monitor → Decoder → Database

This module should be called during Flask app initialization to enable
continuous SAME monitoring.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def initialize_eas_monitoring_system() -> bool:
    """
    Initialize and start the complete EAS monitoring system.

    This function:
    1. Gets the global AudioIngestController
    2. Creates an alert callback for processing detections
    3. Initializes the EAS monitor with adapter
    4. Auto-starts continuous monitoring

    Returns:
        True if successfully initialized and started

    Should be called during Flask app startup (in initialize_database or similar).
    """
    try:
        # Import here to avoid circular dependencies
        from webapp.admin.audio_ingest import _get_audio_controller
        from .monitor_manager import initialize_eas_monitor
        from .eas_monitor import create_fips_filtering_callback

        # Step 1: Get the audio controller
        controller = _get_audio_controller()
        if controller is None:
            logger.warning("Audio controller not available - EAS monitoring cannot start")
            return False

        logger.info("Audio controller available for EAS monitoring")

        # Step 2: Create alert callback with FIPS filtering
        # Load configured FIPS codes from settings
        configured_fips = load_fips_codes_from_config()
        logger.info(f"Loaded {len(configured_fips)} FIPS codes for alert filtering")

        # Create the forward handler that processes matched alerts
        def forward_alert_handler(alert):
            """
            Handle alerts that match configured FIPS codes.

            This is called after FIPS filtering for alerts that should be processed.
            The alert has already been stored in ReceivedEASAlert table by the
            filtering callback.
            """
            try:
                from app_core.eas_processing import process_eas_alert

                # Process the alert (generate message, send notifications, etc.)
                result = process_eas_alert(alert)
                logger.info(f"Alert processed successfully: {result}")
                return result

            except Exception as e:
                logger.error(f"Error in forward_alert_handler: {e}", exc_info=True)
                return None

        # Wrap with FIPS filtering
        alert_callback = create_fips_filtering_callback(
            configured_fips_codes=configured_fips,
            forward_callback=forward_alert_handler,
            logger_instance=logger
        )

        logger.info("Created alert callback with FIPS filtering")

        # Step 3: Initialize monitor with controller and callback
        success = initialize_eas_monitor(
            audio_manager=controller,
            alert_callback=alert_callback,
            auto_start=True
        )

        if success:
            logger.info("✅ EAS monitoring system initialized and started successfully")
            logger.info("   - Audio pipeline: Connected")
            logger.info("   - SAME decoder: Active")
            logger.info("   - Alert processing: Enabled")
            logger.info("   - FIPS filtering: Configured")
            return True
        else:
            logger.error("❌ Failed to initialize EAS monitoring system")
            return False

    except Exception as e:
        logger.error(f"❌ Error initializing EAS monitoring system: {e}", exc_info=True)
        return False


def load_fips_codes_from_config() -> list:
    """
    Load configured FIPS codes from application settings.

    Returns list of FIPS codes to monitor, or empty list if none configured.
    """
    try:
        from app_core.location import get_location_settings

        settings = get_location_settings()
        fips_codes = settings.get('monitored_fips_codes', [])

        # Ensure it's a list
        if isinstance(fips_codes, str):
            # Handle comma-separated string
            fips_codes = [code.strip() for code in fips_codes.split(',') if code.strip()]

        return fips_codes

    except Exception as e:
        logger.warning(f"Could not load FIPS codes from config: {e}")
        # Return empty list - will log all alerts but not forward any
        return []
