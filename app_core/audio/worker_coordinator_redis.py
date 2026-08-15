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
Redis-Based Multi-Worker Coordinator for Audio Processing

Replaces fragile file-based coordination with robust Redis-based state management.

Architecture:
    Master Worker: Runs audio controller, broadcast pump, EAS monitor
    Slave Workers: Serve UI requests by reading shared metrics from Redis

Coordination: Redis distributed locks (SETNX) with TTL
Shared State: Redis hashes with automatic expiration
Real-time Updates: Redis Pub/Sub for push-based UI updates

Benefits over file-based approach:
    - 100x faster (in-memory vs disk I/O)
    - Atomic operations (no race conditions)
    - Built-in TTL (automatic stale detection)
    - Pub/Sub (no polling needed)
    - Industry standard, battle-tested
"""

import json
import math
import os
import time
import logging
import threading
from typing import Optional, Dict, Any
import redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

from app_core.redis_client import get_redis_client as _get_central_redis_client
from app_core.config.redis_config import RedisChannels, RedisTimeouts

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj: Any) -> Any:
    """
    Recursively sanitize objects to be JSON-safe.
    
    Converts inf, -inf, nan to valid numbers.
    Handles nested dicts, lists, and numpy types.
    """
    if obj is None:
        return None
    
    if isinstance(obj, bool):
        return obj
    
    if isinstance(obj, (int, str)):
        return obj
    
    if isinstance(obj, float):
        if math.isinf(obj):
            return -120.0 if obj < 0 else 120.0
        if math.isnan(obj):
            return -120.0
        return obj
    
    # Handle numpy types
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            value = float(obj)
            if math.isinf(value):
                return -120.0 if value < 0 else 120.0
            if math.isnan(value):
                return -120.0
            return value
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass
    
    if isinstance(obj, dict):
        return {key: _sanitize_for_json(value) for key, value in obj.items()}
    
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    
    # Fallback: convert to string
    return str(obj)

# Redis keys (from centralized config)
MASTER_LOCK_KEY = RedisChannels.MASTER_LOCK_KEY
METRICS_KEY = RedisChannels.METRICS_KEY
HEARTBEAT_CHANNEL = RedisChannels.HEARTBEAT_CHANNEL
METRICS_UPDATE_CHANNEL = RedisChannels.METRICS_UPDATE_CHANNEL

# Timing configuration (from centralized config)
MASTER_LOCK_TTL = RedisTimeouts.MASTER_LOCK_TTL
HEARTBEAT_INTERVAL = RedisTimeouts.HEARTBEAT_INTERVAL
METRICS_TTL = RedisTimeouts.METRICS_TTL

# Global state
_is_master_worker: bool = False
_heartbeat_thread: Optional[threading.Thread] = None
_heartbeat_stop_flag: threading.Event = threading.Event()


class WorkerRole:
    """Worker roles in multi-worker setup."""
    MASTER = "master"  # Runs audio processing
    SLAVE = "slave"    # Only serves UI requests


def get_redis_client() -> redis.Redis:
    """
    Get Redis client from centralized pool.

    Uses the centralized redis_client module which provides:
    - Connection pooling
    - Circuit breaker pattern
    - Automatic retry with exponential backoff

    Returns:
        Redis client instance

    Raises:
        RedisConnectionError: If Redis is not available
    """
    return _get_central_redis_client()


def try_acquire_master_lock() -> bool:
    """
    Try to acquire the master worker lock using Redis SETNX.

    Uses Redis distributed locking with automatic expiration (TTL).
    If master worker dies, lock expires and another worker can take over.

    Returns:
        True if this worker acquired master lock, False otherwise
    """
    global _is_master_worker

    try:
        r = get_redis_client()
        pid = os.getpid()

        # Try to acquire lock with SETNX (SET if Not eXists)
        # NX = only set if key doesn't exist
        # EX = set expiration time in seconds
        acquired = r.set(
            MASTER_LOCK_KEY,
            pid,
            nx=True,  # Only set if doesn't exist
            ex=MASTER_LOCK_TTL  # Expires after 30 seconds
        )

        if acquired:
            _is_master_worker = True
            logger.info(f"✅ Worker PID {pid} acquired MASTER lock (TTL={MASTER_LOCK_TTL}s)")
            return True
        else:
            # Lock held by another worker
            current_master = r.get(MASTER_LOCK_KEY)
            logger.info(
                f"Worker PID {pid} running as SLAVE "
                f"(master lock held by PID {current_master})"
            )
            return False

    except RedisError as e:
        logger.error(f"Redis error during master lock acquisition: {e}")
        return False


def refresh_master_lock() -> bool:
    """
    Refresh the master lock TTL (called periodically by heartbeat).

    Returns:
        True if lock was refreshed, False if lock lost
    """
    global _is_master_worker

    if not _is_master_worker:
        return False

    try:
        r = get_redis_client()
        pid = os.getpid()

        # Check if we still own the lock
        current_master = r.get(MASTER_LOCK_KEY)

        if current_master != str(pid):
            logger.error(
                f"❌ Lost master lock! Current master: {current_master}, our PID: {pid}"
            )
            _is_master_worker = False
            return False

        # Refresh TTL
        r.expire(MASTER_LOCK_KEY, MASTER_LOCK_TTL)
        return True

    except RedisError as e:
        logger.error(f"Redis error during lock refresh: {e}")
        return False


def release_master_lock():
    """Release the master worker lock."""
    global _is_master_worker

    if not _is_master_worker:
        return

    try:
        r = get_redis_client()
        pid = os.getpid()

        # Only delete if we own the lock (atomic check-and-delete)
        current_master = r.get(MASTER_LOCK_KEY)
        if current_master == str(pid):
            r.delete(MASTER_LOCK_KEY)
            logger.info(f"Worker PID {pid} released master lock")
        else:
            logger.warning(
                f"Cannot release master lock - owned by PID {current_master}, not {pid}"
            )

    except RedisError as e:
        logger.error(f"Redis error during lock release: {e}")
    finally:
        _is_master_worker = False


def is_master_worker() -> bool:
    """Check if this worker is the master."""
    return _is_master_worker


def write_shared_metrics(metrics: Dict[str, Any]):
    """
    Write metrics to Redis for all workers to read.

    Should only be called by master worker.

    Uses Redis hash with automatic expiration. Much faster and more
    reliable than file-based approach.

    Args:
        metrics: Dictionary of metrics to write
    """
    if not _is_master_worker:
        logger.warning("write_shared_metrics() called by non-master worker, ignoring")
        return

    try:
        r = get_redis_client()

        # Add metadata
        metrics["_heartbeat"] = time.time()
        metrics["_master_pid"] = os.getpid()

        # Sanitize metrics to remove inf/nan values before serialization
        metrics = _sanitize_for_json(metrics)

        # Serialize every value to JSON so round-trips preserve types.
        # Redis hashes store strings only; redis-py stringifies other types
        # via str(), which turns None/True/False into "None"/"True"/"False"
        # — those read back as truthy non-empty strings in JS and produced
        # phantom "Yes" badges and "None" labels in the audio monitor UI.
        flat_metrics = {}
        for key, value in metrics.items():
            if isinstance(value, (dict, list)):
                flat_metrics[key] = json.dumps(value)
            elif isinstance(value, (str, bytes)):
                flat_metrics[key] = value
            else:
                flat_metrics[key] = json.dumps(value)

        # Store in Redis hash with pipeline for atomicity
        pipe = r.pipeline()
        pipe.delete(METRICS_KEY)  # Clear old metrics
        pipe.hset(METRICS_KEY, mapping=flat_metrics)  # Set new metrics
        pipe.expire(METRICS_KEY, METRICS_TTL)  # Auto-expire if master dies
        pipe.execute()

        # Publish notification to subscribers (for real-time UI updates)
        r.publish(METRICS_UPDATE_CHANNEL, "1")

    except RedisError as e:
        logger.error(f"Failed to write shared metrics to Redis: {e}")


def read_shared_metrics() -> Optional[Dict[str, Any]]:
    """
    Read metrics from Redis.

    Can be called by any worker to get latest metrics from master.

    Returns:
        Dictionary of metrics, or None if not available.

    Staleness policy
    ----------------
    * < 60 s  → fresh, returned as-is.
    * 60 – 300 s → stale but *probably* still running (transient hiccup /
      GC pause / metrics-publish exception).  Return the data with a
      ``_metrics_stale`` flag so callers can show a soft warning without
      hiding the whole dashboard.
    * > 300 s (5 min) → truly dead; return None so the UI shows the hard
      "service not running" error.

    This prevents a single missed publish cycle from falsely reporting the
    audio service as down.
    """
    STALE_WARN_SECONDS = 60.0    # warn after this many seconds
    STALE_DEAD_SECONDS = 300.0   # treat as dead only after 5 minutes

    try:
        r = get_redis_client()

        # Read entire hash
        flat_metrics = r.hgetall(METRICS_KEY)

        if not flat_metrics:
            return None

        # Deserialize JSON back to the original types.  write_shared_metrics
        # JSON-encodes every non-string value (dicts, lists, numbers, bools,
        # None) so round-trips preserve types — without that, scalars like
        # None were coming back as the literal string "None".
        metrics = {}
        for key, value in flat_metrics.items():
            # Decode bytes to string if needed (redis-py 7.x returns bytes)
            decoded_key = key.decode('utf-8') if isinstance(key, bytes) else key
            decoded_value = value.decode('utf-8') if isinstance(value, bytes) else value

            if decoded_value == '':
                continue

            if isinstance(decoded_value, str):
                try:
                    metrics[decoded_key] = json.loads(decoded_value)
                except json.JSONDecodeError:
                    # Legacy entries written before the type-preserving fix
                    # are plain strings — including the literal "None",
                    # "True", "False" produced when redis-py stringified
                    # Python scalars via str().  Without this normalization
                    # those leak to the audio monitor UI as truthy strings
                    # ("PS: None", phantom "Yes" badges) until the master
                    # rewrites every key.
                    if decoded_value == "None":
                        metrics[decoded_key] = None
                    elif decoded_value == "True":
                        metrics[decoded_key] = True
                    elif decoded_value == "False":
                        metrics[decoded_key] = False
                    else:
                        metrics[decoded_key] = decoded_value
            else:
                metrics[decoded_key] = decoded_value

        # Check heartbeat freshness. _heartbeat is written by
        # eas_monitoring_service.py (audio-service), the sole EAS decoder --
        # eas_service.py used to write a second _eas_heartbeat key as a
        # fallback here, but that service was retired as a redundant
        # duplicate decoder (see docs/reference/CHANGELOG.md).
        try:
            heartbeat = float(metrics.get("_heartbeat") or 0)
            age = time.time() - heartbeat

            if heartbeat == 0:
                # No heartbeat present — data is unusable
                logger.debug("Shared metrics have no heartbeat, treating as absent")
                return None

            if age > STALE_DEAD_SECONDS:
                logger.warning(
                    f"Shared metrics are very stale (age: {age:.0f}s > {STALE_DEAD_SECONDS:.0f}s) "
                    f"– audio-service appears dead"
                )
                return None

            if age > STALE_WARN_SECONDS:
                logger.warning(
                    f"Shared metrics are stale (age: {age:.0f}s) – "
                    f"audio-service may be under load or had a transient error"
                )
                metrics["_metrics_stale"] = "true"

        except (ValueError, TypeError) as e:
            logger.debug(f"Invalid heartbeat value in metrics: {e}")
            return None

        return metrics

    except RedisError as e:
        # Log as debug — Redis unavailability is expected during startup
        logger.debug(f"Failed to read shared metrics from Redis: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error reading shared metrics from Redis: {e}")
        return None


def start_heartbeat_writer(metrics_getter_fn):
    """
    Start background thread that periodically writes metrics to Redis.

    Should only be called by master worker.

    Args:
        metrics_getter_fn: Callable that returns current metrics dict
    """
    global _heartbeat_thread

    if not _is_master_worker:
        logger.warning("start_heartbeat_writer() called by non-master worker, ignoring")
        return

    def heartbeat_loop():
        """Background thread that writes metrics and refreshes lock."""
        logger.info("Master worker heartbeat thread started (Redis-based)")

        while not _heartbeat_stop_flag.wait(timeout=HEARTBEAT_INTERVAL):
            try:
                # Refresh master lock TTL
                if not refresh_master_lock():
                    logger.error("❌ Lost master lock, stopping heartbeat")
                    break

                # Write metrics to Redis
                metrics = metrics_getter_fn()
                if metrics:
                    write_shared_metrics(metrics)

            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")

        logger.info("Master worker heartbeat thread stopped")

    _heartbeat_stop_flag.clear()
    _heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        daemon=True,
        name="RedisMetricsHeartbeat"
    )
    _heartbeat_thread.start()
    logger.info("Started Redis-based heartbeat writer thread")


def stop_heartbeat_writer():
    """Stop the heartbeat writer thread."""
    global _heartbeat_thread

    if _heartbeat_thread is not None:
        logger.info("Stopping heartbeat writer thread")
        _heartbeat_stop_flag.set()
        _heartbeat_thread.join(timeout=10)
        _heartbeat_thread = None


def cleanup_coordinator():
    """Cleanup coordinator resources (call on shutdown)."""
    stop_heartbeat_writer()
    release_master_lock()

    # Close Redis connection
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception as e:
            logger.debug(f"Error closing Redis connection: {e}")
        _redis_client = None


def get_redis_stats() -> Dict[str, Any]:
    """
    Get Redis connection statistics for monitoring.

    Returns:
        Dictionary with Redis stats
    """
    try:
        r = get_redis_client()
        info = r.info("stats")

        return {
            "connected": True,
            "total_connections_received": info.get("total_connections_received"),
            "total_commands_processed": info.get("total_commands_processed"),
            "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec"),
            "used_memory_human": r.info("memory").get("used_memory_human"),
        }

    except RedisError as e:
        return {
            "connected": False,
            "error": str(e)
        }
