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
Alert Forwarding Module

Handles forwarding of matched EAS alerts to:
- Redis pub/sub for real-time web UI updates
- Optional webhook endpoints for external integrations
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Redis channel for alert notifications
ALERT_CHANNEL = "eas:alerts:received"


def forward_alert_to_api(alert: Dict[str, Any]) -> bool:
    """
    Forward a matched EAS alert for processing.

    Publishes the alert to Redis for real-time notifications and
    optionally forwards to configured webhook endpoints.

    Args:
        alert: Dictionary containing alert data with keys:
            - source_name: Name of the audio source that detected the alert
            - event_code: EAS event code (e.g., 'TOR', 'SVR')
            - location_codes: List of FIPS codes from the alert
            - raw_header: Raw SAME header text (optional)
            - timestamp: Detection timestamp (optional)
            - confidence: Decode confidence score (optional)

    Returns:
        True if forwarding succeeded, False otherwise.
    """
    try:
        source_name = alert.get('source_name', 'unknown')
        event_code = alert.get('event_code', 'UNKNOWN')
        location_codes = alert.get('location_codes', [])

        logger.info(
            f"Forwarding alert: {event_code} from '{source_name}' "
            f"for locations {location_codes}"
        )

        # Prepare alert payload for Redis
        payload = {
            'source_name': source_name,
            'event_code': event_code,
            'location_codes': location_codes,
            'raw_header': alert.get('raw_header', ''),
            'timestamp': alert.get('timestamp', datetime.utcnow().isoformat()),
            'confidence': alert.get('confidence', 0.0),
            'forwarded_at': datetime.utcnow().isoformat(),
        }

        # Publish to Redis for real-time updates
        _publish_to_redis(payload)

        # Forward to webhook if configured
        webhook_url = os.environ.get('EAS_ALERT_WEBHOOK_URL')
        if webhook_url:
            _forward_to_webhook(webhook_url, payload)

        return True

    except Exception as e:
        logger.error(f"Failed to forward alert: {e}", exc_info=True)
        return False


def _publish_to_redis(payload: Dict[str, Any]) -> None:
    """Publish alert to Redis pub/sub channel."""
    try:
        from app_core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            logger.warning("Redis client not available, skipping pub/sub notification")
            return

        message = json.dumps(payload)
        client.publish(ALERT_CHANNEL, message)
        logger.debug(f"Published alert to Redis channel '{ALERT_CHANNEL}'")

    except Exception as e:
        logger.warning(f"Failed to publish alert to Redis: {e}")


def _forward_to_webhook(webhook_url: str, payload: Dict[str, Any]) -> None:
    """Forward alert to external webhook endpoint."""
    try:
        import requests

        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )

        if response.status_code < 300:
            logger.info(f"Alert forwarded to webhook: {response.status_code}")
        else:
            logger.warning(
                f"Webhook returned non-success status: {response.status_code}"
            )

    except ImportError:
        logger.warning("requests library not available, skipping webhook forwarding")
    except Exception as e:
        logger.warning(f"Failed to forward alert to webhook: {e}")


__all__ = ['forward_alert_to_api', 'ALERT_CHANNEL']
