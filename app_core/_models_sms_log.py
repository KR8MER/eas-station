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

"""Outbound SMS message log: one row per message Twilio was actually asked
to send (alert broadcasts, opt-in verification codes, and admin test
messages), so "did we text this number, and when" is a searchable database
record instead of something only recoverable by grepping journalctl.

Recording happens in app_core/notifications/sms.py itself, right next to
each Twilio call -- not at the various call sites -- so every send path
(present and future) is covered automatically, and it's best-effort: a
logging failure must never be mistaken for (or cause) a send failure.
"""

import logging
from typing import Optional

from ._models_base import db, utc_now


class SmsMessageLog(db.Model):
    """One outbound SMS send attempt."""
    __tablename__ = "sms_message_log"

    id = db.Column(db.Integer, primary_key=True)

    phone_number = db.Column(db.String(20), nullable=False, index=True)
    # Destination in E.164 format -- the field this log is searched by.

    message_type = db.Column(db.String(20), nullable=False, index=True)
    # 'alert' (EAS broadcast notification), 'verification' (opt-in code),
    # or 'test' (Settings -> Notifications "Send Test SMS").

    event_code = db.Column(db.String(16), nullable=True)
    # EAS event code (e.g. "TOR"), populated for message_type='alert' only.

    success = db.Column(db.Boolean, nullable=False, default=False)
    twilio_sid = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "message_type": self.message_type,
            "event_code": self.event_code,
            "success": self.success,
            "twilio_sid": self.twilio_sid,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def record_sms_message(
    phone_number: str,
    message_type: str,
    success: bool,
    *,
    event_code: Optional[str] = None,
    twilio_sid: Optional[str] = None,
    error_message: Optional[str] = None,
    db_session=None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Best-effort write of one SmsMessageLog row. Never raises -- a
    logging failure here must not be mistaken for (or cause) a send
    failure in the caller.

    db_session is optional: callers reached from a background worker
    context (e.g. app_core.notifications.send_alert_notifications, which
    is threaded an explicit session rather than relying on Flask-SQLAlchemy's
    request-scoped global) should pass theirs through; callers running
    inside a normal Flask request can omit it and the module-global
    ``db.session`` is used.
    """
    session = db_session if db_session is not None else db.session
    try:
        session.add(
            SmsMessageLog(
                phone_number=phone_number,
                message_type=message_type,
                event_code=event_code,
                success=success,
                twilio_sid=twilio_sid,
                error_message=error_message,
            )
        )
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive, logging must not raise
        try:
            session.rollback()
        except Exception:
            pass
        (logger or logging.getLogger(__name__)).warning(
            "Could not record SMS message log entry for %s: %s", phone_number, exc
        )


__all__ = ["SmsMessageLog", "record_sms_message"]
