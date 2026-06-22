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

"""System health snapshot helpers shared across route modules."""

import os
import re
import requests
import threading
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from flask import current_app
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import EASMessage, ManualEASActivation, RadioReceiver, RadioReceiverStatus
from app_utils import build_system_health_snapshot, utc_now
from app_utils.time import UTC_TZ

try:  # pragma: no cover - optional dependency
    from pysnmp.hlapi import (  # type: ignore[import]
        CommunityData,
        ContextData,
        NotificationType,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        sendNotification,
    )
except Exception:  # pragma: no cover - pysnmp is optional
    CommunityData = ContextData = NotificationType = ObjectIdentity = ObjectType = None
    SnmpEngine = UdpTransportTarget = sendNotification = None

_HEALTH_WORKER = None
_HEALTH_WORKER_LOCK = threading.Lock()

# In-process TTL cache for build_system_health_snapshot.  The snapshot scans
# every process and every disk partition, so running it on every WebSocket
# push (and again on every /api/system_health request) put far more load on
# the box than the underlying data ever changes.  A short TTL collapses all
# concurrent callers onto a single computation while still feeling live.
_HEALTH_SNAPSHOT_TTL_SECONDS = 30.0
_HEALTH_SNAPSHOT_LOCK = threading.Lock()
_HEALTH_SNAPSHOT_CACHE: Optional[Dict[str, Any]] = None
_HEALTH_SNAPSHOT_TIMESTAMP: float = 0.0


def get_system_health(logger=None, force_refresh: bool = False) -> Dict[str, Any]:
    """Return a structured health snapshot for the running application.

    Cached for ``_HEALTH_SNAPSHOT_TTL_SECONDS`` to avoid the multi-hundred-ms
    psutil scan running back-to-back from the WebSocket push thread and the
    HTTP API.  Pass ``force_refresh=True`` to bypass the cache (used by the
    HealthAlertWorker once per ``COMPLIANCE_HEALTH_INTERVAL``).
    """

    import time as _time

    global _HEALTH_SNAPSHOT_CACHE, _HEALTH_SNAPSHOT_TIMESTAMP

    effective_logger = logger or _resolve_logger()

    if not force_refresh:
        cached = _HEALTH_SNAPSHOT_CACHE
        cached_at = _HEALTH_SNAPSHOT_TIMESTAMP
        if cached is not None and (_time.time() - cached_at) < _HEALTH_SNAPSHOT_TTL_SECONDS:
            return cached

    with _HEALTH_SNAPSHOT_LOCK:
        # Re-check under the lock so concurrent callers collapse to one build.
        if not force_refresh:
            cached = _HEALTH_SNAPSHOT_CACHE
            cached_at = _HEALTH_SNAPSHOT_TIMESTAMP
            if cached is not None and (_time.time() - cached_at) < _HEALTH_SNAPSHOT_TTL_SECONDS:
                return cached

        snapshot = build_system_health_snapshot(db, effective_logger)
        _HEALTH_SNAPSHOT_CACHE = snapshot
        _HEALTH_SNAPSHOT_TIMESTAMP = _time.time()
        return snapshot


