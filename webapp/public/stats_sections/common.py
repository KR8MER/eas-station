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

"""The contract every /stats section shares.

The dashboard is a sequence of independent queries assembled into one dict. Any
of them can fail without the page being lost — a failing section logs, rolls the
session back, and contributes its declared fallback instead. That pattern was
repeated seventeen times inline; it now lives once, here.
"""

from typing import Any, Callable, Dict, List, NamedTuple

# A section reads the dict built so far (a few sections divide by an earlier
# section's total) and returns only its own fragment.
Collector = Callable[[Dict[str, Any]], Dict[str, Any]]
Fallback = Callable[[], Dict[str, Any]]


class StatsSection(NamedTuple):
    """One independently-failing chunk of the dashboard.

    ``error_message`` is a printf-style template taking the exception, kept
    verbatim from the original handler so log greps still match.
    """

    collect: Collector
    fallback: Fallback
    error_message: str


def empty_dow_hour_matrix() -> List[List[int]]:
    """A 7×24 grid of zeros — day of week by hour of day."""
    return [[0 for _ in range(24)] for _ in range(7)]


def run_sections(sections, logger) -> Dict[str, Any]:
    """Run every section in order, substituting fallbacks for failures.

    The rollback is not optional: a failed query leaves the SQLAlchemy session
    in an aborted transaction, so without it every *later* section would fail
    too and the dashboard would come back empty from the first error onward.
    """
    from app_core.extensions import db

    stats_data: Dict[str, Any] = {}
    for section in sections:
        try:
            stats_data.update(section.collect(stats_data))
        except Exception as exc:
            db.session.rollback()
            logger.error(section.error_message, exc)
            stats_data.update(section.fallback())
    return stats_data


__all__ = [
    "Collector",
    "Fallback",
    "StatsSection",
    "empty_dow_hour_matrix",
    "run_sections",
]
