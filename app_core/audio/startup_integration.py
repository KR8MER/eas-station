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
    1. Checks if audio processing should run in this service
    2. Tries to acquire master worker lock (multi-worker coordination)
    3. Gets the global AudioIngestController (master only)
    4. Creates an alert callback for processing detections
    5. Initializes the EAS monitor with adapter
    6. Auto-starts continuous monitoring

    Service Architecture:
    - Separated: Audio service runs audio processing, web app reads from Redis
    - Integrated: Web app runs everything (with master/slave worker coordination)

    Returns:
        True if successfully initialized and started

    Should be called during Flask app startup (in initialize_database or similar).
    """
    # Separated architecture: Audio processing handled by dedicated audio-service container
    # This app container only serves the web UI and reads metrics from Redis
    logger.info("🌐 App container running in UI-only mode")
    logger.info("   Audio processing handled by dedicated audio-service container")
    logger.info("   Metrics read from Redis (published by audio-service)")
    return True  # Success - separated architecture


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
