"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""GPS subsystem.

Owns the chrony/GPS trend archive (raw → 1m → 10m → 1h tiers) and the
GPS manager bootstrap previously inlined in ``hardware_service.py``.
"""

from services.gps.api import create_blueprint
from services.gps.events import (
    EVENTS_MAX,
    EVENTS_REDIS_KEY,
    EventDetector,
    publish_events,
    read_events,
)
from services.gps.manager import initialize_gps_manager
from services.gps.trends import (
    GPS_TRENDS_DEFAULT_WINDOW,
    GPS_TRENDS_INTERVAL_S,
    GPS_TRENDS_MAX_SAMPLES,
    GPS_TRENDS_RAW_MAX_SAMPLES,
    GPS_TRENDS_REDIS_KEY,
    GPS_TRENDS_TIERS,
    GPS_TRENDS_WINDOW_TO_TIER,
    aggregate_samples,
    collect_chrony_tracking,
    collect_gps_status,
    emit_rollups,
    new_last_bucket_ids,
    publish_sample,
    redis_key_for_tier,
)

__all__ = [
    "EVENTS_MAX",
    "EVENTS_REDIS_KEY",
    "EventDetector",
    "GPS_TRENDS_DEFAULT_WINDOW",
    "GPS_TRENDS_INTERVAL_S",
    "GPS_TRENDS_MAX_SAMPLES",
    "GPS_TRENDS_RAW_MAX_SAMPLES",
    "GPS_TRENDS_REDIS_KEY",
    "GPS_TRENDS_TIERS",
    "GPS_TRENDS_WINDOW_TO_TIER",
    "aggregate_samples",
    "collect_chrony_tracking",
    "collect_gps_status",
    "create_blueprint",
    "emit_rollups",
    "initialize_gps_manager",
    "new_last_bucket_ids",
    "publish_events",
    "publish_sample",
    "read_events",
    "redis_key_for_tier",
]
