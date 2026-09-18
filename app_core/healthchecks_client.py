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

"""Thin client for healthchecks.io's Management API v3
(https://healthchecks.io/docs/api/).

Separate from heartbeat_worker.py's send_heartbeat_ping(), which speaks the
generic, unauthenticated healthchecks.io-style ping protocol that every
check's own ping_url accepts with no auth at all. This module is for the
account-level Management API -- creating/pausing/resuming/deleting a check
and reading its ping history -- which needs the account's API key (from
healthchecks.io -> Settings -> API Access), not the per-check ping token.

Unlike Tickstem's Monitors API (tickstem_client.py), healthchecks.io has no
"poll an external URL" product at all -- every check is a dead-man's-switch:
this box pings it, and healthchecks.io alerts if a ping doesn't arrive
within timeout+grace. That's the same shape as the existing per-service
Tickstem heartbeats (TickstemServiceHeartbeat), so this client only ever
needs the Checks endpoints, not anything resembling create_monitor().
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://healthchecks.io/api/v3"
_TIMEOUT = 15


class HealthchecksAPIError(Exception):
    """Raised when a healthchecks.io Management API call fails.

    Carries status_code so callers can react to specific cases -- e.g. 403
    "wrong api key" or a plan's check-count limit -- without parsing the
    message string.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _headers(api_key: str) -> dict:
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
    }


def _raise_for_error(response: "requests.Response") -> None:
    if 200 <= response.status_code < 300:
        return
    try:
        detail = response.json().get("error", response.text)
    except ValueError:
        detail = response.text
    raise HealthchecksAPIError(f"HTTP {response.status_code}: {detail}", status_code=response.status_code)


def create_check(
    api_key: str,
    name: str,
    timeout_secs: int = 300,
    grace_secs: int = 300,
    tags: str = "",
    unique_key: Optional[str] = None,
) -> dict:
    """Create a new healthchecks.io check. Returns the check dict (includes
    'ping_url', the no-auth URL this box POSTs to on schedule, and 'uuid',
    the identifier every other Management API call below needs).

    unique_key, when given, is compared against existing checks' name/tags/
    timeout by healthchecks.io itself and updates a match in place instead
    of creating a duplicate -- not used here since each per-service check's
    name is already unique per this deployment, but left available for a
    caller that wants idempotent creation.
    """
    payload = {"name": name, "timeout": timeout_secs, "grace": grace_secs, "tags": tags}
    if unique_key:
        payload["unique"] = [unique_key]
    response = requests.post(
        f"{_BASE_URL}/checks/",
        json=payload,
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def pause_check(api_key: str, check_uuid: str) -> dict:
    response = requests.post(
        f"{_BASE_URL}/checks/{check_uuid}/pause",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def resume_check(api_key: str, check_uuid: str) -> dict:
    response = requests.post(
        f"{_BASE_URL}/checks/{check_uuid}/resume",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def delete_check(api_key: str, check_uuid: str) -> None:
    response = requests.delete(
        f"{_BASE_URL}/checks/{check_uuid}",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)


def get_pings(api_key: str, check_uuid: str, limit: Optional[int] = 20) -> list:
    """Return recent pings for one check, most recent first."""
    response = requests.get(
        f"{_BASE_URL}/checks/{check_uuid}/pings/",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    pings = response.json().get("pings", [])
    return pings[:limit] if limit else pings


__all__ = [
    "HealthchecksAPIError",
    "create_check",
    "pause_check",
    "resume_check",
    "delete_check",
    "get_pings",
]
