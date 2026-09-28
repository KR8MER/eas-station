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

"""Off-air self-monitoring ("air-check") of this station's own transmitter.

See ``service`` for the lifecycle and ``matching`` for the header
comparison rules. Theory: docs/architecture/THEORY_OF_OPERATION.md
("Verification & Compliance").
"""

from .matching import compare_headers, normalize_header, parse_header
from .reporting import collect_air_check_issues, summarize
from .roles import (
    DEFAULT_GRACE_SECONDS,
    MAX_GRACE_SECONDS,
    MIN_GRACE_SECONDS,
    RECEIVER_ROLES,
    ROLE_AIR_CHECK,
    ROLE_MONITOR,
    air_check_receivers,
    clear_role_cache,
    get_grace_seconds,
    resolve_source_role,
)
from .service import record_off_air_decode, register_transmission, sweep_overdue

__all__ = [
    "DEFAULT_GRACE_SECONDS",
    "MAX_GRACE_SECONDS",
    "MIN_GRACE_SECONDS",
    "RECEIVER_ROLES",
    "ROLE_AIR_CHECK",
    "ROLE_MONITOR",
    "air_check_receivers",
    "clear_role_cache",
    "collect_air_check_issues",
    "compare_headers",
    "get_grace_seconds",
    "normalize_header",
    "parse_header",
    "record_off_air_decode",
    "register_transmission",
    "resolve_source_role",
    "summarize",
    "sweep_overdue",
]
