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

"""Aggregation helpers for the Traffic Analytics dashboard.

These functions turn the raw :class:`WebRequestLog` rows (and the existing
``audit_logs`` / ``admin_sessions`` tables) into the summary structures the
dashboard renders. Date bucketing is done in Python rather than with database
``date_trunc``/``strftime`` so the same code runs on PostgreSQL (production) and
SQLite (tests).
"""

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy import func

from app_core.extensions import db
from app_core.analytics.web_traffic import WebRequestLog
from app_utils import utc_now

# Status families used for the response-code breakdown chart.
_STATUS_FAMILIES = {2: "2xx Success", 3: "3xx Redirect", 4: "4xx Client Error", 5: "5xx Server Error"}


def _window_start(days: int):
    return utc_now() - timedelta(days=max(int(days), 1))


def get_summary(days: int = 30) -> Dict[str, Any]:
    """High-level counters for the dashboard's metric cards."""
    start = _window_start(days)
    base = WebRequestLog.query.filter(WebRequestLog.timestamp >= start)

    total_hits = base.count()
    page_views = base.filter(
        WebRequestLog.is_api.is_(False), WebRequestLog.is_bot.is_(False)
    ).count()
    api_hits = base.filter(WebRequestLog.is_api.is_(True)).count()
    bot_hits = base.filter(WebRequestLog.is_bot.is_(True)).count()
    error_hits = base.filter(WebRequestLog.status_code >= 400).count()

    unique_visitors = (
        db.session.query(func.count(func.distinct(WebRequestLog.ip_address)))
        .filter(WebRequestLog.timestamp >= start)
        .scalar()
        or 0
    )

    avg_response = (
        db.session.query(func.avg(WebRequestLog.response_time_ms))
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.response_time_ms.isnot(None),
        )
        .scalar()
    )

    # Bandwidth served (awstats-style): total + average response size.
    total_bytes = (
        db.session.query(func.sum(WebRequestLog.content_length))
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.content_length.isnot(None),
        )
        .scalar()
        or 0
    )
    avg_bytes = (
        db.session.query(func.avg(WebRequestLog.content_length))
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.content_length.isnot(None),
        )
        .scalar()
    )

    # Last 24h activity for an "is it live right now" feel.
    last_24h = WebRequestLog.query.filter(
        WebRequestLog.timestamp >= (utc_now() - timedelta(hours=24))
    ).count()

    return {
        "window_days": days,
        "total_hits": total_hits,
        "page_views": page_views,
        "api_hits": api_hits,
        "bot_hits": bot_hits,
        "error_hits": error_hits,
        "unique_visitors": int(unique_visitors),
        "avg_response_ms": round(float(avg_response), 1) if avg_response is not None else None,
        "total_bytes": int(total_bytes),
        "avg_bytes": int(avg_bytes) if avg_bytes is not None else None,
        "hits_last_24h": last_24h,
    }


def get_timeseries(days: int = 30) -> Dict[str, Any]:
    """Per-day series of hits, page views, and unique visitors.

    Uses hourly buckets for short windows (<= 2 days) and daily buckets
    otherwise. Bucketing happens in Python for cross-database portability.
    """
    start = _window_start(days)
    hourly = days <= 2

    rows = (
        db.session.query(
            WebRequestLog.timestamp,
            WebRequestLog.is_api,
            WebRequestLog.is_bot,
            WebRequestLog.ip_address,
        )
        .filter(WebRequestLog.timestamp >= start)
        .all()
    )

    hits: Counter = Counter()
    pages: Counter = Counter()
    visitors: defaultdict = defaultdict(set)

    for ts, is_api, is_bot, ip in rows:
        if ts is None:
            continue
        if hourly:
            bucket = ts.strftime("%Y-%m-%dT%H:00")
        else:
            bucket = ts.strftime("%Y-%m-%d")
        hits[bucket] += 1
        if not is_api and not is_bot:
            pages[bucket] += 1
        if ip:
            visitors[bucket].add(ip)

    labels = sorted(set(hits) | set(pages) | set(visitors))
    return {
        "granularity": "hour" if hourly else "day",
        "labels": labels,
        "hits": [hits.get(b, 0) for b in labels],
        "page_views": [pages.get(b, 0) for b in labels],
        "visitors": [len(visitors.get(b, set())) for b in labels],
    }


