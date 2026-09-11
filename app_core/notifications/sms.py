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

"""SMS notification sender for EAS alerts via Twilio."""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _log_sms(
    phone_number: str,
    message_type: str,
    success: bool,
    *,
    event_code: str = None,
    twilio_sid: str = None,
    error_message: str = None,
    db_session=None,
) -> None:
    """Best-effort write to the sms_message_log table. Never raises --
    see app_core._models_sms_log.record_sms_message's docstring."""
    try:
        from app_core._models_sms_log import record_sms_message

        record_sms_message(
            phone_number,
            message_type,
            success,
            event_code=event_code,
            twilio_sid=twilio_sid,
            error_message=error_message,
            db_session=db_session,
            logger=logger,
        )
    except Exception:
        logger.debug("SMS message log unavailable; skipping", exc_info=True)


def send_eas_alert_sms(
    alert_info: Dict[str, Any],
    recipients: List[str],
    account_sid: str,
    auth_token: str,
    from_number: str,
    db_session=None,
) -> bool:
    """Send EAS alert SMS notifications via Twilio.

    Each message includes an opt-out footer ("Reply STOP to stop msgs") as
    required by CTIA messaging guidelines and enforced by Twilio for
    toll-free number verification.

    Args:
        alert_info:   Dict with alert details (event_code, headline,
                      location_codes, timestamp, source).
        recipients:   List of destination phone numbers in E.164 format
                      (e.g. +15555551234).
        account_sid:  Twilio Account SID.
        auth_token:   Twilio Auth Token.
        from_number:  Twilio sending phone number in E.164 format.
        db_session:   Optional SQLAlchemy session to record each send
                      attempt with (see app_core._models_sms_log). Pass
                      the session this function's caller was itself
                      threaded, if it has one -- callers running in a
                      background worker context may not have Flask's
                      request-scoped global session available. Falls
                      back to that global session if omitted.

    Returns:
        True if at least one message was sent successfully.
    """
    if not recipients:
        logger.debug("No SMS recipients configured; skipping")
        return False

    if not account_sid or not auth_token or not from_number:
        logger.warning("Twilio credentials incomplete; skipping SMS notification")
        return False

    try:
        from twilio.rest import Client  # type: ignore[import]
    except ImportError:
        logger.error(
            "twilio library not installed; cannot send SMS. "
            "Add 'twilio' to requirements.txt and reinstall."
        )
        return False

    event_code = alert_info.get("event_code", "UNKNOWN")
    headline = alert_info.get("headline", "")
    location_codes = alert_info.get("location_codes", [])
    timestamp = alert_info.get("timestamp", "")

    # Build a concise SMS body (target ≤160 chars for single-segment delivery)
    locations_str = ""
    if location_codes:
        locations_str = ", ".join(location_codes[:3])
        if len(location_codes) > 3:
            locations_str += f" (+{len(location_codes) - 3} more)"

    body_parts = [f"EAS ALERT: {event_code}"]

    if headline and headline.lower() != f"eas alert: {event_code}".lower():
        short_headline = headline[:60] if len(headline) > 60 else headline
        body_parts.append(short_headline)

    if locations_str:
        body_parts.append(f"Areas: {locations_str}")

    if timestamp:
        # Include only the date/time portion (first 19 chars of ISO format)
        body_parts.append(timestamp[:19])

    body_parts.append("- EAS Station")
    # CTIA / Twilio compliance: every outbound message must include opt-out
    # instructions so recipients always know how to stop messages.
    body_parts.append("Reply STOP to stop msgs")

    message_body = "\n".join(body_parts)

    client = Client(account_sid, auth_token)
    success = False

    for number in recipients:
        try:
            msg = client.messages.create(
                body=message_body,
                from_=from_number,
                to=number,
            )
            logger.info("SMS sent to %s (SID: %s)", number, msg.sid)
            success = True
            _log_sms(
                number, "alert", True,
                event_code=event_code, twilio_sid=msg.sid, db_session=db_session,
            )
        except Exception as exc:
            logger.error("Failed to send SMS to %s: %s", number, exc)
            _log_sms(
                number, "alert", False,
                event_code=event_code, error_message=str(exc), db_session=db_session,
            )

    return success


def send_verification_sms(
    account_sid: str,
    auth_token: str,
    from_number: str,
    recipient: str,
    code: str,
) -> Tuple[bool, str]:
    """Send a one-time confirmation code for the public SMS opt-in flow
    (see webapp/public/sms_optin.py). Double opt-in: the recipient must
    prove they actually control the number they submitted by relaying
    this code back, before it's added to the live alert recipient list.

    Args:
        account_sid: Twilio Account SID.
        auth_token:  Twilio Auth Token.
        from_number: Twilio sending number in E.164 format.
        recipient:   Destination phone number in E.164 format.
        code:        The plaintext code to send (caller generates/hashes it
                     for storage; this function only sends it).

    Returns:
        (success: bool, message: str)
    """
    if not account_sid or not auth_token or not from_number:
        return False, "SMS notifications are not configured on this system."

    try:
        from twilio.rest import Client  # type: ignore[import]
    except ImportError:
        return False, "twilio library is not installed."

    try:
        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            body=(
                f"EAS Station verification code: {code}\n"
                "Enter this on the page where you requested it to confirm "
                "you want to receive emergency alert texts. Expires in 10 "
                "minutes. Reply STOP to opt out, HELP for help."
            ),
            from_=from_number,
            to=recipient,
        )
        _log_sms(recipient, "verification", True, twilio_sid=msg.sid)
        return True, f"Verification code sent (SID: {msg.sid})"
    except Exception as exc:
        _log_sms(recipient, "verification", False, error_message=str(exc))
        return False, f"Failed to send verification code: {exc}"


def test_sms(
    account_sid: str,
    auth_token: str,
    from_number: str,
    recipient: str,
) -> Tuple[bool, str]:
    """Send a test SMS to verify the Twilio configuration.

    Args:
        account_sid: Twilio Account SID.
        auth_token:  Twilio Auth Token.
        from_number: Twilio sending number in E.164 format.
        recipient:   Destination phone number in E.164 format.

    Returns:
        (success: bool, message: str)
    """
    if not account_sid or not auth_token or not from_number:
        return (
            False,
            "Account SID, Auth Token, and From Number are all required",
        )

    if not recipient:
        return False, "A recipient phone number is required for testing"

    try:
        from twilio.rest import Client  # type: ignore[import]
    except ImportError:
        return (
            False,
            "twilio library is not installed. Add 'twilio' to requirements.txt.",
        )

    try:
        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            body=(
                "EAS Station - Test SMS. "
                "Your SMS notification configuration is working correctly. "
                "Reply STOP to stop msgs, HELP for help."
            ),
            from_=from_number,
            to=recipient,
        )
        _log_sms(recipient, "test", True, twilio_sid=msg.sid)
        return True, f"Test SMS sent successfully (SID: {msg.sid})"

    except Exception as exc:
        _log_sms(recipient, "test", False, error_message=str(exc))
        return False, f"Failed to send test SMS: {exc}"


__all__ = ["send_eas_alert_sms", "send_verification_sms", "test_sms"]
