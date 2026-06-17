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

Every section helper accepts an optional ``filters=TrafficFilters(...)`` so the
dashboard can request a **custom date range** and/or **drill down** on a
dimension (path, country, status family, browser, OS, method). When ``filters``
is omitted the legacy trailing-``days`` window is used, keeping existing callers
working unchanged.
"""

import ipaddress
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy import func

from app_core.extensions import db
from app_core.analytics.geo import network_key
from app_core.analytics.traffic_filters import TrafficFilters
from app_core.analytics.web_traffic import WebRequestLog
from app_utils import utc_now

# Status families used for the response-code breakdown chart.
_STATUS_FAMILIES = {2: "2xx Success", 3: "3xx Redirect", 4: "4xx Client Error", 5: "5xx Server Error"}


def _window_start(days: int):
    return utc_now() - timedelta(days=max(int(days), 1))


def _resolve(days: int, filters: Optional[TrafficFilters]) -> TrafficFilters:
    """Return the active filter, building a legacy day-window when absent."""
    return filters if filters is not None else TrafficFilters(days=days)


def get_summary(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """High-level counters for the dashboard's metric cards."""
    flt = _resolve(days, filters)
    start, end = flt.window()
    base = flt.apply(WebRequestLog.query)

    total_hits = base.count()
    page_views = base.filter(
        WebRequestLog.is_api.is_(False), WebRequestLog.is_bot.is_(False)
    ).count()
    api_hits = base.filter(WebRequestLog.is_api.is_(True)).count()
    bot_hits = base.filter(WebRequestLog.is_bot.is_(True)).count()
    error_hits = base.filter(WebRequestLog.status_code >= 400).count()

    # Count unique visitors by network key: IPv4 addresses count individually,
    # but IPv6 addresses are collapsed to their /64 prefix so a single device's
    # rotating privacy addresses aren't counted as many visitors. We pull the
    # distinct addresses (a small set) and fold them in Python for portability.
    distinct_ips = flt.apply(
        db.session.query(func.distinct(WebRequestLog.ip_address)).filter(
            WebRequestLog.ip_address.isnot(None)
        )
    ).all()
    unique_visitors = len({network_key(ip) for (ip,) in distinct_ips})

    avg_response = flt.apply(
        db.session.query(func.avg(WebRequestLog.response_time_ms)).filter(
            WebRequestLog.response_time_ms.isnot(None)
        )
    ).scalar()

    # Bandwidth served (awstats-style): total + average response size.
    total_bytes = flt.apply(
        db.session.query(func.sum(WebRequestLog.content_length)).filter(
            WebRequestLog.content_length.isnot(None)
        )
    ).scalar() or 0
    avg_bytes = flt.apply(
        db.session.query(func.avg(WebRequestLog.content_length)).filter(
            WebRequestLog.content_length.isnot(None)
        )
    ).scalar()

    # Last 24h activity for an "is it live right now" feel. This keeps the same
    # dimension drill-down but always uses the trailing 24h regardless of window.
    last_24h = flt.apply_dimensions(
        WebRequestLog.query.filter(
            WebRequestLog.timestamp >= (utc_now() - timedelta(hours=24))
        )
    ).count()

    return {
        "window_days": flt.days,
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


def get_summary_previous(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Same counters as :func:`get_summary` for the *preceding* window.

    Used to show "vs previous period" deltas on the dashboard's metric tiles.
    The window is the equal-length period immediately before the one shown.
    """
    flt = _resolve(days, filters).previous()
    base = flt.apply(WebRequestLog.query)

    page_views = base.filter(
        WebRequestLog.is_api.is_(False), WebRequestLog.is_bot.is_(False)
    ).count()
    error_hits = base.filter(WebRequestLog.status_code >= 400).count()
    distinct_ips = flt.apply(
        db.session.query(func.distinct(WebRequestLog.ip_address)).filter(
            WebRequestLog.ip_address.isnot(None)
        )
    ).all()
    unique_visitors = len({network_key(ip) for (ip,) in distinct_ips})
    avg_response = flt.apply(
        db.session.query(func.avg(WebRequestLog.response_time_ms)).filter(
            WebRequestLog.response_time_ms.isnot(None)
        )
    ).scalar()
    total_bytes = flt.apply(
        db.session.query(func.sum(WebRequestLog.content_length)).filter(
            WebRequestLog.content_length.isnot(None)
        )
    ).scalar() or 0
    return {
        "total_hits": base.count(),
        "page_views": page_views,
        "error_hits": error_hits,
        "unique_visitors": int(unique_visitors),
        "avg_response_ms": round(float(avg_response), 1) if avg_response is not None else None,
        "total_bytes": int(total_bytes),
    }


def get_timeseries(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Per-day series of hits, page views, and unique visitors.

    Uses hourly buckets for short windows (<= 2 days) and daily buckets
    otherwise. Bucketing happens in Python for cross-database portability.
    """
    flt = _resolve(days, filters)
    start, end = flt.window()
    hourly = (end - start) <= timedelta(days=2)

    rows = flt.apply(
        db.session.query(
            WebRequestLog.timestamp,
            WebRequestLog.is_api,
            WebRequestLog.is_bot,
            WebRequestLog.ip_address,
        )
    ).all()

    hits: Counter = Counter()
    pages: Counter = Counter()
    visitors: defaultdict = defaultdict(set)

    for ts, is_api, is_bot, ip in rows:
        if ts is None:
            continue
        bucket = ts.strftime("%Y-%m-%dT%H:00") if hourly else ts.strftime("%Y-%m-%d")
        hits[bucket] += 1
        if not is_api and not is_bot:
            pages[bucket] += 1
        if ip:
            visitors[bucket].add(network_key(ip))

    labels = sorted(set(hits) | set(pages) | set(visitors))
    return {
        "granularity": "hour" if hourly else "day",
        "labels": labels,
        "hits": [hits.get(b, 0) for b in labels],
        "page_views": [pages.get(b, 0) for b in labels],
        "visitors": [len(visitors.get(b, set())) for b in labels],
    }


def get_top_pages(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Most-requested non-API paths."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.path,
                func.count(WebRequestLog.id).label("hits"),
                func.avg(WebRequestLog.response_time_ms).label("avg_ms"),
            ).filter(WebRequestLog.is_api.is_(False))
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


def get_top_visitors(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Most active source IP addresses (awstats-style "Hosts")."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.ip_address,
                func.count(WebRequestLog.id).label("hits"),
                func.max(WebRequestLog.timestamp).label("last_seen"),
                func.max(WebRequestLog.username).label("username"),
                func.max(WebRequestLog.hostname).label("hostname"),
                func.max(WebRequestLog.country).label("country"),
                func.max(WebRequestLog.country_code).label("country_code"),
            ).filter(WebRequestLog.ip_address.isnot(None))
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


def get_status_breakdown(days: int = 30, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Counts grouped into 2xx/3xx/4xx/5xx families."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.status_code,
                func.count(WebRequestLog.id).label("count"),
            )
        )
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


def _simple_breakdown(column, days: int, limit: int, label: str, filters: Optional[TrafficFilters]) -> List[Dict[str, Any]]:
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(column, func.count(WebRequestLog.id).label("count")).filter(
                column.isnot(None)
            )
        )
        .group_by(column)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [{label: value, "count": int(count)} for value, count in rows]