def collect_receiver_health_snapshot(logger=None) -> Dict[str, Any]:
    """Summarise the state of configured radio receivers."""

    effective_logger = logger or _resolve_logger()

    try:
        threshold_minutes = int(current_app.config.get("RECEIVER_OFFLINE_THRESHOLD_MINUTES", 10))
    except (TypeError, ValueError):
        threshold_minutes = 10

    now = utc_now()
    summary: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    try:
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc()).all()

        # Batch-load latest status for all receivers in a single query to avoid N+1
        # Use a subquery to get the max reported_at per receiver
        latest_subquery = (
            db.session.query(
                RadioReceiverStatus.receiver_id,
                func.max(RadioReceiverStatus.reported_at).label('max_reported_at')
            )
            .group_by(RadioReceiverStatus.receiver_id)
            .subquery()
        )

        latest_statuses_query = (
            db.session.query(RadioReceiverStatus)
            .join(
                latest_subquery,
                db.and_(
                    RadioReceiverStatus.receiver_id == latest_subquery.c.receiver_id,
                    RadioReceiverStatus.reported_at == latest_subquery.c.max_reported_at
                )
            )
        )

        # Build a map of receiver_id -> latest status
        latest_status_map: Dict[int, RadioReceiverStatus] = {
            status.receiver_id: status for status in latest_statuses_query.all()
        }
    except Exception as exc:  # pragma: no cover - defensive logging
        effective_logger.error("Failed to load receiver statuses: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return {
            "items": [],
            "total": 0,
            "issues": 0,
            "issue_items": [],
            "threshold_minutes": threshold_minutes,
        }

    for receiver in receivers:
        latest = latest_status_map.get(receiver.id)
        status_issue = None
        status_age_minutes: Optional[float] = None

        if latest and latest.reported_at:
            reported_at = _ensure_aware(latest.reported_at)
            if reported_at:
                delta = now - reported_at
                status_age_minutes = max(delta.total_seconds() / 60.0, 0.0)
        else:
            status_issue = "No status samples received"

        if status_age_minutes is None or status_age_minutes > threshold_minutes:
            if status_issue is None:
                status_issue = (
                    f"Last update {(status_age_minutes or 0):.1f} minutes ago"
                    if status_age_minutes is not None
                    else "No recent status available"
                )

        if latest and latest.locked is False:
            status_issue = status_issue or "Receiver not locked"

        item = {
            "id": receiver.id,
            "identifier": receiver.identifier,
            "display_name": receiver.display_name,
            "driver": receiver.driver,
            "locked": bool(latest.locked) if latest else None,
            "signal_strength": latest.signal_strength if latest else None,
            "last_reported": latest.reported_at,
            "status_age_minutes": status_age_minutes,
            "issue": status_issue,
        }
        summary.append(item)
        if status_issue:
            issues.append(item)

    return {
        "items": summary,
        "total": len(summary),
        "issues": len(issues),
        "issue_items": issues,
        "threshold_minutes": threshold_minutes,
    }


def collect_audio_path_status(logger=None) -> Dict[str, Any]:
    """Summarise the health of configured audio output paths."""

    effective_logger = logger or _resolve_logger()
    app = current_app

    enabled = bool(app.config.get("ENABLE_AUDIO_ALERTS")) or bool(
        app.config.get("EAS_BROADCAST_ENABLED")
    )

    try:
        heartbeat_minutes = int(app.config.get("AUDIO_PATH_ALERT_THRESHOLD_MINUTES", 60))
    except (TypeError, ValueError):
        heartbeat_minutes = 60

    output_dir = (
        str(app.config.get("AUDIO_OUTPUT_DIR") or app.config.get("EAS_OUTPUT_DIR") or "").strip()
        or None
    )

    issues: List[str] = []
    last_activity: Optional[datetime] = None

    if enabled:
        if not output_dir:
            issues.append("Audio output directory is not configured")
        else:
            if not os.path.isdir(output_dir):
                issues.append(f"Audio output directory does not exist: {output_dir}")
            elif not os.access(output_dir, os.W_OK):
                issues.append(f"Audio output directory is not writable: {output_dir}")

        last_activity = _resolve_last_audio_activity(effective_logger)

        if heartbeat_minutes > 0:
            if last_activity is None:
                issues.append("No audio playout activity has been recorded yet")
            else:
                age_minutes = max((utc_now() - _ensure_aware(last_activity)).total_seconds() / 60.0, 0.0)
                if age_minutes > heartbeat_minutes:
                    issues.append(
                        f"Last audio playout {age_minutes:.1f} minutes ago (threshold {heartbeat_minutes}m)"
                    )

    status = "disabled"
    if enabled:
        status = "ok" if not issues else "degraded"

    return {
        "enabled": enabled,
        "status": status,
        "output_dir": output_dir,
        "heartbeat_minutes": heartbeat_minutes,
        "last_activity": last_activity,
        "issues": issues,
    }


