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

"""Aggregation helpers for the API Dashboard.

Turns the same :class:`~app_core.analytics.web_traffic.WebRequestLog` rows
the Traffic Analytics dashboard reads -- filtered to ``is_api`` -- into
per-route request counts, latency percentiles, and error rates. Traffic
Analytics deliberately excludes API traffic from its own per-page
breakdowns (it only ever shows a single rolled-up "API hits" count); this
module is where that traffic actually gets broken out by route.

Grouping is by ``endpoint`` (Flask's dotted view-function name, e.g.
``webapp.admin.audio_ingest.routes_alerts.api_get_source``), not the raw
``path`` -- a parameterized route like ``/api/alerts/<id>`` would otherwise
fragment into one bucket per ID ever requested. Rows recorded before the
``endpoint`` column existed have it as ``None`` and are excluded from the
per-route breakdown (they still count in the overall summary).

Percentiles are computed in Python rather than with a database-side
``percentile_cont`` for the same reason ``traffic_stats.py`` buckets
timestamps in Python: the same code needs to run on PostgreSQL (production)
and SQLite (tests), and route/day volumes here are small enough that pulling
raw response-time values per group is cheap.
"""

import threading
import time as _time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from app_core.extensions import db
from app_core.analytics.traffic_filters import TrafficFilters
from app_core.analytics.web_traffic import WebRequestLog

# ---------------------------------------------------------------- dashboard cache
# Mirrors traffic_stats.py's cache: the page auto-refreshes on a timer and is
# often open in more than one tab/admin at once, so a short in-process TTL
# collapses repeat/concurrent loads into one set of queries. Kept as its own
# cache (not shared with traffic_stats.py's) since the key shape differs.
_CACHE_TTL_SECONDS = 55
_CACHE_MAX = 32
_cache: Dict[Any, tuple] = {}
_cache_lock = threading.Lock()


def _cache_key(days: int) -> Any:
    return ("api_dashboard", int(days))


def _cache_get(key: Any) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < _time.monotonic():
            _cache.pop(key, None)
            return None
        return value


def _cache_put(key: Any, value: Any) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = (_time.monotonic() + _CACHE_TTL_SECONDS, value)


def invalidate_dashboard_cache() -> None:
    """Drop every cached API dashboard payload."""
    with _cache_lock:
        _cache.clear()


def _percentile(sorted_values: List[int], pct: float) -> Optional[int]:
    """Nearest-rank percentile of an already-sorted list (0 <= pct <= 100)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return int(sorted_values[0])
    rank = max(0, min(len(sorted_values) - 1, round(pct / 100.0 * (len(sorted_values) - 1))))
    return int(sorted_values[rank])


def get_api_summary(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """High-level counters for the API dashboard's metric cards."""
    flt = filters if filters is not None else TrafficFilters(days=days)
    base = flt.apply_window(WebRequestLog.query.filter(WebRequestLog.is_api.is_(True)))

    total = base.count()
    errors = base.filter(WebRequestLog.status_code >= 400).count()

    latencies = sorted(
        ms
        for (ms,) in flt.apply_window(
            db.session.query(WebRequestLog.response_time_ms).filter(
                WebRequestLog.is_api.is_(True),
                WebRequestLog.response_time_ms.isnot(None),
            )
        ).all()
        if ms is not None
    )

    return {
        "window_days": flt.days,
        "total_requests": total,
        "error_count": errors,
        "error_rate_pct": round(errors / total * 100, 2) if total else 0.0,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": _percentile(latencies, 99),
    }


