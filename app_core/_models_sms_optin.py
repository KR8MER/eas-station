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

"""Public self-serve SMS opt-in: double opt-in (web form + SMS code
confirmation) for the SMS recipient list, replacing the old design where an
administrator added a number and merely attested that consent was obtained
out-of-band. That design gave a carrier/Twilio campaign reviewer nothing
verifiable to point at -- see docs/guides/SMS_OPT_IN.md and
docs/policies/SMS_MESSAGING.md for the compliance rationale.

One row per opt-in *attempt*, not per recipient: a phone number that starts
over after an expired/wrong code gets a fresh row rather than mutating the
old one, so the audit trail shows every attempt, not just the outcome.
verified_at is the single source of truth for "did this number actually
confirm" -- NotificationSettings.sms_recipients is updated at the moment of
verification, but this table is what a compliance reviewer (or the admin
Consent Records view) actually reads.
"""

from ._models_base import db, utc_now


class SmsOptInRequest(db.Model):
    """One SMS opt-in attempt: pending until the emailed/texted code is
    confirmed, permanent evidence afterward."""
    __tablename__ = "sms_opt_in_requests"

    id = db.Column(db.Integer, primary_key=True)

    phone_number = db.Column(db.String(20), nullable=False, index=True)
    # E.164 format (e.g. +15555550100) -- validated before a row is created.

    name = db.Column(db.String(255), nullable=True)
    # Optional, operator-facing only (never sent in the SMS itself).

    consent_text = db.Column(db.Text, nullable=False)
    # Exact wording shown next to the consent checkbox at submission time --
    # a verbatim snapshot, not a reference to the current policy text, so a
    # later wording change can never retroactively alter what a given
    # recipient is shown to have agreed to.

    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)

    code_hash = db.Column(db.String(255), nullable=False)
    # Peppered+hashed the same way MFA backup codes are (see
    # app_core.auth.mfa.MFAManager.hash_backup_codes) -- never store the
    # plaintext code once it has been sent.

    code_expires_at = db.Column(db.DateTime, nullable=False)
    code_attempts = db.Column(db.Integer, nullable=False, default=0)
    # Wrong-code guesses against this row; the route locks the row out
    # after a small fixed number rather than letting it be brute-forced.

    verified_at = db.Column(db.DateTime, nullable=True)
    # NULL until the code is confirmed. This is the field that makes a row
    # "real" consent evidence rather than an unconfirmed attempt.

    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "name": self.name,
            "ip_address": self.ip_address,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
