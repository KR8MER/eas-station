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

"""Received-alert purge service.

The "Received Alerts" history (``received_eas_alerts``) accumulates one row
per EAS header decoded from an OTA / streaming monitor.  A noisy source can
produce thousands of rows, each carrying a raw WAV blob in
``raw_audio_data`` that is by far the biggest storage cost.

This module provides a single place to purge those records, by:

* age (older than N days),
* source (``source_name`` or ``alert_source``),
* forwarding decision (e.g. everything that was NOT forwarded),
* or any combination of the above.

Two scopes are supported:

* ``audio`` — strip only the ``raw_audio_data`` blob, keeping the row so the
  FCC Part 11 compliance log still reflects the reception.
* ``full``  — delete the entire row.  Optionally also deletes the generated
  EAS broadcast message (and its on-disk audio files) that a forwarded alert
  produced, so no instance of the audio remains anywhere.

The same primitives back both the manual admin action and the scheduled
auto-purge (:class:`AutoPurgeScheduler`).  Every purge writes a ``SystemLog``
audit entry — purging alerts never purges logs.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_

from app_core.extensions import db
from app_utils import utc_now

logger = logging.getLogger(__name__)

# Purge scopes
SCOPE_AUDIO = "audio"   # Strip raw_audio_data, keep the compliance record
SCOPE_FULL = "full"     # Delete the entire received_eas_alerts row
VALID_SCOPES = (SCOPE_AUDIO, SCOPE_FULL)

# Forwarding-decision filters accepted by build_filters().
DECISION_ANY = "any"
DECISION_NOT_FORWARDED = "not_forwarded"
DECISION_FORWARDED = "forwarded"
DECISION_IGNORED = "ignored"
DECISION_ERROR = "error"
VALID_DECISION_FILTERS = (
    DECISION_ANY,
    DECISION_NOT_FORWARDED,
    DECISION_FORWARDED,
    DECISION_IGNORED,
    DECISION_ERROR,
)

_MAX_AGE_DAYS = 3650


# ---------------------------------------------------------------------------
# Criteria helpers
# ---------------------------------------------------------------------------

def normalize_criteria(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise a raw criteria mapping.

    Accepts the keys ``older_than_days``, ``source``, ``decision``,
    ``event_code``, ``scope`` and ``delete_generated_messages`` and returns a
    cleaned dict.  Raises ``ValueError`` on invalid input.
    """
    criteria: Dict[str, Any] = {}

    age = raw.get("older_than_days")
    if age in (None, ""):
        criteria["older_than_days"] = None
    else:
        try:
            age_int = int(age)
        except (TypeError, ValueError):
            raise ValueError("Days must be a whole number")
        if age_int < 0 or age_int > _MAX_AGE_DAYS:
            raise ValueError(f"Days must be between 0 and {_MAX_AGE_DAYS}")
        criteria["older_than_days"] = age_int or None

    source = (raw.get("source") or "").strip()
    criteria["source"] = source or None

    decision = (raw.get("decision") or DECISION_ANY).strip().lower()
    if decision not in VALID_DECISION_FILTERS:
        raise ValueError(f"Invalid decision filter: {decision}")
    criteria["decision"] = decision

    event_code = (raw.get("event_code") or "").strip().upper()
    criteria["event_code"] = event_code or None

    scope = (raw.get("scope") or SCOPE_FULL).strip().lower()
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid scope: {scope}")
    criteria["scope"] = scope

    criteria["delete_generated_messages"] = _as_bool(
        raw.get("delete_generated_messages")
    )
    return criteria


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_filters(criteria: Dict[str, Any], now: Optional[datetime] = None) -> List[Any]:
    """Translate a normalised *criteria* dict into SQLAlchemy filter clauses."""
    from app_core._models_alerts import ReceivedEASAlert

    filters: List[Any] = []

    age = criteria.get("older_than_days")
    if age:
        cutoff = (now or utc_now()) - timedelta(days=int(age))
        filters.append(ReceivedEASAlert.received_at < cutoff)

    source = criteria.get("source")
    if source:
        filters.append(
            or_(
                ReceivedEASAlert.source_name == source,
                ReceivedEASAlert.alert_source == source,
            )
        )

    decision = criteria.get("decision", DECISION_ANY)
    if decision == DECISION_NOT_FORWARDED:
        filters.append(ReceivedEASAlert.forwarding_decision != DECISION_FORWARDED)
    elif decision in (DECISION_FORWARDED, DECISION_IGNORED, DECISION_ERROR):
        filters.append(ReceivedEASAlert.forwarding_decision == decision)

    event_code = criteria.get("event_code")
    if event_code:
        filters.append(ReceivedEASAlert.event_code == event_code)

    return filters


