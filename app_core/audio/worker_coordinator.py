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
    Slave Workers: Serve UI requests by reading shared metrics file

Coordination: File-based locking with heartbeat monitoring
Shared State: JSON file updated by master, read by all workers
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

# Shared state file location (world-readable, master-writable)
METRICS_FILE = "/tmp/eas-station-metrics.json"
MASTER_LOCK_FILE = "/tmp/eas-station-master.lock"
HEARTBEAT_INTERVAL = 5.0  # Master updates heartbeat every 5 seconds
STALE_HEARTBEAT_THRESHOLD = 15.0  # Consider master dead after 15 seconds

# Global master lock file descriptor (kept open to hold lock)
_master_lock_fd: Optional[int] = None
_is_master_worker: bool = False
_heartbeat_thread: Optional[threading.Thread] = None
_heartbeat_stop_flag: threading.Event = threading.Event()


class WorkerRole:
    """Worker roles in multi-worker setup."""
    MASTER = "master"  # Runs audio processing
    SLAVE = "slave"    # Only serves UI requests


def try_acquire_master_lock() -> bool:
    """
    Try to acquire the master worker lock.

    Uses file-based exclusive locking (LOCK_EX | LOCK_NB) to ensure only
    one worker across all processes can be master.

    Returns:
        True if this worker acquired master lock, False otherwise
    """
    global _master_lock_fd, _is_master_worker

    try:
        # Open lock file (create if doesn't exist)
        fd = os.open(MASTER_LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)

        # Try to acquire exclusive lock (non-blocking)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Success! We are the master
        _master_lock_fd = fd
        _is_master_worker = True

        # Write our PID to lock file
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode())

        logger.info(f"✅ Worker PID {os.getpid()} acquired MASTER lock")
        return True

    except (IOError, OSError) as e:
        # Lock held by another worker
        if fd is not None:
            try:
                os.close(fd)
            except:
                pass

        logger.info(f"Worker PID {os.getpid()} running as SLAVE (master lock held)")
        return False


def release_master_lock():
    """Release the master worker lock."""
    global _master_lock_fd, _is_master_worker

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
    Write metrics to shared file for all workers to read.

    Should only be called by master worker.

    Args:
        metrics: Dictionary of metrics to write
    """
    if not _is_master_worker:
        logger.warning("write_shared_metrics() called by non-master worker, ignoring")
        return

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
    Read metrics from shared file.

    Can be called by any worker to get latest metrics from master.

    Returns:
        Dictionary of metrics, or None if file doesn't exist or is stale
    """
    try:
        if not os.path.exists(METRICS_FILE):
            return None

        with open(METRICS_FILE, 'r') as f:
            metrics = json.load(f)

        # Check heartbeat freshness
        heartbeat = metrics.get("_heartbeat", 0)
        age = time.time() - heartbeat

        if age > STALE_HEARTBEAT_THRESHOLD:
            logger.warning(f"Shared metrics are stale (age: {age:.1f}s), master may be dead")
            return None

        return metrics

    except Exception as e:
        logger.error(f"Failed to read shared metrics: {e}")
        return None


def start_heartbeat_writer(metrics_getter_fn):
    """
    Start background thread that periodically writes metrics to shared file.

    Should only be called by master worker.

    Args:
        metrics_getter_fn: Callable that returns current metrics dict
    """
    global _heartbeat_thread

    if not _is_master_worker:
        logger.warning("start_heartbeat_writer() called by non-master worker, ignoring")
        return

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

    if _heartbeat_thread is not None:
        logger.info("Stopping heartbeat writer thread")
        _heartbeat_stop_flag.set()
        _heartbeat_thread.join(timeout=10)
        _heartbeat_thread = None


def cleanup_coordinator():
    """Cleanup coordinator resources (call on shutdown)."""
    stop_heartbeat_writer()
    release_master_lock()
