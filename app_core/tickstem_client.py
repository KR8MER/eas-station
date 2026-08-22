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

"""Thin client for Tickstem's Monitors API (https://tickstem.dev/docs).

Separate from heartbeat_worker.py's send_heartbeat_ping(), which speaks the
generic, unauthenticated healthchecks.io-style ping protocol. This module
is Tickstem-specific: creating/pausing/resuming/deleting an *uptime*
monitor and reading its check history both require the account's bearer
API key (from app.tickstem.dev -> API Keys), not the heartbeat ping token.
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tickstem.dev/v1"
_TIMEOUT = 15


class TickstemAPIError(Exception):
    """Raised when a Tickstem Monitors API call fails."""


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _raise_for_error(response: "requests.Response") -> None:
    if 200 <= response.status_code < 300:
        return
    try:
        detail = response.json().get("error", response.text)
    except ValueError:
        detail = response.text
    raise TickstemAPIError(f"HTTP {response.status_code}: {detail}")


def create_monitor(
    api_key: str,
    name: str,
    url: str,
    interval_secs: int = 60,
    timeout_secs: int = 10,
) -> dict:
    """Create a new Tickstem uptime monitor. Returns the monitor dict (includes 'id')."""
    response = requests.post(
        f"{_BASE_URL}/monitors",
        json={
            "name": name,
            "url": url,
            "interval_secs": interval_secs,
            "timeout_secs": timeout_secs,
        },
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def pause_monitor(api_key: str, monitor_id: str) -> None:
    response = requests.patch(
        f"{_BASE_URL}/monitors/{monitor_id}/pause",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)


def resume_monitor(api_key: str, monitor_id: str) -> None:
    response = requests.patch(
        f"{_BASE_URL}/monitors/{monitor_id}/resume",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)


def delete_monitor(api_key: str, monitor_id: str) -> None:
    response = requests.delete(
        f"{_BASE_URL}/monitors/{monitor_id}",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)


def get_checks(api_key: str, monitor_id: str, limit: Optional[int] = 20) -> list:
    """Return recent checks, most recent first."""
    response = requests.get(
        f"{_BASE_URL}/monitors/{monitor_id}/checks",
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    checks = response.json()
    if not isinstance(checks, list):
        checks = checks.get("checks", [])
    return checks[:limit] if limit else checks


__all__ = [
    "TickstemAPIError",
    "create_monitor",
    "pause_monitor",
    "resume_monitor",
    "delete_monitor",
    "get_checks",
]
