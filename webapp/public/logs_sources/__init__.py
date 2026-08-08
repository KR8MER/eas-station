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

"""Per-category loaders for the unified /logs hub.

``webapp/public/logs_data.py`` used to be one 1,057-line function dispatching
on ``log_type`` through a seventeen-way ``if/elif`` chain. Each branch is now a
loader here, all sharing the :class:`~.common.LogQuery` /
:class:`~.common.LogPage` contract so the dispatcher can be a table lookup.

Adding a category means writing a loader, registering it in its module's
``LOADERS`` dict, and adding the tab to ``templates/logs.html`` — nothing in
``logs_data.py`` needs to change.
"""

from typing import Callable, Dict, Optional

from . import aggregate, audit, database, eas, reports, services
from .common import LogPage, LogQuery, MIN_LOGS_PER_CATEGORY, timestamp_sort_key
from .reports import REPORT_PREFIX, load_report

Loader = Callable[[LogQuery], LogPage]

# Exact ``log_type`` matches. The FCC reports are deliberately absent — they
# match on the ``report_`` prefix instead, since the kind is open-ended.
LOADERS: Dict[str, Loader] = {
    **aggregate.LOADERS,
    **database.LOADERS,
    **eas.LOADERS,
    **audit.LOADERS,
    **services.LOADERS,
}


def resolve_loader(log_type: str) -> Optional[Loader]:
    """The loader for ``log_type``, or ``None`` if nothing handles it.

    An unhandled type is not an error — the caller falls back to an empty
    "System Logs" page, which is what the pre-refactor ``if/elif`` chain did by
    reaching the end without matching.
    """
    loader = LOADERS.get(log_type)
    if loader is not None:
        return loader
    if log_type.startswith(REPORT_PREFIX):
        return load_report
    return None


__all__ = [
    "LOADERS",
    "LogPage",
    "LogQuery",
    "MIN_LOGS_PER_CATEGORY",
    "aggregate",
    "audit",
    "database",
    "eas",
    "reports",
    "resolve_loader",
    "services",
    "timestamp_sort_key",
]