def _has_any_criteria(criteria: Dict[str, Any]) -> bool:
    """True when at least one selective criterion is present.

    Guards against an empty criteria set wiping the whole table by accident.
    """
    return bool(
        criteria.get("older_than_days")
        or criteria.get("source")
        or (criteria.get("decision") and criteria["decision"] != DECISION_ANY)
        or criteria.get("event_code")
    )


# ---------------------------------------------------------------------------
# Preview / stats
# ---------------------------------------------------------------------------

def preview_purge(criteria: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return counts and byte totals for the alerts *criteria* would purge."""
    from app_core._models_alerts import ReceivedEASAlert

    filters = build_filters(criteria, now=now)
    base = db.session.query(ReceivedEASAlert).filter(*filters)

    matching = base.count()
    audio_count = base.filter(ReceivedEASAlert.raw_audio_data.isnot(None)).count()
    audio_bytes = (
        db.session.query(
            func.coalesce(func.sum(func.length(ReceivedEASAlert.raw_audio_data)), 0)
        )
        .filter(*filters)
        .scalar()
        or 0
    )
    return {
        "matching_count": int(matching),
        "audio_count": int(audio_count),
        "audio_bytes": int(audio_bytes),
        "audio_bytes_human": human_bytes(int(audio_bytes)),
    }


def get_storage_stats() -> Dict[str, Any]:
    """Return overall received-alert storage statistics for the admin page."""
    from app_core._models_alerts import ReceivedEASAlert

    total = db.session.query(func.count(ReceivedEASAlert.id)).scalar() or 0
    with_audio = (
        db.session.query(func.count(ReceivedEASAlert.id))
        .filter(ReceivedEASAlert.raw_audio_data.isnot(None))
        .scalar()
        or 0
    )
    audio_bytes = (
        db.session.query(
            func.coalesce(func.sum(func.length(ReceivedEASAlert.raw_audio_data)), 0)
        ).scalar()
        or 0
    )

    by_decision = {
        row[0]: int(row[1])
        for row in db.session.query(
            ReceivedEASAlert.forwarding_decision, func.count(ReceivedEASAlert.id)
        ).group_by(ReceivedEASAlert.forwarding_decision)
    }

    return {
        "total": int(total),
        "with_audio": int(with_audio),
        "audio_bytes": int(audio_bytes),
        "audio_bytes_human": human_bytes(int(audio_bytes)),
        "forwarded": by_decision.get("forwarded", 0),
        "ignored": by_decision.get("ignored", 0),
        "error": by_decision.get("error", 0),
    }


def get_sources() -> List[str]:
    """Return the distinct source identifiers present in received alerts."""
    from app_core._models_alerts import ReceivedEASAlert

    names = {
        row[0]
        for row in db.session.query(ReceivedEASAlert.source_name).distinct()
        if row[0]
    }
    names.update(
        row[0]
        for row in db.session.query(ReceivedEASAlert.alert_source).distinct()
        if row[0]
    )
    return sorted(names)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_purge(
    criteria: Dict[str, Any],
    *,
    actor: str = "system",
    trigger: str = "manual",
    require_criteria: bool = True,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Purge received alerts matching *criteria* and write an audit log.

    Must be called inside a Flask app context.  Returns a summary dict.
    """
    from app_core._models_alerts import EASMessage, ReceivedEASAlert
    from app_core._models_admin import SystemLog

    if require_criteria and not _has_any_criteria(criteria):
        raise ValueError(
            "Refusing to purge with no criteria — set an age, source, "
            "decision, or event code."
        )

    scope = criteria.get("scope", SCOPE_FULL)
    delete_messages = bool(criteria.get("delete_generated_messages")) and scope == SCOPE_FULL
    filters = build_filters(criteria, now=now)

    # Measure before mutating so the summary reflects what was reclaimed.
    audio_bytes = (
        db.session.query(
            func.coalesce(func.sum(func.length(ReceivedEASAlert.raw_audio_data)), 0)
        )
        .filter(*filters)
        .scalar()
        or 0
    )

    summary: Dict[str, Any] = {
        "scope": scope,
        "trigger": trigger,
        "actor": actor,
        "rows_deleted": 0,
        "audio_stripped": 0,
        "audio_bytes_freed": int(audio_bytes),
        "audio_bytes_freed_human": human_bytes(int(audio_bytes)),
        "messages_deleted": 0,
        "criteria": _summarize_criteria(criteria),
    }

    try:
        if scope == SCOPE_AUDIO:
            stripped = (
                db.session.query(ReceivedEASAlert)
                .filter(*filters, ReceivedEASAlert.raw_audio_data.isnot(None))
                .update({ReceivedEASAlert.raw_audio_data: None}, synchronize_session=False)
            )
            summary["audio_stripped"] = int(stripped or 0)
        else:
            message_ids: List[int] = []
            if delete_messages:
                message_ids = [
                    row[0]
                    for row in db.session.query(ReceivedEASAlert.generated_message_id)
                    .filter(*filters, ReceivedEASAlert.generated_message_id.isnot(None))
                    .distinct()
                ]

            deleted = (
                db.session.query(ReceivedEASAlert)
                .filter(*filters)
                .delete(synchronize_session=False)
            )
            summary["rows_deleted"] = int(deleted or 0)

            if message_ids:
                summary["messages_deleted"] = _delete_orphaned_messages(
                    message_ids, EASMessage, ReceivedEASAlert
                )

        db.session.add(
            SystemLog(
                level="INFO",
                message=(
                    f"Received-alert purge ({trigger}): "
                    f"{summary['rows_deleted']} deleted, "
                    f"{summary['audio_stripped']} audio stripped, "
                    f"{summary['audio_bytes_freed_human']} freed"
                ),
                module="alert_purge",
                details=summary,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.error("Received-alert purge failed", exc_info=True)
        raise

    logger.info(
        "Received-alert purge complete (%s by %s): rows=%d audio_stripped=%d "
        "messages=%d bytes_freed=%d",
        trigger,
        actor,
        summary["rows_deleted"],
        summary["audio_stripped"],
        summary["messages_deleted"],
        summary["audio_bytes_freed"],
    )
    return summary


def _delete_orphaned_messages(message_ids, EASMessage, ReceivedEASAlert) -> int:
    """Delete generated EAS messages no longer referenced by any alert.

    Also removes the message's on-disk audio/text artifacts.  Runs after the
    received-alert rows have been deleted so reference checks are accurate.
    """
    from app_core.eas_storage import remove_eas_files

    deleted = 0
    for mid in message_ids:
        still_referenced = (
            db.session.query(ReceivedEASAlert.id)
            .filter(ReceivedEASAlert.generated_message_id == mid)
            .first()
        )
        if still_referenced:
            continue
        message = db.session.get(EASMessage, mid)
        if message is None:
            continue
        try:
            remove_eas_files(message)
        except Exception:  # pragma: no cover - best-effort file cleanup
            logger.warning("Could not remove files for EAS message %s", mid, exc_info=True)
        db.session.delete(message)
        deleted += 1
    return deleted


def _summarize_criteria(criteria: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "older_than_days": criteria.get("older_than_days"),
        "source": criteria.get("source"),
        "decision": criteria.get("decision", DECISION_ANY),
        "event_code": criteria.get("event_code"),
        "scope": criteria.get("scope", SCOPE_FULL),
        "delete_generated_messages": bool(criteria.get("delete_generated_messages")),
    }


def human_bytes(num: int) -> str:
    """Format a byte count as a human-readable string."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


# ---------------------------------------------------------------------------
# Auto-purge settings + scheduled run
# ---------------------------------------------------------------------------

def get_auto_purge_settings():
    """Get or create the singleton auto-purge settings record (id=1)."""
    from app_core._models_settings import AutoPurgeSettings

    settings = db.session.get(AutoPurgeSettings, 1)
    if settings is None:
        settings = AutoPurgeSettings(id=1)
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default auto-purge settings")
    return settings


def update_auto_purge_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and merge *updates* into the auto-purge settings row."""
    settings = get_auto_purge_settings()

    if "enabled" in updates:
        settings.enabled = _as_bool(updates["enabled"])

    if "max_age_days" in updates:
        try:
            value = int(updates["max_age_days"])
        except (TypeError, ValueError):
            raise ValueError("max_age_days must be an integer number of days")
        if value < 0 or value > _MAX_AGE_DAYS:
            raise ValueError(f"max_age_days must be between 0 and {_MAX_AGE_DAYS}")
        settings.max_age_days = value

    if "scope" in updates:
        scope = str(updates["scope"]).strip().lower()
        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope: {scope}")
        settings.scope = scope

    if "decision_filter" in updates:
        decision = str(updates["decision_filter"]).strip().lower()
        if decision not in VALID_DECISION_FILTERS:
            raise ValueError(f"Invalid decision filter: {decision}")
        settings.decision_filter = decision

    if "source_filter" in updates:
        source = (updates.get("source_filter") or "").strip()
        settings.source_filter = source or None

    if "delete_generated_messages" in updates:
        settings.delete_generated_messages = _as_bool(updates["delete_generated_messages"])

    settings.updated_at = utc_now()
    db.session.commit()
    return settings.to_dict()


def settings_to_criteria(settings) -> Dict[str, Any]:
    """Build a normalised purge-criteria dict from an AutoPurgeSettings row."""
    return {
        "older_than_days": settings.max_age_days or None,
        "source": settings.source_filter or None,
        "decision": settings.decision_filter or DECISION_ANY,
        "event_code": None,
        "scope": settings.scope or SCOPE_FULL,
        "delete_generated_messages": bool(settings.delete_generated_messages),
    }


def run_auto_purge(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Run one auto-purge cycle from saved settings (inside an app context)."""
    settings = get_auto_purge_settings()
    if not settings.enabled:
        return {"skipped": True, "reason": "disabled"}
    if not settings.max_age_days:
        return {"skipped": True, "reason": "max_age_days is 0 (keep forever)"}

    criteria = settings_to_criteria(settings)
    summary = execute_purge(
        criteria,
        actor="auto-purge",
        trigger="auto",
        require_criteria=True,
        now=now,
    )

    settings.last_run_at = now or utc_now()
    settings.last_run_summary = summary
    db.session.commit()
    return summary


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

SWEEP_INTERVAL_SECONDS = 6 * 3600
STARTUP_DELAY_SECONDS = 180


class AutoPurgeScheduler:
    """Daemon thread that runs the auto-purge a few minutes after startup
    and then every six hours.  Settings are re-read from the database on
    every cycle, so admin changes take effect without a restart.
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
            name="auto-purge-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Auto-purge scheduler started (interval=%ss, first run in %ss)",
            self._interval,
            self._startup_delay,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Auto-purge scheduler stopped")

    def run_now(self) -> Dict[str, Any]:
        with self._app.app_context():
            return run_auto_purge()

    def _run(self) -> None:
        if self._stop_event.wait(self._startup_delay):
            return
        while not self._stop_event.is_set():
            try:
                self.run_now()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Auto-purge run failed: %s", exc, exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass
            self._stop_event.wait(self._interval)


_scheduler_instance: Optional[AutoPurgeScheduler] = None
_scheduler_lock = threading.Lock()


def start_scheduler(app) -> AutoPurgeScheduler:
    """Start the global auto-purge scheduler (idempotent)."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.is_running:
            return _scheduler_instance
        scheduler = AutoPurgeScheduler(app)
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
    "AutoPurgeScheduler",
    "SCOPE_AUDIO",
    "SCOPE_FULL",
    "VALID_DECISION_FILTERS",
    "VALID_SCOPES",
    "build_filters",
    "execute_purge",
    "get_auto_purge_settings",
    "get_sources",
    "get_storage_stats",
    "human_bytes",
    "normalize_criteria",
    "preview_purge",
    "run_auto_purge",
    "settings_to_criteria",
    "start_scheduler",
    "stop_scheduler",
    "update_auto_purge_settings",
]
