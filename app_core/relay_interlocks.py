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

"""Database access for relay interlock (mutual-exclusion) groups."""

from typing import Any, Dict, List


def get_relay_interlock_groups(enabled_only: bool = True) -> List[Dict[str, Any]]:
    """Return interlock groups as plain dicts (id, name, pins, force_deactivate_conflict).

    Returns an empty list if the database/table is unavailable (e.g. before
    the migration has run, or outside an application context) rather than
    raising -- this is read at GPIO-subprocess startup and must never be the
    reason the whole controller fails to come up.
    """
    try:
        from app_core.models import RelayInterlockGroup

        query = RelayInterlockGroup.query
        if enabled_only:
            query = query.filter_by(enabled=True)
        groups = query.order_by(RelayInterlockGroup.name.asc()).all()
        return [
            {
                "id": g.id,
                "name": g.name,
                "enabled": g.enabled,
                "force_deactivate_conflict": g.force_deactivate_conflict,
                "pins": [m.pin for m in g.members],
            }
            for g in groups
        ]
    except Exception:
        return []