def get_browser_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.browser, days, limit, "browser", filters)


def get_method_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Hits grouped by HTTP method (GET/POST/PUT/…)."""
    return _simple_breakdown(WebRequestLog.method, days, limit, "method", filters)


# OS names that imply a touch device. Everything else (Windows, macOS, Linux,
# ChromeOS, unknown) is treated as a desktop/laptop.
_MOBILE_OS = {"iOS", "Android"}
_TABLET_OS = {"iPadOS"}


def _classify_device(os_name: Optional[str], user_agent: Optional[str]) -> str:
    """Bucket a request into Desktop / Mobile / Tablet from OS + user-agent."""
    ua = (user_agent or "")
    os_name = os_name or ""
    if os_name in _TABLET_OS or "iPad" in ua or ("Tablet" in ua):
        return "Tablet"
    if os_name in _MOBILE_OS or "Mobi" in ua:
        # Android tablets omit "Mobile" in the UA; treat those as tablets.
        if os_name == "Android" and "Mobi" not in ua and ua:
            return "Tablet"
        return "Mobile"
    return "Desktop"


def get_device_breakdown(days: int = 30, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Human (non-bot) hits grouped into Desktop / Mobile / Tablet."""
    flt = _resolve(days, filters)
    rows = flt.apply(
        db.session.query(WebRequestLog.os, WebRequestLog.user_agent).filter(
            WebRequestLog.is_bot.is_(False)
        )
    ).all()
    counts: Counter = Counter()
    for os_name, ua in rows:
        counts[_classify_device(os_name, ua)] += 1
    order = ["Desktop", "Mobile", "Tablet"]
    return [{"device": d, "count": counts[d]} for d in order if counts.get(d)]


