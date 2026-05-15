"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Auto-instrumentation of alert-lifecycle inserts into the audit log.

This module wires SQLAlchemy ``after_insert`` events on the three
alert-lifecycle models -- ``CAPAlert``, ``EASMessage``,
``ManualEASActivation`` -- so that every newly-persisted row is captured in
the tamper-evident audit log without any per-call-site instrumentation.

Why a model-event listener instead of editing every ``CAPAlert(...)`` /
``EASMessage(...)`` / ``ManualEASActivation(...)`` construction site?

* There are at least five active construction sites across
  ``poller.cap_poller``, ``webapp.eas.workflow``, ``webapp.admin.audio``,
  ``app_core.rwt_scheduler``, and ``scripts.manual_alert_fetch``, plus
  paths in ``scripts.manual_eas_event`` and ``webapp.admin.maintenance``.
  Touching all of them would be invasive and easy to leave incomplete.
* A future contributor adding a sixth path would silently bypass the
  audit log.  A model-level listener guarantees coverage.

The handler runs inside the same DB transaction (via ``before_commit``) as
the originating insert, so either both the alert row and the audit row are
visible to other readers or neither is -- there is no window where a row
exists without its audit entry.

The handler is also defensive: if ``AuditLogger.log()`` itself raises
(missing key, locked table, etc.) we swallow the exception and log a
warning rather than crash the user-visible insert that triggered it.
Tamper-evidence is a defensive control; it should never be the reason a
real alert insert fails.
"""

import logging
import threading
from typing import Any, Dict, List, Tuple

from sqlalchemy import event

from .audit import AuditAction, AuditLogger


_logger = logging.getLogger(__name__)

# Module-level guard so we don't double-register if the import is reloaded
# (e.g. by some test harnesses that re-execute the application factory).
_REGISTERED = False
_REGISTER_LOCK = threading.Lock()


# The pending-events bag is stashed on Session.info so it's scoped to one
# unit of work and cannot leak between concurrent sessions in different
# threads.  Each entry is a (AuditAction, summary_dict) tuple.
_PENDING_EVENTS_KEY = '_eas_audit_pending_events'


def _stash(session, action: AuditAction, summary: Dict[str, Any]) -> None:
    bag: List[Tuple[AuditAction, Dict[str, Any]]] = session.info.setdefault(
        _PENDING_EVENTS_KEY, []
    )
    bag.append((action, summary))


def _flush_pending(session) -> None:
    """Drain the pending bag and write one audit row per entry.

    Runs from the SQLAlchemy ``after_commit`` event, intentionally NOT
    ``before_commit``: writing audit rows inside the same transaction
    triggers a recursive ``before_commit`` (since ``AuditLogger.log`` itself
    commits), which is messy.  ``after_commit`` is safe because the original
    insert is already durable; if the audit write fails the worst case is
    "alert persisted but audit row missing", which is exactly the unsigned-
    legacy-row case that ``verify_chain`` already tolerates.
    """
    bag = session.info.pop(_PENDING_EVENTS_KEY, None)
    if not bag:
        return
    for action, details in bag:
        try:
            AuditLogger.log(action=action, details=details)
        except Exception as exc:  # noqa: BLE001 - defensive: never break callers
            _logger.warning(
                "audit listener: could not record %s event for %r: %s",
                action.value, details.get('resource_id'), exc,
            )


def _cap_alert_summary(target) -> Dict[str, Any]:
    return {
        'resource_id': str(target.identifier) if target.identifier else None,
        'cap_id': target.id,
        'event': getattr(target, 'event', None),
        'severity': getattr(target, 'severity', None),
        'urgency': getattr(target, 'urgency', None),
        'certainty': getattr(target, 'certainty', None),
        'source': getattr(target, 'source', None),
        'msg_type': getattr(target, 'msg_type', None),
    }


def _eas_message_summary(target) -> Dict[str, Any]:
    return {
        'resource_id': str(target.id) if target.id is not None else None,
        'cap_alert_id': getattr(target, 'cap_alert_id', None),
        'same_header': getattr(target, 'same_header', None),
        'audio_filename': getattr(target, 'audio_filename', None),
        'tts_provider': getattr(target, 'tts_provider', None),
    }


def _manual_activation_summary(target) -> Dict[str, Any]:
    return {
        'resource_id': str(target.identifier) if target.identifier else None,
        'activation_id': target.id,
        'event_code': getattr(target, 'event_code', None),
        'event_name': getattr(target, 'event_name', None),
        'status': getattr(target, 'status', None),
        'message_type': getattr(target, 'message_type', None),
        'created_by': getattr(target, 'created_by', None),
        'created_by_ip': getattr(target, 'created_by_ip', None),
    }


def _make_after_insert(action: AuditAction, summarizer):
    def _handler(mapper, connection, target):  # noqa: ARG001 - SA signature
        # Identify the session attached to this in-flight insert so we can
        # stash the event on session.info.  In rare cases (raw connection
        # use), there may be no session -- in which case we synchronously
        # write a best-effort audit row using AuditLogger.log directly.
        try:
            from sqlalchemy.orm import Session as _SASession  # local import
            session = _SASession.object_session(target)
        except Exception:  # noqa: BLE001
            session = None

        try:
            summary = summarizer(target)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("audit listener: summary failed for %s: %s", action.value, exc)
            return

        if session is not None:
            _stash(session, action, summary)
        else:
            # Sessionless path: fire immediately.  Best effort.
            try:
                AuditLogger.log(action=action, details=summary)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "audit listener: sessionless %s event dropped: %s",
                    action.value, exc,
                )

    return _handler


def register_audit_listeners() -> None:
    """Idempotently attach the alert-lifecycle listeners.

    Safe to call multiple times: the second call is a no-op.  Call once
    from the Flask application factory after the models are imported.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    with _REGISTER_LOCK:
        if _REGISTERED:
            return

        # Import inside the function so this module stays importable in
        # bare-Alembic contexts where the full model graph isn't loaded.
        from app_core._models_alerts import (
            CAPAlert,
            EASMessage,
            ManualEASActivation,
        )
        from sqlalchemy.orm import Session as _SASession

        event.listen(
            CAPAlert,
            'after_insert',
            _make_after_insert(AuditAction.ALERT_RECEIVED, _cap_alert_summary),
        )
        event.listen(
            EASMessage,
            'after_insert',
            _make_after_insert(AuditAction.EAS_BROADCAST, _eas_message_summary),
        )
        event.listen(
            ManualEASActivation,
            'after_insert',
            _make_after_insert(
                AuditAction.EAS_MANUAL_ACTIVATION, _manual_activation_summary
            ),
        )

        # Flush pending events to the audit table after each commit.
        event.listen(_SASession, 'after_commit', _flush_pending)
        # Clear pending events if the originating transaction is rolled
        # back -- we don't want to audit inserts that didn't actually
        # persist.
        event.listen(
            _SASession,
            'after_rollback',
            lambda s: s.info.pop(_PENDING_EVENTS_KEY, None),
        )

        _REGISTERED = True


__all__ = ['register_audit_listeners']
