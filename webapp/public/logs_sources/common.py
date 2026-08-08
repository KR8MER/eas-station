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

"""The contract every /logs category loader shares.

A loader takes one :class:`LogQuery` and returns one :class:`LogPage`. Keeping
the signature uniform is what lets ``logs_data.build_logs_loader`` dispatch
through a table instead of the ~17-branch ``if/elif`` chain it used to be.
"""

from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional

MIN_LOGS_PER_CATEGORY = 10  # Minimum logs to show per category in "All Logs" view


class LogQuery(NamedTuple):
    """Everything a category loader is allowed to depend on.

    ``service_filter`` is read only by the systemd loader and ``action_filter``
    only by the audit loader, but both travel with every query so the dispatch
    table can stay uniform.
    """

    log_type: str
    limit: int
    service_filter: Optional[str] = None
    action_filter: Optional[str] = None
    logger: Any = None


class LogPage(NamedTuple):
    """What a category loader produces.

    ``report_meta`` is populated only by the FCC report loader; every other
    category leaves it ``None``, which is what the ``/logs`` template keys off
    to decide between the columnar report layout and the generic log table.
    """

    display_name: str
    rows: List[Dict[str, Any]]
    report_meta: Optional[Dict[str, Any]] = None


def timestamp_sort_key(log_entry: Dict[str, Any]) -> datetime:
    """Sort key that tolerates missing and mixed-awareness timestamps.

    Database rows come back timezone-aware; ``datetime.fromtimestamp`` on a
    journal entry does not, and comparing the two raises. Rows with no
    timestamp at all sort to the bottom rather than blowing up the page.

    The ``all`` and ``services`` branches each carried a private copy of this
    function; the two were verified ``ast.dump()``-identical before being
    collapsed into this one.
    """
    ts = log_entry.get('timestamp')
    if ts is None:
        return datetime.min.replace(tzinfo=None)
    # Strip timezone info for consistent comparison
    if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
        return ts.replace(tzinfo=None)
    return ts


__all__ = ["LogPage", "LogQuery", "MIN_LOGS_PER_CATEGORY", "timestamp_sort_key"]
