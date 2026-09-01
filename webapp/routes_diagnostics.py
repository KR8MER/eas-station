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

"""
System Diagnostics Routes

Provides web-based system validation. Each check exercises the actual
subsystem (Redis ping, Icecast stats fetch, audio-service heartbeat, NTP
sync, etc.) rather than printing static "looks fine" output. Failures
include the underlying error message so an operator can act on the result.
"""

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template

from app_core.config.services import get_eas_services
from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)


CheckResult = Dict[str, List[str]]


def _empty_result() -> CheckResult:
    return {"passed": [], "warnings": [], "failed": [], "info": []}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_command(cmd: List[str], timeout: int = 15) -> Tuple[int, str, str]:
    """Run a command and return ``(exit_code, stdout, stderr)``."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except Exception as exc:
        return -1, "", str(exc)


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #

def _systemd_unavailable_reason() -> Optional[str]:
    """Return why systemd cannot be queried here, or ``None`` if it can.

    Checking that the ``systemctl`` binary exists is not enough — it is
    present in plenty of environments where the bus is not, and there it
    exits non-zero on every query with an empty stdout. ``is-system-running``
    is the probe that actually touches the bus: it reports ``offline`` when
    systemd is not PID 1, while a healthy host answers ``running`` (and a host
    with a failed unit answers ``degraded``, which is still queryable — so the
    exit code alone cannot be the signal).
    """
    code, stdout, stderr = _run_command(["systemctl", "is-system-running"])
    if code == 127:
        return "`systemctl` is not installed"

    state = stdout.strip().lower()
    if state in {"offline", "unknown"}:
        return f"systemd reports '{state}' (not running as init here)"

    combined = f"{stderr} {stdout}".lower()
    for marker in ("not been booted with systemd", "failed to connect to bus"):
        if marker in combined:
            return stderr.strip().splitlines()[0] if stderr.strip() else marker

    return None


def check_services_running() -> CheckResult:
    """Verify each EAS Station systemd unit is active."""
    out = _empty_result()

    # Establish that systemd is actually reachable before drawing conclusions
    # from it. Every `is-active` probe below returns an empty state when the
    # bus is down, which reads as "unknown" — and the per-unit branch reported
    # that as a hard failure. On any host where systemd cannot be queried (a
    # container, or a sandboxed web user without bus access) the check failed
    # every unit regardless of whether the services were running. That is
    # worse than no check: it buries real failures in a wall of false ones.
    unavailable = _systemd_unavailable_reason()
    if unavailable:
        out["info"].append(f"Cannot verify service state: {unavailable}")
        return out

    code, stdout, _ = _run_command(["systemctl", "is-active", "eas-station.target"])
    target_state = stdout.strip() or "unknown"
    if code == 0 and target_state == "active":
        out["passed"].append("eas-station.target is active")
    else:
        # The target is optional in some installs; warn rather than fail so
        # we still inspect each unit individually below.
        out["warnings"].append(
            f"eas-station.target state is '{target_state}' (proceeding with per-unit checks)"
        )

    services = get_eas_services()
    if not services:
        out["warnings"].append("No EAS Station services configured to check")
        return out

    for unit in services:
        code, stdout, stderr = _run_command(["systemctl", "is-active", unit])
        state = stdout.strip() or "unknown"
        if code == 0 and state == "active":
            out["passed"].append(f"{unit} is active")
            continue

        # Distinguish "missing unit" from "failed unit".
        sub_code, sub_stdout, _ = _run_command(
            ["systemctl", "show", "-p", "LoadState", "--value", unit]
        )
        load_state = sub_stdout.strip()
        if sub_code == 0 and load_state in {"not-found", "masked"}:
            out["warnings"].append(f"{unit} is not installed ({load_state})")
        else:
            out["failed"].append(f"{unit} is not active (state: {state})")
            out["info"].append(f"Inspect with: systemctl status {unit}")

    return out


def check_database_connection() -> CheckResult:
    """Confirm we can connect to the database and execute a trivial query."""
    out = _empty_result()
    try:
        from sqlalchemy import text

        from app_core.extensions import db
        from flask import current_app

        with current_app.app_context():
            t0 = time.perf_counter()
            with db.engine.connect() as conn:
                value = conn.execute(text("SELECT 1")).scalar()
            elapsed_ms = (time.perf_counter() - t0) * 1000

            if value == 1:
                out["passed"].append(
                    f"Database SELECT 1 succeeded ({elapsed_ms:.1f} ms)"
                )
            else:
                out["failed"].append(f"Database SELECT 1 returned unexpected value: {value!r}")
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        out["failed"].append(f"Database connection failed: {exc}")
    return out


# Placeholders/defaults that are clearly unsuitable for production. We compare
# against exact values (case-insensitively) rather than substrings so that a
# legitimately strong key containing letters like "secret" doesn't false-flag.
_BAD_SECRET_KEYS = frozenset(
    s.lower() for s in (
        "",
        "change-me",
        "changeme",
        "change_me",
        "dev-secret-key",
        "development",
        "example",
        "example-secret-key",
        "insecure",
        "please-change-me",
        "secret",
        "secret-key",
        "your-secret-key-here",
    )
)
_BAD_DB_PASSWORDS = frozenset(
    s.lower() for s in (
        "",
        "changeme",
        "change-me",
        "password",
        "postgres",
        "admin",
        "root",
    )
)


def _resolve_env_file() -> Optional[Path]:
    """Locate the .env file used by the running app, if any."""
    candidate = os.environ.get("CONFIG_PATH")
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
    for path in (_project_root() / ".env", Path.cwd() / ".env"):
        if path.is_file():
            return path
    return None


def check_environment_config() -> CheckResult:
    """Validate critical environment variables and the .env file."""
    out = _empty_result()

    env_file = _resolve_env_file()
    if env_file is None:
        out["warnings"].append(
            "No .env file found via CONFIG_PATH, project root, or working directory"
        )
    else:
        out["passed"].append(f".env file located at {env_file}")

    # DATABASE_URL, not POSTGRES_PASSWORD: app.py reads DATABASE_URL directly
    # and raises at startup if it's missing -- there's no discrete
    # POSTGRES_HOST/PORT/DB/USER/PASSWORD fallback in the running app.
    # install.sh and .env.example both only ever set DATABASE_URL, so
    # checking POSTGRES_PASSWORD here always reported "not set" on every
    # current-style install, a permanent false-positive warning.
    critical_vars = ["SECRET_KEY", "DATABASE_URL", "DEFAULT_STATE_CODE", "DEFAULT_COUNTY_NAME"]
    for var in critical_vars:
        value = os.getenv(var, "")
        if not value:
            out["warnings"].append(f"{var} is not set")
            continue

        if var == "SECRET_KEY":
            if value.lower() in _BAD_SECRET_KEYS:
                out["warnings"].append(f"SECRET_KEY uses a known placeholder value")
            elif len(value) < 16:
                out["warnings"].append(
                    f"SECRET_KEY is only {len(value)} chars; recommend ≥32"
                )
            else:
                out["passed"].append("SECRET_KEY is configured (≥16 chars, not a placeholder)")
        elif var == "DATABASE_URL":
            db_password = (urlparse(value).password or "").lower()
            if db_password in _BAD_DB_PASSWORDS:
                out["warnings"].append("DATABASE_URL uses a known weak/default database password")
            else:
                out["passed"].append("DATABASE_URL is configured (not a default password)")
        else:
            out["passed"].append(f"{var} is configured")

    return out


def check_audio_devices() -> CheckResult:
    """Look for ALSA playback devices when audio output is enabled."""
    out = _empty_result()
    if os.getenv("AUDIO_OUTPUT_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        out["info"].append("Audio output is disabled in configuration; skipping ALSA check")
        return out

    code, stdout, stderr = _run_command(["aplay", "-l"])
    if code == 127:
        out["warnings"].append("`aplay` not found — install alsa-utils to enable this check")
        return out
    if code != 0:
        out["warnings"].append(f"`aplay -l` failed: {stderr.strip() or 'no output'}")
        return out

    cards = re.findall(r"^card (\d+):\s*(\S+)", stdout, flags=re.MULTILINE)
    if not cards:
        out["failed"].append("No ALSA playback devices detected")
        out["info"].append("Verify hardware is connected and the alsa kernel module is loaded")
        return out

    out["passed"].append(f"Found {len(cards)} ALSA playback device(s)")
    for card_num, card_id in cards:
        out["info"].append(f"card {card_num}: {card_id}")
    return out


def check_redis() -> CheckResult:
    """Ping Redis and report version + latency."""
    out = _empty_result()
    try:
        import redis  # noqa: F401  (only to surface ImportError clearly)
        from app_core.redis_client import get_redis_client

        client = get_redis_client(max_retries=1, initial_backoff=0.5)
        if client is None:
            out["failed"].append("Redis client could not be constructed (see logs)")
            return out

        t0 = time.perf_counter()
        client.ping()
        latency_ms = (time.perf_counter() - t0) * 1000

        info = client.info(section="server") or {}
        version = info.get("redis_version") or "unknown"
        out["passed"].append(
            f"Redis PING ok in {latency_ms:.1f} ms (v{version})"
        )
    except ImportError as exc:
        out["failed"].append(f"redis package not importable: {exc}")
    except Exception as exc:
        logger.error("Redis check failed: %s", exc)
        out["failed"].append(f"Redis ping failed: {exc}")
        out["info"].append("Check that redis-server is running and credentials match")
    return out


def check_icecast() -> CheckResult:
    """Use the existing system_health helper to check Icecast."""
    out = _empty_result()
    try:
        from app_core.system_health import collect_icecast_status

        status = collect_icecast_status(logger) or {}
    except Exception as exc:
        out["failed"].append(f"Could not check Icecast: {exc}")
        return out

    state = status.get("status") or "unknown"
    server = status.get("server")
    port = status.get("port")
    location = f"{server}:{port}" if server and port else server or "configured server"

    if not status.get("enabled"):
        out["info"].append("Icecast streaming is disabled — skipping reachability check")
        return out

    if state == "ok":
        out["passed"].append(
            f"Icecast at {location} is reachable "
            f"(listeners={status.get('listeners', 0)}, sources={status.get('sources', 0)})"
        )
    elif state == "degraded":
        issues = ", ".join(status.get("issues") or []) or "see logs"
        out["warnings"].append(f"Icecast at {location} is reachable but degraded: {issues}")
    else:
        err = status.get("error") or ", ".join(status.get("issues") or []) or "not reachable"
        out["failed"].append(f"Icecast at {location} is unhealthy: {err}")
    return out


def check_audio_service_heartbeat() -> CheckResult:
    """Verify the audio-service process is publishing fresh metrics to Redis."""
    out = _empty_result()
    if os.getenv("AUDIO_OUTPUT_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        out["info"].append("AUDIO_OUTPUT_ENABLED=false — skipping audio-service heartbeat check")
        return out

    try:
        from app_core.audio.worker_coordinator_redis import read_shared_metrics

        metrics = read_shared_metrics()
    except Exception as exc:
        out["warnings"].append(f"Could not read audio metrics from Redis: {exc}")
        return out

    if not metrics:
        out["failed"].append("audio-service is not publishing metrics to Redis")
        out["info"].append("Check: systemctl status eas-station-audio")
        return out

    heartbeat = float(metrics.get("_heartbeat") or 0)
    if heartbeat <= 0:
        out["failed"].append("audio-service metrics present but no heartbeat recorded")
        return out

    age = time.time() - heartbeat
    if age <= 15:
        out["passed"].append(f"audio-service heartbeat is {age:.1f}s old (fresh)")
    elif age <= 60:
        out["warnings"].append(f"audio-service heartbeat is {age:.1f}s old (stale)")
    else:
        out["failed"].append(f"audio-service heartbeat is {age:.1f}s old (very stale)")
    return out


def check_ntp_sync() -> CheckResult:
    """Check that the system clock is NTP-synchronised."""
    out = _empty_result()
    code, stdout, stderr = _run_command(
        ["timedatectl", "show", "-p", "NTP", "-p", "NTPSynchronized", "--value"]
    )
    if code == 127:
        out["info"].append("`timedatectl` not available — skipping NTP check")
        return out
    if code != 0:
        out["warnings"].append(f"`timedatectl` failed: {stderr.strip() or 'no output'}")
        return out

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    # Output: first line = NTP enabled, second = NTPSynchronized
    ntp_enabled = lines[0].lower() == "yes" if len(lines) >= 1 else False
    ntp_synced = lines[1].lower() == "yes" if len(lines) >= 2 else False

    if ntp_synced:
        out["passed"].append("System clock is NTP-synchronised")
    elif ntp_enabled:
        out["warnings"].append("NTP is enabled but the clock has not yet synchronised")
    else:
        out["warnings"].append("NTP synchronisation is disabled on this host")
        out["info"].append("Enable with: sudo timedatectl set-ntp true")
    return out


_LOG_ERROR_PATTERN = re.compile(
    r"\b(ERROR|CRITICAL|Traceback|Exception)\b", flags=re.IGNORECASE
)


def check_recent_logs() -> CheckResult:
    """Pull recent web-service logs and surface actual error lines, not just counts."""
    out = _empty_result()
    try:
        from app_core.config.services import get_web_service

        unit = get_web_service()
    except Exception as exc:
        out["warnings"].append(f"Could not determine web service name: {exc}")
        return out

    code, stdout, stderr = _run_command(
        ["journalctl", "-u", unit, "-n", "200", "--no-pager", "-o", "short-iso"],
        timeout=20,
    )
    if code == 127:
        out["info"].append("`journalctl` not available — skipping log scan")
        return out
    if code != 0:
        out["warnings"].append(f"Could not retrieve logs for {unit}: {stderr.strip() or 'no output'}")
        return out

    matches = [line for line in stdout.splitlines() if _LOG_ERROR_PATTERN.search(line)]
    if not matches:
        out["passed"].append(f"No ERROR/CRITICAL/Exception lines in last 200 entries for {unit}")
        return out

    out["warnings"].append(
        f"Found {len(matches)} error line(s) in last 200 entries for {unit}; showing newest 5"
    )
    for line in matches[-5:]:
        if len(line) > 240:
            line = line[:237] + "..."
        out["info"].append(line)
    out["info"].append(f"Full log: journalctl -u {unit} -n 200")
    return out


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

CHECKS: List[Tuple[str, Callable[[], CheckResult]]] = [
    ("Services", check_services_running),
    ("Database", check_database_connection),
    ("Environment", check_environment_config),
    ("Redis", check_redis),
    ("Icecast", check_icecast),
    ("Audio Service", check_audio_service_heartbeat),
    ("Audio Devices", check_audio_devices),
    ("NTP Sync", check_ntp_sync),
    ("Recent Logs", check_recent_logs),
]


def register(app: Flask, route_logger: logging.Logger) -> None:
    """Register diagnostics routes."""

    @app.route("/diagnostics")
    def diagnostics_page() -> Any:
        return render_template(
            "diagnostics.html",
            check_names=[name for name, _ in CHECKS],
        )

    @app.route("/api/diagnostics/validate", methods=["POST"])
    @require_permission('system.configure')
    def validate_installation() -> Tuple[Any, int]:
        """Run the full installation-health check suite and return the results.

        Runs each check in CHECKS in turn (Services, Database, Environment,
        Redis, Icecast, Audio Service, Audio Devices, NTP Sync, Recent
        Logs) -- the same suite the Diagnostics page's "Run Validation"
        button triggers. A check that raises is caught and reported as a
        failure for that check rather than failing the whole request.

        Returns:
            200 with {success, checks: [{name, elapsed_ms, passed, warnings,
            failed, info}, ...], passed: [...], warnings: [...],
            failed: [...], info: [...]} -- the per-check summary counts plus
            every individual finding message, pooled across all checks.
        """
        all_results = _empty_result()
        per_check: List[Dict[str, Any]] = []

        for name, fn in CHECKS:
            t0 = time.perf_counter()
            try:
                result = fn()
            except Exception as exc:
                route_logger.error("Diagnostic check '%s' raised: %s", name, exc, exc_info=True)
                result = {
                    "passed": [],
                    "warnings": [],
                    "failed": [f"{name} check crashed: {exc}"],
                    "info": [],
                }
            elapsed_ms = (time.perf_counter() - t0) * 1000

            for bucket in ("passed", "warnings", "failed", "info"):
                all_results[bucket].extend(result.get(bucket, []))

            per_check.append({
                "name": name,
                "elapsed_ms": round(elapsed_ms, 1),
                "passed": len(result.get("passed", [])),
                "warnings": len(result.get("warnings", [])),
                "failed": len(result.get("failed", [])),
                "info": len(result.get("info", [])),
            })

        return jsonify({
            "success": True,
            "checks": per_check,
            **all_results,
        }), 200


__all__ = ["register"]
