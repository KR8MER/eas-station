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

"""A CAP alert row rendered for the admin alert views."""

from datetime import datetime
from typing import Any, Dict, Optional

from app_core.models import CAPAlert
from app_utils import UTC_TZ


def _alert_datetime_to_iso(dt_value: Optional[datetime]) -> Optional[str]:
    """Render alert datetimes in ISO8601 with UTC timezone."""

    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        aware_value = dt_value.replace(tzinfo=UTC_TZ)
    else:
        aware_value = dt_value.astimezone(UTC_TZ)
    return aware_value.isoformat()

def serialize_admin_alert(alert: CAPAlert) -> Dict[str, Any]:
    """Return a JSON-serializable representation of an alert for admin tooling."""

    return {
        "id": alert.id,
        "identifier": alert.identifier,
        "event": alert.event,
        "source": alert.source,
        "headline": alert.headline,
        "description": alert.description,
        "instruction": alert.instruction,
        "area_desc": alert.area_desc,
        "status": alert.status,
        "message_type": alert.message_type,
        "scope": alert.scope,
        "category": alert.category,
        "severity": alert.severity,
        "urgency": alert.urgency,
        "certainty": alert.certainty,
        "sent": _alert_datetime_to_iso(alert.sent),
        "expires": _alert_datetime_to_iso(alert.expires),
        "updated_at": _alert_datetime_to_iso(alert.updated_at),
        "created_at": _alert_datetime_to_iso(alert.created_at),
    }