def get_top_pages(days: int = 30, limit: int = 15) -> List[Dict[str, Any]]:
    """Most-requested non-API paths."""
    start = _window_start(days)
    rows = (
        db.session.query(
            WebRequestLog.path,
            func.count(WebRequestLog.id).label("hits"),
            func.avg(WebRequestLog.response_time_ms).label("avg_ms"),
        )
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.is_api.is_(False),
        )
        .group_by(WebRequestLog.path)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "path": r.path,
            "hits": int(r.hits),
            "avg_response_ms": round(float(r.avg_ms), 1) if r.avg_ms is not None else None,
        }
        for r in rows
    ]


def get_top_visitors(days: int = 30, limit: int = 15) -> List[Dict[str, Any]]:
    """Most active source IP addresses (awstats-style "Hosts").

    Each row carries the reverse-DNS hostname and the country/flag (when
    resolved) so the dashboard can render them alongside the raw IP.
    """
    start = _window_start(days)
    rows = (
        db.session.query(
            WebRequestLog.ip_address,
            func.count(WebRequestLog.id).label("hits"),
            func.max(WebRequestLog.timestamp).label("last_seen"),
            func.max(WebRequestLog.username).label("username"),
            func.max(WebRequestLog.hostname).label("hostname"),
            func.max(WebRequestLog.country).label("country"),
            func.max(WebRequestLog.country_code).label("country_code"),
        )
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.ip_address.isnot(None),
        )
        .group_by(WebRequestLog.ip_address)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "ip_address": r.ip_address,
            "hits": int(r.hits),
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "username": r.username,
            "hostname": r.hostname,
            "country": r.country,
            "country_code": r.country_code,
        }
        for r in rows
    ]


