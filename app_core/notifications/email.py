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

import io
import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Dict, List, Optional, Tuple

from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_extended_same_lookup

logger = logging.getLogger(__name__)

# Standalone Jinja2 environment for rendering email bodies. Alert emails are
# sent from the broadcast worker (no Flask request context), so we load the
# templates directly from the project ``templates/email`` directory rather
# than going through Flask's ``render_template``.
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
    "email",
)
_jinja_env = None


def _get_template(name: str):
    """Return a compiled Jinja2 template from ``templates/email`` (cached env)."""
    global _jinja_env
    if _jinja_env is None:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        _jinja_env = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "xml"]),
        )
    return _jinja_env.get_template(name)


# Header accent colour keyed off the event's product class in the SAME event
# registry: WRN=Warning, WCH=Watch, ADV=Advisory/Statement, TEST=Test.
# Falls back to a neutral blue for unrecognised codes.
_PRODUCT_ACCENTS = {
    "WRN": ("#c0392b", "Warning"),
    "WCH": ("#e67e22", "Watch"),
    "ADV": ("#2c6fb0", "Advisory"),
    "TEST": ("#5d6d7e", "Test"),
}
_DEFAULT_ACCENT = ("#2c6fb0", "")


def _event_accent(event_code: str) -> Tuple[str, str]:
    """Return ``(accent_hex, severity_label)`` for a SAME event code.

    Uses the ``default_product`` class from EVENT_CODE_REGISTRY (WRN/WCH/
    ADV/TEST) rather than guessing from the code letters, since SAME codes
    are 3-letter mnemonics (e.g. TOR, SVR) with no severity suffix.
    """
    code = (event_code or "").strip().upper()
    entry = EVENT_CODE_REGISTRY.get(code)
    product = str(entry.get("default_product", "")).upper() if entry else ""
    return _PRODUCT_ACCENTS.get(product, _DEFAULT_ACCENT)


def _maybe_compress_audio(
    audio_data: bytes, filename: str
) -> Tuple[bytes, str, str, str]:
    """Best-effort transcode of WAV bytes to MP3 to shrink the attachment.

    Returns ``(data, maintype, subtype, filename)``. Falls back to the
    original WAV if pydub/ffmpeg are unavailable or the encode fails.
    """
    try:
        from pydub import AudioSegment

        seg = AudioSegment.from_file(io.BytesIO(audio_data), format="wav")
        buf = io.BytesIO()
        seg.export(buf, format="mp3", bitrate="64k")
        mp3 = buf.getvalue()
        if mp3:
            mp3_name = os.path.splitext(filename)[0] + ".mp3"
            logger.debug(
                "Compressed alert audio %d -> %d bytes (mp3)", len(audio_data), len(mp3)
            )
            return mp3, "audio", "mpeg", mp3_name
    except Exception as exc:
        logger.warning("Audio compression unavailable, attaching WAV: %s", exc)
    return audio_data, "audio", "wav", filename


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
    html: bool = False,
    map_image: Optional[bytes] = None,
    audio_url: Optional[str] = None,
    compress_audio: bool = False,
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
        html:          When True, add a styled HTML body (multipart/alternative)
                       alongside the plain-text fallback.
        map_image:     Optional PNG bytes embedded inline in the HTML body
                       (ignored unless ``html`` is True).
        audio_url:     Optional URL for a "listen / download" link in the HTML
                       body (ignored unless ``html`` is True).
        compress_audio: When True, transcode the WAV attachment to MP3 to
                       shrink it (falls back to WAV if encoding is unavailable).

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

    # ------------------------------------------------------------------
    # HTML alternative (with optional inline coverage-map image)
    # ------------------------------------------------------------------
    if html:
        accent_color, severity_label = _event_accent(event_code)
        map_cid = None
        map_cid_header = None
        if map_image:
            map_cid_header = make_msgid()
            map_cid = map_cid_header[1:-1]  # bare id for the HTML cid: ref
        try:
            html_body = _get_template("eas_alert.html").render(
                accent_color=accent_color,
                severity_label=severity_label,
                event_label=event_label,
                headline=headline,
                same_header=same_header,
                locations=location_labels,
                timestamp=timestamp,
                source=source,
                map_cid=map_cid,
                audio_url=audio_url,
            )
            msg.add_alternative(html_body, subtype="html")
            if map_image and map_cid_header:
                # Attach the PNG related to the HTML part so the cid: ref
                # resolves to an inline image.
                msg.get_payload()[1].add_related(
                    map_image,
                    maintype="image",
                    subtype="png",
                    cid=map_cid_header,
                )
        except Exception as exc:
            logger.warning("Failed to render HTML email body, sending text-only: %s", exc)

    if audio_data:
        filename = audio_filename or f"eas_alert_{event_code}.wav"
        data, maintype, subtype, filename = (
            _maybe_compress_audio(audio_data, filename)
            if compress_audio
            else (audio_data, "audio", "wav", filename)
        )
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
        # Python only sets filename in Content-Disposition; also set name in
        # Content-Type so iOS Mail and similar clients display it correctly.
        target_type = f"{maintype}/{subtype}"
        for part in msg.iter_attachments():
            if part.get_content_type() == target_type:
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
