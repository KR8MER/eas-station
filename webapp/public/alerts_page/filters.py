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

"""Request arguments for /alerts, parsed and validated once.

Everything here is attacker-controlled, so nothing is trusted: pagination is
clamped, the sort column is allow-listed against real model columns (it is
interpolated into ORDER BY), and unparseable dates are dropped rather than
raising. A dropped date is also cleared from the echoed filter state, so the
form does not redisplay a value that had no effect.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app_core.models import CAPAlert

# Columns a caller may sort by. The key is the public name; the value is the
# column. Anything not in here falls back to DEFAULT_SORT.
SORTABLE_COLUMNS = {
    "event": CAPAlert.event,
    "severity": CAPAlert.severity,
    "status": CAPAlert.status,
    "source": CAPAlert.source,
    "sent": CAPAlert.sent,
    "expires": CAPAlert.expires,
    "headline": CAPAlert.headline,
    "area": CAPAlert.area_desc,
}

DEFAULT_SORT = "sent"
DEFAULT_DIRECTION = "desc"
DEFAULT_PER_PAGE = 25
MIN_PER_PAGE = 10
MAX_PER_PAGE = 100
DATE_FORMAT = "%Y-%m-%d"

# Spellings accepted for the boolean toggles. URL builders and hand-typed links
# disagree about this, so all the common ones are honoured.
TRUTHY = {"true", "1", "t", "yes", "on"}


def _as_bool(raw: Any) -> bool:
    return str(raw).lower() in TRUTHY


def _as_int(raw: str) -> Optional[int]:
    """``None`` rather than raising, for filters that may be junk."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class AlertFilters:
    """One parsed /alerts request.

    ``date_from``/``date_to`` keep the *string* the form should redisplay —
    blanked if it did not parse — while ``date_from_dt``/``date_to_dt`` carry
    the values the query uses.
    """

    page: int = 1
    per_page: int = DEFAULT_PER_PAGE
    search: str = ""
    status: str = ""
    severity: str = ""
    event: str = ""
    source: str = ""
    vtec_office: str = ""
    vtec_etn: str = ""
    vtec_year: str = ""
    show_expired: bool = False
    show_superseded: bool = False
    date_from: str = ""
    date_to: str = ""
    date_from_dt: Optional[datetime] = None
    date_to_dt: Optional[datetime] = None
    sort: str = DEFAULT_SORT
    direction: str = DEFAULT_DIRECTION

    @property
    def vtec_active(self) -> bool:
        """Whether the request is browsing a VTEC event chain.

        Derived from the raw strings, not the parsed integers, so a malformed
        ``vtec_etn`` still counts: the caller clearly meant to follow a chain,
        and the chain must not be silently truncated by the expiry filters.
        """
        return bool(self.vtec_office or self.vtec_etn or self.vtec_year)

    @property
    def vtec_etn_int(self) -> Optional[int]:
        return _as_int(self.vtec_etn)

    @property
    def vtec_year_int(self) -> Optional[int]:
        return _as_int(self.vtec_year)

    @property
    def sort_column(self):
        return SORTABLE_COLUMNS[self.sort]

    def as_template_dict(self) -> Dict[str, Any]:
        """The ``current_filters`` mapping the template redisplays."""
        return {
            "search": self.search,
            "status": self.status,
            "severity": self.severity,
            "event": self.event,
            "source": self.source,
            "per_page": self.per_page,
            "show_expired": self.show_expired,
            "show_superseded": self.show_superseded,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "vtec_office": self.vtec_office,
            "vtec_etn": self.vtec_etn,
            "vtec_year": self.vtec_year,
            "sort": self.sort,
            "direction": self.direction,
        }


def parse_filters(request) -> AlertFilters:
    """Build :class:`AlertFilters` from a Flask request."""
    args = request.args

    page = max(1, args.get("page", 1, type=int))
    per_page = min(max(args.get("per_page", DEFAULT_PER_PAGE, type=int), MIN_PER_PAGE), MAX_PER_PAGE)

    sort = args.get("sort", DEFAULT_SORT).strip().lower()
    if sort not in SORTABLE_COLUMNS:
        sort = DEFAULT_SORT
    direction = args.get("direction", DEFAULT_DIRECTION).strip().lower()
    if direction not in {"asc", "desc"}:
        direction = DEFAULT_DIRECTION

    date_from = args.get("date_from", "").strip()
    date_from_dt = None
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, DATE_FORMAT)
        except ValueError:
            date_from = ""

    date_to = args.get("date_to", "").strip()
    date_to_dt = None
    if date_to:
        try:
            # The filter is ``sent < date_to_dt``, so a whole extra day is
            # added to make the requested date inclusive.
            date_to_dt = datetime.strptime(date_to, DATE_FORMAT) + timedelta(days=1)
        except ValueError:
            date_to = ""

    return AlertFilters(
        page=page,
        per_page=per_page,
        search=args.get("search", "").strip(),
        status=args.get("status", "").strip(),
        severity=args.get("severity", "").strip(),
        event=args.get("event", "").strip(),
        source=args.get("source", "").strip(),
        vtec_office=args.get("vtec_office", "").strip(),
        vtec_etn=args.get("vtec_etn", "").strip(),
        vtec_year=args.get("vtec_year", "").strip(),
        show_expired=_as_bool(args.get("show_expired", "")),
        show_superseded=_as_bool(args.get("show_superseded", "")),
        date_from=date_from,
        date_to=date_to,
        date_from_dt=date_from_dt,
        date_to_dt=date_to_dt,
        sort=sort,
        direction=direction,
    )


__all__ = [
    "AlertFilters",
    "DATE_FORMAT",
    "DEFAULT_DIRECTION",
    "DEFAULT_PER_PAGE",
    "DEFAULT_SORT",
    "MAX_PER_PAGE",
    "MIN_PER_PAGE",
    "SORTABLE_COLUMNS",
    "TRUTHY",
    "parse_filters",
]
