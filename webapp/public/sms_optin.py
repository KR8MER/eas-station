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

Public, unauthenticated double opt-in for the SMS emergency-alert recipient
list: a web form collects a phone number and explicit consent, then a
one-time code texted to that number confirms the submitter actually
controls it before it's added to NotificationSettings.sms_recipients.

Replaces the old design where an administrator added a number and merely
attested that consent was obtained out-of-band -- a carrier/Twilio A2P
10DLC campaign reviewer has nothing verifiable to point at in that flow.
See docs/guides/SMS_OPT_IN.md and docs/policies/SMS_MESSAGING.md.

Every opt-in attempt is recorded in app_core.models.SmsOptInRequest (see
that module for why one row per attempt, not per recipient) -- Settings ->
Notifications' "Consent Records" panel reads it back for the admin, and a
compliance reviewer can be pointed at this page directly.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

from flask import jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from app_core.auth.rate_limiter import get_rate_limiter
from app_core.crypto import pepper_password
from app_core.extensions import db
from app_core.models import NotificationSettings, SmsOptInRequest
from app_core.notifications.sms import send_verification_sms
from app_utils import utc_now

# Standard E.164 shape: a leading '+', a non-zero first digit, then up to 14
# more digits (ITU-T E.164 §4). Deliberately not carrier-specific -- Twilio
# itself accepts any well-formed E.164 number.
_E164_PATTERN = re.compile(r'^\+[1-9]\d{1,14}$')

_CODE_TTL_MINUTES = 10
_MAX_CODE_ATTEMPTS = 5
_RESEND_COOLDOWN_SECONDS = 60
_SESSION_KEY = 'sms_optin_pending_id'

# Verbatim text shown next to the consent checkbox, and copied into
# SmsOptInRequest.consent_text at submission time -- see that model's
# docstring for why a snapshot, not a reference to the current wording.
CONSENT_TEXT = (
    "I agree to receive SMS emergency alerts from this EAS Station. "
    "Message frequency varies. Message and data rates may apply. "
    "Reply STOP to opt out at any time, HELP for help. "
    "See the Terms of Use and Privacy Policy."
)


