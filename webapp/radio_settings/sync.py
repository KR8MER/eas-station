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

"""Reconciling the database against the running RadioManager.

The database is the source of truth for which receivers should exist; these
functions push that state onto the live manager and the audio-ingest sources,
and report what changed.
"""

from typing import Any, Dict, List

from app_core.models import RadioReceiver
from webapp.admin.audio_ingest import (
    ensure_sdr_audio_monitor_source,
    list_radio_managed_audio_sources,
    remove_radio_managed_audio_source,
)

from . import deps
from .sdr_client import _send_sdr_command


def _sync_radio_manager_state(route_logger) -> Dict[str, Any]:
    """Reload radio manager configuration after CRUD operations."""

    summary: Dict[str, Any] = {
        "configured": 0,
        "auto_started": [],
        "errors": [],
    }
    
    enabled_receivers = RadioReceiver.query.filter_by(enabled=True).all()
    summary["configured"] = len(enabled_receivers)

    # CRITICAL: In separated architecture, tell sdr-service to reload receivers from database
    # This ensures sdr-service picks up newly created/updated/deleted receivers
    try:
        reload_result = _send_sdr_command("reload_receivers")
        if reload_result.get("success"):
            route_logger.info(
                "SDR service reloaded: %d receivers configured, %d started",
                reload_result.get("receivers_configured", 0),
                reload_result.get("receivers_started", 0)
            )
            # Only report actually started receivers, not just those with auto_start flag
            started_count = reload_result.get("receivers_started", 0)
            if started_count > 0:
                # Get the list of receivers that should have started
                auto_start_receivers = [r.identifier for r in enabled_receivers if r.auto_start]
                # Truncate to actual started count
                summary["auto_started"] = auto_start_receivers[:started_count]
            else:
                summary["auto_started"] = []
        else:
            error_msg = reload_result.get("error", "Unknown error")
            route_logger.warning("SDR service reload failed: %s", error_msg)
            summary["errors"].append(f"SDR service: {error_msg}")
    except Exception as exc:
        route_logger.error("Failed to communicate with SDR service: %s", exc)
        summary["errors"].append(f"SDR service unreachable: {exc}")
        
        # Fall back to app-side radio manager (for backward compatibility)
        try:
            radio_manager = deps.get_radio_manager()
            radio_manager.configure_from_records(enabled_receivers)

            for receiver in enabled_receivers:
                instance = radio_manager.get_receiver(receiver.identifier)

                if instance is not None and receiver.auto_start:
                    try:
                        instance.start()
                        summary["auto_started"].append(receiver.identifier)
                    except Exception as exc:  # pragma: no cover - hardware specific
                        message = f"Failed to auto-start {receiver.identifier}: {exc}"
                        route_logger.error(message, exc_info=True)
                        summary["errors"].append(message)
                        deps._log_radio_event(
                            "ERROR",
                            message,
                            module_suffix="sync",
                            details={
                                "identifier": receiver.identifier,
                                "error": str(exc),
                            },
                        )
        except Exception as fallback_exc:
            route_logger.error("Fallback radio manager also failed: %s", fallback_exc)
            summary["errors"].append(str(fallback_exc))

    _sync_audio_monitors(route_logger, enabled_receivers)

    return summary


def _sync_audio_monitors(route_logger, receivers: List[RadioReceiver]) -> None:
    """Ensure each receiver with audio output has an Icecast-backed monitor."""

    active_sources: set[str] = set()

    for receiver in receivers:
        try:
            result = ensure_sdr_audio_monitor_source(
                receiver,
                start_immediately=receiver.auto_start,
                commit=True,
            )
        except Exception as exc:
            route_logger.error(
                "Failed to ensure audio monitor for %s: %s",
                receiver.identifier,
                exc,
                exc_info=True,
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to ensure audio monitor for {receiver.identifier}: {exc}",
                module_suffix="audio",
                details={
                    "identifier": receiver.identifier,
                    "error": str(exc),
                },
            )
            continue

        source_name = result.get("source_name")
        if source_name and not result.get("removed"):
            active_sources.add(source_name)

    for config in list_radio_managed_audio_sources():
        if config.name in active_sources:
            continue
        try:
            if remove_radio_managed_audio_source(config.name):
                route_logger.info("Removed inactive SDR audio monitor %s", config.name)
        except Exception as exc:
            route_logger.error(
                "Failed to remove SDR audio monitor %s: %s", config.name, exc, exc_info=True
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to remove SDR audio monitor {config.name}: {exc}",
                module_suffix="audio",
                details={
                    "source_name": config.name,
                    "error": str(exc),
                },
            )


__all__ = [
    "_sync_audio_monitors",
    "_sync_radio_manager_state",
]