def get_status_breakdown(days: int = 30) -> List[Dict[str, Any]]:
    """Counts grouped into 2xx/3xx/4xx/5xx families."""
    start = _window_start(days)
    rows = (
        db.session.query(
            WebRequestLog.status_code,
            func.count(WebRequestLog.id).label("count"),
        )
        .filter(WebRequestLog.timestamp >= start)
        .group_by(WebRequestLog.status_code)
        .all()
    )
    families: Counter = Counter()
    for status_code, count in rows:
        family = _STATUS_FAMILIES.get((status_code or 0) // 100, "Other")
        families[family] += int(count)
    order = ["2xx Success", "3xx Redirect", "4xx Client Error", "5xx Server Error", "Other"]
    return [
        {"family": fam, "count": families[fam]}
        for fam in order
        if families.get(fam)
    ]


def _simple_breakdown(column, days: int, limit: int, label: str) -> List[Dict[str, Any]]:
    start = _window_start(days)
    rows = (
        db.session.query(column, func.count(WebRequestLog.id).label("count"))
        .filter(WebRequestLog.timestamp >= start, column.isnot(None))
        .group_by(column)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [{label: value, "count": int(count)} for value, count in rows]


def get_browser_breakdown(days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.browser, days, limit, "browser")


def get_os_breakdown(days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.os, days, limit, "os")


def get_referer_breakdown(days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.referer, days, limit, "referer")


def get_resolution_breakdown(days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.screen_resolution, days, limit, "resolution")


def get_country_breakdown(days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    """Hits grouped by country/network, with an ISO code for the flag.

    Mirrors awstats' "Countries" report. ``country_code`` is a representative
    ISO 3166-1 alpha-2 code (or ``None`` for local/unresolved labels).
    """
    start = _window_start(days)
    rows = (
        db.session.query(
            WebRequestLog.country,
            func.count(WebRequestLog.id).label("count"),
            func.max(WebRequestLog.country_code).label("country_code"),
        )
        .filter(WebRequestLog.timestamp >= start, WebRequestLog.country.isnot(None))
        .group_by(WebRequestLog.country)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {"country": r.country, "count": int(r.count), "country_code": r.country_code}
        for r in rows
    ]


def get_language_breakdown(days: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.language, days, limit, "language")


def get_recent_requests(limit: int = 50) -> List[Dict[str, Any]]:
    rows = (
        WebRequestLog.query.order_by(WebRequestLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in rows]


def get_error_pages(days: int = 30, limit: int = 15) -> List[Dict[str, Any]]:
    """Top URLs returning 4xx/5xx, awstats-style "HTTP errors" report.

    Surfaces the paths most often producing errors (typically 404s from bots
    probing for files that don't exist) so a scanner is obvious at a glance.
    """
    start = _window_start(days)
    rows = (
        db.session.query(
            WebRequestLog.path,
            WebRequestLog.status_code,
            func.count(WebRequestLog.id).label("hits"),
            func.max(WebRequestLog.timestamp).label("last_seen"),
        )
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.status_code >= 400,
        )
        .group_by(WebRequestLog.path, WebRequestLog.status_code)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "path": r.path,
            "status_code": int(r.status_code),
            "hits": int(r.hits),
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
        }
        for r in rows
    ]


def get_error_sources(days: int = 30, limit: int = 15) -> List[Dict[str, Any]]:
    """Source IPs generating the most 4xx/5xx responses (likely scanners)."""
    start = _window_start(days)
    rows = (
        db.session.query(
            WebRequestLog.ip_address,
            func.count(WebRequestLog.id).label("errors"),
            func.max(WebRequestLog.hostname).label("hostname"),
            func.max(WebRequestLog.country_code).label("country_code"),
        )
        .filter(
            WebRequestLog.timestamp >= start,
            WebRequestLog.status_code >= 400,
            WebRequestLog.ip_address.isnot(None),
        )
        .group_by(WebRequestLog.ip_address)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "ip_address": r.ip_address,
            "errors": int(r.errors),
            "hostname": r.hostname,
            "country_code": r.country_code,
        }
        for r in rows
    ]


def get_hourly_distribution(days: int = 30) -> Dict[str, Any]:
    """Hits per hour-of-day (0–23), awstats' "Hourly" histogram.

    Bucketing happens in Python for cross-database portability.
    """
    start = _window_start(days)
    rows = (
        db.session.query(WebRequestLog.timestamp)
        .filter(WebRequestLog.timestamp >= start)
        .all()
    )
    counts = [0] * 24
    for (ts,) in rows:
        if ts is not None:
            counts[ts.hour] += 1
    return {
        "labels": [f"{h:02d}" for h in range(24)],
        "hits": counts,
    }


def get_weekday_distribution(days: int = 30) -> Dict[str, Any]:
    """Hits per day-of-week (Mon–Sun), awstats' "Days of week" histogram."""
    start = _window_start(days)
    rows = (
        db.session.query(WebRequestLog.timestamp)
        .filter(WebRequestLog.timestamp >= start)
        .all()
    )
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    counts = [0] * 7
    for (ts,) in rows:
        if ts is not None:
            counts[ts.weekday()] += 1
    return {"labels": labels, "hits": counts}


# ---------------------------------------------------------------------------
# Login / session analytics (sourced from audit_logs + admin_sessions)
# ---------------------------------------------------------------------------

def get_login_summary(days: int = 30) -> Dict[str, Any]:
    """Authentication counters drawn from the audit log and active sessions."""
    from app_core.auth.audit import AuditAction, AuditLog
    from app_core.models import AdminSession

    start = _window_start(days)
    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)

    base = AuditLog.query.filter(
        AuditLog.timestamp >= start, AuditLog.action.in_(login_actions)
    )
    successes = base.filter(AuditLog.action == AuditAction.LOGIN_SUCCESS.value).count()
    failures = base.filter(AuditLog.action == AuditAction.LOGIN_FAILURE.value).count()

    unique_users = (
        db.session.query(func.count(func.distinct(AuditLog.username)))
        .filter(
            AuditLog.timestamp >= start,
            AuditLog.action == AuditAction.LOGIN_SUCCESS.value,
        )
        .scalar()
        or 0
    )
    unique_ips = (
        db.session.query(func.count(func.distinct(AuditLog.ip_address)))
        .filter(AuditLog.timestamp >= start, AuditLog.action.in_(login_actions))
        .scalar()
        or 0
    )

    active_sessions = AdminSession.query.filter(AdminSession.ended_at.is_(None)).count()

    return {
        "window_days": days,
        "successful_logins": successes,
        "failed_logins": failures,
        "unique_users": int(unique_users),
        "unique_ips": int(unique_ips),
        "active_sessions": active_sessions,
    }


