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

"""How the gated-alerts hold-off timer has been used.

Counts by outcome (pending / auto-released / approved early / cancelled) so
an operator can see at a glance whether the gate is actually catching
anything, and whether they're approving/cancelling manually or mostly
letting the timer run out.
"""

from typing import Any, Dict

from app_core.models import AlertGatingSettings, GatedAlert

from .common import StatsSection

_EMPTY_GATED_ALERT_STATS: Dict[str, Any] = {
    "enabled": False,
    "hold_off_seconds": 0,
    "total": 0,
    "pending": 0,
    "released": 0,
    "approved": 0,
    "cancelled": 0,
}


def collect_gated_alert_stats(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Gate outcome counts, plus whether gating is currently turned on."""
    settings = AlertGatingSettings.query.first()
    return {
        "gated_alert_stats": {
            "enabled": bool(settings.enabled) if settings else False,
            "hold_off_seconds": settings.hold_off_seconds if settings else 0,
            "total": GatedAlert.query.count(),
            "pending": GatedAlert.query.filter_by(status="pending").count(),
            "released": GatedAlert.query.filter_by(status="released").count(),
            "approved": GatedAlert.query.filter_by(status="approved").count(),
            "cancelled": GatedAlert.query.filter_by(status="cancelled").count(),
        }
    }


GATED_ALERTS = StatsSection(
    collect_gated_alert_stats,
    lambda: {"gated_alert_stats": dict(_EMPTY_GATED_ALERT_STATS)},
    "Error getting gated-alert stats: %s",
)

__all__ = [
    "GATED_ALERTS",
    "collect_gated_alert_stats",
]
