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

"""Rendering a RadioReceiver row into the API/UI payload."""

import json
from typing import Any, Dict

from app_core.models import RadioReceiver

from .deps import _module_logger


def _make_offline_status(last_error: str, **flags) -> Dict[str, Any]:
    """Create a status dict for offline/unavailable receiver states."""
    status = {
        "reported_at": None,
        "locked": False,
        "signal_strength": None,
        "last_error": last_error,
        "capture_mode": None,
        "capture_path": None,
        "samples_available": False,
        "sample_count": 0,
        "running": False,
    }
    status.update(flags)
    return status


def _receiver_to_dict(receiver: RadioReceiver) -> Dict[str, Any]:
    # Try to get latest status, but handle DetachedInstanceError gracefully
    # This can happen if the receiver object is not bound to a session
    try:
        latest = receiver.latest_status()
    except Exception:
        # If we can't access the relationship, just skip the status
        latest = None

    # In separated architecture, status comes from Redis (published by sdr-service)
    # Try to get status from Redis first, fall back to database
    redis_status = None
    redis_available = False
    radio_manager_found = False
    try:
        from app_core.redis_client import get_redis_client
        redis_client = get_redis_client()
        redis_available = True

        # Read sdr-service metrics from Redis (published to sdr:metrics)
        sdr_metrics_json = redis_client.get("sdr:metrics")
        if sdr_metrics_json:
            if isinstance(sdr_metrics_json, bytes):
                sdr_metrics_json = sdr_metrics_json.decode('utf-8')
            radio_manager_data = json.loads(sdr_metrics_json)
            radio_manager_found = True

            # Find this receiver's status in the Redis data
            receivers_data = radio_manager_data.get("receivers", {})
            if receiver.identifier in receivers_data:
                redis_receiver = receivers_data[receiver.identifier]
                redis_status = {
                    "reported_at": redis_receiver.get("reported_at"),
                    "locked": redis_receiver.get("locked", False),
                    "signal_strength": redis_receiver.get("signal_strength"),
                    "last_error": redis_receiver.get("last_error"),
                    "capture_mode": None,  # Not tracked in Redis
                    "capture_path": None,  # Not tracked in Redis
                    "samples_available": redis_receiver.get("samples_available", False),
                    "sample_count": redis_receiver.get("sample_count", 0),
                    "running": redis_receiver.get("running", False),
                }
    except Exception as redis_exc:
        # Redis not available or error parsing - fall back to database status
        _module_logger.debug("Could not read receiver status from Redis: %s", redis_exc)

    # Use Redis status if available (it's more current), otherwise use database status
    if redis_status is not None:
        status_data = redis_status
    elif latest is not None:
        status_data = {
            "reported_at": latest.reported_at.isoformat() if latest.reported_at else None,
            "locked": bool(latest.locked),
            "signal_strength": latest.signal_strength,
            "last_error": latest.last_error,
            "capture_mode": latest.capture_mode,
            "capture_path": latest.capture_path,
            "samples_available": False,  # Database status doesn't track sample buffer
            "sample_count": 0,
            "running": False,  # Database status doesn't track running state
        }
    elif radio_manager_found:
        # Redis has radio_manager metrics but this receiver isn't loaded yet
        status_data = _make_offline_status(
            "Receiver not loaded in audio service",
            not_loaded=True
        )
    elif redis_available:
        # Redis is available but no radio_manager metrics yet (audio-service may not be running)
        status_data = _make_offline_status(
            "Audio service not publishing metrics",
            service_unavailable=True
        )
    else:
        # No status available at all - provide minimal structure
        status_data = _make_offline_status(
            "No status available",
            offline=True
        )

    return {
        "id": receiver.id,
        "identifier": receiver.identifier,
        "display_name": receiver.display_name,
        "driver": receiver.driver,
        "frequency_hz": receiver.frequency_hz,
        "sample_rate": receiver.sample_rate,
        "gain": receiver.gain,
        "external_lna_db": float(receiver.external_lna_db or 0.0),
        "bias_t_enabled": bool(receiver.bias_t_enabled),
        "channel": receiver.channel,
        "serial": receiver.serial,
        "auto_start": receiver.auto_start,
        "enabled": receiver.enabled,
        "notes": receiver.notes,
        "modulation_type": receiver.modulation_type,
        "audio_output": receiver.audio_output,
        "stereo_enabled": receiver.stereo_enabled,
        "deemphasis_us": receiver.deemphasis_us,
        "enable_rbds": receiver.enable_rbds,
        "latest_status": status_data,
    }


__all__ = [
    "_make_offline_status",
    "_receiver_to_dict",
]
