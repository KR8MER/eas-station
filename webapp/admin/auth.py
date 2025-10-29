"""Authentication helpers for the admin interface."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

from flask import flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import AdminUser, SystemLog
from app_utils import utc_now


def register_auth_routes(app, logger):
    """Register login and logout handlers."""

    def _is_safe_redirect_target(target: Optional[str]) -> bool:
        if not target:
            return False
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
        return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        next_param = request.args.get('next') if request.method == 'GET' else request.form.get('next')
        if g.current_user:
            target = next_param if _is_safe_redirect_target(next_param) else url_for('admin')
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

                    target = next_param if _is_safe_redirect_target(next_param) else url_for('admin')
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
                error = 'Invalid username or password.'

        show_setup = AdminUser.query.count() == 0

        return render_template(
            'login.html',
            error=error,
            next=next_param or url_for('admin'),
            show_setup=show_setup,
        )

    @app.route('/logout')
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
        session.pop('user_id', None)
        flash('You have been signed out.')
        return redirect(url_for('login'))


__all__ = ['register_auth_routes']
