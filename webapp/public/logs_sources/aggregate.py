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

"""The "All Logs" view — every category merged into one timeline.

Three things make this deliberately *not* a loop over the focused loaders in
the sibling modules, however much it looks like one:

1. **The row shape is different.** Every row here carries a ``category`` label
   and a deliberately trimmed ``details`` payload; the focused views carry the
   full payload and an ``alert_identifier``. Reusing the focused loaders would
   change what the page renders.
2. **Each category is independently fault-tolerant.** A category that raises is
   logged and skipped so one broken table cannot take the whole page down. The
   focused views have no such wrapper — there, a failure *should* surface.
3. **Each category is capped separately** at ``logs_per_category`` before the
   merge, so a chatty table cannot crowd out the others.

The collectors themselves live in ``aggregate_collectors.py`` and are run in
the fixed order of its ``COLLECTORS`` tuple. Adding a category means adding a
collector there and one tuple entry.
"""

from datetime import datetime
from typing import Any, Dict, List

from app_core.config import get_all_log_services
from app_core.extensions import db
from webapp.routes_logs import get_systemd_logs

from .aggregate_collectors import COLLECTORS
from .common import LogPage, LogQuery, MIN_LOGS_PER_CATEGORY, timestamp_sort_key

MIN_JOURNAL_LINES_PER_SERVICE = 3


def _collect_service_logs(cap: int, logger: Any) -> List[Dict[str, Any]]:
    """Journal lines for every unit, sharing ``cap`` between them.

    Note the row shape differs from the focused ``services`` view: ``details``
    carries only the service name here, and the row gains a ``category``.
    """
    rows: List[Dict[str, Any]] = []
    services = get_all_log_services()
    lines_per_service = max(MIN_JOURNAL_LINES_PER_SERVICE, cap // len(services)) if services else 10
    for service in services:
        result = get_systemd_logs(service, lines=lines_per_service, priority=None, since=None)
        if result.get('success') and result.get('logs'):
            for log_entry in result['logs']:
                rows.append({
                    'timestamp': datetime.fromtimestamp(int(log_entry['timestamp']) / 1000000) if log_entry.get('timestamp') else None,
                    'level': 'ERROR' if log_entry.get('priority', '6') in ['0', '1', '2', '3'] else 'WARNING' if log_entry.get('priority') == '4' else 'INFO',
                    'module': log_entry.get('unit', service),
                    'message': log_entry.get('message', ''),
                    'details': {'service': service},
                    'category': 'Services'
                })
    return rows


def load_all(query: LogQuery) -> LogPage:
    """Every category merged into one newest-first timeline."""
    # For 'all' type, return logs organized by category
    # Each category gets a portion of the limit
    logs_per_category = max(MIN_LOGS_PER_CATEGORY, query.limit // 10)
    all_logs: List[Dict[str, Any]] = []

    for collector, failure_message in COLLECTORS:
        # One category failing must not take the whole page down. The rollback
        # matters as much as the log line: a failed query leaves the session in
        # an aborted transaction, and every later collector would then fail too.
        try:
            all_logs.extend(collector(logs_per_category))
        except Exception as e:
            db.session.rollback()
            query.logger.warning(failure_message, e)

    # Service logs are outside the loop because they are not a database
    # category — there is no session to roll back when journalctl fails.
    try:
        all_logs.extend(_collect_service_logs(logs_per_category, query.logger))
    except Exception as e:
        query.logger.warning("Failed to load service logs: %s", e)

    # Sort all logs by timestamp (handle both timezone-aware and naive datetimes)
    all_logs.sort(key=timestamp_sort_key, reverse=True)
    return LogPage("All Logs", all_logs[:query.limit])


LOADERS = {
    'all': load_all,
}

__all__ = ["LOADERS", "MIN_JOURNAL_LINES_PER_SERVICE", "load_all"]
