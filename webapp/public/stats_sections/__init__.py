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

"""The /stats dashboard's data layer.

``webapp/public/stats.py`` used to be one 645-line handler: seventeen
``try/except`` blocks in a row, each running a few queries, writing into a
shared ``stats_data`` dict and declaring its own fallback. Each block is now a
section in this package, and ``build_stats_data`` runs them.
"""

from typing import Any, Dict

from . import alerts_overview, broadcast, coverage, polling, timeline
from .common import StatsSection, empty_dow_hour_matrix, run_sections

# The pipeline, in the order the original handler ran it. The order is listed
# here rather than implied by module grouping because it is load-bearing:
# EAS_FORWARDING, MESSAGE_TYPES and COVERAGE_OVERLAP each divide by
# ``total_alerts``, so they must run after BASIC_COUNTS. The rest are
# independent and are kept in their original positions so the error-log
# sequence on a broken database is unchanged.
SECTIONS = (
    alerts_overview.BASIC_COUNTS,
    alerts_overview.BOUNDARY_STATS,
    alerts_overview.ALERT_CATEGORIES,
    timeline.TIME_BUCKETS,
    coverage.MOST_AFFECTED_BOUNDARIES,
    coverage.DURATION_STATS,
    alerts_overview.URGENCY_CERTAINTY,
    broadcast.EAS_FORWARDING,
    broadcast.MANUAL_ACTIVATIONS,
    broadcast.RECEIVED_EAS,
    timeline.ALERT_EVENTS,
    polling.POLLING,
    alerts_overview.MESSAGE_TYPES,
    coverage.COVERAGE_OVERLAP,
    broadcast.BROADCAST_LATENCY,
    broadcast.RELAY_STATS,
    polling.POLLING_TREND,
)


def apply_derived_defaults(stats_data: Dict[str, Any]) -> None:
    """Fill in the two keys no section produces.

    ``stats.html`` indexes both unconditionally, and neither has a query behind
    it: ``avg_durations`` is an alias the template uses for the duration table,
    and ``lifecycle_timeline`` is a placeholder for a chart that is not wired up
    yet.

    The original handler followed these with 29 further ``setdefault`` calls
    covering every other key. Those were verified redundant — each section sets
    its keys on both its success *and* its failure path, so the defaults could
    never fire — and the section contract now guarantees the same property
    structurally. They are not reproduced here.
    """
    stats_data.setdefault("duration_stats", [])
    stats_data.setdefault("avg_durations", stats_data.get("duration_stats", []))
    stats_data.setdefault("lifecycle_timeline", [])


def build_stats_data(logger) -> Dict[str, Any]:
    """Assemble the whole /stats payload, tolerating any section failing."""
    stats_data = run_sections(SECTIONS, logger)
    apply_derived_defaults(stats_data)
    return stats_data


__all__ = [
    "SECTIONS",
    "StatsSection",
    "alerts_overview",
    "apply_derived_defaults",
    "broadcast",
    "build_stats_data",
    "coverage",
    "empty_dow_hour_matrix",
    "polling",
    "run_sections",
    "timeline",
]