def collect_icecast_status(logger=None) -> Dict[str, Any]:
    """Check the health and status of the Icecast streaming server.
    
    Returns:
        Dictionary with Icecast status information including:
        - enabled: Whether Icecast streaming is enabled
        - running: Whether the Icecast server is reachable
        - status: Overall status (disabled, ok, degraded, error)
        - server: Server hostname
        - port: Server port
        - listeners: Number of current listeners (if available)
        - sources: Number of active sources (if available)
        - issues: List of any issues detected
        - error: Error message if server is unreachable
    """
    effective_logger = logger or _resolve_logger()
    
    try:
        from app_core.icecast_settings import get_icecast_settings
        settings = get_icecast_settings()
    except Exception as exc:
        effective_logger.error(f"Failed to load Icecast settings: {exc}")
        return {
            "enabled": False,
            "running": False,
            "status": "error",
            "issues": ["Failed to load Icecast configuration"],
            "error": str(exc)
        }
    
    if not settings.enabled:
        return {
            "enabled": False,
            "running": False,
            "status": "disabled",
            "issues": [],
        }
    
    issues: List[str] = []
    server = settings.server or 'localhost'
    port = settings.port or 8000
    
    # SECURITY: Validate server hostname (defense in depth)
    # Allow only valid hostnames: alphanumeric, dots, hyphens (not at start/end)
    # This regex allows localhost, IP addresses, and proper domain names
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\.\-]*[a-zA-Z0-9])?$', server):
        effective_logger.error(f"Invalid Icecast server hostname: {server}")
        return {
            "enabled": True,
            "running": False,
            "status": "error",
            "server": server,
            "port": port,
            "issues": ["Invalid server hostname in configuration"],
            "error": "Invalid server hostname"
        }
    
    # Try to get stats from Icecast server
    stats_url = f"http://{server}:{port}/admin/stats.xml"
    
    try:
        # SECURITY: Disable redirects to prevent redirect-based SSRF
        # NOTE: verify=False for internal/localhost connections (Icecast typically on same host)
        # In production with external servers, this should be verify=True
        response = requests.get(
            stats_url,
            auth=(settings.admin_user, settings.admin_password) if settings.admin_user and settings.admin_password else None,
            timeout=3,
            allow_redirects=False,  # SSRF prevention
            verify=False  # Internal connection - external servers should use verify=True
        )
        
        if response.status_code == 200:
            # Parse stats from XML response
            content = response.text
            
            try:
                # SECURITY: Basic validation before regex parsing
                content_stripped = content.strip()
                if not (content_stripped.startswith('<?xml') or content_stripped.startswith('<icestats')):
                    effective_logger.warning(f"Icecast stats response doesn't look like valid XML")
                    issues.append("Received invalid response from Icecast server")
                    total_listeners = 0
                    total_sources = 0
                else:
                    # Use simple regex-based parsing
                    listeners_match = re.search(r'<listeners>(\d+)</listeners>', content)
                    total_listeners = int(listeners_match.group(1)) if listeners_match else 0
                    
                    sources_match = re.search(r'<sources>(\d+)</sources>', content)
                    total_sources = int(sources_match.group(1)) if sources_match else 0
                
                return {
                    "enabled": True,
                    "running": True,
                    "status": "ok" if not issues else "degraded",
                    "server": server,
                    "port": port,
                    "listeners": total_listeners,
                    "sources": total_sources,
                    "issues": issues,
                }
            except (ValueError, AttributeError) as parse_err:
                effective_logger.warning(f"Failed to parse Icecast stats: {parse_err}")
                issues.append("Unable to parse server statistics")
                return {
                    "enabled": True,
                    "running": True,
                    "status": "degraded",
                    "server": server,
                    "port": port,
                    "listeners": 0,
                    "sources": 0,
                    "issues": issues,
                }
        elif response.status_code == 401:
            issues.append("Authentication failed - check admin credentials")
            return {
                "enabled": True,
                "running": True,
                "status": "degraded",
                "server": server,
                "port": port,
                "issues": issues,
                "error": "Authentication failed"
            }
        else:
            issues.append(f"Server returned status code {response.status_code}")
            return {
                "enabled": True,
                "running": False,
                "status": "error",
                "server": server,
                "port": port,
                "issues": issues,
                "error": f"HTTP {response.status_code}"
            }
            
    except requests.exceptions.Timeout:
        issues.append("Connection timeout - server may be unreachable")
        return {
            "enabled": True,
            "running": False,
            "status": "error",
            "server": server,
            "port": port,
            "issues": issues,
            "error": "Connection timeout"
        }
    except requests.exceptions.ConnectionError as conn_err:
        issues.append(f"Cannot connect to server at {server}:{port}")
        return {
            "enabled": True,
            "running": False,
            "status": "error",
            "server": server,
            "port": port,
            "issues": issues,
            "error": f"Connection refused"
        }
    except Exception as req_exc:
        effective_logger.error(f"Error checking Icecast status: {req_exc}")
        issues.append(f"Error checking server: {str(req_exc)}")
        return {
            "enabled": True,
            "running": False,
            "status": "error",
            "server": server,
            "port": port,
            "issues": issues,
            "error": str(req_exc)
        }


def start_health_alert_worker(app, logger):
    """Start the background worker that emits compliance alerts."""

    global _HEALTH_WORKER

    with _HEALTH_WORKER_LOCK:
        if _HEALTH_WORKER is not None:
            if _HEALTH_WORKER.is_running:
                return _HEALTH_WORKER

        worker = HealthAlertWorker(app, logger.getChild("health_alerts"))
        if not worker.should_run:
            logger.getChild("health_alerts").debug(
                "Health alert worker disabled: no alert destinations configured"
            )
            _HEALTH_WORKER = worker
            return worker

        worker.start()
        _HEALTH_WORKER = worker
        return worker


