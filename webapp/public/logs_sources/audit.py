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

"""The audit and compliance categories on /logs.

Both are "who did what" views rather than machine telemetry, and both pull from
outside ``app_core.models`` — the audit trail from ``app_core.auth.audit`` and
the compliance ledger from ``app_core.eas_storage``.
"""

from .common import LogPage, LogQuery

COMPLIANCE_WINDOW_DAYS = 30


def load_audit(query: LogQuery) -> LogPage:
    """The tamper-evident audit trail.

    ``query.action_filter`` is applied **in SQL** rather than to the fetched
    rows, so the newest matching entries survive the ``limit`` window instead
    of being crowded out by unrelated actions.
    """
    from app_core.auth.audit import AuditLog

    audit_query = AuditLog.query
    # Optional action filter (e.g. config.updated) applied at the DB
    # level so the newest matching rows survive the limit window.
    if query.action_filter:
        audit_query = audit_query.filter(AuditLog.action == query.action_filter)
    logs_result = (
        audit_query
        .order_by(AuditLog.timestamp.desc())
        .limit(query.limit)
        .all()
    )
    return LogPage("Audit Log", [
        {
            'timestamp': log.timestamp,
            'level': 'INFO' if log.success else 'WARNING',
            'module': f"audit:{log.action}",
            'message': (
                f"{log.action}"
                + (f" by {log.username}" if log.username else " (anonymous)")
                + (f" on {log.resource_type}#{log.resource_id}"
                   if log.resource_type and log.resource_id else "")
                + ("" if log.success else " — FAILED")
            ),
            'alert_identifier': None,  # AuditLog isn't alert-keyed
            'details': {
                'action': log.action,
                'success': log.success,
                'username': log.username,
                'user_id': log.user_id,
                'resource_type': log.resource_type,
                'resource_id': log.resource_id,
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'details': log.details,
                # Tamper-evidence chain fields (see
                # docs/security/AUDIT_LOG_INTEGRITY.md).  Surfacing
                # all three lets an operator cross-check a single
                # row against an exported copy or the verify API.
                'prev_hash': log.prev_hash,
                'entry_hash': log.entry_hash,
                'signature': log.signature,
            },
        }
        for log in logs_result
    ])


def load_compliance(query: LogQuery) -> LogPage:
    """The unified FCC compliance ledger for the last 30 days."""
    # Pull the unified compliance entries (CAPAlert received +
    # EASMessage relayed + ManualEASActivation), defaulting to the
    # last 30 days so the page is useful out of the box.
    from app_core.eas_storage import collect_compliance_log_entries
    try:
        entries, _, _ = collect_compliance_log_entries(window_days=COMPLIANCE_WINDOW_DAYS)
    except Exception as exc:
        query.logger.error("compliance log query failed: %s", exc)
        entries = []
    logs_data = []
    for entry in entries[:query.limit]:
        category = entry.get('category', 'unknown')
        level = (
            'INFO' if category == 'received'
            else 'SUCCESS' if category == 'relayed'
            else 'WARNING' if category == 'manual'
            else 'SECONDARY'
        )
        logs_data.append({
            'timestamp': entry.get('timestamp'),
            'level': level,
            'module': f"compliance:{category}",
            'message': (
                f"{(entry.get('event_label') or 'Unknown event')} "
                f"— {entry.get('status') or 'no status'}"
            ),
            'alert_identifier': entry.get('identifier'),
            'details': entry.get('details') or {},
        })

    return LogPage("Compliance Log", logs_data)


LOADERS = {
    'audit': load_audit,
    'compliance': load_compliance,
}

__all__ = ["COMPLIANCE_WINDOW_DAYS", "LOADERS", "load_audit", "load_compliance"]
