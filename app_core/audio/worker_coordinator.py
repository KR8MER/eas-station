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
Multi-Worker Coordinator for Audio Processing

Ensures only ONE worker across all Gunicorn processes handles audio ingestion
and EAS monitoring, while all workers can serve UI requests by reading shared state.

Architecture:
    Master Worker: Runs audio controller, broadcast pump, EAS monitor
    Slave Workers: Serve UI requests by reading shared metrics

Coordination Strategy (with automatic fallback):
    1. Try Redis-based coordination (preferred, robust, fast)
    2. Fall back to file-based if Redis unavailable

Redis Mode (default):
    - Distributed locks with TTL (automatic failover)
    - In-memory state (100x faster than files)
    - Pub/Sub for real-time updates
    - Atomic operations (no race conditions)

File Mode (fallback):
    - File-based locking with fcntl
    - JSON file for shared state
    - Periodic polling for updates
    - Used when Redis unavailable
"""

import os
import json
import time
import logging
import fcntl
import threading
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Redis is now REQUIRED for worker coordination in separated architecture.
# File-based fallbacks have been removed as they don't work in containerized environments
# where /tmp is ephemeral per container.
_USE_REDIS = True
_redis_coordinator = None

try:
    from . import worker_coordinator_redis
    _redis_coordinator = worker_coordinator_redis
    logger.info("✅ Redis-based worker coordinator available")
except ImportError as e:
    logger.error(f"❌ CRITICAL: Redis not available for worker coordination: {e}")
    logger.error("   Redis is REQUIRED in separated architecture")
    logger.error("   Set REDIS_HOST and REDIS_PORT environment variables")
    _USE_REDIS = False
    # Don't raise here - let functions fail explicitly when called

# Constants
HEARTBEAT_INTERVAL = 5.0  # Master updates heartbeat every 5 seconds
STALE_HEARTBEAT_THRESHOLD = 15.0  # Consider master dead after 15 seconds

# File-based fallback paths (used when Redis is unavailable)
METRICS_FILE = "/tmp/eas_station_shared_metrics.json"

# Global state
_is_master_worker: bool = False
_heartbeat_thread: Optional[threading.Thread] = None
_heartbeat_stop_flag: threading.Event = threading.Event()

# Note: File-based fallbacks (METRICS_FILE, MASTER_LOCK_FILE, _master_lock_fd) removed.
# These don't work reliably in containerized environments.


class WorkerRole:
    """Worker roles in multi-worker setup."""
    MASTER = "master"  # Runs audio processing
    SLAVE = "slave"    # Only serves UI requests


def try_acquire_master_lock() -> bool:
    """
    Try to acquire the master worker lock using Redis.

    Returns:
        True if this worker acquired master lock, False otherwise

    Raises:
        RuntimeError: If Redis is not available
    """
    global _is_master_worker

    if not _USE_REDIS or not _redis_coordinator:
        raise RuntimeError(
            "Redis is required for worker coordination. "
            "Set REDIS_HOST and REDIS_PORT environment variables."
        )

    try:
        result = _redis_coordinator.try_acquire_master_lock()
        _is_master_worker = result
        return result
    except Exception as e:
        logger.error(f"Failed to acquire master lock via Redis: {e}")
        raise


def release_master_lock():
    """Release the master worker lock."""
    global _master_lock_fd, _is_master_worker

    # Try Redis first
    if _USE_REDIS and _redis_coordinator:
        try:
            _redis_coordinator.release_master_lock()
            _is_master_worker = False
            return
        except Exception as e:
            logger.error(f"Redis coordinator failed during release: {e}")
            # Fall through to file-based

    if _master_lock_fd is not None:
        try:
            fcntl.flock(_master_lock_fd, fcntl.LOCK_UN)
            os.close(_master_lock_fd)
            logger.info(f"Worker PID {os.getpid()} released master lock")
        except Exception as e:
            logger.error(f"Error releasing master lock: {e}")
        finally:
            _master_lock_fd = None
            _is_master_worker = False


def is_master_worker() -> bool:
    """Check if this worker is the master."""
    return _is_master_worker


def write_shared_metrics(metrics: Dict[str, Any]):
    """
    Write metrics to shared storage for all workers to read.

    Uses Redis if available, otherwise writes to file.
    Should only be called by master worker.

    Args:
        metrics: Dictionary of metrics to write
    """
    if not _is_master_worker:
        logger.warning("write_shared_metrics() called by non-master worker, ignoring")
        return

    # Try Redis first
    if _USE_REDIS and _redis_coordinator:
        try:
            _redis_coordinator.write_shared_metrics(metrics)
            return
        except Exception as e:
            logger.error(f"Redis write failed, falling back to file: {e}")
            # Fall through to file-based

    try:
        # Add heartbeat timestamp
        metrics["_heartbeat"] = time.time()
        metrics["_master_pid"] = os.getpid()

        # Write atomically using temp file + rename
        temp_file = f"{METRICS_FILE}.tmp.{os.getpid()}"
        with open(temp_file, 'w') as f:
            json.dump(metrics, f, indent=2)

        # Atomic rename (overwrites old file)
        os.rename(temp_file, METRICS_FILE)

    except Exception as e:
        logger.error(f"Failed to write shared metrics: {e}")


def read_shared_metrics() -> Optional[Dict[str, Any]]:
    """
    Read metrics from Redis shared storage.

    Can be called by any worker to get latest metrics from master.

    Returns:
        Dictionary of metrics, or None if not available or stale

    Raises:
        RuntimeError: If Redis is not available
    """
    if not _USE_REDIS or not _redis_coordinator:
        raise RuntimeError(
            "Redis is required for metrics storage. "
            "Set REDIS_HOST and REDIS_PORT environment variables."
        )

    try:
        return _redis_coordinator.read_shared_metrics()
    except Exception as e:
        logger.error(f"Failed to read shared metrics from Redis: {e}")
        return None


def start_heartbeat_writer(metrics_getter_fn):
    """
    Start background thread that periodically writes metrics to shared storage.

    Uses Redis if available (with lock refresh), otherwise uses file-based.
    Should only be called by master worker.

    Args:
        metrics_getter_fn: Callable that returns current metrics dict
    """
    global _heartbeat_thread

    if not _is_master_worker:
        logger.warning("start_heartbeat_writer() called by non-master worker, ignoring")
        return

    # Try Redis first
    if _USE_REDIS and _redis_coordinator:
        try:
            _redis_coordinator.start_heartbeat_writer(metrics_getter_fn)
            return
        except Exception as e:
            logger.error(f"Redis heartbeat writer failed, falling back to file-based: {e}")
            # Fall through to file-based

    def heartbeat_loop():
        """Background thread that writes metrics every few seconds."""
        logger.info("Master worker heartbeat thread started")

        while not _heartbeat_stop_flag.wait(timeout=HEARTBEAT_INTERVAL):
            try:
                metrics = metrics_getter_fn()
                if metrics:
                    write_shared_metrics(metrics)
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")

        logger.info("Master worker heartbeat thread stopped")

    _heartbeat_stop_flag.clear()
    _heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True, name="MetricsHeartbeat")
    _heartbeat_thread.start()
    logger.info("Started heartbeat writer thread")


def stop_heartbeat_writer():
    """Stop the heartbeat writer thread."""
    global _heartbeat_thread

    # Try Redis first
    if _USE_REDIS and _redis_coordinator:
        try:
            _redis_coordinator.stop_heartbeat_writer()
        except Exception as e:
            logger.error(f"Error stopping Redis heartbeat: {e}")

    if _heartbeat_thread is not None:
        logger.info("Stopping heartbeat writer thread")
        _heartbeat_stop_flag.set()
        _heartbeat_thread.join(timeout=10)
        _heartbeat_thread = None


def cleanup_coordinator():
    """Cleanup coordinator resources (call on shutdown)."""
    stop_heartbeat_writer()
    release_master_lock()

    # Cleanup Redis connection if using Redis
    if _USE_REDIS and _redis_coordinator:
        try:
            _redis_coordinator.cleanup_coordinator()
        except Exception as e:
            logger.error(f"Error cleaning up Redis coordinator: {e}")