def _resolve_logger():
    """Fallback to Flask's application logger when none is provided."""

    try:
        return current_app.logger  # type: ignore[return-value]
    except RuntimeError:
        from logging import getLogger

        return getLogger(__name__)


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(UTC_TZ)


def _resolve_last_audio_activity(logger) -> Optional[datetime]:
    """Return the most recent audio activity timestamp from automated or manual paths."""

    try:
        # Single round-trip: compute the max across both tables and both
        # ManualEASActivation columns at once.  Previously this issued three
        # separate SELECT MAX queries, which the HealthAlertWorker ran on
        # every iteration in addition to the WebSocket-push system-health
        # snapshot.  COALESCE the subqueries so an empty table doesn't make
        # GREATEST() collapse the whole expression to NULL.
        sentinel = datetime(1970, 1, 1, tzinfo=UTC_TZ)
        latest = db.session.query(
            func.greatest(
                func.coalesce(
                    db.session.query(func.max(EASMessage.created_at)).scalar_subquery(),
                    sentinel,
                ),
                func.coalesce(
                    db.session.query(func.max(ManualEASActivation.sent_at)).scalar_subquery(),
                    sentinel,
                ),
                func.coalesce(
                    db.session.query(func.max(ManualEASActivation.created_at)).scalar_subquery(),
                    sentinel,
                ),
            )
        ).scalar()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to inspect audio activity timestamps: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return None

    if latest is None:
        return None
    aware = _ensure_aware(latest)
    # Discard the epoch sentinel when every source table was empty.
    if aware is not None and aware <= datetime(1970, 1, 2, tzinfo=UTC_TZ):
        return None
    return aware


