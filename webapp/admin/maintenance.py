"""Administrative maintenance and manual import routes."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request
from sqlalchemy import desc, or_, text
from sqlalchemy.exc import OperationalError

from app_core.alerts import (
    assign_alert_geometry,
    calculate_alert_intersections,
    parse_noaa_cap_alert,
)
from app_core.extensions import db
from app_core.led import ensure_led_tables
from app_core.location import (
    describe_location_reference,
    get_location_settings,
    update_location_settings,
)
from app_core.models import (
    CAPAlert,
    Intersection,
    LEDMessage,
    SystemLog,
)
from app_utils import UTC_TZ, format_bytes, get_location_timezone, local_now, utc_now


# Create Blueprint for maintenance routes
maintenance_bp = Blueprint('maintenance', __name__)

NOAA_API_BASE_URL = "https://api.weather.gov/alerts"
NOAA_ALLOWED_QUERY_PARAMS = frozenset(
    {
        "area",
        "zone",
        "region",
        "region_type",
        "point",
        "start",
        "end",
        "event",
        "status",
        "message_type",
        "urgency",
        "severity",
        "certainty",
        "limit",
        "cursor",
    }
)
NOAA_USER_AGENT = os.environ.get(
    "NOAA_USER_AGENT",
    "KR8MER Emergency Alert Hub/2.1 (+https://github.com/KR8MER/eas-station; NOAA+IPAWS)",
)

_OPERATION_LOCK = Lock()
_OPERATION_STATE: Dict[str, Dict[str, Any]] = {
    "backup": {
        "running": False,
        "last_started_at": None,
        "last_finished_at": None,
        "last_status": None,
        "last_message": None,
        "last_output": None,
        "last_error_output": None,
    },
    "upgrade": {
        "running": False,
        "last_started_at": None,
        "last_finished_at": None,
        "last_status": None,
        "last_message": None,
        "last_output": None,
        "last_error_output": None,
    },
}


def _format_operation_timestamp(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(UTC_TZ).isoformat()


def _serialize_operation_state(name: str) -> Dict[str, Any]:
    with _OPERATION_LOCK:
        state = dict(_OPERATION_STATE.get(name, {}))
    if not state:
        return {
            "running": False,
            "last_started_at": None,
            "last_finished_at": None,
            "last_status": None,
            "last_message": None,
            "last_output": None,
            "last_error_output": None,
        }
    return {
        "running": bool(state.get("running", False)),
        "last_started_at": _format_operation_timestamp(state.get("last_started_at")),
        "last_finished_at": _format_operation_timestamp(state.get("last_finished_at")),
        "last_status": state.get("last_status"),
        "last_message": state.get("last_message"),
        "last_output": state.get("last_output"),
        "last_error_output": state.get("last_error_output"),
    }

def _serialize_all_operations() -> Dict[str, Dict[str, Any]]:
    return {name: _serialize_operation_state(name) for name in _OPERATION_STATE.keys()}


def _sanitize_label(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"}).strip("-_ ")
    return cleaned[:48]

def _start_background_operation(
    name: str,
    command: List[str],
    *,
    cwd: Path,
    logger,
    description: str,
) -> None:
    with _OPERATION_LOCK:
        state = _OPERATION_STATE[name]
        if state["running"]:
            raise RuntimeError(f"Another {name} operation is already running.")
        state.update(
            {
                "running": True,
                "last_started_at": utc_now(),
                "last_message": f"{description} started.",
                "last_status": "running",
                "last_output": "",
                "last_error_output": "",
            }
        )

    def worker() -> None:
        stdout_text = ""
        stderr_text = ""
        message = ""
        success = False
        returncode: Optional[int] = None
        try:
            # Log operation name only, not full command (may contain sensitive data)
            logger.info("Starting %s operation", name)
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=str(cwd),
            )
            stdout_text = (completed.stdout or "").strip()
            stderr_text = (completed.stderr or "").strip()
            returncode = completed.returncode
            success = returncode == 0
            if success:
                message = stdout_text.splitlines()[-1] if stdout_text else f"{description} completed successfully."
                logger.info("%s operation finished successfully", name)
            else:
                fallback_message = stderr_text.splitlines()[-1] if stderr_text else ""
                if not fallback_message and stdout_text:
                    fallback_message = stdout_text.splitlines()[-1]
                message = fallback_message or f"{description} failed with exit code {returncode}."
                logger.error("%s operation failed with exit code %s", name, returncode)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("%s operation failed with an unexpected error", name)
            message = f"{description} failed: {exc}"
            stderr_text = str(exc)
        finally:
            finished_at = utc_now()
            with _OPERATION_LOCK:
                state = _OPERATION_STATE[name]
                state["running"] = False
                state["last_finished_at"] = finished_at
                state["last_status"] = "success" if success else "failed"
                state["last_message"] = message
                state["last_output"] = stdout_text[:4000] if stdout_text else ""
                state["last_error_output"] = stderr_text[:4000] if stderr_text else ""

    Thread(target=worker, daemon=True).start()


class NOAAImportError(Exception):
    """Raised when manual NOAA alert retrieval fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        query_url: Optional[str] = None,
        params: Optional[Dict[str, Union[str, int]]] = None,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.query_url = query_url
        self.params = params
        self.detail = detail


