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

"""1/5/15-minute load average, where the platform supports it."""

import os
from typing import Optional, Tuple


def _collect_load_averages() -> Optional[Tuple[float, float, float]]:
    """Return the platform's load averages, or None where unsupported."""

    try:
        if hasattr(os, "getloadavg"):
            return os.getloadavg()
    except Exception:
        pass
    return None
