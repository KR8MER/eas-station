"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Authentication helpers for the admin interface."""

from flask import Blueprint

import secrets
from typing import Optional
from urllib.parse import urljoin, urlparse

from flask import current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import AdminUser, SystemLog
from app_utils import utc_now
from app_core.auth.mfa import MFASession, verify_user_mfa
from app_core.auth.audit import AuditLogger, AuditAction


# Create Blueprint for auth routes
auth_bp = Blueprint("auth", __name__)

def register_auth_routes(app, logger):
    """Register routes."""
    
    # Register the blueprint with the app
    app.register_blueprint(auth_bp)
    logger.info("Auth routes registered")


# Helper functions

def _is_safe_redirect_target(target: Optional[str]) -> bool:
    """Check if a redirect target is safe (prevents open redirects)."""
    if not target:
        return False
    
    # Parse the URL
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    
    # Check that the scheme and netloc match
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


# Route definitions

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    next_param = request.args.get('next') if request.method == 'GET' else request.form.get('next')
    if g.current_user:
        target = next_param if _is_safe_redirect_target(next_param) else url_for('dashboard.admin')
        return redirect(target)

    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if not username or not password:
            error = 'Username and password are required.'
        else:
            user = AdminUser.query.filter(
                func.lower(AdminUser.username) == username.lower()
            ).first()
            if user and user.is_active and user.check_password(password):
                csrf_key = current_app.config.get('CSRF_SESSION_KEY', '_csrf_token')

                # Check if MFA is enabled for this user
                if user.mfa_enabled:
                    # Partial authentication - set pending MFA state
                    session.clear()
                    session[csrf_key] = secrets.token_urlsafe(32)
                    MFASession.set_pending(session, user.id)

                    # Redirect to MFA verification page
                    return redirect(url_for('auth.mfa_verify', next=next_param))

                # No MFA - complete login
                session.clear()
                session[csrf_key] = secrets.token_urlsafe(32)
                session['user_id'] = user.id
                session.permanent = True
                user.last_login_at = utc_now()
                log_entry = SystemLog(
                    level='INFO',
                    message='Administrator logged in',
                    module='auth',
                    details={
                        'username': user.username,
                        'remote_addr': request.remote_addr,
                    },
                )
                db.session.add(user)
                db.session.add(log_entry)
                db.session.commit()

                AuditLogger.log_login_success(user.id, user.username)

                target = next_param if _is_safe_redirect_target(next_param) else url_for('dashboard.admin')
                return redirect(target)

            db.session.add(SystemLog(
                level='WARNING',
                message='Failed administrator login attempt',
                module='auth',
                details={
                    'username': username,
                    'remote_addr': request.remote_addr,
                },
            ))
            db.session.commit()

            AuditLogger.log_login_failure(username, 'invalid_credentials')
            error = 'Invalid username or password.'

    show_setup = AdminUser.query.count() == 0

    return render_template(
        'login.html',
        error=error,
        next=next_param or url_for('dashboard.admin'),
        show_setup=show_setup,
    )

@auth_bp.route('/logout')
def logout():
    user = g.current_user
    if user:
        db.session.add(SystemLog(
            level='INFO',
            message='Administrator logged out',
            module='auth',
            details={
                'username': user.username,
                'remote_addr': request.remote_addr,
            },
        ))
        db.session.commit()

        AuditLogger.log_logout(user.id, user.username)

    csrf_key = current_app.config.get('CSRF_SESSION_KEY', '_csrf_token')
    session.clear()
    session[csrf_key] = secrets.token_urlsafe(32)
    flash('You have been signed out.')
    return redirect(url_for('auth.login'))

@auth_bp.route('/mfa/verify', methods=['GET', 'POST'])
def mfa_verify():
    """MFA verification page after password authentication."""
    next_param = request.args.get('next') if request.method == 'GET' else request.form.get('next')

    # Check if user is pending MFA verification
    pending_user_id = MFASession.get_pending(session)
    if not pending_user_id:
        flash('Session expired. Please log in again.')
        return redirect(url_for('auth.login'))

    user = AdminUser.query.get(pending_user_id)
    if not user or not user.is_active or not user.mfa_enabled:
        MFASession.clear_pending(session)
        return redirect(url_for('auth.login'))

    error = None
    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()

        if not code:
            error = 'Verification code is required.'
        else:
            # Verify MFA code (TOTP or backup code)
            if verify_user_mfa(user, code):
                # MFA successful - complete login
                MFASession.complete(session, user.id)
                user.last_login_at = utc_now()

                log_entry = SystemLog(
                    level='INFO',
                    message='Administrator logged in (with MFA)',
                    module='auth',
                    details={
                        'username': user.username,
                        'remote_addr': request.remote_addr,
                    },
                )
                db.session.add(user)
                db.session.add(log_entry)
                db.session.commit()

                # Determine if backup code was used
                method = 'backup_code' if len(code) > 6 else 'totp'
                AuditLogger.log_login_success(user.id, user.username)
                AuditLogger.log_mfa_verify_success(user.id, user.username, method)

                target = next_param if _is_safe_redirect_target(next_param) else url_for('dashboard.admin')
                return redirect(target)
            else:
                AuditLogger.log_mfa_verify_failure(user.id, user.username)
                error = 'Invalid verification code.'

    return render_template(
        'mfa_verify.html',
        error=error,
        next=next_param or url_for('dashboard.admin'),
        username=user.username
    )


__all__ = ['register_auth_routes']