def get_login_timeseries(days: int = 30) -> Dict[str, Any]:
    """Per-day successful vs. failed login counts."""
    from app_core.auth.audit import AuditAction, AuditLog

    start = _window_start(days)
    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)
    rows = (
        db.session.query(AuditLog.timestamp, AuditLog.action)
        .filter(AuditLog.timestamp >= start, AuditLog.action.in_(login_actions))
        .all()
    )

    success: Counter = Counter()
    failure: Counter = Counter()
    for ts, action in rows:
        if ts is None:
            continue
        bucket = ts.strftime("%Y-%m-%d")
        if action == AuditAction.LOGIN_SUCCESS.value:
            success[bucket] += 1
        else:
            failure[bucket] += 1

    labels = sorted(set(success) | set(failure))
    return {
        "labels": labels,
        "successful": [success.get(b, 0) for b in labels],
        "failed": [failure.get(b, 0) for b in labels],
    }


def get_top_login_ips(days: int = 30, limit: int = 15) -> List[Dict[str, Any]]:
    """Source IPs ranked by login attempts, split by success/failure."""
    from app_core.auth.audit import AuditAction, AuditLog

    start = _window_start(days)
    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)
    rows = (
        db.session.query(
            AuditLog.ip_address,
            AuditLog.action,
            func.count(AuditLog.id).label("count"),
        )
        .filter(
            AuditLog.timestamp >= start,
            AuditLog.action.in_(login_actions),
            AuditLog.ip_address.isnot(None),
        )
        .group_by(AuditLog.ip_address, AuditLog.action)
        .all()
    )

    by_ip: defaultdict = defaultdict(lambda: {"success": 0, "failure": 0})
    for ip, action, count in rows:
        if action == AuditAction.LOGIN_SUCCESS.value:
            by_ip[ip]["success"] += int(count)
        else:
            by_ip[ip]["failure"] += int(count)

    result = [
        {
            "ip_address": ip,
            "success": vals["success"],
            "failure": vals["failure"],
            "total": vals["success"] + vals["failure"],
        }
        for ip, vals in by_ip.items()
    ]
    result.sort(key=lambda r: r["total"], reverse=True)
    return result[:limit]


def get_recent_logins(limit: int = 50) -> List[Dict[str, Any]]:
    """Most recent login successes/failures from the audit log."""
    from app_core.auth.audit import AuditAction, AuditLog

    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)
    rows = (
        AuditLog.query.filter(AuditLog.action.in_(login_actions))
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "username": r.username,
            "ip_address": r.ip_address,
            "success": bool(r.success),
            "action": r.action,
        }
        for r in rows
    ]


def get_full_dashboard(days: int = 30) -> Dict[str, Any]:
    """Bundle every section the dashboard needs into one payload."""
    return {
        "summary": get_summary(days),
        "timeseries": get_timeseries(days),
        "top_pages": get_top_pages(days),
        "top_visitors": get_top_visitors(days),
        "status_breakdown": get_status_breakdown(days),
        "browser_breakdown": get_browser_breakdown(days),
        "os_breakdown": get_os_breakdown(days),
        "referer_breakdown": get_referer_breakdown(days),
        "resolution_breakdown": get_resolution_breakdown(days),
        "country_breakdown": get_country_breakdown(days),
        "language_breakdown": get_language_breakdown(days),
        "error_pages": get_error_pages(days),
        "error_sources": get_error_sources(days),
        "hourly_distribution": get_hourly_distribution(days),
        "weekday_distribution": get_weekday_distribution(days),
        "recent_requests": get_recent_requests(limit=25),
        "login_summary": get_login_summary(days),
        "login_timeseries": get_login_timeseries(days),
        "top_login_ips": get_top_login_ips(days),
        "recent_logins": get_recent_logins(limit=25),
    }


__all__ = [
    "get_summary",
    "get_timeseries",
    "get_top_pages",
    "get_top_visitors",
    "get_status_breakdown",
    "get_browser_breakdown",
    "get_os_breakdown",
    "get_referer_breakdown",
    "get_resolution_breakdown",
    "get_country_breakdown",
    "get_language_breakdown",
    "get_recent_requests",
    "get_error_pages",
    "get_error_sources",
    "get_hourly_distribution",
    "get_weekday_distribution",
    "get_login_summary",
    "get_login_timeseries",
    "get_top_login_ips",
    "get_recent_logins",
    "get_full_dashboard",
]
