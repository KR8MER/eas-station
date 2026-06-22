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

"""Application settings admin routes."""

import logging
from types import SimpleNamespace

from flask import Blueprint, render_template, request, jsonify, flash
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import ApplicationSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger

logger = logging.getLogger(__name__)

application_settings_bp = Blueprint('application_settings', __name__, url_prefix='/admin/application')

VALID_LOG_LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}


def _get_or_create_settings() -> ApplicationSettings:
    """Get application settings, creating defaults if none exist."""
    settings = ApplicationSettings.query.first()
    if not settings:
        settings = ApplicationSettings(
            id=1,
            log_level='INFO',
            log_file='logs/eas_station.log',
            upload_folder='/opt/eas-station/uploads',
            backup_dir='/var/backups/eas-station',
            dashboard_headline='',
            dashboard_subtitle='',
            password_min_length=8,
            password_require_uppercase=False,
            password_require_lowercase=False,
            password_require_digits=False,
            password_require_special=False,
            password_expiration_days=0,
        )
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default application settings")
    return settings


def _fallback_application_settings():
    """Return in-memory defaults when the database is unavailable."""
    return SimpleNamespace(
        log_level='INFO',
        log_file='logs/eas_station.log',
        upload_folder='/opt/eas-station/uploads',
        backup_dir='/var/backups/eas-station',
        dashboard_headline='',
        dashboard_subtitle='',
        password_min_length=8,
        password_require_uppercase=False,
        password_require_lowercase=False,
        password_require_digits=False,
        password_require_special=False,
        password_expiration_days=0,
    )


@application_settings_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def application_settings_page():
    """Display application settings page."""
    try:
        settings = _get_or_create_settings()
    except SQLAlchemyError as e:
        logger.error(f"Database error loading application settings: {str(e)}")
        try:
            db.session.rollback()
        except Exception:
            pass
        flash(
            'Database error loading application settings. '
            'Settings are shown with defaults — run database migrations to restore full functionality.',
            'danger',
        )
        settings = _fallback_application_settings()
    return render_template('admin/application_settings.html', settings=settings,
                           valid_log_levels=sorted(VALID_LOG_LEVELS))


