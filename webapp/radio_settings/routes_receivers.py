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

"""Receiver CRUD: list, create, update, delete."""

from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.cache import cache
from app_core.extensions import db
from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
)
from app_core.auth.roles import require_permission

from . import deps
from .payload import _parse_receiver_payload
from .sdr_client import _send_sdr_command
from .serialization import _receiver_to_dict
from .sync import _sync_radio_manager_state


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/api/radio/receivers", methods=["GET"])
    @cache.cached(timeout=15, key_prefix='receivers_list')
    def api_list_receivers() -> Any:
        ensure_radio_tables(route_logger)
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        return jsonify({"receivers": [_receiver_to_dict(receiver) for receiver in receivers]})

    @app.route("/api/radio/receivers", methods=["POST"])
    @require_permission('receivers.configure')
    def api_create_receiver() -> Any:
        try:
            ensure_radio_tables(route_logger)
            payload = request.get_json(silent=True) or {}

            route_logger.info(f"Creating new receiver with payload: {payload}")

            data, error = _parse_receiver_payload(payload)
            if error:
                route_logger.error(f"Validation error for new receiver: {error}")
                return jsonify({"error": error}), 400

            existing = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
            if existing:
                return jsonify({"error": "A receiver with this identifier already exists."}), 400

            receiver = RadioReceiver(**data)
            try:
                db.session.add(receiver)
                db.session.commit()
                receiver_id = receiver.id
            except SQLAlchemyError as exc:
                route_logger.error("Failed to create receiver: %s", exc)
                db.session.rollback()
                deps._log_radio_event(
                    "ERROR",
                    f"Failed to create receiver {data.get('identifier')}: {exc}",
                    module_suffix="crud",
                    details={
                        "identifier": data.get("identifier"),
                        "error": str(exc),
                    },
                )
                return jsonify({"error": "Failed to save receiver."}), 500

            manager_state = _sync_radio_manager_state(route_logger)

            # Re-query the receiver to ensure it's bound to the session
            receiver = db.session.query(RadioReceiver).filter_by(id=receiver_id).first()
            if not receiver:
                return jsonify({"error": "Receiver not found after creation."}), 404

            # Ensure the receiver is in the current session
            db.session.refresh(receiver)

            # Clear the cached receiver list so it shows updated data
            cache.delete('receivers_list')

            return jsonify({
                "receiver": _receiver_to_dict(receiver),
                "radio_manager": manager_state,
            }), 201

        except Exception as exc:
            # Catch ALL unexpected errors and return JSON instead of HTML
            route_logger.error(f"Unexpected error creating receiver: {exc}", exc_info=True)
            return jsonify({
                "error": f"Unexpected error: {str(exc)}",
                "type": type(exc).__name__
            }), 500

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["PUT", "PATCH"])
    @require_permission('receivers.configure')
    def api_update_receiver(receiver_id: int) -> Any:
        try:
            ensure_radio_tables(route_logger)
            receiver = RadioReceiver.query.get_or_404(receiver_id)
            payload = request.get_json(silent=True) or {}

            route_logger.info(f"Updating receiver {receiver_id} with payload: {payload}")

            data, error = _parse_receiver_payload(payload, partial=True)
            if error:
                route_logger.error(f"Validation error for receiver {receiver_id}: {error}")
                return jsonify({"error": error}), 400

            if "identifier" in data and data["identifier"] != receiver.identifier:
                conflict = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
                if conflict and conflict.id != receiver.id:
                    return jsonify({"error": "Another receiver already uses this identifier."}), 400

            # Detect frequency-only changes so we can issue a live retune
            # instead of bouncing the whole audio system.  A change counts as
            # "frequency only" when nothing else (driver, sample rate, gain,
            # modulation, enabled state, identifier, …) is being touched.
            receiver_identifier = receiver.identifier
            old_frequency = receiver.frequency_hz
            new_frequency = data.get("frequency_hz")
            non_freq_keys = {k for k in data.keys() if k != "frequency_hz"}
            frequency_only_change = (
                "frequency_hz" in data
                and not non_freq_keys
                and new_frequency is not None
                and float(new_frequency) != float(old_frequency or 0)
                and bool(receiver.enabled)
            )

            for key, value in data.items():
                setattr(receiver, key, value)

            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                route_logger.error("Failed to update receiver %s: %s", receiver.identifier, exc)
                db.session.rollback()
                deps._log_radio_event(
                    "ERROR",
                    f"Failed to update receiver {receiver.identifier}: {exc}",
                    module_suffix="crud",
                    details={
                        "identifier": receiver.identifier,
                        "error": str(exc),
                    },
                )
                return jsonify({"error": "Failed to update receiver."}), 500

            # Try a live retune first when only the frequency changed.  If the
            # driver/device cannot retune live, fall back to the full reload.
            manager_state: Optional[Dict[str, Any]] = None
            if frequency_only_change:
                tune_result = _send_sdr_command(
                    "tune_frequency",
                    receiver_id=receiver_identifier,
                    frequency_hz=float(new_frequency),
                )
                if tune_result.get("success"):
                    route_logger.info(
                        "Live retune succeeded for %s: %.6f MHz -> %.6f MHz",
                        receiver_identifier,
                        float(old_frequency or 0) / 1_000_000,
                        float(new_frequency) / 1_000_000,
                    )
                    manager_state = {
                        "configured": 1,
                        "auto_started": [],
                        "errors": [],
                        "live_retune": True,
                    }
                else:
                    route_logger.warning(
                        "Live retune unavailable for %s (%s); falling back to reload",
                        receiver_identifier,
                        tune_result.get("error", "unknown reason"),
                    )

            if manager_state is None:
                manager_state = _sync_radio_manager_state(route_logger)

            # Explicitly re-query with a fresh session query to avoid DetachedInstanceError
            # We use filter_by + first() instead of get() to ensure a fresh query
            receiver = db.session.query(RadioReceiver).filter_by(id=receiver_id).first()
            if not receiver:
                return jsonify({"error": "Receiver not found after update."}), 404

            # Ensure the receiver is in the current session
            db.session.refresh(receiver)

            # Clear the cached receiver list so it shows updated data
            cache.delete('receivers_list')

            return jsonify({
                "receiver": _receiver_to_dict(receiver),
                "radio_manager": manager_state,
            })

        except Exception as exc:
            # Catch ALL unexpected errors and return JSON instead of HTML
            route_logger.error(f"Unexpected error updating receiver {receiver_id}: {exc}", exc_info=True)
            return jsonify({
                "error": f"Unexpected error: {str(exc)}",
                "type": type(exc).__name__
            }), 500

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["DELETE"])
    @require_permission('receivers.configure')
    def api_delete_receiver(receiver_id: int) -> Any:
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            db.session.delete(receiver)
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to delete receiver %s: %s", receiver.identifier, exc)
            db.session.rollback()
            deps._log_radio_event(
                "ERROR",
                f"Failed to delete receiver {receiver.identifier}: {exc}",
                module_suffix="crud",
                details={
                    "identifier": receiver.identifier,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Failed to delete receiver."}), 500

        manager_state = _sync_radio_manager_state(route_logger)

        # Clear the cached receiver list so it shows updated data
        cache.delete('receivers_list')

        return jsonify({"success": True, "radio_manager": manager_state})


__all__ = ["register"]