def _notification_settings() -> NotificationSettings:
    settings = NotificationSettings.query.get(1)
    if settings is None:
        settings = NotificationSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def register(app, route_logger):
    """Attach the public SMS opt-in routes to the Flask app."""

    @app.route("/sms-opt-in", methods=["GET"])
    def sms_optin_page():
        return render_template("sms_optin.html", consent_text=CONSENT_TEXT)

    @app.route("/sms-opt-in/start", methods=["POST"])
    def sms_optin_start():
        """Validate the submitted number + consent, then text a one-time
        code to it. Rate-limited per IP (abuse of this endpoint costs the
        operator real Twilio spend) and per phone number (so the same
        number can't be repeatedly texted by a bystander who doesn't
        control it)."""
        rate_limiter = get_rate_limiter()
        ip_key = f"sms-optin-ip:{request.remote_addr}"
        is_locked, seconds_remaining = rate_limiter.is_locked_out(ip_key)
        if is_locked:
            minutes = (seconds_remaining + 59) // 60
            return jsonify({
                'error': f'Too many requests from this address. Try again in {minutes} minute(s).'
            }), 429

        phone_number = (request.form.get('phone_number') or '').strip()
        name = (request.form.get('name') or '').strip()[:255] or None
        consent_given = request.form.get('consent') == 'on'

        if not consent_given:
            return jsonify({'error': 'You must agree to receive SMS alerts to continue.'}), 400
        if not _E164_PATTERN.match(phone_number):
            return jsonify({
                'error': 'Enter a valid phone number in international format, e.g. +15555550100.'
            }), 400

        settings = _notification_settings()
        if phone_number in (settings.sms_recipients or []):
            return jsonify({
                'success': True,
                'already_subscribed': True,
                'message': 'This number is already signed up for SMS alerts.',
            })
        if not settings.sms_account_sid or not settings.sms_auth_token or not settings.sms_from_number:
            return jsonify({'error': 'SMS notifications are not configured on this system yet.'}), 503

        rate_limiter.record_failed_attempt(ip_key)  # counts the attempt regardless of outcome below

        phone_key = f"sms-optin-phone:{phone_number}"
        phone_locked, phone_seconds = rate_limiter.is_locked_out(phone_key)
        if phone_locked:
            return jsonify({
                'error': 'Too many opt-in attempts for this number recently. Please wait and try again.'
            }), 429

        # A cooldown against re-sending to the same number within the last
        # minute -- covers double-submits and a bystander re-triggering a
        # send to a number they don't control, without a full lockout.
        recent_cutoff = utc_now() - timedelta(seconds=_RESEND_COOLDOWN_SECONDS)
        recent_pending = (
            SmsOptInRequest.query
            .filter(
                SmsOptInRequest.phone_number == phone_number,
                SmsOptInRequest.verified_at.is_(None),
                SmsOptInRequest.created_at > recent_cutoff,
            )
            .first()
        )
        if recent_pending is not None:
            return jsonify({
                'error': 'A verification code was already sent to this number. Please wait a moment before requesting another.'
            }), 429

        code = _generate_code()
        code_hash = generate_password_hash(pepper_password(code))

        opt_in = SmsOptInRequest(
            phone_number=phone_number,
            name=name,
            consent_text=CONSENT_TEXT,
            ip_address=request.remote_addr,
            user_agent=(request.headers.get('User-Agent') or '')[:512] or None,
            code_hash=code_hash,
            code_expires_at=utc_now() + timedelta(minutes=_CODE_TTL_MINUTES),
            code_attempts=0,
            created_at=utc_now(),
        )
        db.session.add(opt_in)
        db.session.commit()

        sent, send_message = send_verification_sms(
            settings.sms_account_sid,
            settings.sms_auth_token,
            settings.sms_from_number,
            phone_number,
            code,
        )
        if not sent:
            route_logger.error("SMS opt-in verification send failed for %s: %s", phone_number, send_message)
            db.session.delete(opt_in)
            db.session.commit()
            return jsonify({'error': 'Could not send the verification code. Please try again shortly.'}), 502

        session[_SESSION_KEY] = opt_in.id
        return jsonify({
            'success': True,
            'message': f'A verification code was texted to {phone_number}. Enter it below to confirm.',
        })

    @app.route("/sms-opt-in/confirm", methods=["POST"])
    def sms_optin_confirm():
        """Confirm the code texted by sms_optin_start() and, on success,
        add the number to the live recipient list."""
        pending_id = session.get(_SESSION_KEY)
        if not pending_id:
            return jsonify({'error': 'Your session expired. Please start over.'}), 400

        opt_in = SmsOptInRequest.query.get(pending_id)
        if opt_in is None or opt_in.verified_at is not None:
            session.pop(_SESSION_KEY, None)
            return jsonify({'error': 'Your session expired. Please start over.'}), 400

        if utc_now() > opt_in.code_expires_at:
            session.pop(_SESSION_KEY, None)
            return jsonify({'error': 'That code has expired. Please start over.'}), 400

        if opt_in.code_attempts >= _MAX_CODE_ATTEMPTS:
            session.pop(_SESSION_KEY, None)
            return jsonify({'error': 'Too many incorrect attempts. Please start over.'}), 429

        submitted = ''.join((request.form.get('code') or '').split())
        if not check_password_hash(opt_in.code_hash, pepper_password(submitted)):
            opt_in.code_attempts += 1
            db.session.commit()
            remaining = max(0, _MAX_CODE_ATTEMPTS - opt_in.code_attempts)
            return jsonify({'error': f'Incorrect code. {remaining} attempt(s) remaining.'}), 400

        opt_in.verified_at = utc_now()
        db.session.commit()
        session.pop(_SESSION_KEY, None)

        settings = _notification_settings()
        recipients = list(settings.sms_recipients or [])
        if opt_in.phone_number not in recipients:
            recipients.append(opt_in.phone_number)
            settings.sms_recipients = recipients
            db.session.commit()

        route_logger.info(
            "SMS opt-in confirmed for %s (request id %s)", opt_in.phone_number, opt_in.id
        )
        return jsonify({
            'success': True,
            'message': "You're all set -- you'll now receive SMS emergency alerts from this station.",
        })


__all__ = ["register", "CONSENT_TEXT"]
