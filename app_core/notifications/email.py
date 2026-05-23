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

"""Email notification sender for EAS alerts."""

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_extended_same_lookup

logger = logging.getLogger(__name__)


def build_smtp_connection(host: str, port: int, security: str):
    """Return an active SMTP connection based on security mode.

    Args:
        host:     SMTP server hostname.
        port:     SMTP server port.
        security: "ssl" uses SMTP_SSL; "starttls" upgrades via STARTTLS;
                  "none" makes a plain connection.

    Returns:
        An smtplib.SMTP or smtplib.SMTP_SSL instance (not yet authenticated).
    """
    if security == "ssl":
        smtp = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        smtp = smtplib.SMTP(host, port, timeout=15)
        if security == "starttls":
            smtp.starttls()
    return smtp


def send_eas_alert_email(
    alert_info: Dict[str, Any],
    recipients: List[str],
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    smtp_security: str = "starttls",
    audio_data: Optional[bytes] = None,
    audio_filename: Optional[str] = None,
) -> bool:
    """Send an EAS alert notification email.

    Args:
        alert_info:    Dict with alert details (event_code, headline, same_header,
                       location_codes, source, timestamp).
        recipients:    List of destination email addresses.
        smtp_host:     SMTP server hostname.
        smtp_port:     SMTP server port.
        smtp_username: SMTP login username (empty string for unauthenticated relay).
        smtp_password: SMTP login password.
        smtp_security: "none", "starttls", or "ssl".
        audio_data:    Optional WAV bytes to attach to the email.
        audio_filename: Filename for the audio attachment.

    Returns:
        True on success, False on failure.
    """
    if not recipients:
        logger.debug("No alert email recipients configured; skipping")
        return False

    if not smtp_host:
        logger.warning("No SMTP host configured; skipping alert email")
        return False

    event_code = alert_info.get("event_code", "UNKNOWN")
    headline = alert_info.get("headline", f"EAS Alert: {event_code}")
    same_header = alert_info.get("same_header", "")
    source = alert_info.get("source", "EAS Station")
    timestamp = alert_info.get("timestamp", "")
    location_codes = alert_info.get("location_codes", [])

    event_entry = EVENT_CODE_REGISTRY.get(event_code)
    event_name = event_entry.get("name") if event_entry else None
    event_label = f"{event_code} - {event_name}" if event_name else event_code

    fips_lookup = get_extended_same_lookup()
    location_labels = []
    for code in location_codes:
        name = fips_lookup.get(code)
        location_labels.append(name if name else code)

    sender = smtp_username or "alerts@localhost"

    msg = EmailMessage()
    msg["Subject"] = f"EAS Alert: {event_code} - {headline}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    body_lines = [
        "EAS Station Alert Notification",
        "=" * 40,
        f"Event:       {event_label}",
        f"Headline:    {headline}",
    ]
    if same_header:
        body_lines.append(f"SAME Header: {same_header}")
    if location_labels:
        body_lines.append(f"Locations:   {', '.join(location_labels)}")
    if timestamp:
        body_lines.append(f"Time:        {timestamp}")
    body_lines.append(f"Source:      {source}")
    body_lines.append("")
    body_lines.append("This is an automated notification from EAS Station.")

    msg.set_content("\n".join(body_lines))

    if audio_data:
        filename = audio_filename or f"eas_alert_{event_code}.wav"
        msg.add_attachment(
            audio_data,
            maintype="audio",
            subtype="wav",
            filename=filename,
        )
        # Python only sets filename in Content-Disposition; also set name in
        # Content-Type so iOS Mail and similar clients display it correctly.
        for part in msg.iter_attachments():
            if part.get_content_type() == "audio/wav":
                part.set_param("name", filename, header="Content-Type")

    try:
        with build_smtp_connection(smtp_host, smtp_port, smtp_security) as smtp:
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(msg)

        logger.info(
            "EAS alert email sent to %d recipient(s) for event %s",
            len(recipients),
            event_code,
        )
        return True

    except Exception as exc:
        logger.error(
            "Failed to send EAS alert email for event %s (%s:%d security=%s): %s",
            event_code,
            smtp_host,
            smtp_port,
            smtp_security,
            exc,
        )
        return False


def test_email(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    smtp_security: str,
    recipient: str,
) -> Tuple[bool, str]:
    """Send a test email to verify the SMTP configuration.

    Args:
        smtp_host:     SMTP server hostname.
        smtp_port:     SMTP server port.
        smtp_username: SMTP login username.
        smtp_password: SMTP login password.
        smtp_security: "none", "starttls", or "ssl".
        recipient:     Destination email address for the test.

    Returns:
        (success: bool, message: str)
    """
    if not smtp_host:
        return False, "No SMTP host configured"

    if not recipient:
        return False, "A recipient email address is required for testing"

    sender = smtp_username or "alerts@localhost"

    msg = EmailMessage()
    msg["Subject"] = "EAS Station - Test Email"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(
        "This is a test email from EAS Station.\n\n"
        "If you received this message, your email notification "
        "configuration is working correctly."
    )

    try:
        with build_smtp_connection(smtp_host, smtp_port, smtp_security) as smtp:
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(msg)

        logger.info(
            "Test email sent to %s via %s:%d (security=%s)",
            recipient,
            smtp_host,
            smtp_port,
            smtp_security,
        )
        return True, "Test email sent successfully"

    except Exception as exc:
        logger.error(
            "Test email to %s failed (%s:%d security=%s): %s",
            recipient,
            smtp_host,
            smtp_port,
            smtp_security,
            exc,
        )
        return False, f"Failed to send test email: {exc}"


__all__ = ["build_smtp_connection", "send_eas_alert_email", "test_email"]
