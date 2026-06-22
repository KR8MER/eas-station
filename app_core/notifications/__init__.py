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

"""EAS Station notification subsystem (email + SMS)."""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def send_alert_notifications(
    record_id: Optional[int],
    alert_info: Dict[str, Any],
    db_session,
    logger_instance: Optional[logging.Logger] = None,
) -> None:
    """Send email and/or SMS notifications for a broadcast EAS alert.

    Called after a successful EAS broadcast. Fires email to configured
    alert_emails and/or SMS to configured sms_recipients based on the
    current NotificationSettings row.

    Args:
        record_id: EASMessage primary key (used to fetch audio for attachment).
                   May be None if the record ID is unavailable.
        alert_info: Dict describing the alert. Expected keys:
                    event_code, headline, same_header, location_codes,
                    source, timestamp.
        db_session: Active SQLAlchemy session.
        logger_instance: Optional logger override.
    """
    log = logger_instance or logger
    log.debug(
        "send_alert_notifications: record_id=%s event=%s",
        record_id,
        alert_info.get("event_code", "?"),
    )

    try:
        from app_core.models import NotificationSettings, EASMessage

        settings = db_session.query(NotificationSettings).first()
        if not settings:
            log.warning("No notification settings row found; skipping alert notifications")
            return

        # ------------------------------------------------------------------
        # Gather email media: composite audio, the linked CAP alert id (for
        # the inline coverage map), and a public "listen" link.
        # ------------------------------------------------------------------
        audio_data: Optional[bytes] = None
        audio_filename: Optional[str] = None
        cap_alert_id: Optional[int] = None

        # Backwards/forwards compatible reads of the new settings columns.
        email_html = bool(getattr(settings, "email_html", True))
        email_include_map = bool(getattr(settings, "email_include_map", True))
        email_audio_link = bool(getattr(settings, "email_audio_link", True))
        email_compress_audio = bool(getattr(settings, "email_compress_audio", False))
        public_base_url = (getattr(settings, "public_base_url", "") or "").strip()

        if record_id and settings.email_enabled:
            try:
                eas_msg = db_session.get(EASMessage, record_id)
                if eas_msg:
                    cap_alert_id = getattr(eas_msg, "cap_alert_id", None)
                    if settings.email_attach_audio and eas_msg.audio_data:
                        audio_data = bytes(eas_msg.audio_data)
                        audio_filename = eas_msg.audio_filename or "eas_alert.wav"
            except Exception as exc:
                log.warning(
                    "Could not fetch EASMessage for notification media: %s", exc
                )

        # Inline coverage-map image (HTML emails only).
        map_image: Optional[bytes] = None
        if settings.email_enabled and email_html and email_include_map:
            if cap_alert_id:
                try:
                    from app_core.notifications.alert_image import build_alert_image

                    map_image = build_alert_image(db_session, cap_alert_id, log)
                except Exception as exc:
                    log.warning("Could not build alert coverage image: %s", exc)
                if map_image is None:
                    log.warning(
                        "Alert image could not be built for CAP alert %s; "
                        "email will be sent without the inline card",
                        cap_alert_id,
                    )
            elif record_id:
                log.info(
                    "EAS message %s has no linked CAP alert (OTA broadcast); "
                    "email will not include a coverage map",
                    record_id,
                )

        # Public "listen / download" link for the broadcast audio.
        audio_url: Optional[str] = None
        if email_audio_link and public_base_url and record_id:
            audio_url = (
                f"{public_base_url.rstrip('/')}/eas_messages/{record_id}/audio?download=1"
            )

        # ------------------------------------------------------------------
        # Email
        # ------------------------------------------------------------------
        if not settings.email_enabled:
            log.debug("Email notifications disabled; skipping")
        elif not settings.smtp_host:
            log.warning("Email notifications enabled but no SMTP host configured; skipping")
        else:
            recipients = list(settings.alert_emails or [])
            if not recipients:
                log.warning("Email notifications enabled but no alert recipients configured; skipping")
            if recipients:
                try:
                    from app_core.notifications.email import send_eas_alert_email

                    send_eas_alert_email(
                        alert_info=alert_info,
                        recipients=recipients,
                        smtp_host=settings.smtp_host,
                        smtp_port=settings.smtp_port or 587,
                        smtp_username=settings.smtp_username or "",
                        smtp_password=settings.smtp_password or "",
                        smtp_security=settings.smtp_security or "starttls",
                        audio_data=audio_data if settings.email_attach_audio else None,
                        audio_filename=audio_filename,
                        html=email_html,
                        map_image=map_image,
                        audio_url=audio_url,
                        compress_audio=email_compress_audio,
                    )
                except Exception as exc:
                    log.error("Alert email notification failed: %s", exc)

        # ------------------------------------------------------------------
        # SMS
        # ------------------------------------------------------------------
        if (
            settings.sms_enabled
            and settings.sms_account_sid
            and settings.sms_auth_token
            and settings.sms_from_number
        ):
            recipients = list(settings.sms_recipients or [])
            if recipients:
                try:
                    from app_core.notifications.sms import send_eas_alert_sms

                    send_eas_alert_sms(
                        alert_info=alert_info,
                        recipients=recipients,
                        account_sid=settings.sms_account_sid,
                        auth_token=settings.sms_auth_token,
                        from_number=settings.sms_from_number,
                    )
                except Exception as exc:
                    log.error("Alert SMS notification failed: %s", exc)

    except Exception as exc:
        log.error("Alert notification dispatch failed: %s", exc)


__all__ = ["send_alert_notifications"]