class HealthAlertWorker:
    """Background monitor that notifies operators about degraded health."""

    def __init__(self, app, logger) -> None:
        self._app = app
        self._logger = logger

        try:
            interval = int(app.config.get("COMPLIANCE_HEALTH_INTERVAL", 300))
        except (TypeError, ValueError):
            interval = 300

        self._interval = max(interval, 60)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_fingerprint: Optional[tuple] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def should_run(self) -> bool:
        try:
            with self._app.app_context():
                from app_core.models import NotificationSettings
                settings = NotificationSettings.query.first()
                if settings:
                    has_email = bool(
                        settings.email_enabled
                        and settings.smtp_host
                        and settings.compliance_alert_emails
                    )
                    has_snmp = bool(
                        settings.snmp_enabled
                        and settings.snmp_targets
                    )
                    if has_email or has_snmp:
                        return True
        except Exception:
            pass
        # Fall back to legacy env-var config
        recipients = list(self._app.config.get("COMPLIANCE_ALERT_EMAILS") or [])
        traps = list(self._app.config.get("COMPLIANCE_SNMP_TARGETS") or [])
        return bool(recipients or traps)

    def start(self) -> None:
        if self.is_running:
            return

        if not self.should_run:
            return

        self._thread = threading.Thread(target=self._run, name="HealthAlertWorker", daemon=True)
        self._thread.start()
        self._logger.info(
            "Started health alert worker with interval %ss", self._interval
        )

    def stop(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._app.app_context():
                    issues = self._collect_issues()
                    self._handle_issues(issues)
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.error("Health alert worker iteration failed: %s", exc)

            self._stop_event.wait(self._interval)

    def _collect_issues(self) -> List[str]:
        issues: List[str] = []

        receiver_snapshot = collect_receiver_health_snapshot(self._logger)
        for item in receiver_snapshot.get("items", []):
            issue = item.get("issue")
            if issue:
                issues.append(
                    f"Receiver {item.get('display_name') or item.get('identifier')}: {issue}"
                )

        audio_status = collect_audio_path_status(self._logger)
        for message in audio_status.get("issues", []):
            issues.append(f"Audio path: {message}")

        return issues

    def _handle_issues(self, issues: List[str]) -> None:
        if not issues:
            self._last_fingerprint = None
            return

        fingerprint = tuple(sorted(issues))
        if fingerprint == self._last_fingerprint:
            return

        self._last_fingerprint = fingerprint
        self._send_email_alert(issues)
        self._send_snmp_traps(issues)

    def _send_email_alert(self, issues: List[str]) -> None:
        # Prefer database-backed NotificationSettings; fall back to legacy env vars
        smtp_host = None
        smtp_port = 587
        smtp_security = "starttls"
        smtp_username = None
        smtp_password = None
        recipients: List[str] = []

        try:
            from app_core.models import NotificationSettings
            settings = NotificationSettings.query.first()
            if settings and settings.email_enabled and settings.smtp_host:
                smtp_host = settings.smtp_host
                smtp_port = settings.smtp_port or 587
                smtp_security = settings.smtp_security or "starttls"
                smtp_username = settings.smtp_username or None
                smtp_password = settings.smtp_password or None
                recipients = [
                    addr.strip()
                    for addr in (settings.compliance_alert_emails or [])
                    if addr and addr.strip()
                ]
        except Exception as exc:
            self._logger.warning("Could not load NotificationSettings from DB: %s", exc)

        # Legacy fallback: COMPLIANCE_ALERT_EMAILS + MAIL_* env vars
        if not recipients:
            recipients = [
                addr.strip()
                for addr in self._app.config.get("COMPLIANCE_ALERT_EMAILS", [])
                if addr and addr.strip()
            ]
        if not smtp_host:
            smtp_host = self._app.config.get("MAIL_SERVER")
            if smtp_host:
                smtp_port = int(self._app.config.get("MAIL_PORT", 587))
                smtp_security = "starttls" if self._app.config.get("MAIL_USE_TLS", True) else "none"
                smtp_username = self._app.config.get("MAIL_USERNAME")
                smtp_password = self._app.config.get("MAIL_PASSWORD")

        if not recipients:
            return

        if not smtp_host:
            self._logger.warning("Mail server not configured; skipping compliance email alert")
            return

        sender = smtp_username or "alerts@localhost"

        message = EmailMessage()
        message["Subject"] = "EAS System Health Alert"
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(
            "\n".join(
                [
                    "The following compliance issues were detected:",
                    "",
                    *[f"- {issue}" for issue in issues],
                    "",
                    f"Generated at {utc_now().isoformat()}",
                ]
            )
        )

        try:
            from app_core.notifications.email import build_smtp_connection
            with build_smtp_connection(smtp_host, smtp_port, smtp_security) as smtp:
                if smtp_username and smtp_password:
                    smtp.login(smtp_username, smtp_password)
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - network dependent
            self._logger.error("Failed to send compliance email alert: %s", exc)

    def _send_snmp_traps(self, issues: List[str]) -> None:
        # Prefer database-backed NotificationSettings; fall back to legacy env vars
        targets: List[str] = []
        community = "public"

        try:
            from app_core.models import NotificationSettings
            settings = NotificationSettings.query.first()
            if settings and settings.snmp_enabled:
                targets = [
                    t.strip()
                    for t in (settings.snmp_targets or [])
                    if t and t.strip()
                ]
                community = (settings.snmp_community or "public").strip() or "public"
        except Exception as exc:
            self._logger.warning("Could not load SNMP settings from DB: %s", exc)

        # Legacy fallback: COMPLIANCE_SNMP_TARGETS / COMPLIANCE_SNMP_COMMUNITY env vars
        if not targets:
            targets = [
                target.strip()
                for target in self._app.config.get("COMPLIANCE_SNMP_TARGETS", [])
                if target and target.strip()
            ]
            community = self._app.config.get("COMPLIANCE_SNMP_COMMUNITY", "public")

        if not targets:
            return

        if sendNotification is None:
            self._logger.warning(
                "pysnmp not available; unable to emit SNMP compliance traps"
            )
            return

        payload = "; ".join(issues)

        for target in targets:
            host, _, port_str = target.partition(":")
            try:
                port = int(port_str) if port_str else 162
            except ValueError:
                port = 162

            try:
                for error_indication, _error_status, _error_index, _var_binds in sendNotification(  # type: ignore[misc]
                    SnmpEngine(),
                    CommunityData(community, mpModel=1),
                    UdpTransportTarget((host, port), timeout=3, retries=1),
                    ContextData(),
                    "trap",
                    NotificationType(ObjectIdentity("1.3.6.1.4.1.32473.1.0.1")).addVarBinds(
                        ObjectType(ObjectIdentity("1.3.6.1.4.1.32473.1.1.1.0"), payload)
                    ),
                ):
                    if error_indication:  # pragma: no cover - depends on network stack
                        self._logger.error("SNMP trap to %s:%s failed: %s", host, port, error_indication)
            except Exception as exc:  # pragma: no cover - network dependent
                self._logger.error(
                    "Failed to send SNMP trap to %s:%s: %s", host, port, exc
                )


__all__ = [
    "collect_audio_path_status",
    "collect_icecast_status",
    "collect_receiver_health_snapshot",
    "get_system_health",
    "start_health_alert_worker",
]
