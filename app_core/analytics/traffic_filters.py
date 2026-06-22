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

"""Shared time-window and dimension filtering for Traffic Analytics.

:class:`TrafficFilters` is the single abstraction that powers two dashboard
features at once:

* **Custom date ranges** — instead of only the preset windows (24h/7d/30d/…),
  the dashboard can request an explicit ``start``/``end`` range. The filter
  resolves to a concrete ``(start, end)`` window via :meth:`window`.
* **Drill-down filtering** — clicking a country, path, status family, browser,
  OS or HTTP method on the dashboard narrows *every* section to matching rows.
  The active dimensions are applied uniformly through :meth:`apply`.

Every aggregation helper in ``traffic_stats`` accepts an optional
``filters=TrafficFilters(...)``; when omitted it falls back to the legacy
``days`` window so existing callers (and tests) keep working unchanged.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app_core.analytics.web_traffic import WebRequestLog
from app_utils import utc_now

# Bounds so a crafted request can't ask for an unbounded scan.
MIN_DAYS = 1
MAX_DAYS = 365
# Hard ceiling on an explicit custom range (covers the preset "Last year").
MAX_RANGE_DAYS = 366

# Dimensions a user can drill down on, mapped to the human label shown on a
# filter chip. Order controls chip display order.
_DIMENSION_LABELS = {
    "path": "Path",
    "path_prefix": "Path starts with",
    "ip_address": "IP",
    "country": "Country",
    "country_code": "Country code",
    "browser": "Browser",
    "os": "OS",
    "method": "Method",
    "status_family": "Status",
}


@dataclass
class TrafficFilters:
    """A resolved time window plus optional drill-down dimensions."""

    days: int = 30
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    # Drill-down dimensions (all optional; ``None`` means "no constraint").
    path: Optional[str] = None
    path_prefix: Optional[str] = None
    ip_address: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    method: Optional[str] = None
    # Status family is the leading digit (2/3/4/5) of the response code.
    status_family: Optional[int] = None

    def __post_init__(self) -> None:
        try:
            self.days = max(MIN_DAYS, min(int(self.days), MAX_DAYS))
        except (TypeError, ValueError):
            self.days = 30

    # ------------------------------------------------------------------ window
    def window(self) -> tuple:
        """Return the concrete ``(start, end)`` datetimes for this filter.

        An explicit ``start``/``end`` takes precedence; otherwise the window is
        the trailing ``days`` ending now.
        """
        end = self.end or utc_now()
        if self.start is not None:
            start = self.start
        else:
            start = end - timedelta(days=max(int(self.days), 1))
        if start > end:
            start, end = end, start
        return start, end

    def window_seconds(self) -> float:
        start, end = self.window()
        return max((end - start).total_seconds(), 1.0)

    def previous(self) -> "TrafficFilters":
        """The equal-length window immediately *before* this one (for deltas)."""
        start, end = self.window()
        span = end - start
        prev = TrafficFilters(**{**self._dimension_kwargs(), "start": start - span, "end": start})
        return prev

    # ------------------------------------------------------------------ apply
    def filter_timestamp(self, query, column):
        """Constrain *query* on an arbitrary timestamp *column* to this window.

        The lower bound (``>= start``) always applies. The upper bound
        (``< end``) is only applied when an explicit ``end`` was set — i.e. a
        custom range or the previous-period comparison. Preset trailing-day
        windows stay open-ended at the top so rows recorded "right now" (which
        may be a hair after the resolved ``end``) are still counted.
        """
        start, _ = self.window()
        query = query.filter(column >= start)
        if self.end is not None:
            query = query.filter(column < self.end)
        return query

    def apply_window(self, query):
        """Constrain *query* to this filter's time window."""
        return self.filter_timestamp(query, WebRequestLog.timestamp)

    def apply_dimensions(self, query):
        """Constrain *query* to the active drill-down dimensions."""
        if self.path:
            query = query.filter(WebRequestLog.path == self.path)
        if self.path_prefix:
            query = query.filter(WebRequestLog.path.like(self.path_prefix + "%"))
        if self.ip_address:
            query = query.filter(WebRequestLog.ip_address == self.ip_address)
        if self.country:
            query = query.filter(WebRequestLog.country == self.country)
        if self.country_code:
            query = query.filter(WebRequestLog.country_code == self.country_code)
        if self.browser:
            query = query.filter(WebRequestLog.browser == self.browser)
        if self.os:
            query = query.filter(WebRequestLog.os == self.os)
        if self.method:
            query = query.filter(WebRequestLog.method == self.method)
        if self.status_family:
            lo = int(self.status_family) * 100
            query = query.filter(
                WebRequestLog.status_code >= lo, WebRequestLog.status_code < lo + 100
            )
        return query

    def apply(self, query):
        """Apply both the time window and every active dimension to *query*."""
        return self.apply_dimensions(self.apply_window(query))

    # ------------------------------------------------------------------ helpers
    def has_dimensions(self) -> bool:
        return any(v is not None for v in self._dimension_kwargs().values())

    def _dimension_kwargs(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "path_prefix": self.path_prefix,
            "ip_address": self.ip_address,
            "country": self.country,
            "country_code": self.country_code,
            "browser": self.browser,
            "os": self.os,
            "method": self.method,
            "status_family": self.status_family,
        }

    def describe(self) -> List[Dict[str, str]]:
        """Return active dimensions as ``[{key,label,value}]`` for filter chips."""
        chips: List[Dict[str, str]] = []
        dims = self._dimension_kwargs()
        for key, label in _DIMENSION_LABELS.items():
            value = dims.get(key)
            if value is None:
                continue
            display = f"{value}xx" if key == "status_family" else str(value)
            chips.append({"key": key, "label": label, "value": display})
        return chips

    def window_label(self) -> str:
        """A short, human-readable label for the active window."""
        start, end = self.window()
        if self.start is not None or self.end is not None:
            return f"{start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}"
        return f"{self.days} day{'s' if self.days != 1 else ''}"

    def to_query_meta(self) -> Dict[str, Any]:
        """Compact description of the active filter for the API response."""
        start, end = self.window()
        return {
            "days": self.days,
            "custom_range": self.start is not None or self.end is not None,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "window_label": self.window_label(),
            "dimensions": self.describe(),
        }

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_request(cls, args, default_days: int = 30) -> "TrafficFilters":
        """Build a filter from Flask ``request.args`` (or any mapping).

        Recognises ``days`` plus ``start``/``end`` (ISO-8601 dates or
        datetimes) and any of the drill-down dimensions. Bad values are ignored
        rather than raising, so a malformed query degrades to the default
        window instead of erroring.
        """
        get = args.get

        days = default_days
        try:
            days = int(get("days", default_days))
        except (TypeError, ValueError):
            days = default_days

        start = _parse_dt(get("start"), end_of_day=False)
        end = _parse_dt(get("end"), end_of_day=True)
        # Guard against an over-wide custom range.
        if start is not None and end is not None:
            if (end - start) > timedelta(days=MAX_RANGE_DAYS):
                start = end - timedelta(days=MAX_RANGE_DAYS)

        status_family = None
        raw_status = get("status_family")
        if raw_status:
            try:
                fam = int(str(raw_status).rstrip("xX")[:1])
                if fam in (1, 2, 3, 4, 5):
                    status_family = fam
            except (TypeError, ValueError):
                status_family = None

        def clean(name: str, limit: int = 512) -> Optional[str]:
            value = get(name)
            if value is None:
                return None
            value = str(value).strip()
            return value[:limit] or None

        return cls(
            days=days,
            start=start,
            end=end,
            path=clean("path"),
            path_prefix=clean("path_prefix"),
            ip_address=clean("ip", 64) or clean("ip_address", 64),
            country=clean("country", 64),
            country_code=(clean("country_code", 2) or "").upper() or None,
            browser=clean("browser", 64),
            os=clean("os", 64),
            method=(clean("method", 8) or "").upper() or None,
            status_family=status_family,
        )


def _parse_dt(value: Optional[str], end_of_day: bool) -> Optional[datetime]:
    """Parse an ISO date/datetime string, or ``None`` on any problem.

    A bare ``YYYY-MM-DD`` is treated as the start (00:00) or, when
    *end_of_day* is set, the inclusive end (23:59:59.999999) of that day.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Accept a trailing "Z" (UTC) which datetime.fromisoformat rejects pre-3.11.
    if text.endswith("Z"):
        text = text[:-1]
    try:
        if len(text) == 10:  # date only
            dt = datetime.strptime(text, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


__all__ = ["TrafficFilters", "MIN_DAYS", "MAX_DAYS", "MAX_RANGE_DAYS"]
