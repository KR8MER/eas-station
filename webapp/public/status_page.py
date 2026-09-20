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

"""Public transparency/status page.

Unlike /system_health (login-required -- it exposes hostname, network
interfaces, disk serials, etc. via LOCAL_API_GET_PATHS/system_health.py's
own docstring), this page is meant to be readable by anyone: a lab
operator's supervisor, a training-program auditor, or a curious visitor
checking "is this thing actually working" without an account.

That means every field collected here has been deliberately chosen to be
non-sensitive: which EAS subsystems are up (already documented by name in
the public README/CLAUDE.md), when the tamper-evident audit chain was last
verified, whether the weekly/monthly compliance tests are current, and a
running alert count. No hostname, IP, disk, receiver or process detail is
read or returned -- see PUBLIC_API_GET_PATHS's docstring in app.py for the
line this page is careful to stay on the right side of.
"""

import threading
import time as _time
from datetime import timedelta
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template

from app_core.extensions import db
from app_core.system_health import get_system_health
from app_utils import utc_now

# FCC Part 11 calls for a weekly RWT and a monthly RMT. A little slack is
# given past the nominal 7/30-day cadence before flagging "overdue" so a
# test that lands a day late (schedule skipped, manual catch-up) doesn't
# flash red the moment the calendar ticks over.
_RWT_GRACE_DAYS = 9
_RMT_GRACE_DAYS = 35

# Cheap DB lookups still cost a round trip; a public, unauthenticated route
# is the one page on this site anyone on the internet can hit as fast as
# they like, so this mirrors the TTL-cache pattern system_health.py already
# uses rather than hitting the database on every request.
_CACHE_TTL_SECONDS = 30.0
_cache_lock = threading.Lock()
_cache_data: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0


def _last_same_message_at(event_code: str):
    """Timestamp of the newest EASMessage whose SAME header carries *event_code*."""
    from app_core.models import EASMessage

    row = (
        db.session.query(EASMessage.created_at)
        .filter(EASMessage.same_header.like(f"%-{event_code}-%"))
        .order_by(EASMessage.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _cadence_status(last_at, grace_days: int) -> str:
    if last_at is None:
        return "unknown"
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=utc_now().tzinfo)
    return "current" if (utc_now() - last_at) <= timedelta(days=grace_days) else "overdue"


def _audit_chain_summary() -> Dict[str, Any]:
    from app_core.auth.audit import AuditAction, AuditLog

    row = (
        db.session.query(AuditLog.timestamp, AuditLog.success)
        .filter(AuditLog.action == AuditAction.AUDIT_CHAIN_VERIFIED.value)
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    if row is None:
        return {"last_verified_at": None, "ok": None}
    verified_at, ok = row
    return {
        "last_verified_at": verified_at.isoformat() if verified_at else None,
        "ok": bool(ok),
    }


def _eas_services_summary(logger) -> Dict[str, Any]:
    """Up/down state for the core EAS subsystems only.

    Filters the (login-gated) full snapshot's systemd list down to
    ``is_eas_service`` entries -- dropping nginx/postgres/redis/icecast and
    every host-identifying field the snapshot also carries.
    """
    health = get_system_health(logger=logger)
    systemd = health.get("systemd") or {}
    services = [
        {
            "name": svc.get("display_name") or svc.get("name"),
            "up": bool(svc.get("is_running")),
        }
        for svc in systemd.get("services", [])
        if svc.get("is_eas_service")
    ]
    return {
        "services": services,
        "overall_status": health.get("status", "unknown"),
        "status_summary": health.get("status_summary", "Status unavailable"),
        "uptime_human": (health.get("system") or {}).get("uptime_human"),
    }


def _collect_public_status(logger) -> Dict[str, Any]:
    from app_core.models import CAPAlert

    alerts_monitored = db.session.query(db.func.count(CAPAlert.id)).scalar() or 0

    last_rwt = _last_same_message_at("RWT")
    last_rmt = _last_same_message_at("RMT")

    return {
        "generated_at": utc_now().isoformat(),
        "services": _eas_services_summary(logger),
        "audit_chain": _audit_chain_summary(),
        "compliance": {
            "last_rwt_at": last_rwt.isoformat() if last_rwt else None,
            "rwt_status": _cadence_status(last_rwt, _RWT_GRACE_DAYS),
            "last_rmt_at": last_rmt.isoformat() if last_rmt else None,
            "rmt_status": _cadence_status(last_rmt, _RMT_GRACE_DAYS),
        },
        "alerts_monitored": int(alerts_monitored),
    }


def _cached_public_status(logger) -> Dict[str, Any]:
    global _cache_data, _cache_at

    now = _time.time()
    if _cache_data is not None and (now - _cache_at) < _CACHE_TTL_SECONDS:
        return _cache_data

    with _cache_lock:
        if _cache_data is not None and (now - _cache_at) < _CACHE_TTL_SECONDS:
            return _cache_data
        try:
            data = _collect_public_status(logger)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to collect public status data: %s", exc)
            data = {
                "generated_at": utc_now().isoformat(),
                "error": "Status data is temporarily unavailable.",
            }
        _cache_data = data
        _cache_at = now
        return data


def register(app: Flask, route_logger) -> None:
    """Attach the public status/transparency page to the Flask app."""

    @app.route("/status")
    def public_status_page():
        return render_template("status.html", status=_cached_public_status(route_logger))

    @app.route("/api/public/status")
    def public_status_api():
        return jsonify(_cached_public_status(route_logger))


__all__ = ["register"]
