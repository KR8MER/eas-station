from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.location import get_location_settings
from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
    enumerate_devices,
    check_soapysdr_installation,
    get_device_capabilities,
    get_recommended_settings,
    SDR_PRESETS,
)


def _receiver_to_dict(receiver: RadioReceiver) -> Dict[str, Any]:
    latest = receiver.latest_status()
    return {
        "id": receiver.id,
        "identifier": receiver.identifier,
        "display_name": receiver.display_name,
        "driver": receiver.driver,
        "frequency_hz": receiver.frequency_hz,
        "sample_rate": receiver.sample_rate,
        "gain": receiver.gain,
        "channel": receiver.channel,
        "serial": receiver.serial,
        "auto_start": receiver.auto_start,
        "enabled": receiver.enabled,
        "notes": receiver.notes,
        "latest_status": (
            {
                "reported_at": latest.reported_at.isoformat() if latest and latest.reported_at else None,
                "locked": bool(latest.locked) if latest else None,
                "signal_strength": latest.signal_strength if latest else None,
                "last_error": latest.last_error if latest else None,
                "capture_mode": latest.capture_mode if latest else None,
                "capture_path": latest.capture_path if latest else None,
            }
            if latest
            else None
        ),
    }


def _parse_receiver_payload(payload: Dict[str, Any], *, partial: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    data: Dict[str, Any] = {}

    def _coerce_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return bool(value)

    if not partial or "identifier" in payload:
        identifier = str(payload.get("identifier", "")).strip()
        if not identifier:
            return None, "Identifier is required."
        data["identifier"] = identifier

    if not partial or "display_name" in payload:
        display_name = str(payload.get("display_name", "")).strip()
        if not display_name:
            return None, "Display name is required."
        data["display_name"] = display_name

    if not partial or "driver" in payload:
        driver = str(payload.get("driver", "")).strip()
        if not driver:
            return None, "Driver is required."
        data["driver"] = driver

    if not partial or "frequency_hz" in payload:
        try:
            frequency = float(payload.get("frequency_hz"))
            if frequency <= 0:
                raise ValueError
            data["frequency_hz"] = frequency
        except Exception:
            return None, "Frequency must be a positive number of hertz."

    if not partial or "sample_rate" in payload:
        try:
            sample_rate = int(payload.get("sample_rate"))
            if sample_rate <= 0:
                raise ValueError
            data["sample_rate"] = sample_rate
        except Exception:
            return None, "Sample rate must be a positive integer."

    if "gain" in payload:
        gain = payload.get("gain")
        if gain in (None, "", []):
            data["gain"] = None
        else:
            try:
                data["gain"] = float(gain)
            except Exception:
                return None, "Gain must be numeric."

    if "channel" in payload:
        channel = payload.get("channel")
        if channel in (None, "", []):
            data["channel"] = None
        else:
            try:
                parsed_channel = int(channel)
                if parsed_channel < 0:
                    raise ValueError
                data["channel"] = parsed_channel
            except Exception:
                return None, "Channel must be a non-negative integer."

    if "serial" in payload:
        serial = payload.get("serial")
        data["serial"] = str(serial).strip() if serial not in (None, "") else None

    if "auto_start" in payload or not partial:
        data["auto_start"] = _coerce_bool(payload.get("auto_start"), True)

    if "enabled" in payload or not partial:
        data["enabled"] = _coerce_bool(payload.get("enabled"), True)

    if "notes" in payload:
        notes = payload.get("notes")
        data["notes"] = str(notes).strip() if notes not in (None, "") else None

    return data, None


def register(app: Flask, logger) -> None:
    route_logger = logger.getChild("routes_settings_radio")

    @app.route("/settings/radio")
    def radio_settings() -> Any:
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Radio table validation failed: %s", exc)

        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name, RadioReceiver.identifier).all()
        location_settings = get_location_settings()

        return render_template(
            "settings/radio.html",
            receivers=[_receiver_to_dict(receiver) for receiver in receivers],
            location_settings=location_settings,
        )

    @app.route("/api/radio/receivers", methods=["GET"])
    def api_list_receivers() -> Any:
        ensure_radio_tables(route_logger)
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name, RadioReceiver.identifier).all()
        return jsonify({"receivers": [_receiver_to_dict(receiver) for receiver in receivers]})

    @app.route("/api/radio/receivers", methods=["POST"])
    def api_create_receiver() -> Any:
        ensure_radio_tables(route_logger)
        payload = request.get_json(silent=True) or {}
        data, error = _parse_receiver_payload(payload)
        if error:
            return jsonify({"error": error}), 400

        existing = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
        if existing:
            return jsonify({"error": "A receiver with this identifier already exists."}), 400

        receiver = RadioReceiver(**data)
        try:
            db.session.add(receiver)
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to create receiver: %s", exc)
            db.session.rollback()
            return jsonify({"error": "Failed to save receiver."}), 500

        return jsonify({"receiver": _receiver_to_dict(receiver)}), 201

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["PUT", "PATCH"])
    def api_update_receiver(receiver_id: int) -> Any:
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)
        payload = request.get_json(silent=True) or {}
        data, error = _parse_receiver_payload(payload, partial=True)
        if error:
            return jsonify({"error": error}), 400

        if "identifier" in data and data["identifier"] != receiver.identifier:
            conflict = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
            if conflict and conflict.id != receiver.id:
                return jsonify({"error": "Another receiver already uses this identifier."}), 400

        for key, value in data.items():
            setattr(receiver, key, value)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to update receiver %s: %s", receiver.identifier, exc)
            db.session.rollback()
            return jsonify({"error": "Failed to update receiver."}), 500

        return jsonify({"receiver": _receiver_to_dict(receiver)})

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["DELETE"])
    def api_delete_receiver(receiver_id: int) -> Any:
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            db.session.delete(receiver)
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to delete receiver %s: %s", receiver.identifier, exc)
            db.session.rollback()
            return jsonify({"error": "Failed to delete receiver."}), 500

        return jsonify({"success": True})

    @app.route("/api/radio/discover", methods=["GET"])
    def api_discover_devices() -> Any:
        """Enumerate all SoapySDR-compatible devices connected to the system."""
        try:
            devices = enumerate_devices()
            return jsonify({"devices": devices, "count": len(devices)})
        except Exception as exc:
            route_logger.error("Device enumeration failed: %s", exc)
            return jsonify({"error": str(exc), "devices": []}), 500

    @app.route("/api/radio/diagnostics", methods=["GET"])
    def api_radio_diagnostics() -> Any:
        """Check SoapySDR installation status and available drivers."""
        try:
            diagnostics = check_soapysdr_installation()
            return jsonify(diagnostics)
        except Exception as exc:
            route_logger.error("Diagnostics check failed: %s", exc)
            return jsonify({"error": str(exc), "ready": False}), 500

    @app.route("/api/radio/capabilities/<driver>", methods=["GET"])
    def api_device_capabilities(driver: str) -> Any:
        """Query capabilities of a specific SDR driver."""
        try:
            # Optional device-specific arguments from query params
            device_args = {}
            if request.args.get("serial"):
                device_args["serial"] = request.args.get("serial")
            if request.args.get("device_id"):
                device_args["device_id"] = request.args.get("device_id")

            capabilities = get_device_capabilities(driver, device_args if device_args else None)
            if capabilities is None:
                return jsonify({"error": f"Unable to query capabilities for driver '{driver}'"}), 404

            return jsonify(capabilities)
        except Exception as exc:
            route_logger.error("Failed to query capabilities for driver '%s': %s", driver, exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/radio/presets", methods=["GET"])
    def api_radio_presets() -> Any:
        """Get preset configurations for common SDR use cases."""
        return jsonify({"presets": SDR_PRESETS})

    @app.route("/api/radio/presets/<preset_key>", methods=["GET"])
    def api_radio_preset(preset_key: str) -> Any:
        """Get a specific preset configuration."""
        preset = SDR_PRESETS.get(preset_key)
        if preset is None:
            return jsonify({"error": f"Preset '{preset_key}' not found"}), 404
        return jsonify({"preset": preset})


__all__ = ["register"]