def get_auth_breakdown(days: int = 30, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Human (non-bot) hits split into authenticated vs anonymous."""
    flt = _resolve(days, filters)
    base = flt.apply(WebRequestLog.query.filter(WebRequestLog.is_bot.is_(False)))
    authed = base.filter(WebRequestLog.is_authenticated.is_(True)).count()
    anon = base.filter(WebRequestLog.is_authenticated.is_(False)).count()
    result = []
    if authed:
        result.append({"label": "Authenticated", "count": authed})
    if anon:
        result.append({"label": "Anonymous", "count": anon})
    return result


def get_slowest_pages(days: int = 30, limit: int = 15, min_hits: int = 3, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Endpoints with the highest average server response time."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.path,
                func.count(WebRequestLog.id).label("hits"),
                func.avg(WebRequestLog.response_time_ms).label("avg_ms"),
                func.max(WebRequestLog.response_time_ms).label("max_ms"),
            ).filter(WebRequestLog.response_time_ms.isnot(None))
        )
        .group_by(WebRequestLog.path)
        .having(func.count(WebRequestLog.id) >= min_hits)
        .order_by(func.avg(WebRequestLog.response_time_ms).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "path": r.path,
            "hits": int(r.hits),
            "avg_response_ms": round(float(r.avg_ms), 1) if r.avg_ms is not None else None,
            "max_response_ms": int(r.max_ms) if r.max_ms is not None else None,
        }
        for r in rows
    ]


def get_os_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.os, days, limit, "os", filters)


def get_referer_breakdown(
    days: int = 30, limit: int = 10, self_hosts: Optional[set] = None, filters: Optional[TrafficFilters] = None
) -> List[Dict[str, Any]]:
    """External referrers grouped by domain (awstats-style)."""
    flt = _resolve(days, filters)
    hosts = {h.lower() for h in (self_hosts or set())}
    rows = flt.apply(
        db.session.query(WebRequestLog.referer).filter(WebRequestLog.referer.isnot(None))
    ).all()
    counts: Counter = Counter()
    for (ref,) in rows:
        if not ref:
            continue
        host = urlparse(ref).netloc.lower()
        if not host:
            continue
        host = host.split("@")[-1].split(":")[0]  # strip any user-info / port
        if host in hosts:
            continue  # internal self-referral
        counts[host] += 1
    return [{"referer": host, "count": count} for host, count in counts.most_common(limit)]


def get_resolution_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.screen_resolution, days, limit, "resolution", filters)


def get_country_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Hits grouped by country/network, with an ISO code for the flag."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.country,
                func.count(WebRequestLog.id).label("count"),
                func.max(WebRequestLog.country_code).label("country_code"),
            ).filter(WebRequestLog.country.isnot(None))
        )
        .group_by(WebRequestLog.country)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {"country": r.country, "count": int(r.count), "country_code": r.country_code}
        for r in rows
    ]


def get_language_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    return _simple_breakdown(WebRequestLog.language, days, limit, "language", filters)


def get_city_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Hits grouped by city + state/region (requires a GeoLite2 City database)."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.city,
                WebRequestLog.region,
                WebRequestLog.region_code,
                func.count(WebRequestLog.id).label("count"),
            ).filter(WebRequestLog.city.isnot(None))
        )
        # Group by city *and* region so same-named cities in different
        # states/provinces stay distinct (e.g. Springfield, IL vs Springfield, MO).
        .group_by(WebRequestLog.city, WebRequestLog.region, WebRequestLog.region_code)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    result = []
    for r in rows:
        suffix = r.region_code or r.region
        label = f"{r.city}, {suffix}" if suffix else r.city
        result.append(
            {
                "city": r.city,
                "region": r.region,
                "region_code": r.region_code,
                "label": label,
                "count": int(r.count),
            }
        )
    return result


def get_region_breakdown(days: int = 30, limit: int = 60, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Hits grouped by state/region within each country.

    Requires a GeoLite2 City database (country-only databases do not resolve
    subdivisions). Powers the per-state markers on the visitor map. The limit is
    generous so all US states can be plotted; rows whose ``region_code`` has no
    centroid are simply skipped client-side.
    """
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.country_code,
                WebRequestLog.region,
                WebRequestLog.region_code,
                func.count(WebRequestLog.id).label("count"),
            ).filter(WebRequestLog.region_code.isnot(None))
        )
        .group_by(
            WebRequestLog.country_code,
            WebRequestLog.region,
            WebRequestLog.region_code,
        )
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "country_code": r.country_code,
            "region": r.region,
            "region_code": r.region_code,
            "count": int(r.count),
        }
        for r in rows
    ]


