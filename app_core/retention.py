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

from __future__ import annotations

"""Automated data-retention sweeper for EAS Station.

Broadcast audio archives already have their own retention (see
``app_core/audio/archiver.py``).  This module covers everything else that
grows without bound:

* Raw IQ capture files (``*.npy``) written by ``sdr_hardware_service.py``
  to ``RADIO_CAPTURE_DIR`` (default ``/var/log/eas-station/captures``).
* Debug audio written to ``/tmp/eas-audio`` when ``EAS_SAVE_AUDIO_FILES``
  is enabled (previously cleaned by a manual ``find -mtime +7 -delete``,
  see docs/maintenance/DISK_SPACE_CLEANUP.md).
* Database tables: ``stream_metadata_log``, ``audio_alerts``,
  ``audio_source_metrics``.
* ``received_eas_alerts.raw_audio_data`` blobs.  Only the audio payload is
  stripped — the alert rows themselves are compliance history and are
  NEVER deleted.

Policies live in the single-row ``retention_settings`` table
(:class:`app_core._models_settings.RetentionSettings`).  A value of ``0``
for any age field means "disabled / keep forever".

A :class:`RetentionScheduler` daemon thread runs a sweep shortly after
startup and then every six hours; it is wired into ``app.py`` next to the
auto-backup scheduler via :func:`start_scheduler`.
"""

import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app_core.extensions import db
from app_core._models_settings import RetentionSettings
from app_utils import utc_now

logger = logging.getLogger(__name__)

# Same env default as sdr_hardware_service.py / webapp/routes_settings_radio.py.
DEFAULT_CAPTURE_DIR = "/var/log/eas-station/captures"

# No EAS_TEMP_AUDIO_DIR env exists in the codebase; the debug-audio writers
# and docs/maintenance/DISK_SPACE_CLEANUP.md both use this fixed path.
TEMP_AUDIO_DIR = "/tmp/eas-audio"

SWEEP_INTERVAL_SECONDS = 6 * 3600
STARTUP_DELAY_SECONDS = 120

# Day-count fields accepted by update_retention_settings().
RETENTION_AGE_FIELDS = (
    "iq_capture_max_age_days",
    "temp_audio_max_age_days",
    "stream_metadata_max_age_days",
    "audio_alert_max_age_days",
    "audio_metrics_max_age_days",
    "received_alert_audio_max_age_days",
)

_MAX_AGE_DAYS = 3650


def _capture_dir() -> str:
    return os.environ.get("RADIO_CAPTURE_DIR", DEFAULT_CAPTURE_DIR)


# ---------------------------------------------------------------------------
# Settings accessors (single row id=1, same pattern as hardware_settings)
# ---------------------------------------------------------------------------

def get_retention_settings() -> RetentionSettings:
    """Get or create the singleton retention settings record (id=1)."""
    settings = db.session.get(RetentionSettings, 1)
    if settings is None:
        settings = RetentionSettings(id=1)
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default retention settings")
    return settings


