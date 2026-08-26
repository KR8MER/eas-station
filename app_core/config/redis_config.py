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

"""
Centralized Redis Configuration for EAS Station.

All Redis connection settings are defined here to avoid configuration sprawl.
Import from this module instead of reading environment variables directly.

Usage:
    from app_core.config.redis_config import (
        get_redis_host,
        get_redis_port,
        get_redis_url,
    )
"""

import os
from typing import Optional


def get_redis_host() -> str:
    """Get Redis host from environment.

    Returns:
        Redis host (default: 'localhost')
    """
    return os.getenv("REDIS_HOST", "localhost")


def get_redis_port() -> int:
    """Get Redis port from environment.

    Returns:
        Redis port (default: 6379)
    """
    return int(os.getenv("REDIS_PORT", "6379"))


def get_redis_db() -> int:
    """Get Redis database number from environment.

    Returns:
        Redis database number (default: 0)
    """
    return int(os.getenv("REDIS_DB", "0"))


def get_redis_password() -> Optional[str]:
    """Get Redis password from environment (if authentication required).

    Returns:
        Redis password or None if not set
    """
    password = os.getenv("REDIS_PASSWORD")
    # Treat empty string as None
    return password if password else None


def get_redis_url() -> str:
    """Get full Redis connection URL.

    Constructs URL from individual settings. Use this for libraries
    that require a Redis URL (e.g., Flask-Caching, Celery).

    Returns:
        Redis URL in format: redis://[password@]host:port/db
    """
    host = get_redis_host()
    port = get_redis_port()
    db = get_redis_db()
    password = get_redis_password()

    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def get_cache_redis_url() -> str:
    """Get Redis URL for Flask-Caching.

    Checks CACHE_REDIS_URL first for explicit override,
    falls back to standard Redis URL.

    Returns:
        Redis URL for caching
    """
    # Allow explicit override for cache-specific Redis instance
    cache_url = os.getenv("CACHE_REDIS_URL")
    if cache_url:
        return cache_url
    return get_redis_url()


# Redis pub/sub channel names (centralized registry)
class RedisChannels:
    """Centralized registry of Redis pub/sub channels and keys."""

    # Worker coordination
    MASTER_LOCK_KEY = "eas:master:lock"
    METRICS_KEY = "eas:metrics"
    HEARTBEAT_CHANNEL = "eas:heartbeat"
    METRICS_UPDATE_CHANNEL = "eas:metrics:update"

    # Audio service
    AUDIO_COMMAND_CHANNEL = "eas:audio:commands"
    AUDIO_RESPONSE_PREFIX = "eas:audio:response:"  # + command_id

    # SDR service
    SDR_COMMANDS_QUEUE = "sdr:commands"
    SDR_COMMAND_RESULT_PREFIX = "sdr:command_result:"  # + command_id
    SDR_METRICS_KEY = "sdr:metrics"
    SDR_SAMPLES_PREFIX = "sdr:samples:"  # + receiver_id

    # Demod service -- FM demodulation runs here, in its own process, so
    # the oaconvolve/FFT-heavy DSP work (stereo pilot detection, L+R/L-R
    # extraction) can never share a GIL with the audio service's real-time
    # Icecast feeder threads. See docs/architecture/SDR_SERVICE_ARCHITECTURE.md.
    # Audio is published per-chunk on the pub/sub channel; status (RBDS
    # PS/PI/radiotext, stereo lock, etc.) changes far less often, so it
    # rides a separately-updated SETEX key instead of riding every chunk.
    DEMOD_AUDIO_PREFIX = "demod:audio:"  # + receiver_id
    DEMOD_STATUS_PREFIX = "demod:status:"  # + receiver_id
    DEMOD_STATUS_TTL_SECONDS = 10
    DEMOD_METRICS_KEY = "demod:metrics"

    # Audio streaming
    AUDIO_SAMPLES_PREFIX = "audio:samples:"  # + source_name

    # Spectrum data
    SPECTRUM_PREFIX = "eas:spectrum:"  # + receiver_identifier

    # Dead-air (silence) monitor state, published by the audio service and
    # read by the GPIO service to drive the tower light and rack buzzer.
    # Short TTL: a stale key must not keep an alarm asserted after the
    # publisher dies. Absence is deliberately read as "not alarming" rather
    # than "alarm", so disabling the feature or restarting the audio
    # service cannot strand a buzzer on. Audio-service liveness is covered
    # separately by the existing service health monitoring.
    DEAD_AIR_KEY = "eas:dead_air"
    DEAD_AIR_TTL_SECONDS = 30
    # Operator acknowledgement: silences the buzzer for the current dead-air
    # episode without clearing the tower light. Cleared automatically when
    # audio returns, so the next outage sounds again.
    DEAD_AIR_ACK_KEY = "eas:dead_air:ack"

    # Alert forwarding
    ALERT_CHANNEL = "eas:alerts:received"


# Timing constants for Redis operations
class RedisTimeouts:
    """Timeout and TTL constants for Redis operations."""

    # Master lock
    MASTER_LOCK_TTL = 30  # seconds - auto-expire if master dies

    # Metrics
    METRICS_TTL = 60  # seconds - auto-expire if not refreshed

    # Heartbeat
    HEARTBEAT_INTERVAL = 5.0  # seconds - how often to update
    STALE_THRESHOLD = 15.0  # seconds - consider stale after this

    # Command timeouts
    COMMAND_TIMEOUT = 30  # seconds - wait for response
    SDR_COMMAND_TIMEOUT = 5  # seconds - SDR command response wait

    # Connection
    CONNECT_TIMEOUT = 5  # seconds - initial connection
    SOCKET_TIMEOUT = 5  # seconds - socket operations
    HEALTH_CHECK_INTERVAL = 30  # seconds - connection health check