def normalize_manual_import_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Normalize manual import datetimes to UTC for consistent NOAA queries."""

    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            dt_value = datetime.fromisoformat(raw_value)
        except ValueError:
            try:
                dt_value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            except ValueError:
                return None
    if dt_value.tzinfo is None:
        dt_value = get_location_timezone().localize(dt_value)
    return dt_value.astimezone(UTC_TZ)


def format_noaa_timestamp(dt_value: Optional[datetime]) -> Optional[str]:
    """Render UTC timestamps in the NOAA API's preferred ISO format."""

    if not dt_value:
        return None
    return dt_value.astimezone(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_noaa_alert_request(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
) -> Tuple[str, Optional[Dict[str, Union[str, int]]]]:
    """Construct the NOAA alerts endpoint and query parameters for manual imports."""

    query_url = NOAA_API_BASE_URL
    params: Optional[Dict[str, Union[str, int]]] = None

    if identifier:
        encoded_identifier = quote(identifier.strip(), safe=":.")
        query_url = f"{NOAA_API_BASE_URL}/{encoded_identifier}.json"
    else:
        params = {}
        if start:
            formatted_start = format_noaa_timestamp(start)
            if formatted_start:
                params["start"] = formatted_start
        if end:
            formatted_end = format_noaa_timestamp(end)
            if formatted_end:
                params["end"] = formatted_end
        if area:
            params["area"] = area
        if event:
            params["event"] = event

        if params:
            params = {
                key: value
                for key, value in params.items()
                if key in NOAA_ALLOWED_QUERY_PARAMS and value is not None
            } or None
        else:
            params = None

    return query_url, params


def _alert_datetime_to_iso(dt_value: Optional[datetime]) -> Optional[str]:
    """Render alert datetimes in ISO8601 with UTC timezone."""

    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        aware_value = dt_value.replace(tzinfo=UTC_TZ)
    else:
        aware_value = dt_value.astimezone(UTC_TZ)
    return aware_value.isoformat()


def serialize_admin_alert(alert: CAPAlert) -> Dict[str, Any]:
    """Return a JSON-serializable representation of an alert for admin tooling."""

    return {
        "id": alert.id,
        "identifier": alert.identifier,
        "event": alert.event,
        "source": alert.source,
        "headline": alert.headline,
        "description": alert.description,
        "instruction": alert.instruction,
        "area_desc": alert.area_desc,
        "status": alert.status,
        "message_type": alert.message_type,
        "scope": alert.scope,
        "category": alert.category,
        "severity": alert.severity,
        "urgency": alert.urgency,
        "certainty": alert.certainty,
        "sent": _alert_datetime_to_iso(alert.sent),
        "expires": _alert_datetime_to_iso(alert.expires),
        "updated_at": _alert_datetime_to_iso(alert.updated_at),
        "created_at": _alert_datetime_to_iso(alert.created_at),
    }


def retrieve_noaa_alerts(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
):
    """Execute a NOAA alerts query and return parsed features."""

    query_url, params = build_noaa_alert_request(
        identifier=identifier,
        start=start,
        end=end,
        area=area,
        event=event,
        limit=limit,
    )

    headers = {
        "Accept": "application/geo+json, application/json;q=0.9",
        "User-Agent": NOAA_USER_AGENT,
    }

    try:
        response = requests.get(query_url, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        raise NOAAImportError(
            f"Failed to retrieve NOAA alert data: {exc}",
            query_url=query_url,
            params=params,
        ) from exc

    final_url = response.url

    if response.status_code == 404:
        raise NOAAImportError(
            "No alert was found for the supplied identifier or filters.",
            status_code=404,
            query_url=final_url,
            params=params,
        )

    if response.status_code >= 400:
        error_detail: Optional[str] = None
        parameter_errors: Optional[List[str]] = None
        try:
            error_payload = response.json()
            if isinstance(error_payload, dict):
                error_detail = error_payload.get("detail") or error_payload.get("title")
                raw_parameter_errors = error_payload.get("parameterErrors")
                if isinstance(raw_parameter_errors, list):
                    formatted_errors = []
                    for item in raw_parameter_errors:
                        if isinstance(item, dict):
                            name = item.get("parameter")
                            message = item.get("message")
                            if name and message:
                                formatted_errors.append(f"{name}: {message}")
                    if formatted_errors:
                        parameter_errors = formatted_errors
        except ValueError:
            error_detail = response.text.strip() or None

        message = f"Failed to retrieve NOAA alert data: {response.status_code} {response.reason}"
        if error_detail:
            message = f"{message} ({error_detail})"
        if parameter_errors:
            message = f"{message} — {'; '.join(parameter_errors)}"

        raise NOAAImportError(
            message,
            status_code=response.status_code,
            query_url=final_url,
            params=params,
            detail=error_detail,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise NOAAImportError(
            "NOAA API response could not be decoded as JSON.",
            query_url=final_url,
            params=params,
        ) from exc

    if identifier:
        if isinstance(payload, dict) and "features" in payload:
            alerts_payloads = payload.get("features", []) or []
        else:
            alerts_payloads = [payload]
    else:
        alerts_payloads = payload.get("features", []) if isinstance(payload, dict) else []

    if not identifier:
        try:
            effective_limit = max(1, min(int(limit or 10), 50))
        except (TypeError, ValueError):
            effective_limit = 10
        alerts_payloads = alerts_payloads[:effective_limit]

    if not alerts_payloads:
        raise NOAAImportError(
            "NOAA API did not return any alerts for the provided criteria.",
            status_code=404,
            query_url=final_url,
            params=params,
        )

    return alerts_payloads, final_url, params


def register_maintenance_routes(app, logger):
    """Attach administrative maintenance endpoints to the Flask app."""
    
    # Register the blueprint with the app
    app.register_blueprint(maintenance_bp)
    logger.info("Maintenance routes registered")


# Route definitions

@maintenance_bp.route("/admin/operations/status", methods=["GET"])
def get_operation_status():
    return jsonify({"operations": _serialize_all_operations()})

@maintenance_bp.route("/admin/operations/backup", methods=["POST"])
def run_one_click_backup():
    payload = request.get_json(silent=True) or {}
    label_value = payload.get("label", "")
    sanitized_label = _sanitize_label(label_value) if isinstance(label_value, str) else ""
    extra_args: List[str] = []
    if sanitized_label:
        extra_args.extend(["--label", sanitized_label])
    output_dir = payload.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        extra_args.extend(["--output-dir", output_dir.strip()])
    python_executable = sys.executable or "python3"
    command = [python_executable, str(repo_root / "tools" / "create_backup.py"), *extra_args]
    try:
        _start_background_operation(
            "backup",
            command,
            cwd=repo_root,
            logger=logger,
            description="Backup",
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": str(exc), "operation": _serialize_operation_state("backup")}),
            409,
        )
    message = "Backup started."
    if sanitized_label:
        message = f"Backup started (label: {sanitized_label})."
    return jsonify({"message": message, "operation": _serialize_operation_state("backup")})

@maintenance_bp.route("/admin/operations/upgrade", methods=["POST"])
def run_one_click_upgrade():
    payload = request.get_json(silent=True) or {}
    python_executable = sys.executable or "python3"
    command = [python_executable, str(repo_root / "tools" / "inplace_upgrade.py")]
    checkout_value = payload.get("checkout")
    compose_file = payload.get("compose_file")
    summary_bits = []
    if isinstance(checkout_value, str) and checkout_value.strip():
        checkout_clean = checkout_value.strip()
        command.extend(["--checkout", checkout_clean])
        summary_bits.append(f"checkout {checkout_clean}")
    if isinstance(compose_file, str) and compose_file.strip():
        compose_clean = compose_file.strip()
        command.extend(["--compose-file", compose_clean])
        summary_bits.append(f"compose {compose_clean}")
    if payload.get("skip_migrations"):
        command.append("--skip-migrations")
        summary_bits.append("skip migrations")
    if payload.get("allow_dirty"):
        command.append("--allow-dirty")
        summary_bits.append("allow dirty worktree")
    try:
        _start_background_operation(
            "upgrade",
            command,
            cwd=repo_root,
            logger=logger,
            description="Upgrade",
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": str(exc), "operation": _serialize_operation_state("upgrade")}),
            409,
        )
    message = "Upgrade started."
    if summary_bits:
        message = f"Upgrade started ({', '.join(summary_bits)})."
    return jsonify({"message": message, "operation": _serialize_operation_state("upgrade")})

@maintenance_bp.route("/admin/check_db_health", methods=["GET"])
def check_db_health():
    """Provide a quick health check of the database connection and size."""

    try:
        db.session.execute(text("SELECT 1"))
        connectivity_status = "Connected"
    except OperationalError as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return jsonify({"error": "Database connectivity check failed."}), 500
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error during database health check: %s", exc)
        return (
            jsonify(
                {
                    "error": "Database health check encountered an unexpected error.",
                }
            ),
            500,
        )

    database_size = "Unavailable"
    try:
        size_bytes = db.session.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()
        if size_bytes is not None:
            database_size = format_bytes(size_bytes)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not determine database size: %s", exc)

    active_connections: Union[str, int] = "Unavailable"
    try:
        connection_count = db.session.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database()"
            )
        ).scalar()
        if connection_count is not None:
            active_connections = int(connection_count)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not determine active connection count: %s", exc)

    return jsonify(
        {
            "connectivity": connectivity_status,
            "database_size": database_size,
            "active_connections": active_connections,
            "checked_at": utc_now().isoformat(),
        }
    )

@maintenance_bp.route("/admin/optimize_db", methods=["POST"])
def optimize_database():
    """Optimize database performance using VACUUM and ANALYZE."""

    try:
        # Get database size before optimization
        size_before = db.session.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()

        # Run VACUUM to reclaim space and optimize
        # Note: VACUUM cannot run inside a transaction block
        db.session.commit()  # Ensure any pending transaction is committed
        connection = db.engine.raw_connection()
        try:
            connection.set_isolation_level(0)  # AUTOCOMMIT mode
            cursor = connection.cursor()
            cursor.execute("VACUUM ANALYZE")
            cursor.close()
        finally:
            connection.close()

        # Important: Remove the session after raw connection usage
        # This ensures the next query gets a fresh connection
        db.session.remove()

        # Get database size after optimization (with fresh session)
        size_after = db.session.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()

        space_reclaimed = size_before - size_after if size_before and size_after else 0

        # Log the optimization
        log_entry = SystemLog(
            level="INFO",
            message="Database optimization completed",
            module="admin",
            details={
                "optimized_at_utc": utc_now().isoformat(),
                "optimized_at_local": local_now().isoformat(),
                "size_before": format_bytes(size_before) if size_before else "Unknown",
                "size_after": format_bytes(size_after) if size_after else "Unknown",
                "space_reclaimed": format_bytes(space_reclaimed) if space_reclaimed > 0 else "0 bytes",
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        logger.info("Database optimized successfully. Space reclaimed: %s", format_bytes(space_reclaimed) if space_reclaimed > 0 else "0 bytes")

        return jsonify({
            "message": "Database optimized successfully",
            "size_before": format_bytes(size_before) if size_before else "Unknown",
            "size_after": format_bytes(size_after) if size_after else "Unknown",
            "space_reclaimed": format_bytes(space_reclaimed) if space_reclaimed > 0 else "0 bytes",
        })

    except Exception as exc:
        logger.error("Error optimizing database: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Database optimization failed: {str(exc)}"}), 500

@maintenance_bp.route("/admin/env_config", methods=["GET", "POST"])
def env_config():
    """Read or update the environment configuration file (.env or stack.env)."""

    # Support both .env (CLI deployments) and stack.env (Portainer deployments)
    env_file_path = repo_root / ".env"
    if not env_file_path.exists():
        env_file_path = repo_root / "stack.env"

    if request.method == "GET":
        try:
            if not env_file_path.exists():
                return jsonify({"error": f"Environment file not found (checked .env and stack.env)"}), 404

            with open(env_file_path, "r") as f:
                content = f.read()

            # Parse the env file to extract key-value pairs (excluding comments)
            env_vars = {}
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()

            return jsonify({
                "content": content,
                "env_vars": env_vars,
                "path": str(env_file_path),
            })

        except Exception as exc:
            logger.error("Failed to read env file: %s", exc)
            return jsonify({"error": f"Failed to read configuration: {exc}"}), 500

    # POST - Update the env file
    try:
        payload = request.get_json(silent=True) or {}
        new_content = payload.get("content", "")

        if not new_content:
            return jsonify({"error": "No content provided"}), 400

        # Initialize backup_path
        backup_path = None

        # Create backup of existing file
        if env_file_path.exists():
            backup_path = env_file_path.with_suffix(".env.backup")
            import shutil
            shutil.copy2(env_file_path, backup_path)
            logger.info("Created backup of %s at %s", env_file_path.name, backup_path)

        # Write new content
        with open(env_file_path, "w") as f:
            f.write(new_content)

        # Log the change
        log_entry = SystemLog(
            level="WARNING",
            message="Environment configuration file updated via admin interface",
            module="admin",
            details={
                "updated_at_utc": utc_now().isoformat(),
                "updated_at_local": local_now().isoformat(),
                "file_path": str(env_file_path),
                "backup_created": str(backup_path) if backup_path else None,
                "warning": "Application restart required for changes to take effect",
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        logger.warning("Environment configuration updated. Restart required for changes to take effect.")

        return jsonify({
            "message": "Configuration updated successfully. Restart the application for changes to take effect.",
            "backup_path": str(backup_path) if backup_path else None,
            "restart_required": True,
        })

    except Exception as exc:
        logger.error("Failed to update env file: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to update configuration: {exc}"}), 500

@maintenance_bp.route("/admin/trigger_poll", methods=["POST"])
def trigger_poll():
    try:
        log_entry = SystemLog(
            level="INFO",
            message="Manual CAP poll triggered",
            module="admin",
            details={
                "triggered_at_utc": utc_now().isoformat(),
                "triggered_at_local": local_now().isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({"message": "CAP poll triggered successfully"})
    except Exception as exc:
        logger.error("Error triggering poll: %s", exc)
        return jsonify({"error": str(exc)}), 500

@maintenance_bp.route("/admin/location_settings", methods=["GET", "PUT"])
def admin_location_settings():
    try:
        if request.method == "GET":
            settings = get_location_settings()
            return jsonify({"settings": settings})

        payload = request.get_json(silent=True) or {}
        updated = update_location_settings(
            {
                "county_name": payload.get("county_name"),
                "state_code": payload.get("state_code"),
                "timezone": payload.get("timezone"),
                "fips_codes": payload.get("fips_codes"),
                "zone_codes": payload.get("zone_codes"),
                "area_terms": payload.get("area_terms"),
                "led_default_lines": payload.get("led_default_lines"),
                "map_center_lat": payload.get("map_center_lat"),
                "map_center_lng": payload.get("map_center_lng"),
                "map_default_zoom": payload.get("map_default_zoom"),
            }
        )
        return jsonify({"success": "Location settings updated", "settings": updated})
    except Exception as exc:
        logger.error("Error processing location settings update: %s", exc)
        return jsonify({"error": f"Failed to process location settings: {exc}"}), 500

@maintenance_bp.route("/admin/location_reference", methods=["GET"])
def admin_location_reference():
    try:
        summary = describe_location_reference()
        return jsonify(summary)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load location reference data: %s", exc)
        return (
            jsonify(
                {
                    "error": "Failed to load location reference data.",
                }
            ),
            500,
        )

@maintenance_bp.route("/admin/import_alert", methods=["POST"])
def import_specific_alert():
    data = request.get_json(silent=True) or request.form or {}

    identifier = (data.get("identifier") or "").strip()
    start_raw = (data.get("start") or "").strip()
    end_raw = (data.get("end") or "").strip()
    area = (data.get("area") or "").strip()
    event_filter = (data.get("event") or "").strip()

    try:
        limit_value = int(data.get("limit", 10))
    except (TypeError, ValueError):
        limit_value = 10
    limit_value = max(1, min(limit_value, 50))

    start_dt = normalize_manual_import_datetime(start_raw)
    end_dt = normalize_manual_import_datetime(end_raw)

    if start_raw and start_dt is None:
        return (
            jsonify(
                {
                    "error": "Could not parse the provided start timestamp. Use ISO 8601 format (e.g., 2025-01-15T13:00:00-05:00).",
                }
            ),
            400,
        )

    if end_raw and end_dt is None:
        return (
            jsonify(
                {
                    "error": "Could not parse the provided end timestamp. Use ISO 8601 format (e.g., 2025-01-15T18:00:00-05:00).",
                }
            ),
            400,
        )

    if not identifier and not (start_dt and end_dt):
        return (
            jsonify(
                {
                    "error": "Provide an alert identifier or both start and end timestamps.",
                }
            ),
            400,
        )

    now_utc = utc_now()
    if end_dt and end_dt > now_utc:
        logger.info(
            "Clamping manual NOAA import end time %s to current UTC %s",
            end_dt.isoformat(),
            now_utc.isoformat(),
        )
        end_dt = now_utc

    if start_dt and end_dt and start_dt > end_dt:
        return jsonify({"error": "The start time must be before the end time."}), 400

    cleaned_area = "".join(ch for ch in area.upper() if ch.isalpha()) if area else ""
    normalized_area = cleaned_area[:2] if cleaned_area else None

    if identifier:
        if area and (not normalized_area or len(normalized_area) != 2):
            return (
                jsonify({"error": "State filters must use the two-letter postal abbreviation."}),
                400,
            )
    else:
        if not normalized_area or len(normalized_area) != 2:
            return (
                jsonify(
                    {
                        "error": "Provide the two-letter state code when searching without an identifier.",
                    }
                ),
                400,
            )

    try:
        alerts_payloads, query_url, params = retrieve_noaa_alerts(
            identifier=identifier or None,
            start=start_dt,
            end=end_dt,
            area=normalized_area,
            event=event_filter or None,
            limit=limit_value,
        )
    except NOAAImportError as exc:
        status_code = exc.status_code or 502
        response_payload: Dict[str, Any] = {
            "error": str(exc),
            "status_code": exc.status_code,
            "query_url": exc.query_url,
            "params": exc.params,
        }
        if exc.detail:
            response_payload["detail"] = exc.detail
        if status_code == 404 and identifier:
            response_payload["identifier"] = identifier
        return jsonify(response_payload), status_code

    start_iso = format_noaa_timestamp(start_dt)
    end_iso = format_noaa_timestamp(end_dt)

    inserted = 0
    updated = 0
    skipped = 0
    identifiers: List[str] = []

    try:
        for feature in alerts_payloads:
            parsed_result = parse_noaa_cap_alert(feature)
            if not parsed_result:
                skipped += 1
                continue

            parsed, geometry = parsed_result
            alert_identifier = parsed["identifier"]
            if alert_identifier not in identifiers:
                identifiers.append(alert_identifier)

            existing = CAPAlert.query.filter_by(identifier=alert_identifier).first()

            if existing:
                for key, value in parsed.items():
                    setattr(existing, key, value)
                existing.updated_at = utc_now()
                assign_alert_geometry(existing, geometry)
                db.session.flush()
                try:
                    if existing.geom:
                        calculate_alert_intersections(existing)
                except Exception as intersection_error:
                    logger.warning(
                        "Intersection recalculation failed for alert %s: %s",
                        alert_identifier,
                        intersection_error,
                    )
                updated += 1
            else:
                new_alert = CAPAlert(**parsed)
                new_alert.created_at = utc_now()
                new_alert.updated_at = utc_now()
                assign_alert_geometry(new_alert, geometry)
                db.session.add(new_alert)
                db.session.flush()
                try:
                    if new_alert.geom:
                        calculate_alert_intersections(new_alert)
                except Exception as intersection_error:
                    logger.warning(
                        "Intersection calculation failed for new alert %s: %s",
                        alert_identifier,
                        intersection_error,
                    )
                inserted += 1

        log_entry = SystemLog(
            level="INFO",
            message="Manual NOAA alert import executed",
            module="admin",
            details={
                "identifiers": identifiers,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "query_url": query_url,
                "params": params,
                "requested_filters": {
                    "identifier": identifier or None,
                    "start": start_iso,
                    "end": end_iso,
                    "area": normalized_area,
                    "event": event_filter or None,
                    "limit": limit_value,
                },
                "requested_at_utc": utc_now().isoformat(),
                "requested_at_local": local_now().isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        logger.error("Manual NOAA alert import failed: %s", exc)
        return jsonify({"error": f"Failed to import NOAA alert data: {exc}"}), 500

    return jsonify(
        {
            "message": f"Imported {inserted} alert(s) and updated {updated} existing alert(s).",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "identifiers": identifiers,
            "query_url": query_url,
            "params": params,
        }
    )

@maintenance_bp.route("/admin/alerts", methods=["GET"])
def admin_list_alerts():
    try:
        include_expired = request.args.get("include_expired", "false").lower() == "true"
        search_term = (request.args.get("search") or "").strip()
        limit_param = request.args.get("limit", type=int)
        limit = 100 if not limit_param else max(1, min(limit_param, 200))

        base_query = CAPAlert.query

        if not include_expired:
            now = utc_now()
            base_query = base_query.filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
            )

        if search_term:
            like_pattern = f"%{search_term}%"
            base_query = base_query.filter(
                or_(
                    CAPAlert.identifier.ilike(like_pattern),
                    CAPAlert.event.ilike(like_pattern),
                    CAPAlert.headline.ilike(like_pattern),
                )
            )

        total_count = base_query.order_by(None).count()
        alerts = (
            base_query.order_by(desc(CAPAlert.sent)).limit(limit).all()
        )

        serialized_alerts = [serialize_admin_alert(alert) for alert in alerts]

        return jsonify(
            {
                "alerts": serialized_alerts,
                "returned": len(serialized_alerts),
                "total": total_count,
                "include_expired": include_expired,
                "limit": limit,
                "search": search_term or None,
            }
        )
    except Exception as exc:
        logger.error("Failed to load alerts for admin listing: %s", exc)
        return jsonify({"error": "Failed to load alerts."}), 500

@maintenance_bp.route("/admin/alerts/<int:alert_id>", methods=["GET", "PATCH", "DELETE"])
def admin_alert_detail(alert_id: int):
    alert = CAPAlert.query.get(alert_id)
    if not alert:
        return jsonify({"error": "Alert not found."}), 404

    if request.method == "GET":
        return jsonify({"alert": serialize_admin_alert(alert)})

    if request.method == "DELETE":
        identifier = alert.identifier
        try:
            Intersection.query.filter_by(cap_alert_id=alert.id).delete(
                synchronize_session=False
            )

            try:
                if ensure_led_tables():
                    LEDMessage.query.filter_by(alert_id=alert.id).delete(
                        synchronize_session=False
                    )
            except Exception as led_cleanup_error:
                logger.warning(
                    "Failed to clean LED messages for alert %s during deletion: %s",
                    identifier,
                    led_cleanup_error,
                )
                db.session.rollback()
                return (
                    jsonify(
                        {
                            "error": "Failed to remove LED sign entries linked to this alert.",
                        }
                    ),
                    500,
                )

            db.session.delete(alert)

            log_entry = SystemLog(
                level="WARNING",
                message="Alert deleted from admin interface",
                module="admin",
                details={
                    "alert_id": alert_id,
                    "identifier": identifier,
                    "deleted_at_utc": utc_now().isoformat(),
                },
            )
            db.session.add(log_entry)
            db.session.commit()

            logger.info("Admin deleted alert %s (%s)", identifier, alert_id)
            return jsonify(
                {"message": f"Alert {identifier} deleted.", "identifier": identifier}
            )
        except Exception as exc:
            db.session.rollback()
            logger.error(
                "Failed to delete alert %s (%s): %s", identifier, alert_id, exc
            )
            return jsonify({"error": "Failed to delete alert."}), 500

    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({"error": "No update payload provided."}), 400

    allowed_fields = {
        "event",
        "headline",
        "description",
        "instruction",
        "area_desc",
        "status",
        "severity",
        "urgency",
        "certainty",
        "category",
        "expires",
    }
    required_non_empty = {"event", "status"}

    updates: Dict[str, Any] = {}
    change_details: Dict[str, Dict[str, Optional[str]]] = {}

    for field in allowed_fields:
        if field not in payload:
            continue

        value = payload[field]

        if field == "expires":
            if value in (None, "", []):
                updates[field] = None
            else:
                normalized = normalize_manual_import_datetime(value)
                if not normalized:
                    return jsonify(
                        {"error": "Could not parse the provided expiration time."}
                    ), 400
                updates[field] = normalized
        else:
            if isinstance(value, str):
                value = value.strip()
            if field in required_non_empty and not value:
                return (
                    jsonify(
                        {
                            "error": f"{field.replace('_', ' ').title()} is required.",
                        }
                    ),
                    400,
                )
            updates[field] = value or None

        previous_value = getattr(alert, field)
        if isinstance(previous_value, datetime):
            previous_rendered = _alert_datetime_to_iso(previous_value)
        else:
            previous_rendered = previous_value

        new_value = updates[field]
        if isinstance(new_value, datetime):
            new_rendered: Optional[str] = new_value.isoformat()
        else:
            new_rendered = new_value

        change_details[field] = {
            "old": previous_rendered,
            "new": new_rendered,
        }

    if not updates:
        return jsonify(
            {"message": "No changes detected.", "alert": serialize_admin_alert(alert)}
        )

    try:
        for field, value in updates.items():
            setattr(alert, field, value)

        alert.updated_at = utc_now()

        log_entry = SystemLog(
            level="INFO",
            message="Alert updated from admin interface",
            module="admin",
            details={
                "alert_id": alert.id,
                "identifier": alert.identifier,
                "changes": change_details,
                "updated_at_utc": alert.updated_at.isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        logger.info(
            "Admin updated alert %s fields: %s",
            alert.identifier,
            ", ".join(sorted(updates.keys())),
        )

        db.session.refresh(alert)
        return jsonify(
            {
                "message": "Alert updated successfully.",
                "alert": serialize_admin_alert(alert),
            }
        )
    except Exception as exc:
        db.session.rollback()
        logger.error(
            "Failed to update alert %s (%s): %s", alert.identifier, alert.id, exc
        )
        return jsonify({"error": "Failed to update alert."}), 500

@maintenance_bp.route("/admin/mark_expired", methods=["POST"])
def mark_expired():
    try:
        now = utc_now()

        expired_alerts = CAPAlert.query.filter(
            CAPAlert.expires < now, CAPAlert.status != "Expired"
        ).all()

        count = len(expired_alerts)

        if count == 0:
            return jsonify({"message": "No alerts need to be marked as expired"})

        for alert in expired_alerts:
            alert.status = "Expired"
            alert.updated_at = now

        db.session.commit()

        log_entry = SystemLog(
            level="INFO",
            message=f"Marked {count} alerts as expired (data preserved)",
            module="admin",
            details={
                "marked_at_utc": now.isoformat(),
                "marked_at_local": local_now().isoformat(),
                "count": count,
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify(
            {
                "message": f"Marked {count} alerts as expired",
                "note": "Alert data has been preserved in the database",
                "marked_count": count,
            }
        )

    except Exception as exc:
        db.session.rollback()
        logger.error("Error marking expired alerts: %s", exc)
        return jsonify({"error": str(exc)}), 500


__all__ = [
"NOAAImportError",
"NOAA_API_BASE_URL",
"NOAA_ALLOWED_QUERY_PARAMS",
"NOAA_USER_AGENT",
"build_noaa_alert_request",
"format_noaa_timestamp",
"normalize_manual_import_datetime",
"register_maintenance_routes",
"retrieve_noaa_alerts",
"serialize_admin_alert",
]