def update_retention_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and merge *updates* into the settings row.

    Returns the new settings as a dict.  Unknown keys are ignored; age
    fields are clamped to 0..3650 days (0 = keep forever).
    """
    settings = get_retention_settings()

    if "enabled" in updates:
        settings.enabled = bool(updates["enabled"])

    for field in RETENTION_AGE_FIELDS:
        if field not in updates:
            continue
        try:
            value = int(updates[field])
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be an integer number of days")
        if value < 0 or value > _MAX_AGE_DAYS:
            raise ValueError(
                f"{field} must be between 0 and {_MAX_AGE_DAYS} (0 = keep forever)"
            )
        setattr(settings, field, value)

    settings.updated_at = utc_now()
    db.session.commit()
    return settings.to_dict()


# ---------------------------------------------------------------------------
# Sweep primitives
# ---------------------------------------------------------------------------

def compute_cutoff(max_age_days: Any, now: Optional[datetime] = None) -> Optional[datetime]:
    """Return the UTC cutoff for *max_age_days*, or None when disabled (<= 0)."""
    try:
        days = int(max_age_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return (now or utc_now()) - timedelta(days=days)


def prune_directory(
    directory: str,
    max_age_days: Any,
    pattern: str = "*",
    now: Optional[datetime] = None,
) -> Tuple[int, int]:
    """Delete files matching *pattern* in *directory* older than the cutoff.

    Returns ``(files_removed, bytes_removed)``.  Missing directories and a
    disabled (0) retention age are no-ops.  Only regular files are touched;
    subdirectories are left alone.
    """
    cutoff = compute_cutoff(max_age_days, now=now)
    if cutoff is None:
        return 0, 0

    root = Path(directory)
    if not root.is_dir():
        return 0, 0

    cutoff_ts = cutoff.timestamp()
    files_removed = 0
    bytes_removed = 0
    for path in root.glob(pattern):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
            if stat.st_mtime >= cutoff_ts:
                continue
            size = stat.st_size
            path.unlink()
            files_removed += 1
            bytes_removed += size
        except OSError as exc:
            logger.warning("Retention: could not remove %s: %s", path, exc)
    return files_removed, bytes_removed


def _prune_table(model, column, max_age_days: Any, now: Optional[datetime] = None) -> int:
    """Bulk-delete rows of *model* whose *column* is older than the cutoff."""
    cutoff = compute_cutoff(max_age_days, now=now)
    if cutoff is None:
        return 0
    deleted = (
        db.session.query(model)
        .filter(column < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return int(deleted or 0)


def strip_received_alert_audio(max_age_days: Any, now: Optional[datetime] = None) -> int:
    """NULL out ``raw_audio_data`` on old received_eas_alerts rows.

    The rows themselves are compliance history and are never deleted —
    only the raw audio blob is dropped to reclaim space.
    """
    from app_core._models_alerts import ReceivedEASAlert

    cutoff = compute_cutoff(max_age_days, now=now)
    if cutoff is None:
        return 0
    stripped = (
        db.session.query(ReceivedEASAlert)
        .filter(
            ReceivedEASAlert.received_at < cutoff,
            ReceivedEASAlert.raw_audio_data.isnot(None),
        )
        .update({ReceivedEASAlert.raw_audio_data: None}, synchronize_session=False)
    )
    db.session.commit()
    return int(stripped or 0)


def run_sweep(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Run every retention step once.  Must be called inside an app context.

    Each step is guarded so one failure does not stop the others; a summary
    line with files/rows/bytes removed is logged at the end.
    """
    from app_core._models_audio import (
        AudioAlert,
        AudioSourceMetrics,
        StreamMetadataLog,
    )

    summary: Dict[str, Any] = {
        "iq_files_removed": 0,
        "temp_files_removed": 0,
        "bytes_removed": 0,
        "stream_metadata_rows_deleted": 0,
        "audio_alert_rows_deleted": 0,
        "audio_metrics_rows_deleted": 0,
        "received_alert_audio_stripped": 0,
        "errors": [],
    }

    def _guard(step_name, func):
        try:
            return func()
        except Exception as exc:
            logger.error("Retention step %s failed: %s", step_name, exc, exc_info=True)
            summary["errors"].append(f"{step_name}: {exc}")
            try:
                db.session.rollback()
            except Exception:
                pass
            return None

    # a. IQ captures (*.npy in RADIO_CAPTURE_DIR)
    result = _guard(
        "iq_captures",
        lambda: prune_directory(
            _capture_dir(), settings.get("iq_capture_max_age_days"), pattern="*.npy"
        ),
    )
    if result:
        summary["iq_files_removed"] = result[0]
        summary["bytes_removed"] += result[1]

    # b. Temp debug audio (/tmp/eas-audio)
    result = _guard(
        "temp_audio",
        lambda: prune_directory(
            TEMP_AUDIO_DIR, settings.get("temp_audio_max_age_days")
        ),
    )
    if result:
        summary["temp_files_removed"] = result[0]
        summary["bytes_removed"] += result[1]

    # c. Fast-growing DB tables
    deleted = _guard(
        "stream_metadata_log",
        lambda: _prune_table(
            StreamMetadataLog,
            StreamMetadataLog.timestamp,
            settings.get("stream_metadata_max_age_days"),
        ),
    )
    if deleted:
        summary["stream_metadata_rows_deleted"] = deleted

    deleted = _guard(
        "audio_alerts",
        lambda: _prune_table(
            AudioAlert,
            AudioAlert.created_at,
            settings.get("audio_alert_max_age_days"),
        ),
    )
    if deleted:
        summary["audio_alert_rows_deleted"] = deleted

    deleted = _guard(
        "audio_source_metrics",
        lambda: _prune_table(
            AudioSourceMetrics,
            AudioSourceMetrics.timestamp,
            settings.get("audio_metrics_max_age_days"),
        ),
    )
    if deleted:
        summary["audio_metrics_rows_deleted"] = deleted

    # d. Strip raw audio blobs from old received alerts (rows preserved)
    stripped = _guard(
        "received_alert_audio",
        lambda: strip_received_alert_audio(
            settings.get("received_alert_audio_max_age_days")
        ),
    )
    if stripped:
        summary["received_alert_audio_stripped"] = stripped

    logger.info(
        "Retention sweep complete: %d IQ file(s) + %d temp file(s) removed "
        "(%d bytes), rows deleted: stream_metadata=%d audio_alerts=%d "
        "audio_metrics=%d, audio blobs stripped=%d, errors=%d",
        summary["iq_files_removed"],
        summary["temp_files_removed"],
        summary["bytes_removed"],
        summary["stream_metadata_rows_deleted"],
        summary["audio_alert_rows_deleted"],
        summary["audio_metrics_rows_deleted"],
        summary["received_alert_audio_stripped"],
        len(summary["errors"]),
    )
    return summary


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

