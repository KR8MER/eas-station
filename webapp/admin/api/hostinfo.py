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

"""Host CPU and address readings for the system-status endpoint.

``psutil.cpu_percent(interval=None)`` is only meaningful as a delta between
calls, so the sample is cached here and refreshed at most every five seconds
rather than blocking the request.

That cache is module-level mutable state mutated under ``global``. It has to
stay in the module that mutates it, and must never be imported by value
elsewhere — ``from .hostinfo import _last_cpu_sample_value`` would snapshot the
value at import time and never see an update.
"""

import contextlib
import socket
from datetime import datetime
from typing import Optional

import psutil


_CPU_SAMPLE_INTERVAL_SECONDS: float = 5.0

_last_cpu_sample_timestamp: Optional[datetime] = None

_last_cpu_sample_value: float = 0.0

def _get_cpu_usage_percent() -> float:
    """Return a recently sampled CPU percentage without blocking the request."""

    global _last_cpu_sample_timestamp, _last_cpu_sample_value

    now = datetime.utcnow()
    if (
        _last_cpu_sample_timestamp is None
        or (now - _last_cpu_sample_timestamp).total_seconds() >= _CPU_SAMPLE_INTERVAL_SECONDS
    ):
        _last_cpu_sample_value = psutil.cpu_percent(interval=None)
        _last_cpu_sample_timestamp = now
    return _last_cpu_sample_value

def _get_primary_ip_address() -> Optional[str]:
    """Best-effort detection of the host's primary IPv4 address."""

    try:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
            sock.connect(("8.8.8.8", 80))
            ip_address = sock.getsockname()[0]
            if ip_address:
                return ip_address
    except OSError:
        pass

    try:
        ip_address = socket.gethostbyname(socket.gethostname())
        if ip_address:
            return ip_address
    except OSError:
        pass

    return None