def get_api_by_route(days: int = 30, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Per-route (per-``endpoint``) request count, latency, and error rate.

    Routes with no matching entry in the live ``compute_api_reference()``
    catalog (renamed or removed since traffic was recorded) still appear,
    just without the docstring/auth enrichment the caller can layer on top
    by joining this list against that catalog on ``endpoint``.
    """
    flt = filters if filters is not None else TrafficFilters(days=days)
    rows = flt.apply_window(
        db.session.query(
            WebRequestLog.endpoint,
            WebRequestLog.status_code,
            WebRequestLog.response_time_ms,
        ).filter(
            WebRequestLog.is_api.is_(True),
            WebRequestLog.endpoint.isnot(None),
        )
    ).all()

    by_endpoint: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"hits": 0, "errors": 0, "latencies": []}
    )
    for endpoint, status_code, response_time_ms in rows:
        entry = by_endpoint[endpoint]
        entry["hits"] += 1
        if status_code is not None and status_code >= 400:
            entry["errors"] += 1
        if response_time_ms is not None:
            entry["latencies"].append(response_time_ms)

    results = []
    for endpoint, data in by_endpoint.items():
        latencies = sorted(data["latencies"])
        hits = data["hits"]
        results.append({
            "endpoint": endpoint,
            "hits": hits,
            "errors": data["errors"],
            "error_rate_pct": round(data["errors"] / hits * 100, 2) if hits else 0.0,
            "p50_ms": _percentile(latencies, 50),
            "p95_ms": _percentile(latencies, 95),
        })

    results.sort(key=lambda r: r["hits"], reverse=True)
    return results


def get_api_timeseries(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Per-bucket series of API request count and error count.

    Uses hourly buckets for short windows (<= 2 days) and daily buckets
    otherwise, matching traffic_stats.get_timeseries's convention.
    """
    from collections import Counter
    from datetime import timedelta

    flt = filters if filters is not None else TrafficFilters(days=days)
    start, end = flt.window()
    hourly = (end - start) <= timedelta(days=2)

    rows = flt.apply_window(
        db.session.query(WebRequestLog.timestamp, WebRequestLog.status_code).filter(
            WebRequestLog.is_api.is_(True)
        )
    ).all()

    hits: Counter = Counter()
    errors: Counter = Counter()
    for ts, status_code in rows:
        if ts is None:
            continue
        bucket = ts.strftime("%Y-%m-%dT%H:00") if hourly else ts.strftime("%Y-%m-%d")
        hits[bucket] += 1
        if status_code is not None and status_code >= 400:
            errors[bucket] += 1

    labels = sorted(set(hits) | set(errors))
    return {
        "granularity": "hour" if hourly else "day",
        "labels": labels,
        "hits": [hits.get(b, 0) for b in labels],
        "errors": [errors.get(b, 0) for b in labels],
    }


def get_api_slowest_routes(
    days: int = 30, limit: int = 15, min_hits: int = 3, filters: Optional[TrafficFilters] = None
) -> List[Dict[str, Any]]:
    """Endpoints with the highest average response time."""
    flt = filters if filters is not None else TrafficFilters(days=days)
    rows = (
        flt.apply_window(
            db.session.query(
                WebRequestLog.endpoint,
                func.count(WebRequestLog.id).label("hits"),
                func.avg(WebRequestLog.response_time_ms).label("avg_ms"),
                func.max(WebRequestLog.response_time_ms).label("max_ms"),
            ).filter(
                WebRequestLog.is_api.is_(True),
                WebRequestLog.endpoint.isnot(None),
                WebRequestLog.response_time_ms.isnot(None),
            )
        )
        .group_by(WebRequestLog.endpoint)
        .having(func.count(WebRequestLog.id) >= min_hits)
        .order_by(func.avg(WebRequestLog.response_time_ms).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "endpoint": r.endpoint,
            "hits": int(r.hits),
            "avg_response_ms": round(float(r.avg_ms), 1) if r.avg_ms is not None else None,
            "max_response_ms": int(r.max_ms) if r.max_ms is not None else None,
        }
        for r in rows
    ]


def get_api_top_errors(
    days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None
) -> List[Dict[str, Any]]:
    """Top (endpoint, status_code) pairs by hit count, awstats-style."""
    flt = filters if filters is not None else TrafficFilters(days=days)
    rows = (
        flt.apply_window(
            db.session.query(
                WebRequestLog.endpoint,
                WebRequestLog.status_code,
                func.count(WebRequestLog.id).label("hits"),
                func.max(WebRequestLog.timestamp).label("last_seen"),
            ).filter(
                WebRequestLog.is_api.is_(True),
                WebRequestLog.endpoint.isnot(None),
                WebRequestLog.status_code >= 400,
            )
        )
        .group_by(WebRequestLog.endpoint, WebRequestLog.status_code)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "endpoint": r.endpoint,
            "status_code": int(r.status_code),
            "hits": int(r.hits),
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
        }
        for r in rows
    ]
