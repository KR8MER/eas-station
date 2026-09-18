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

"""Determining EAS message precedence and enriching playout events with it."""

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from app_core.models import CAPAlert


# Import precedence levels for priority tracking
try:
    from app_core.audio.playout_queue import PrecedenceLevel
    PRECEDENCE_AVAILABLE = True
except ImportError:
    PRECEDENCE_AVAILABLE = False
    PrecedenceLevel = None

def determine_alert_precedence(alert: CAPAlert) -> Optional[str]:
    """
    Determine the FCC precedence level for a CAP alert.

    Args:
        alert: CAPAlert database model instance

    Returns:
        String name of precedence level, or None if cannot be determined
    """
    if not PRECEDENCE_AVAILABLE or not PrecedenceLevel:
        return None

    try:
        from app_core.audio.playout_queue import PlayoutItem

        # Use the PlayoutItem logic to determine precedence
        metadata = alert.raw_json or {}
        event_code = None

        # Try to extract event code from metadata
        if isinstance(metadata, dict):
            event_code = metadata.get('event_code')

        precedence_value = PlayoutItem._determine_precedence(
            event_code=event_code,
            scope=alert.scope,
            message_type=alert.message_type,
        )

        return PrecedenceLevel(precedence_value).name

    except Exception:
        return None

def get_precedence_statistics(
    alerts: Sequence[CAPAlert],
) -> Dict[str, Any]:
    """
    Calculate precedence-based statistics for a set of alerts.

    Args:
        alerts: Sequence of CAPAlert instances

    Returns:
        Dictionary with precedence statistics
    """
    if not PRECEDENCE_AVAILABLE:
        return {'available': False}

    precedence_counts: Dict[str, int] = defaultdict(int)
    severity_counts: Dict[str, int] = defaultdict(int)
    urgency_counts: Dict[str, int] = defaultdict(int)

    for alert in alerts:
        precedence = determine_alert_precedence(alert)
        if precedence:
            precedence_counts[precedence] += 1

        if alert.severity:
            severity_counts[alert.severity.upper()] += 1

        if alert.urgency:
            urgency_counts[alert.urgency.upper()] += 1

    return {
        'available': True,
        'precedence_distribution': dict(precedence_counts),
        'severity_distribution': dict(severity_counts),
        'urgency_distribution': dict(urgency_counts),
        'total_alerts': len(alerts),
    }

def enrich_playout_events_with_precedence(
    events: List[Dict[str, Any]],
    alerts_by_id: Dict[int, CAPAlert],
) -> List[Dict[str, Any]]:
    """
    Enrich playout event records with precedence information.

    Args:
        events: List of playout event dictionaries
        alerts_by_id: Mapping of alert IDs to CAPAlert instances

    Returns:
        Updated events list with precedence metadata
    """
    if not PRECEDENCE_AVAILABLE:
        return events

    for event in events:
        alert_id = event.get('alert_id')
        if alert_id and alert_id in alerts_by_id:
            alert = alerts_by_id[alert_id]
            precedence = determine_alert_precedence(alert)
            if precedence:
                event['precedence'] = precedence
                event['severity'] = alert.severity
                event['urgency'] = alert.urgency

    return events
