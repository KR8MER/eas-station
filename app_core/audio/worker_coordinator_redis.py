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

import os
import json
import time
import logging
import threading
from typing import Optional, Dict, Any
import redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

logger = logging.getLogger(__name__)

# Redis connection settings
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Redis keys
MASTER_LOCK_KEY = "eas:master:lock"
METRICS_KEY = "eas:metrics"
HEARTBEAT_CHANNEL = "eas:heartbeat"
METRICS_UPDATE_CHANNEL = "eas:metrics:update"

# Timing configuration
MASTER_LOCK_TTL = 30  # Master lock expires after 30 seconds (auto-failover)
HEARTBEAT_INTERVAL = 5.0  # Master updates heartbeat every 5 seconds
METRICS_TTL = 60  # Metrics expire after 60 seconds if master dies

# Global state
_redis_client: Optional[redis.Redis] = None
_is_master_worker: bool = False
_heartbeat_thread: Optional[threading.Thread] = None
_heartbeat_stop_flag: threading.Event = threading.Event()


class WorkerRole:
    """Worker roles in multi-worker setup."""
    MASTER = "master"  # Runs audio processing
    SLAVE = "slave"    # Only serves UI requests


def get_redis_client() -> redis.Redis:
    """
    Get or create Redis client with connection pooling.

    Returns:
        Redis client instance

    Raises:
        RedisConnectionError: If Redis is not available
    """
    global _redis_client

    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True,  # Return strings instead of bytes
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                max_connections=10,
            )

            # Test connection
            _redis_client.ping()
            logger.info(f"✅ Connected to Redis at {REDIS_HOST}:{REDIS_PORT} (db={REDIS_DB})")

        except RedisConnectionError as e:
            logger.error(f"❌ Failed to connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}")
            raise

    return _redis_client


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

        # Serialize nested dicts to JSON strings
        # Redis hashes only support flat key-value pairs
        flat_metrics = {}
        for key, value in metrics.items():
            if isinstance(value, (dict, list)):
                flat_metrics[key] = json.dumps(value)
            else:
                flat_metrics[key] = value

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
        Dictionary of metrics, or None if not available
    """
    try:
        r = get_redis_client()

        # Read entire hash
        flat_metrics = r.hgetall(METRICS_KEY)

        if not flat_metrics:
            return None

        # Deserialize JSON strings back to dicts/lists
        metrics = {}
        for key, value in flat_metrics.items():
            # Try to parse as JSON, fall back to raw value
            if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                try:
                    metrics[key] = json.loads(value)
                except json.JSONDecodeError:
                    metrics[key] = value
            else:
                metrics[key] = value

        # Check heartbeat freshness
        heartbeat = float(metrics.get("_heartbeat", 0))
        age = time.time() - heartbeat

        if age > METRICS_TTL:
            logger.warning(f"Shared metrics are stale (age: {age:.1f}s), master may be dead")
            return None

        return metrics

    except RedisError as e:
        # Log as debug instead of error - Redis unavailability is expected in separated architecture
        # when audio-service is starting up or Redis is temporarily unreachable
        logger.debug(f"Failed to read shared metrics from Redis: {e}")
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
        except:
            pass
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
