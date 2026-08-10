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

"""Tracking the long-running admin operations (backup, upgrade).

``_OPERATION_STATE`` is a module-level dict guarded by ``_OPERATION_LOCK`` and
mutated from the background threads ``_start_background_operation`` spawns. It
is only ever mutated *in place*, never rebound, so importing it by value is
safe — but it still lives here, with the lock and the only functions that
touch it.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, List, Optional

from app_utils import UTC_TZ, utc_now


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
