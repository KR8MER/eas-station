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

"""Notification settings admin routes."""

import logging
import socket
from types import SimpleNamespace

from flask import Blueprint, render_template, request, jsonify, flash
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import NotificationSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)

notifications_bp = Blueprint('notifications', __name__, url_prefix='/admin/notifications')


def _get_or_create_settings() -> NotificationSettings:
    """Get notification settings, creating defaults if none exist."""
    settings = NotificationSettings.query.first()
    if not settings:
        settings = NotificationSettings(
            id=1,
            email_enabled=False,
            smtp_host='',
            smtp_port=587,
            smtp_username='',
            smtp_password='',
            smtp_security='starttls',
            compliance_alert_emails=[],
            alert_emails=[],
            email_attach_audio=False,
            email_html=True,
            email_include_map=True,
            email_audio_link=True,
            email_compress_audio=False,
            public_base_url='',
            sms_enabled=False,
            sms_provider='twilio',
            sms_account_sid='',
            sms_auth_token='',
            sms_from_number='',
            sms_recipients=[],
            snmp_enabled=False,
            snmp_targets=[],
            snmp_community='public',
        )
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default notification settings")
    return settings


def _fallback_notification_settings():
    """Return in-memory defaults when the database is unavailable."""
    return SimpleNamespace(
        email_enabled=False,
        smtp_host='',
        smtp_port=587,
        smtp_username='',
        smtp_password='',
        smtp_security='starttls',
        compliance_alert_emails=[],
        alert_emails=[],
        email_attach_audio=False,
        email_html=True,
        email_include_map=True,
        email_audio_link=True,
        email_compress_audio=False,
        public_base_url='',
        sms_enabled=False,
        sms_provider='twilio',
        sms_account_sid='',
        sms_auth_token='',
        sms_from_number='',
        sms_recipients=[],
        snmp_enabled=False,
        snmp_targets=[],
        snmp_community='public',
    )


@notifications_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def notification_settings():
    """Display notification configuration settings page."""
    try:
        settings = _get_or_create_settings()
    except SQLAlchemyError as e:
        logger.error(f"Database error loading notification settings: {str(e)}")
        try:
            db.session.rollback()
        except Exception:
            pass
        flash(
            'Database error loading notification settings. '
            'Settings are shown with defaults — run database migrations to restore full functionality.',
            'danger',
        )
        settings = _fallback_notification_settings()
    return render_template('admin/notifications.html', settings=settings)