class RetentionScheduler:
    """Daemon thread that runs a retention sweep every six hours.

    The first sweep runs roughly two minutes after startup so a freshly
    booted station reclaims space quickly without slowing app start.
    Settings are re-read from the database inside an app context on every
    sweep, so admin changes take effect without a restart.
    """

    def __init__(
        self,
        app,
        interval_seconds: int = SWEEP_INTERVAL_SECONDS,
        startup_delay_seconds: int = STARTUP_DELAY_SECONDS,
    ) -> None:
        self._app = app
        self._interval = max(int(interval_seconds), 60)
        self._startup_delay = max(int(startup_delay_seconds), 0)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="retention-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Retention scheduler started (interval=%ss, first sweep in %ss)",
            self._interval,
            self._startup_delay,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Retention scheduler stopped")

    def run_sweep_now(self) -> Dict[str, Any]:
        """Run a single sweep immediately (used by the loop and tests)."""
        with self._app.app_context():
            settings = get_retention_settings()
            if not settings.enabled:
                logger.debug("Retention sweep skipped: retention disabled")
                return {"skipped": True, "reason": "disabled"}
            return run_sweep(settings.to_dict())

    def _run(self) -> None:
        if self._stop_event.wait(self._startup_delay):
            return
        while not self._stop_event.is_set():
            try:
                self.run_sweep_now()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Retention sweep failed: %s", exc, exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass
            self._stop_event.wait(self._interval)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_scheduler_instance: Optional[RetentionScheduler] = None
_scheduler_lock = threading.Lock()


def start_scheduler(app) -> RetentionScheduler:
    """Start the global retention scheduler (idempotent)."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.is_running:
            return _scheduler_instance
        scheduler = RetentionScheduler(app)
        scheduler.start()
        _scheduler_instance = scheduler
        return scheduler


def stop_scheduler() -> None:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None:
            _scheduler_instance.stop()
            _scheduler_instance = None


__all__ = [
    "RetentionScheduler",
    "compute_cutoff",
    "get_retention_settings",
    "prune_directory",
    "run_sweep",
    "start_scheduler",
    "stop_scheduler",
    "strip_received_alert_audio",
    "update_retention_settings",
]
