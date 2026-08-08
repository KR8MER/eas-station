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

"""Query layer for the unified /logs hub.

``build_logs_loader`` returns the loader the ``/logs`` routes call. The loader
itself is now only a dispatch: every category lives in
``webapp/public/logs_sources/`` behind the shared ``LogQuery`` → ``LogPage``
contract, and this module picks the right one.
"""

from typing import Any, Dict, List, Optional, Tuple

from .logs_sources import LogQuery, MIN_LOGS_PER_CATEGORY, resolve_loader

# The display name a log type nobody handles falls back to, matching what the
# original if/elif chain produced by reaching the end without matching.
DEFAULT_LOG_TYPE_NAME = "System Logs"


def build_logs_loader(route_logger):
    """Return the loader the /logs routes call.

    Bound to ``route_logger`` the same way the original
    nested definition closed over it.
    """
    def _load_logs_data(
        log_type: str,
        limit: int,
        service_filter: str = None,
        action_filter: str = None,
    ) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Load the requested log data and metadata for rendering or export.

        Returns a triple of ``(display_name, logs_data, report_meta)``.  The
        third element is populated only for ``report_*`` log types and carries
        the FCC report's column labels, summary lines, and window — the
        template uses it to render a real columnar layout instead of cramming
        every column into the generic ``message`` cell.

        ``action_filter`` applies only to the ``audit`` log type and restricts
        the query to a single ``AuditAction`` value (e.g. ``config.updated``)
        at the database level so the newest matching rows aren't lost behind
        the ``limit`` window.
        """
        loader = resolve_loader(log_type)
        if loader is None:
            return DEFAULT_LOG_TYPE_NAME, [], None

        page = loader(LogQuery(
            log_type=log_type,
            limit=limit,
            service_filter=service_filter,
            action_filter=action_filter,
            logger=route_logger,
        ))
        return page.display_name, page.rows, page.report_meta

    return _load_logs_data


__all__ = ["MIN_LOGS_PER_CATEGORY", "build_logs_loader"]