def get_asn_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Hits grouped by network operator / ISP (requires a GeoLite2 ASN database)."""
    return _simple_breakdown(WebRequestLog.asn_org, days, limit, "asn_org", filters)


def get_ip_version_breakdown(days: int = 30, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Split traffic into IPv4 vs IPv6, with reverse-DNS coverage per family.

    Address family is not stored as a column, so it is derived in Python from the
    distinct visitor IPs (cheap — one grouped row per address). For each family we
    report total hits, unique visitors (grouped by :func:`network_key` so rotating
    IPv6 privacy addresses don't over-count a single host), the number of distinct
    addresses seen, and how many of those addresses have a resolved reverse-DNS
    hostname. The ``resolved``/``ips`` pair makes rDNS health visible per family —
    e.g. it surfaces the common case where IPv6 hosts exist but lack PTR records.
    """
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.ip_address,
                func.count(WebRequestLog.id).label("hits"),
                func.count(WebRequestLog.hostname).label("host_rows"),
            ).filter(WebRequestLog.ip_address.isnot(None))
        )
        .group_by(WebRequestLog.ip_address)
        .all()
    )

    buckets: Dict[int, Dict[str, Any]] = {
        4: {"hits": 0, "ips": 0, "resolved": 0, "networks": set()},
        6: {"hits": 0, "ips": 0, "resolved": 0, "networks": set()},
    }
    for ip, hits, host_rows in rows:
        try:
            version = ipaddress.ip_address(ip).version
        except (ValueError, TypeError):
            continue
        bucket = buckets[version]
        bucket["hits"] += int(hits or 0)
        bucket["ips"] += 1
        bucket["networks"].add(network_key(ip))
        if host_rows:
            bucket["resolved"] += 1

    result: List[Dict[str, Any]] = []
    for version, label in ((4, "IPv4"), (6, "IPv6")):
        bucket = buckets[version]
        if not bucket["ips"]:
            continue
        result.append(
            {
                "label": label,
                "version": version,
                "count": bucket["hits"],
                "visitors": len(bucket["networks"]),
                "ips": bucket["ips"],
                "resolved": bucket["resolved"],
            }
        )
    result.sort(key=lambda r: r["count"], reverse=True)
    return result


