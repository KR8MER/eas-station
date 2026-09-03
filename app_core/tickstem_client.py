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
    """Raised when a Tickstem Monitors/Heartbeats API call fails.

    Carries status_code so callers can react to specific cases -- e.g. 402
    "quota reached for your plan" -- without parsing the message string.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


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
    raise TickstemAPIError(f"HTTP {response.status_code}: {detail}", status_code=response.status_code)


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


def create_heartbeat(
    api_key: str,
    name: str,
    interval_secs: int = 300,
    grace_secs: int = 300,
) -> dict:
    """Create a new Tickstem heartbeat (dead-man's-switch). Returns the
    heartbeat dict, which includes 'id' (for management calls) and 'token'
    (embed in a ping URL: https://api.tickstem.dev/v1/heartbeats/<token>/ping
    -- pinging needs no auth, the token itself is the credential).
    """
    response = requests.post(
        f"{_BASE_URL}/heartbeats",
        json={"name": name, "interval_secs": interval_secs, "grace_secs": grace_secs},
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def set_heartbeat_status(api_key: str, heartbeat_id: str, status: str) -> dict:
    """Pause or resume a heartbeat. status must be 'paused' or 'active'."""
    response = requests.patch(
        f"{_BASE_URL}/heartbeats/{heartbeat_id}",
        json={"status": status},
        headers=_headers(api_key),
        timeout=_TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def delete_heartbeat(api_key: str, heartbeat_id: str) -> None:
    response = requests.delete(
        f"{_BASE_URL}/heartbeats/{heartbeat_id}",
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
    "create_heartbeat",
    "set_heartbeat_status",
    "delete_heartbeat",
]