@notifications_bp.route('/update', methods=['POST'])
@require_auth
@require_permission('system.configure')
def update_notification_settings():
    """Update notification settings."""
    try:
        settings = NotificationSettings.query.first()
        if not settings:
            settings = NotificationSettings(id=1)
            db.session.add(settings)

        # --- Email ---
        settings.email_enabled = request.form.get('email_enabled', 'false').lower() == 'true'
        settings.smtp_host = request.form.get('smtp_host', '').strip()
        settings.smtp_port = int(request.form.get('smtp_port', '587') or '587')
        settings.smtp_username = request.form.get('smtp_username', '').strip()
        settings.smtp_security = request.form.get('smtp_security', 'starttls').strip() or 'starttls'
        settings.email_attach_audio = (
            request.form.get('email_attach_audio', 'false').lower() == 'true'
        )
        settings.email_html = (
            request.form.get('email_html', 'true').lower() == 'true'
        )
        settings.email_include_map = (
            request.form.get('email_include_map', 'true').lower() == 'true'
        )
        settings.email_audio_link = (
            request.form.get('email_audio_link', 'true').lower() == 'true'
        )
        settings.email_compress_audio = (
            request.form.get('email_compress_audio', 'false').lower() == 'true'
        )
        settings.public_base_url = request.form.get('public_base_url', '').strip()

        # Only update smtp_password if a non-empty value was submitted
        new_smtp_password = request.form.get('smtp_password', '').strip()
        if new_smtp_password:
            settings.smtp_password = new_smtp_password

        # Compliance alert emails: one address per line
        compliance_raw = request.form.get('compliance_alert_emails', '').strip()
        settings.compliance_alert_emails = [
            addr.strip() for addr in compliance_raw.splitlines() if addr.strip()
        ]

        # EAS alert notification emails: one address per line
        alert_raw = request.form.get('alert_emails', '').strip()
        settings.alert_emails = [
            addr.strip() for addr in alert_raw.splitlines() if addr.strip()
        ]

        # --- SMS ---
        settings.sms_enabled = request.form.get('sms_enabled', 'false').lower() == 'true'
        settings.sms_provider = request.form.get('sms_provider', 'twilio').strip() or 'twilio'
        settings.sms_account_sid = request.form.get('sms_account_sid', '').strip()
        settings.sms_from_number = request.form.get('sms_from_number', '').strip()

        # Only update auth_token if a non-empty value was submitted
        new_token = request.form.get('sms_auth_token', '').strip()
        if new_token:
            settings.sms_auth_token = new_token

        # SMS recipients: one phone number per line
        sms_raw = request.form.get('sms_recipients', '').strip()
        settings.sms_recipients = [
            num.strip() for num in sms_raw.splitlines() if num.strip()
        ]

        # --- SNMP ---
        settings.snmp_enabled = request.form.get('snmp_enabled', 'false').lower() == 'true'
        settings.snmp_community = request.form.get('snmp_community', 'public').strip() or 'public'

        # SNMP targets: one host:port per line
        snmp_raw = request.form.get('snmp_targets', '').strip()
        settings.snmp_targets = [
            t.strip() for t in snmp_raw.splitlines() if t.strip()
        ]

        db.session.commit()
        logger.info(
            "Updated notification settings: email_enabled=%s smtp=%s:%d, sms_enabled=%s, "
            "snmp_enabled=%s, alert_emails=%d, sms_recipients=%d, snmp_targets=%d",
            settings.email_enabled,
            settings.smtp_host or '(none)',
            settings.smtp_port or 587,
            settings.sms_enabled,
            settings.snmp_enabled,
            len(settings.alert_emails or []),
            len(settings.sms_recipients or []),
            len(settings.snmp_targets or []),
        )

        return jsonify({
            'success': True,
            'message': 'Notification settings updated successfully',
            'settings': settings.to_dict(),
        })

    except SQLAlchemyError as e:
        logger.error(f"Database error updating notification settings: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving notification settings'}), 500


@notifications_bp.route('/test-email', methods=['POST'])
@require_auth
@require_permission('system.configure')
def test_email():
    """Send a test email using the current SMTP configuration."""
    try:
        settings = _get_or_create_settings()

        if not settings.smtp_host:
            return jsonify({'success': False, 'error': 'No SMTP host configured'}), 400

        recipient = request.form.get('test_recipient', '').strip()
        if not recipient:
            # Fall back to first configured alert email or compliance email
            all_emails = list(settings.alert_emails or []) + list(settings.compliance_alert_emails or [])
            if all_emails:
                recipient = all_emails[0]
            else:
                return jsonify({'success': False, 'error': 'No recipient address specified'}), 400

        from app_core.notifications.email import test_email as _send_test
        logger.warning(
            "Test email attempt: recipient=%s smtp=%s:%d security=%s",
            recipient,
            settings.smtp_host or '(none)',
            settings.smtp_port or 587,
            settings.smtp_security or 'starttls',
        )

        success, message = _send_test(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port or 587,
            smtp_username=settings.smtp_username or '',
            smtp_password=settings.smtp_password or '',
            smtp_security=settings.smtp_security or 'starttls',
            recipient=recipient,
        )

        if success:
            logger.info("Test email sent to %s", recipient)
            return jsonify({'success': True, 'message': message})
        else:
            logger.warning("Test email failed: %s", message)
            return jsonify({'success': False, 'error': message}), 502

    except Exception as e:
        logger.error("Unexpected error sending test email: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@notifications_bp.route('/test-sms', methods=['POST'])
@require_auth
@require_permission('system.configure')
def test_sms():
    """Send a test SMS using the current Twilio configuration."""
    try:
        settings = _get_or_create_settings()

        if not settings.sms_account_sid or not settings.sms_auth_token or not settings.sms_from_number:
            return jsonify({
                'success': False,
                'error': 'Twilio credentials (Account SID, Auth Token, From Number) are not configured',
            }), 400

        recipient = request.form.get('test_recipient', '').strip()
        if not recipient:
            # Fall back to first configured SMS recipient
            sms_recipients = list(settings.sms_recipients or [])
            if sms_recipients:
                recipient = sms_recipients[0]
            else:
                return jsonify({'success': False, 'error': 'No recipient phone number specified'}), 400

        from app_core.notifications.sms import test_sms as _send_test

        success, message = _send_test(
            account_sid=settings.sms_account_sid,
            auth_token=settings.sms_auth_token,
            from_number=settings.sms_from_number,
            recipient=recipient,
        )

        if success:
            logger.info("Test SMS sent to %s", recipient)
            return jsonify({'success': True, 'message': message})
        else:
            logger.warning("Test SMS failed: %s", message)
            return jsonify({'success': False, 'error': message}), 502

    except Exception as e:
        logger.error("Unexpected error sending test SMS: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@notifications_bp.route('/test-snmp', methods=['POST'])
@require_auth
@require_permission('system.configure')
def test_snmp():
    """Send a test SNMP trap using the current SNMP configuration."""
    try:
        settings = _get_or_create_settings()

        if not settings.snmp_targets:
            return jsonify({'success': False, 'error': 'No SNMP targets configured'}), 400

        try:
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
        except Exception:
            return jsonify({'success': False, 'error': 'pysnmp is not installed; install it to use SNMP traps'}), 400

        community = (settings.snmp_community or 'public').strip() or 'public'
        targets = [t.strip() for t in (settings.snmp_targets or []) if t and t.strip()]
        payload = "EAS Station SNMP trap test"
        errors = []

        for target in targets:
            host, _, port_str = target.partition(':')
            try:
                port = int(port_str) if port_str else 162
            except ValueError:
                port = 162

            try:
                for error_indication, _error_status, _error_index, _var_binds in sendNotification(
                    SnmpEngine(),
                    CommunityData(community, mpModel=1),
                    UdpTransportTarget((host, port), timeout=3, retries=1),
                    ContextData(),
                    'trap',
                    NotificationType(ObjectIdentity('1.3.6.1.4.1.32473.1.0.1')).addVarBinds(
                        ObjectType(ObjectIdentity('1.3.6.1.4.1.32473.1.1.1.0'), payload)
                    ),
                ):
                    if error_indication:
                        errors.append(f"{target}: {error_indication}")
            except Exception as exc:
                errors.append(f"{target}: {exc}")

        if errors:
            msg = '; '.join(errors)
            logger.warning("Test SNMP trap(s) failed: %s", msg)
            return jsonify({'success': False, 'error': msg}), 502

        logger.info("Test SNMP trap sent to %d target(s)", len(targets))
        return jsonify({'success': True, 'message': f"Test trap sent to {len(targets)} target(s)"})

    except Exception as e:
        logger.error("Unexpected error sending test SNMP trap: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@notifications_bp.route('/postal-status', methods=['GET'])
@require_auth
@require_permission('system.configure')
def postal_status():
    """Check whether a local Postfix SMTP server is reachable on localhost:25.
    Route name kept for backwards compatibility."""
    smtp_host = '127.0.0.1'
    smtp_port = 25

    running = False
    try:
        with socket.create_connection((smtp_host, smtp_port), timeout=2):
            running = True
    except OSError:
        pass

    return jsonify({
        'running': running,
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
    })


@notifications_bp.route('/status', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def notification_status():
    """Get current notification settings as JSON."""
    try:
        settings = NotificationSettings.query.first()
        if not settings:
            return jsonify({'success': False, 'error': 'Notification settings not configured'}), 404
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching notification status: {str(e)}")
        return jsonify({'success': False, 'error': 'Database error'}), 500