def get_recent_requests(limit: int = 50, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Most recent recorded requests, optionally scoped to *filters*."""
    query = WebRequestLog.query
    if filters is not None:
        query = filters.apply(query)
    rows = query.order_by(WebRequestLog.timestamp.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


def get_error_pages(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Top URLs returning 4xx/5xx, awstats-style "HTTP errors" report."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.path,
                WebRequestLog.status_code,
                func.count(WebRequestLog.id).label("hits"),
                func.max(WebRequestLog.timestamp).label("last_seen"),
            ).filter(WebRequestLog.status_code >= 400)
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


def get_error_sources(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Source IPs generating the most 4xx/5xx responses (likely scanners)."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.ip_address,
                func.count(WebRequestLog.id).label("errors"),
                func.max(WebRequestLog.hostname).label("hostname"),
                func.max(WebRequestLog.country_code).label("country_code"),
            ).filter(
                WebRequestLog.status_code >= 400,
                WebRequestLog.ip_address.isnot(None),
            )
        )
        .group_by(WebRequestLog.ip_address)
        .order_by(func.count(WebRequestLog.id).desc())
        .limit(limit)
        .all()
    )
    sources = [
        {
            "ip_address": r.ip_address,
            "errors": int(r.errors),
            "hostname": r.hostname,
            "country_code": r.country_code,
        }
        for r in rows
    ]

    # Annotate each noisy source with the single path it errors on most, plus
    # that path's status code — so the table answers "what *are* these errors?"
    # at a glance. One grouped query for just the already-selected source IPs
    # keeps this cheap.
    ips = [s["ip_address"] for s in sources]
    if ips:
        detail = (
            flt.apply(
                db.session.query(
                    WebRequestLog.ip_address,
                    WebRequestLog.path,
                    WebRequestLog.status_code,
                    func.count(WebRequestLog.id).label("hits"),
                ).filter(
                    WebRequestLog.status_code >= 400,
                    WebRequestLog.ip_address.in_(ips),
                )
            )
            .group_by(WebRequestLog.ip_address, WebRequestLog.path, WebRequestLog.status_code)
            .order_by(func.count(WebRequestLog.id).desc())
            .all()
        )
        top_by_ip: Dict[str, Dict[str, Any]] = {}
        for ip, path, status, hits in detail:
            # Rows are ordered by count desc, so the first seen per IP is its worst.
            if ip not in top_by_ip:
                top_by_ip[ip] = {
                    "top_path": path,
                    "top_status": int(status),
                    "top_path_hits": int(hits),
                }
        for s in sources:
            s.update(
                top_by_ip.get(
                    s["ip_address"],
                    {"top_path": None, "top_status": None, "top_path_hits": 0},
                )
            )
    return sources


def get_hourly_distribution(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Hits per hour-of-day (0–23), awstats' "Hourly" histogram."""
    flt = _resolve(days, filters)
    rows = flt.apply(db.session.query(WebRequestLog.timestamp)).all()
    counts = [0] * 24
    for (ts,) in rows:
        if ts is not None:
            counts[ts.hour] += 1
    return {"labels": [f"{h:02d}" for h in range(24)], "hits": counts}


def get_weekday_distribution(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Hits per day-of-week (Mon–Sun), awstats' "Days of week" histogram."""
    flt = _resolve(days, filters)
    rows = flt.apply(db.session.query(WebRequestLog.timestamp)).all()
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    counts = [0] * 7
    for (ts,) in rows:
        if ts is not None:
            counts[ts.weekday()] += 1
    return {"labels": labels, "hits": counts}


# A "visit" ends after this much inactivity from the same host (awstats groups
# requests into visits the same way; 30 minutes is the common analytics default).
VISIT_TIMEOUT_SECONDS = 1800


def get_visits(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Sessionise human requests into visits with entry/exit pages + duration."""
    flt = _resolve(days, filters)
    rows = (
        flt.apply(
            db.session.query(
                WebRequestLog.ip_address,
                WebRequestLog.timestamp,
                WebRequestLog.path,
                WebRequestLog.is_api,
            ).filter(
                WebRequestLog.is_bot.is_(False),
                WebRequestLog.ip_address.isnot(None),
            )
        )
        .order_by(WebRequestLog.ip_address, WebRequestLog.timestamp)
        .all()
    )

    entry: Counter = Counter()
    exit_: Counter = Counter()
    totals = {"visits": 0, "duration": 0.0, "bounces": 0}
    state = {"ip": None, "start": None, "last": None, "entry": None, "exit": None, "pages": 0}

    def flush():
        if state["start"] is None:
            return
        totals["visits"] += 1
        totals["duration"] += (state["last"] - state["start"]).total_seconds()
        # A "bounce" is a visit with a single page view (awstats/GA convention).
        if state["pages"] <= 1:
            totals["bounces"] += 1
        if state["entry"]:
            entry[state["entry"]] += 1
        if state["exit"]:
            exit_[state["exit"]] += 1

    for ip, ts, path, is_api in rows:
        if ts is None:
            continue
        gap = (
            state["last"] is not None
            and (ts - state["last"]).total_seconds() > VISIT_TIMEOUT_SECONDS
        )
        if ip != state["ip"] or gap:
            flush()
            state.update(ip=ip, start=ts, entry=None, exit=None, pages=0)
        if not is_api:
            if state["entry"] is None:
                state["entry"] = path
            state["exit"] = path
            state["pages"] += 1
        state["last"] = ts
    flush()

    visits = totals["visits"]
    avg = totals["duration"] / visits if visits else 0.0
    bounce_rate = round(100.0 * totals["bounces"] / visits, 1) if visits else 0.0
    return {
        "visits": visits,
        "avg_duration_seconds": round(avg, 1),
        "bounce_rate": bounce_rate,
        "single_page_visits": totals["bounces"],
        "entry_pages": [{"path": p, "count": c} for p, c in entry.most_common(limit)],
        "exit_pages": [{"path": p, "count": c} for p, c in exit_.most_common(limit)],
    }


def get_filetype_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Hits grouped by file extension (awstats' "File types")."""
    flt = _resolve(days, filters)
    rows = flt.apply(db.session.query(WebRequestLog.path)).all()
    counts: Counter = Counter()
    for (path,) in rows:
        if not path:
            continue
        segment = path.rsplit("/", 1)[-1]
        if "." in segment:
            ext = segment.rsplit(".", 1)[-1].lower()
            if ext.isalnum() and 1 <= len(ext) <= 5:
                counts[ext] += 1
            else:
                counts["(other)"] += 1
        else:
            counts["(page)"] += 1
    return [{"filetype": k, "count": v} for k, v in counts.most_common(limit)]


# host substring -> query parameter that carries the search terms.
_SEARCH_ENGINES = {
    "google": "q", "bing": "q", "duckduckgo": "q", "ecosia": "q",
    "startpage": "q", "brave": "q", "ask": "q", "aol": "q",
    "yahoo": "p", "yandex": "text", "baidu": "wd",
}


def get_search_terms(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Search keywords/keyphrases parsed from search-engine referrers."""
    from urllib.parse import parse_qs

    flt = _resolve(days, filters)
    rows = flt.apply(
        db.session.query(WebRequestLog.referer).filter(WebRequestLog.referer.isnot(None))
    ).all()
    counts: Counter = Counter()
    for (ref,) in rows:
        if not ref:
            continue
        parsed = urlparse(ref)
        host = parsed.netloc.lower()
        for engine, param in _SEARCH_ENGINES.items():
            if engine in host:
                values = parse_qs(parsed.query).get(param)
                if values and values[0].strip():
                    counts[values[0].strip().lower()[:120]] += 1
                break
    return [{"term": k, "count": v} for k, v in counts.most_common(limit)]


# Search-engine referrer host substring -> display name for the breakdown chart.
_SEARCH_ENGINE_NAMES = {
    "google": "Google", "bing": "Bing", "duckduckgo": "DuckDuckGo",
    "ecosia": "Ecosia", "startpage": "Startpage", "brave": "Brave",
    "ask": "Ask", "aol": "AOL", "yahoo": "Yahoo", "yandex": "Yandex",
    "baidu": "Baidu",
}


def get_search_engine_breakdown(days: int = 30, limit: int = 10, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Referrals grouped by originating search engine (awstats' "Search engines")."""
    flt = _resolve(days, filters)
    rows = flt.apply(
        db.session.query(WebRequestLog.referer).filter(WebRequestLog.referer.isnot(None))
    ).all()
    counts: Counter = Counter()
    for (ref,) in rows:
        if not ref:
            continue
        host = urlparse(ref).netloc.lower()
        for needle, name in _SEARCH_ENGINE_NAMES.items():
            if needle in host:
                counts[name] += 1
                break
    return [{"engine": name, "count": count} for name, count in counts.most_common(limit)]


def get_bot_breakdown(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Robots/spiders grouped by name (awstats' "Robots/Spiders visitors")."""
    from app_core.analytics.web_traffic import classify_bot

    flt = _resolve(days, filters)
    rows = flt.apply(
        db.session.query(WebRequestLog.user_agent, WebRequestLog.timestamp).filter(
            WebRequestLog.is_bot.is_(True)
        )
    ).all()
    counts: Counter = Counter()
    last_seen: Dict[str, Any] = {}
    for ua, ts in rows:
        name = classify_bot(ua)
        counts[name] += 1
        if ts is not None and (name not in last_seen or ts > last_seen[name]):
            last_seen[name] = ts
    return [
        {
            "bot": name,
            "hits": count,
            "last_seen": last_seen[name].isoformat() if last_seen.get(name) else None,
        }
        for name, count in counts.most_common(limit)
    ]


# ---------------------------------------------------------------------------
# Login / session analytics (sourced from audit_logs + admin_sessions)
#
# These draw from the audit log, which has no path/browser/etc. columns, so the
# drill-down *dimensions* don't apply — only the time window from the filter is
# honoured (so a custom date range still scopes login activity correctly).
# ---------------------------------------------------------------------------

def get_login_summary(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Authentication counters drawn from the audit log and active sessions."""
    from app_core.auth.audit import AuditAction, AuditLog
    from app_core.models import AdminSession

    flt = _resolve(days, filters)
    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)

    base = flt.filter_timestamp(
        AuditLog.query.filter(AuditLog.action.in_(login_actions)), AuditLog.timestamp
    )
    successes = base.filter(AuditLog.action == AuditAction.LOGIN_SUCCESS.value).count()
    failures = base.filter(AuditLog.action == AuditAction.LOGIN_FAILURE.value).count()

    unique_users = (
        flt.filter_timestamp(
            db.session.query(func.count(func.distinct(AuditLog.username))).filter(
                AuditLog.action == AuditAction.LOGIN_SUCCESS.value
            ),
            AuditLog.timestamp,
        )
        .scalar()
        or 0
    )
    unique_ips = (
        flt.filter_timestamp(
            db.session.query(func.count(func.distinct(AuditLog.ip_address))).filter(
                AuditLog.action.in_(login_actions)
            ),
            AuditLog.timestamp,
        )
        .scalar()
        or 0
    )

    active_sessions = AdminSession.query.filter(AdminSession.ended_at.is_(None)).count()

    return {
        "window_days": flt.days,
        "successful_logins": successes,
        "failed_logins": failures,
        "unique_users": int(unique_users),
        "unique_ips": int(unique_ips),
        "active_sessions": active_sessions,
    }


def get_login_timeseries(days: int = 30, filters: Optional[TrafficFilters] = None) -> Dict[str, Any]:
    """Per-day successful vs. failed login counts."""
    from app_core.auth.audit import AuditAction, AuditLog

    flt = _resolve(days, filters)
    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)
    rows = flt.filter_timestamp(
        db.session.query(AuditLog.timestamp, AuditLog.action).filter(
            AuditLog.action.in_(login_actions)
        ),
        AuditLog.timestamp,
    ).all()

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


def _annotate_login_hostnames(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach reverse-DNS hostname + country to login records (awstats-style)."""
    ips = {r.get("ip_address") for r in records if r.get("ip_address")}
    if not ips:
        return records
    lookup: Dict[str, Dict[str, Any]] = {}
    try:
        rows = (
            db.session.query(
                WebRequestLog.ip_address,
                func.max(WebRequestLog.hostname).label("hostname"),
                func.max(WebRequestLog.country_code).label("country_code"),
            )
            .filter(WebRequestLog.ip_address.in_(ips))
            .group_by(WebRequestLog.ip_address)
            .all()
        )
        lookup = {
            r.ip_address: {"hostname": r.hostname, "country_code": r.country_code}
            for r in rows
        }
    except Exception:  # pragma: no cover - defensive: enrichment is best-effort
        try:
            db.session.rollback()
        except Exception:
            pass
        lookup = {}
    for r in records:
        meta = lookup.get(r.get("ip_address"), {})
        r["hostname"] = meta.get("hostname")
        r["country_code"] = meta.get("country_code")
    return records


def get_top_login_ips(days: int = 30, limit: int = 15, filters: Optional[TrafficFilters] = None) -> List[Dict[str, Any]]:
    """Source IPs ranked by login attempts, split by success/failure."""
    from app_core.auth.audit import AuditAction, AuditLog

    flt = _resolve(days, filters)
    login_actions = (AuditAction.LOGIN_SUCCESS.value, AuditAction.LOGIN_FAILURE.value)
    rows = (
        flt.filter_timestamp(
            db.session.query(
                AuditLog.ip_address,
                AuditLog.action,
                func.count(AuditLog.id).label("count"),
            ).filter(
                AuditLog.action.in_(login_actions),
                AuditLog.ip_address.isnot(None),
            ),
            AuditLog.timestamp,
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
    return _annotate_login_hostnames(result[:limit])


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
    return _annotate_login_hostnames(
        [
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "username": r.username,
                "ip_address": r.ip_address,
                "success": bool(r.success),
                "action": r.action,
            }
            for r in rows
        ]
    )


def get_full_dashboard(
    days: int = 30,
    self_hosts: Optional[set] = None,
    filters: Optional[TrafficFilters] = None,
) -> Dict[str, Any]:
    """Bundle every section the dashboard needs into one payload.

    *self_hosts* is the set of hostnames considered "internal" (the station's own
    host), used to exclude self-referrals from the referrer report. *filters*
    carries the active time window and any drill-down dimensions.
    """
    flt = _resolve(days, filters)
    from app_core.analytics.traffic_anomalies import detect_anomalies

    return {
        "summary": get_summary(filters=flt),
        "summary_prev": get_summary_previous(filters=flt),
        "timeseries": get_timeseries(filters=flt),
        "top_pages": get_top_pages(filters=flt),
        "slowest_pages": get_slowest_pages(filters=flt),
        "top_visitors": get_top_visitors(filters=flt),
        "status_breakdown": get_status_breakdown(filters=flt),
        "browser_breakdown": get_browser_breakdown(filters=flt),
        "os_breakdown": get_os_breakdown(filters=flt),
        "device_breakdown": get_device_breakdown(filters=flt),
        "method_breakdown": get_method_breakdown(filters=flt),
        "auth_breakdown": get_auth_breakdown(filters=flt),
        "referer_breakdown": get_referer_breakdown(self_hosts=self_hosts, filters=flt),
        "search_engine_breakdown": get_search_engine_breakdown(filters=flt),
        "resolution_breakdown": get_resolution_breakdown(filters=flt),
        "country_breakdown": get_country_breakdown(filters=flt),
        "city_breakdown": get_city_breakdown(filters=flt),
        "region_breakdown": get_region_breakdown(filters=flt),
        "asn_breakdown": get_asn_breakdown(filters=flt),
        "ip_version_breakdown": get_ip_version_breakdown(filters=flt),
        "language_breakdown": get_language_breakdown(filters=flt),
        "error_pages": get_error_pages(filters=flt),
        "error_sources": get_error_sources(filters=flt),
        "hourly_distribution": get_hourly_distribution(filters=flt),
        "weekday_distribution": get_weekday_distribution(filters=flt),
        "visits": get_visits(filters=flt),
        "filetype_breakdown": get_filetype_breakdown(filters=flt),
        "search_terms": get_search_terms(filters=flt),
        "bot_breakdown": get_bot_breakdown(filters=flt),
        "recent_requests": get_recent_requests(limit=25, filters=flt),
        "login_summary": get_login_summary(filters=flt),
        "login_timeseries": get_login_timeseries(filters=flt),
        "top_login_ips": get_top_login_ips(filters=flt),
        "recent_logins": get_recent_logins(limit=25),
        "anomalies": detect_anomalies(filters=flt),
        "filter_meta": flt.to_query_meta(),
    }


__all__ = [
    "get_summary",
    "get_summary_previous",
    "get_timeseries",
    "get_top_pages",
    "get_slowest_pages",
    "get_top_visitors",
    "get_status_breakdown",
    "get_browser_breakdown",
    "get_os_breakdown",
    "get_device_breakdown",
    "get_method_breakdown",
    "get_auth_breakdown",
    "get_referer_breakdown",
    "get_search_engine_breakdown",
    "get_resolution_breakdown",
    "get_country_breakdown",
    "get_city_breakdown",
    "get_region_breakdown",
    "get_asn_breakdown",
    "get_ip_version_breakdown",
    "get_language_breakdown",
    "get_recent_requests",
    "get_error_pages",
    "get_error_sources",
    "get_hourly_distribution",
    "get_weekday_distribution",
    "get_visits",
    "get_filetype_breakdown",
    "get_search_terms",
    "get_bot_breakdown",
    "get_login_summary",
    "get_login_timeseries",
    "get_top_login_ips",
    "get_recent_logins",
    "get_full_dashboard",
]