@application_settings_bp.route('/update', methods=['POST'])
@require_auth
@require_permission('system.configure')
def update_application_settings():
    """Update application settings."""
    try:
        settings = ApplicationSettings.query.first()
        if not settings:
            settings = ApplicationSettings(id=1)
            db.session.add(settings)

        log_level = request.form.get('log_level', 'INFO').strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            return jsonify({'success': False,
                            'error': f'Invalid log level. Must be one of: {", ".join(sorted(VALID_LOG_LEVELS))}'}), 400
        settings.log_level = log_level

        log_file = request.form.get('log_file', '').strip()
        if not log_file:
            return jsonify({'success': False, 'error': 'Log file path is required'}), 400
        settings.log_file = log_file

        upload_folder = request.form.get('upload_folder', '').strip()
        if not upload_folder:
            return jsonify({'success': False, 'error': 'Upload folder path is required'}), 400
        settings.upload_folder = upload_folder

        backup_dir = request.form.get('backup_dir', '').strip()
        if not backup_dir:
            return jsonify({'success': False, 'error': 'Backup directory path is required'}), 400
        # Create the directory now (and confirm we can write to it) so the
        # operator gets immediate feedback instead of a failure on the next
        # backup attempt.  We don't fail the save if creation fails — the
        # path may live on a mount that comes up later (USB, NFS) — but we
        # surface the warning in the response.
        from pathlib import Path
        import os
        backup_dir_warning = None
        try:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            if not os.access(backup_dir, os.W_OK):
                backup_dir_warning = (
                    f"Saved, but {backup_dir} is not writable by the service "
                    "user. Backups will fail until permissions are fixed."
                )
        except OSError as exc:
            backup_dir_warning = (
                f"Saved, but could not create {backup_dir}: {exc}. "
                "Backups will fail until the path exists and is writable."
            )
        settings.backup_dir = backup_dir

        # Dashboard branding (optional, may be blank to use defaults)
        dashboard_headline = request.form.get('dashboard_headline', '').strip()
        if len(dashboard_headline) > 120:
            return jsonify({'success': False,
                            'error': 'Dashboard headline must be 120 characters or fewer'}), 400
        settings.dashboard_headline = dashboard_headline

        dashboard_subtitle = request.form.get('dashboard_subtitle', '').strip()
        if len(dashboard_subtitle) > 160:
            return jsonify({'success': False,
                            'error': 'Dashboard subtitle must be 160 characters or fewer'}), 400
        settings.dashboard_subtitle = dashboard_subtitle

        # Password policy
        try:
            min_length = int(request.form.get('password_min_length', 8))
            if min_length < 1 or min_length > 128:
                return jsonify({'success': False, 'error': 'Minimum password length must be between 1 and 128'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid minimum password length'}), 400
        settings.password_min_length = min_length
        settings.password_require_uppercase = request.form.get('password_require_uppercase') == 'on'
        settings.password_require_lowercase = request.form.get('password_require_lowercase') == 'on'
        settings.password_require_digits = request.form.get('password_require_digits') == 'on'
        settings.password_require_special = request.form.get('password_require_special') == 'on'
        try:
            expiry_days = int(request.form.get('password_expiration_days', 0))
            if expiry_days < 0 or expiry_days > 3650:
                return jsonify({'success': False,
                                'error': 'Password expiration days must be between 0 and 3650 (0 = disabled)'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid password expiration days value'}), 400
        settings.password_expiration_days = expiry_days

        db.session.commit()

        # Apply log level change immediately to the running process
        import logging as _logging
        numeric_level = getattr(_logging, settings.log_level, _logging.INFO)
        _logging.getLogger().setLevel(numeric_level)
        # Propagate backup_dir to the live Flask config so the next backup uses
        # the new path without requiring a restart.
        from flask import current_app
        current_app.config['BACKUP_DIR'] = settings.backup_dir
        logger.info(
            "Updated application settings: log_level=%s, log_file=%s, upload_folder=%s, backup_dir=%s, "
            "password_min_length=%d, require_upper=%s, require_lower=%s, require_digits=%s, require_special=%s",
            settings.log_level, settings.log_file, settings.upload_folder, settings.backup_dir,
            settings.password_min_length, settings.password_require_uppercase,
            settings.password_require_lowercase, settings.password_require_digits,
            settings.password_require_special,
        )

        # Audit: record who changed application settings, when, and from where.
        AuditLogger.log_config_change(
            resource_type='application_settings',
            resource_id=str(settings.id) if settings.id is not None else None,
            details={
                'log_level': settings.log_level,
                'log_file': settings.log_file,
                'upload_folder': settings.upload_folder,
                'backup_dir': settings.backup_dir,
                'password_min_length': settings.password_min_length,
                'password_require_uppercase': settings.password_require_uppercase,
                'password_require_lowercase': settings.password_require_lowercase,
                'password_require_digits': settings.password_require_digits,
                'password_require_special': settings.password_require_special,
                'password_expiration_days': settings.password_expiration_days,
            },
        )

        message = 'Application settings updated successfully. Log level applied immediately.'
        if backup_dir_warning:
            message = f"{message} {backup_dir_warning}"
            logger.warning("backup_dir save warning: %s", backup_dir_warning)
        return jsonify({
            'success': True,
            'message': message,
            'warning': backup_dir_warning,
            'settings': settings.to_dict(),
        })

    except SQLAlchemyError as e:
        logger.error(f"Database error updating application settings: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving application settings'}), 500


@application_settings_bp.route('/retention', methods=['GET', 'PUT'])
@require_auth
@require_permission('system.configure')
def retention_settings():
    """Get or update automated data-retention policies (JSON API).

    Day values of 0 mean "keep forever" for that artifact class.  The
    received-alert setting only strips the raw audio blob — alert rows are
    compliance history and are never deleted.
    """
    from app_core.retention import get_retention_settings, update_retention_settings

    try:
        if request.method == 'GET':
            settings = get_retention_settings()
            return jsonify({'success': True, 'settings': settings.to_dict()})

        payload = request.get_json(silent=True) or {}
        try:
            updated = update_retention_settings(payload)
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

        logger.info("Retention settings updated: %s", updated)
        AuditLogger.log_config_change(
            resource_type='retention_settings',
            details={'settings': updated},
        )
        return jsonify({
            'success': True,
            'message': 'Retention settings updated. Changes apply on the next sweep (within 6 hours).',
            'settings': updated,
        })
    except SQLAlchemyError as e:
        logger.error(f"Database error processing retention settings: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving retention settings'}), 500


@application_settings_bp.route('/status', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def application_status():
    """Get current application settings as JSON."""
    try:
        settings = ApplicationSettings.query.first()
        if not settings:
            return jsonify({'success': False, 'error': 'Application settings not configured'}), 404
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching application status: {str(e)}")
        return jsonify({'success': False, 'error': 'Database error'}), 500
