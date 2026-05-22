"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Common bootstrap scaffolding for the split hardware-side services.

The monolithic ``hardware_service.py`` is being broken up into one process
per hardware subsystem (GPIO, GPS, OLED, LED, VFD, Zigbee, indicators,
screens, network).  Every one of those services repeats the same startup
choreography:

* load environment from ``CONFIG_PATH`` (or the default ``.env``);
* configure logging with the alert-context filter;
* register SIGTERM/SIGINT handlers that flip a shutdown flag;
* apply glibc malloc tuning, start the periodic ``malloc_trim`` thread,
  install the on-demand memory-diagnostic signal handlers;
* connect to Redis with retry/backoff;
* build a minimal Flask + Flask-SQLAlchemy app for database access.

Pulling that scaffolding here keeps the per-service modules small and
guarantees they all behave identically at startup.

NOTE: This is a no-functional-change extraction — the helpers preserve the
exact behaviour previously inlined in ``hardware_service.main()`` and the
top-level module bootstrap.
"""

import logging
import os
import signal
import sys
from typing import Callable, Optional, Tuple

import redis
from dotenv import load_dotenv
from flask import Flask

from app_core.logging_context import LOG_FORMAT_WITH_ALERT, install_alert_filter
from app_utils.glibc_tuning import apply_glibc_tuning, start_malloc_trim_thread
from app_utils.memdiag import install_memdiag_handlers


_redis_client: Optional[redis.Redis] = None


def load_environment(logger: Optional[logging.Logger] = None) -> None:
    """Load environment variables from the persistent config volume.

    Mirrors the bootstrap block at the top of ``hardware_service.py``:
    honour ``CONFIG_PATH`` first, then fall back to the default ``.env``
    discovery path.  Always called with ``override=True`` because the
    systemd unit's ``EnvironmentFile=`` already populated ``os.environ``
    and we want the in-repo ``.env`` (the writable source of truth) to
    win.
    """
    log = logger or logging.getLogger(__name__)
    config_path = os.environ.get("CONFIG_PATH")
    if config_path:
        if os.path.exists(config_path):
            load_dotenv(config_path, override=True)
            log.info(f"✅ Loaded environment from: {config_path}")
            return
        log.warning(f"⚠️  CONFIG_PATH set but file not found: {config_path}")
    load_dotenv(override=True)


def configure_logging() -> logging.Logger:
    """Install the standard EAS Station log format and alert filter.

    Returns the root logger so the caller can keep using ``logging``
    module-level helpers without re-fetching.
    """
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT_WITH_ALERT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    install_alert_filter()
    return logging.getLogger()


def install_signal_handlers(on_shutdown: Callable[[int], None]) -> None:
    """Register SIGTERM and SIGINT handlers.

    ``on_shutdown(signum)`` is invoked from inside the handler so the
    caller can flip a process-local ``_running`` flag (or equivalent).
    """

    def _handler(signum, frame):  # noqa: ARG001 — frame is required by signal API
        on_shutdown(signum)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def init_runtime(
    service_name: str,
    *,
    arena_max: int = 2,
    trim_threshold: int = 131072,
    trim_interval_s: float = 60.0,
) -> None:
    """Apply glibc malloc tuning and install memory-diagnostic hooks.

    Must be called **before** any worker threads spawn — ``mallopt
    (M_ARENA_MAX)`` only constrains arenas created after the call.  The
    systemd unit sets the same caps via ``MALLOC_ARENA_MAX=2`` /
    ``MALLOC_TRIM_THRESHOLD_=131072`` (the fix from eb48eea that cut
    hardware-service RSS from 9.68 GB → 320 MB); applying them from
    inside the process makes the fix robust to unit-file drift.

    A periodic ``malloc_trim()`` ticker is started so freed top-of-heap
    memory actually returns to the kernel under sustained allocation.

    Memory diagnostics: ``kill -USR1 <pid>`` produces an RSS/heap dump,
    ``kill -USR2 <pid>`` produces an all-threads Python traceback.  Set
    ``MEMDIAG_TRACEMALLOC=1`` in the unit env to capture per-allocation
    tracebacks while reproducing a leak.
    """
    apply_glibc_tuning(arena_max=arena_max, trim_threshold=trim_threshold)
    start_malloc_trim_thread(interval_s=trim_interval_s)
    install_memdiag_handlers(service_name)


def get_redis() -> redis.Redis:
    """Get or create a process-wide Redis client with retry/backoff."""
    global _redis_client
    log = logging.getLogger(__name__)

    from app_core.redis_client import get_redis_client as get_robust_client

    try:
        _redis_client = get_robust_client(
            max_retries=5,
            initial_backoff=1.0,
            max_backoff=30.0,
        )
        return _redis_client
    except Exception as e:
        log.error(f"❌ Failed to connect to Redis: {e}")
        raise


def init_database() -> Tuple[Flask, "object"]:
    """Build the minimal Flask + SQLAlchemy app used for DB access.

    Returns ``(app, db)`` so the caller can ``app.app_context()`` around
    any work that needs the database.  Mirrors the old
    ``initialize_database()`` in ``hardware_service.py``.
    """
    from app_core.extensions import db

    app = Flask(__name__)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    db.init_app(app)
    return app, db
