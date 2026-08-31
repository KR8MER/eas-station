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

from __future__ import annotations

"""Health of the CAP poller — the process that feeds everything else."""

from datetime import timedelta
from typing import Any, Dict, Sequence

from app_core.models import PollHistory
from app_utils import utc_now

from .common import StatsSection

# Statuses that count as a healthy run. A run is only successful if it *also*
# carries no error message — a poll can report "success" and still have failed
# partway through, and counting those as healthy overstates the success rate.
SUCCESS_VALUES = {"success", "ok", "completed"}

# How many recent runs the success-rate figures are computed over.
POLL_HISTORY_WINDOW = 200

# How many of those runs are listed individually in the UI.
RECENT_RUN_LIMIT = 10

TREND_SHORT_DAYS = 7
TREND_LONG_DAYS = 30
P95 = 0.95

EMPTY_POLLING = {
    "success_rate": 0,
    "total_runs": 0,
    "failed_runs": 0,
    "recent_runs": [],
    "total_polls": 0,
    "successful_polls": 0,
    "failed_polls": 0,
    "avg_time_ms": 0,
}

EMPTY_TREND = {
    "rate_7d": 0,
    "rate_30d": 0,
    "count_7d": 0,
    "count_30d": 0,
    "p95_execution_ms": 0,
}


def _is_success(record) -> bool:
    return (record.status or "").lower() in SUCCESS_VALUES and not record.error_message


def collect_polling(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Success rate, timing and the most recent runs.

    The payload carries each figure under two names — ``total_runs`` and
    ``total_polls``, ``average_execution_ms`` and ``avg_time_ms`` — because the
    template and the charts grew different vocabularies for the same numbers.
    """
    polling_records = (
        PollHistory.query.order_by(PollHistory.timestamp.desc())
        .limit(POLL_HISTORY_WINDOW)
        .all()
    )
    if not polling_records:
        return {"polling": dict(EMPTY_POLLING)}

    total_runs = len(polling_records)
    successes = sum(1 for record in polling_records if _is_success(record))
    failures = sum(1 for record in polling_records if not _is_success(record))
    avg_execution = (
        sum(record.execution_time_ms or 0 for record in polling_records) / total_runs
    )
    last_run = polling_records[0]
    last_error = next(
        (record for record in polling_records if record.error_message), None
    )
    recent_runs = [
        {
            "timestamp": record.timestamp.isoformat() if record.timestamp else None,
            "status": record.status,
            "alerts_fetched": record.alerts_fetched,
            "alerts_new": record.alerts_new,
            "alerts_updated": record.alerts_updated,
            "error": record.error_message,
            "execution_time_ms": record.execution_time_ms,
            "data_source": record.data_source,
        }
        for record in polling_records[:RECENT_RUN_LIMIT]
    ]

    return {
        "polling": {
            "success_rate": successes / total_runs if total_runs else 0,
            "total_runs": total_runs,
            "failed_runs": failures,
            "average_execution_ms": avg_execution,
            "last_run_status": last_run.status if last_run else None,
            "last_run_timestamp": last_run.timestamp.isoformat()
            if last_run and last_run.timestamp
            else None,
            "last_error": last_error.error_message if last_error else None,
            "last_error_timestamp": last_error.timestamp.isoformat()
            if last_error and last_error.timestamp
            else None,
            "recent_runs": recent_runs,
            # Additional keys expected by the template
            "total_polls": total_runs,
            "successful_polls": successes,
            "failed_polls": failures,
            "avg_time_ms": avg_execution,
        }
    }


def _poll_rate(polls: Sequence) -> float:
    if not polls:
        return 0.0
    return round(sum(1 for p in polls if _is_success(p)) / len(polls) * 100, 1)


def collect_polling_trend(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Success rates over a 7- and 30-day window, plus a p95 run time.

    One query over the 30-day window (the 7-day set is always a subset of
    it) fetching only the four columns _is_success()/the p95 calc actually
    read -- not the full row. poll_history rows carry a `details` JSON blob
    and an `error_message` Text column; on a table where nearly every row
    is inside 30 days (a poller running every few minutes fills that
    window fast), SELECT * plus full ORM hydration of tens of thousands of
    such rows measured at 7+ seconds despite the raw filtered scan itself
    taking under 100ms -- the cost was fetching and instantiating columns
    nothing here uses, not the query plan.
    """
    now = utc_now()
    cutoff_short = now - timedelta(days=TREND_SHORT_DAYS)
    cutoff_long = now - timedelta(days=TREND_LONG_DAYS)

    rows = (
        PollHistory.query
        .with_entities(
            PollHistory.timestamp,
            PollHistory.status,
            PollHistory.error_message,
            PollHistory.execution_time_ms,
        )
        .filter(PollHistory.timestamp >= cutoff_long)
        .all()
    )
    polls_long = rows
    polls_short = [r for r in rows if r.timestamp >= cutoff_short]

    times = sorted(r.execution_time_ms for r in polls_long if r.execution_time_ms is not None)
    p95 = times[int(len(times) * P95)] if times else 0

    return {
        "polling_trend": {
            "rate_7d": _poll_rate(polls_short),
            "rate_30d": _poll_rate(polls_long),
            "count_7d": len(polls_short),
            "count_30d": len(polls_long),
            "p95_execution_ms": p95,
        }
    }


POLLING = StatsSection(
    collect_polling, lambda: {"polling": dict(EMPTY_POLLING)},
    "Error calculating polling metrics: %s",
)
POLLING_TREND = StatsSection(
    collect_polling_trend, lambda: {"polling_trend": dict(EMPTY_TREND)},
    "Error getting polling trend: %s",
)

__all__ = [
    "EMPTY_POLLING",
    "EMPTY_TREND",
    "POLLING",
    "POLLING_TREND",
    "POLL_HISTORY_WINDOW",
    "RECENT_RUN_LIMIT",
    "SUCCESS_VALUES",
    "collect_polling",
    "collect_polling_trend",
]
