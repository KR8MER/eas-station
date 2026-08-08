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

"""The systemd journal category on /logs.

This is the tab that keeps operators out of a shell: everything ``journalctl``
would show for the EAS Station units, rendered in the browser. See the
CLI-free operations rule in ``docs/development/AGENTS.md``.
"""

from datetime import datetime
from typing import Any, Dict, List

from app_core.config import get_all_log_services
from webapp.routes_logs import get_systemd_logs

from .common import LogPage, LogQuery, timestamp_sort_key

MIN_LINES_PER_SERVICE = 5


def journal_entry_to_log(log_entry: Dict[str, Any], service: str) -> Dict[str, Any]:
    """One journal record shaped into the generic log dict.

    Journal timestamps are microseconds since the epoch as a string; a record
    without one yields ``None`` rather than raising, and sorts to the bottom.
    Syslog priorities 0–3 are errors, 4 is a warning, everything else is info.
    """
    return {
        'timestamp': datetime.fromtimestamp(int(log_entry['timestamp']) / 1000000) if log_entry.get('timestamp') else None,
        'level': 'ERROR' if log_entry.get('priority', '6') in ['0', '1', '2', '3'] else 'WARNING' if log_entry.get('priority') == '4' else 'INFO',
        'module': log_entry.get('unit', service),
        'message': log_entry.get('message', ''),
        'details': {'service': service, 'priority': log_entry.get('priority')},
    }


def load_services(query: LogQuery) -> LogPage:
    """Recent journal lines for every EAS Station unit, newest first."""
    # Fetch systemd journal logs for EAS Station services
    logs_data: List[Dict[str, Any]] = []

    # If a specific service is selected, only fetch from that service
    if query.service_filter and query.service_filter in get_all_log_services():
        services_to_fetch = [query.service_filter]
        lines_per_service = query.limit
    else:
        services_to_fetch = get_all_log_services()
        lines_per_service = (
            max(MIN_LINES_PER_SERVICE, query.limit // len(services_to_fetch))
            if services_to_fetch else query.limit
        )

    for service in services_to_fetch:
        # Don't restrict to 'today' - fetch recent logs regardless of date
        result = get_systemd_logs(service, lines=lines_per_service, priority=None, since=None)
        if result.get('success') and result.get('logs'):
            for log_entry in result['logs']:
                logs_data.append(journal_entry_to_log(log_entry, service))
        elif not result.get('success'):
            # Log the error but continue with other services
            query.logger.debug("Failed to fetch logs for %s: %s", service, result.get('error', 'Unknown error'))

    logs_data.sort(key=timestamp_sort_key, reverse=True)
    return LogPage("Service Logs (systemd)", logs_data[:query.limit])


LOADERS = {
    'services': load_services,
}

__all__ = ["LOADERS", "MIN_LINES_PER_SERVICE", "journal_entry_to_log", "load_services"]
