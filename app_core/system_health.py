"""System health snapshot helpers shared across route modules."""

from __future__ import annotations

import os
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from flask import current_app
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import EASMessage, ManualEASActivation, RadioReceiver
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


def get_system_health(logger=None) -> Dict[str, Any]:
    """Return a structured health snapshot for the running application."""

    effective_logger = logger or _resolve_logger()
    return build_system_health_snapshot(db, effective_logger)


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
        latest = receiver.latest_status()
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
        latest_auto = db.session.query(func.max(EASMessage.created_at)).scalar()
        latest_manual_sent = db.session.query(func.max(ManualEASActivation.sent_at)).scalar()
        latest_manual_created = db.session.query(func.max(ManualEASActivation.created_at)).scalar()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to inspect audio activity timestamps: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        return None

    candidates = [
        _ensure_aware(value)
        for value in (latest_auto, latest_manual_sent, latest_manual_created)
        if value is not None
    ]

    if not candidates:
        return None

    return max(candidates)


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
        recipients = [
            addr.strip()
            for addr in self._app.config.get("COMPLIANCE_ALERT_EMAILS", [])
            if addr and addr.strip()
        ]

        if not recipients:
            return

        server = self._app.config.get("MAIL_SERVER")
        if not server:
            self._logger.warning("Mail server not configured; skipping compliance email alert")
            return

        port = int(self._app.config.get("MAIL_PORT", 587))
        use_tls = bool(self._app.config.get("MAIL_USE_TLS", True))
        username = self._app.config.get("MAIL_USERNAME")
        password = self._app.config.get("MAIL_PASSWORD")
        sender = username or "alerts@localhost"

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
            with smtplib.SMTP(server, port, timeout=10) as smtp:
                if use_tls:
                    smtp.starttls()
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - network dependent
            self._logger.error("Failed to send compliance email alert: %s", exc)

    def _send_snmp_traps(self, issues: List[str]) -> None:
        targets = [
            target.strip()
            for target in self._app.config.get("COMPLIANCE_SNMP_TARGETS", [])
            if target and target.strip()
        ]

        if not targets:
            return

        if sendNotification is None:
            self._logger.warning(
                "pysnmp not available; unable to emit SNMP compliance traps"
            )
            return

        community = self._app.config.get("COMPLIANCE_SNMP_COMMUNITY", "public")
        payload = "; ".join(issues)

        for target in targets:
            host, _, port_str = target.partition(":")
            try:
                port = int(port_str) if port_str else 162
            except ValueError:
                port = 162

            try:
                error = sendNotification(  # type: ignore[misc]
                    SnmpEngine(),
                    CommunityData(community, mpModel=1),
                    UdpTransportTarget((host, port), timeout=3, retries=1),
                    ContextData(),
                    "trap",
                    NotificationType(ObjectIdentity("1.3.6.1.4.1.32473.1.0.1")).addVarBinds(
                        ObjectType(ObjectIdentity("1.3.6.1.4.1.32473.1.1.1.0"), payload)
                    ),
                )
                if error:  # pragma: no cover - depends on network stack
                    self._logger.error("SNMP trap to %s:%s failed: %s", host, port, error)
            except Exception as exc:  # pragma: no cover - network dependent
                self._logger.error(
                    "Failed to send SNMP trap to %s:%s: %s", host, port, exc
                )


__all__ = [
    "collect_audio_path_status",
    "collect_receiver_health_snapshot",
    "get_system_health",
    "start_health_alert_worker",
]
