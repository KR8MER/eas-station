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

"""What the station actually put to air, and how quickly.

These are the compliance-facing numbers: how many received alerts were relayed,
how many were originated locally, the delay between a CAP alert arriving and the
EAS message being generated, and whether the relays fired.
"""

from typing import Any, Dict

from app_core.extensions import db
from app_core.models import (
    CAPAlert,
    EASMessage,
    GPIOActivationLog,
    ManualEASActivation,
    ReceivedEASAlert,
)
from sqlalchemy import func

from .common import StatsSection


def collect_eas_forwarding(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """What share of ingested alerts were forwarded to air."""
    eas_forwarded_count = CAPAlert.query.filter_by(eas_forwarded=True).count()
    total_for_eas = stats_data.get("total_alerts") or 0
    return {
        "eas_forwarding_stats": {
            "forwarded": eas_forwarded_count,
            "total": total_for_eas,
            "rate": round(eas_forwarded_count / total_for_eas * 100, 1) if total_for_eas > 0 else 0,
        }
    }


def collect_manual_activation_count(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """How many alerts an operator originated from this station."""
    return {"manual_activation_count": ManualEASActivation.query.count()}


def collect_received_eas(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Alerts decoded off monitored sources, split by relay decision."""
    return {
        "received_eas_stats": {
            "total": ReceivedEASAlert.query.count(),
            "forwarded": ReceivedEASAlert.query.filter_by(forwarding_decision="forwarded").count(),
            "ignored": ReceivedEASAlert.query.filter_by(forwarding_decision="ignored").count(),
        }
    }


def collect_broadcast_latency(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Seconds between a CAP alert being sent and its EAS message existing.

    ``None`` rather than a zeroed dict when there is nothing to measure — the
    template distinguishes "no data yet" from "zero latency".
    """
    latency_result = (
        db.session.query(
            func.avg(
                func.extract("epoch", EASMessage.created_at) - func.extract("epoch", CAPAlert.sent)
            ).label("avg_seconds"),
            func.min(
                func.extract("epoch", EASMessage.created_at) - func.extract("epoch", CAPAlert.sent)
            ).label("min_seconds"),
            func.max(
                func.extract("epoch", EASMessage.created_at) - func.extract("epoch", CAPAlert.sent)
            ).label("max_seconds"),
            func.count(EASMessage.id).label("total"),
        )
        .join(CAPAlert, EASMessage.cap_alert_id == CAPAlert.id)
        .filter(CAPAlert.sent.isnot(None), EASMessage.created_at.isnot(None))
        .first()
    )
    if latency_result and latency_result.avg_seconds is not None:
        return {
            "broadcast_latency": {
                "avg_seconds": round(float(latency_result.avg_seconds), 1),
                "min_seconds": round(float(latency_result.min_seconds), 1),
                "max_seconds": round(float(latency_result.max_seconds), 1),
                "total_broadcasts": latency_result.total,
            }
        }
    return {"broadcast_latency": None}


def collect_relay_stats(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """GPIO relay activations: how many, how reliable, how long."""
    relay_by_type = (
        db.session.query(
            GPIOActivationLog.activation_type,
            func.count(GPIOActivationLog.id).label("count"),
            func.avg(GPIOActivationLog.duration_seconds).label("avg_duration"),
        )
        .group_by(GPIOActivationLog.activation_type)
        .all()
    )
    relay_total = GPIOActivationLog.query.count()
    relay_success = GPIOActivationLog.query.filter_by(success=True).count()
    return {
        "relay_stats": {
            "total": relay_total,
            "success_rate": round(relay_success / relay_total * 100, 1) if relay_total > 0 else 0,
            "by_type": [
                {
                    "type": act_type or "unknown",
                    "count": count,
                    "avg_duration": round(float(avg_dur), 1) if avg_dur else 0,
                }
                for act_type, count, avg_dur in relay_by_type
            ],
        }
    }


# Divides by ``total_alerts``, so it must run after BASIC_COUNTS.
EAS_FORWARDING = StatsSection(
    collect_eas_forwarding,
    lambda: {"eas_forwarding_stats": {"forwarded": 0, "total": 0, "rate": 0}},
    "Error getting EAS forwarding stats: %s",
)
MANUAL_ACTIVATIONS = StatsSection(
    collect_manual_activation_count, lambda: {"manual_activation_count": 0},
    "Error getting manual activation count: %s",
)
RECEIVED_EAS = StatsSection(
    collect_received_eas,
    lambda: {"received_eas_stats": {"total": 0, "forwarded": 0, "ignored": 0}},
    "Error getting received EAS stats: %s",
)
BROADCAST_LATENCY = StatsSection(
    collect_broadcast_latency, lambda: {"broadcast_latency": None},
    "Error getting broadcast latency stats: %s",
)
RELAY_STATS = StatsSection(
    collect_relay_stats,
    lambda: {"relay_stats": {"total": 0, "success_rate": 0, "by_type": []}},
    "Error getting relay activation stats: %s",
)

__all__ = [
    "BROADCAST_LATENCY",
    "EAS_FORWARDING",
    "MANUAL_ACTIVATIONS",
    "RECEIVED_EAS",
    "RELAY_STATS",
    "collect_broadcast_latency",
    "collect_eas_forwarding",
    "collect_manual_activation_count",
    "collect_received_eas",
    "collect_relay_stats",
]
