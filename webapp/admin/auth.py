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
from app_core.auth.session_tracking import start_session, end_session
from app_core.auth.audit import AuditLogger, AuditAction
from app_core.auth.input_validation import InputValidator
from app_core.auth.rate_limiter import get_rate_limiter
from app_core.auth.security_logger import log_malicious_login_attempt, log_failed_login_attempt, log_rate_limit_exceeded
from app_core.auth.ip_filter import IPFilter, FloodProtection, AutoBanManager


def _check_password_expiry(user: 'AdminUser') -> tuple:
    """
    Return (is_expired, days_remaining) based on ApplicationSettings policy.

    Returns (False, None) when expiration is disabled or password_changed_at is unset.
    """
    from datetime import timezone, timedelta
    from app_core.models import ApplicationSettings
    try:
        settings = ApplicationSettings.query.first()
        expiry_days = (settings.password_expiration_days or 0) if settings else 0
        if not expiry_days or not user.password_changed_at:
            return False, None
        changed = user.password_changed_at
        if changed.tzinfo is None:
            changed = changed.replace(tzinfo=timezone.utc)
        from datetime import datetime
        deadline = changed + timedelta(days=expiry_days)
        now = datetime.now(timezone.utc)
        days_remaining = (deadline - now).days
        return days_remaining < 0, max(days_remaining, 0)
    except Exception as exc:  # pragma: no cover
        current_app.logger.warning("Password expiry check failed: %s", exc)
        return False, None


def _create_admin_session(user_id: int) -> None:
    """Record a new administrator login session and link it to the cookie."""
    start_session(user_id)


def _end_admin_session(user_id: int, reason: str = 'logout') -> None:
    """Mark this login's administrator session as ended."""
    end_session(user_id, reason=reason)


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
        # Check IP filter first
        is_allowed, block_reason = IPFilter.is_ip_allowed(request.remote_addr)
        if not is_allowed:
            error = 'Access denied. Your IP address has been blocked.'
            db.session.add(SystemLog(
                level='WARNING',
                message='Login attempt from blocked IP',
                module='auth',
                details={
                    'remote_addr': request.remote_addr,
                    'block_reason': block_reason,
                },
            ))
            db.session.commit()
        else:
            # Check rate limiting
            rate_limiter = get_rate_limiter()
            
            # Check for flooding
            is_flooding, flood_attempts = FloodProtection.check_flood(request.remote_addr, rate_limiter)
            if is_flooding:
                # Auto-ban for flooding
                FloodProtection.auto_ban_flooder(request.remote_addr)
                error = 'Access denied. Too many rapid login attempts.'
                db.session.add(SystemLog(
                    level='CRITICAL',
                    message='IP auto-banned for flooding',
                    module='auth',
                    details={
                        'remote_addr': request.remote_addr,
                        'attempts_per_minute': flood_attempts,
                    },
                ))
                db.session.commit()
            else:
                is_locked, seconds_remaining = rate_limiter.is_locked_out(request.remote_addr)
                
                if is_locked:
                    minutes_remaining = (seconds_remaining + 59) // 60  # Round up to nearest minute
                    error = f'Too many failed login attempts. Please try again in {minutes_remaining} minute(s).'
                    
                    # Log to security log for fail2ban
                    log_rate_limit_exceeded(request.remote_addr)
                    
                    db.session.add(SystemLog(
                        level='WARNING',
                        message='Login attempt while locked out',
                        module='auth',
                        details={
                            'remote_addr': request.remote_addr,
                            'seconds_remaining': seconds_remaining,
                        },
                    ))
                    db.session.commit()
                else:
                    username = (request.form.get('username') or '').strip()
                    password = request.form.get('password') or ''

                    if not username or not password:
                        error = 'Username and password are required.'
                    else:
                        # Validate inputs for security issues
                        username_valid, username_error = InputValidator.validate_username(username)
                        password_valid, password_error = InputValidator.validate_password(password)
                        
                        if not username_valid:
                            # Log malicious attempt with sanitized username
                            sanitized_username = InputValidator.sanitize_for_logging(username)
                            
                            # Log to security log for fail2ban (immediate ban)
                            log_malicious_login_attempt(request.remote_addr, sanitized_username, 'malicious_input')
                            
                            # Auto-ban for malicious input
                            IPFilter.add_to_blocklist(
                                ip_address=request.remote_addr,
                                reason='auto_malicious',
                                description='Automatically banned for SQL/command injection attempt',
                                expires_in_hours=24
                            )
                            
                            db.session.add(SystemLog(
                                level='CRITICAL',
                                message='Malicious login attempt detected - IP auto-banned',
                                module='auth',
                                details={
                                    'username': sanitized_username,
                                    'remote_addr': request.remote_addr,
                                    'reason': 'invalid_input_format',
                                },
                            ))
                            db.session.commit()
                            AuditLogger.log_login_failure(sanitized_username, 'malicious_input')
                            rate_limiter.record_failed_attempt(request.remote_addr)
                            error = 'Invalid username or password.'
                        elif not password_valid:
                            rate_limiter.record_failed_attempt(request.remote_addr)
                            error = 'Invalid username or password.'
                        else:
                            user = AdminUser.query.filter(
                                func.lower(AdminUser.username) == username.lower()
                            ).first()
                            if user and user.is_active and user.check_password(password):
                                # Clear rate limiting on successful login
                                rate_limiter.clear_attempts(request.remote_addr)
                                
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
                                _create_admin_session(user.id)
                                db.session.commit()

                                AuditLogger.log_login_success(user.id, user.username)

                                pw_expired, pw_days = _check_password_expiry(user)
                                if pw_expired:
                                    session['pw_expired'] = True
                                elif pw_days is not None and pw_days <= 14:
                                    session['pw_expires_in_days'] = pw_days

                                target = next_param if _is_safe_redirect_target(next_param) else url_for('dashboard.admin')
                                return redirect(target)

                            # Failed login - record attempt and sanitize username before logging
                            rate_limiter.record_failed_attempt(request.remote_addr)
                            
                            # Check if should auto-ban
                            AutoBanManager.check_and_ban(request.remote_addr, rate_limiter)
                            
                            sanitized_username = InputValidator.sanitize_for_logging(username)
                            
                            # Log to security log for fail2ban
                            log_failed_login_attempt(request.remote_addr, sanitized_username)
                            
                            db.session.add(SystemLog(
                                level='WARNING',
                                message='Failed administrator login attempt',
                                module='auth',
                                details={
                                    'username': sanitized_username,
                                    'remote_addr': request.remote_addr,
                                },
                            ))
                            db.session.commit()

                            AuditLogger.log_login_failure(sanitized_username, 'invalid_credentials')
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
        _end_admin_session(user.id, reason='logout')
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
                _create_admin_session(user.id)
                db.session.commit()

                # Determine if backup code was used
                method = 'backup_code' if len(code) > 6 else 'totp'
                AuditLogger.log_login_success(user.id, user.username)
                AuditLogger.log_mfa_verify_success(user.id, user.username, method)

                pw_expired, pw_days = _check_password_expiry(user)
                if pw_expired:
                    session['pw_expired'] = True
                elif pw_days is not None and pw_days <= 14:
                    session['pw_expires_in_days'] = pw_days

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
