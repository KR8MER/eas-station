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

"""Admin dashboard and user management routes."""

from flask import Blueprint, current_app

import re

from flask import g, jsonify, render_template, request
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import AdminSession, AdminUser, ApplicationSettings, Boundary, CAPAlert, SystemLog
from app_core.auth.roles import Role
from app_core.auth.roles import require_permission
from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import (
    get_extended_same_lookup,
    get_extended_state_county_tree,
)

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,64}$')


def _load_password_policy() -> dict:
    """Return the active password policy from ApplicationSettings."""
    settings = ApplicationSettings.query.first()
    if settings:
        return {
            'min_length': settings.password_min_length or 8,
            'require_uppercase': bool(settings.password_require_uppercase),
            'require_lowercase': bool(settings.password_require_lowercase),
            'require_digits': bool(settings.password_require_digits),
            'require_special': bool(settings.password_require_special),
        }
    return {'min_length': 8, 'require_uppercase': False, 'require_lowercase': False,
            'require_digits': False, 'require_special': False}


# Create Blueprint for dashboard routes
dashboard_bp = Blueprint("dashboard", __name__)

def register_dashboard_routes(app, logger, eas_config):
    """Register routes."""
    
    # Store eas_config for use by routes
    dashboard_bp.eas_config = eas_config
    
    # Register the blueprint with the app
    app.register_blueprint(dashboard_bp)
    logger.info("Dashboard routes registered")


# Route definitions

@dashboard_bp.route('/admin')
def admin():
    """Admin interface -- now just a stats overview plus the first-time
    setup wizard.

    Used to also compute and pass a large amount of location/EAS context
    (location_settings, eas_event_codes, eas_fips_states, boundary_stats,
    recent EAS messages, etc.) for the tabbed interface that lived here.
    That interface has been fully extracted to its own registered pages
    (see the phase 1-5 admin/settings consolidation entries in
    docs/reference/CHANGELOG.md) -- none of that context is read by
    admin.html anymore, so it was dropped rather than computed and thrown
    away on every request.
    """

    def safe_db_operation(description: str, default, operation):
        try:
            return operation()
        except SQLAlchemyError as exc:  # pragma: no cover - defensive
            current_app.logger.warning('Failed to %s: %s', description, exc)
            try:
                db.session.rollback()
            except SQLAlchemyError:  # pragma: no cover - defensive fallback
                pass
            return default

    try:
        try:
            db.session.rollback()
        except SQLAlchemyError:  # pragma: no cover - defensive
            pass

        setup_mode = getattr(g, 'admin_setup_mode', None)
        if setup_mode is None:
            setup_mode = safe_db_operation(
                'determine administrator setup status',
                False,
                lambda: AdminUser.query.count() == 0,
            )

        total_boundaries = safe_db_operation(
            'count boundaries', 0, lambda: Boundary.query.count()
        )
        total_alerts = safe_db_operation(
            'count CAP alerts', 0, lambda: CAPAlert.query.count()
        )
        active_alerts = safe_db_operation(
            'count active CAP alerts', 0, lambda: get_active_alerts_query().count()
        )
        expired_alerts = safe_db_operation(
            'count expired CAP alerts', 0, lambda: get_expired_alerts_query().count()
        )

        return render_template(
            'admin.html',
            total_boundaries=total_boundaries,
            total_alerts=total_alerts,
            active_alerts=active_alerts,
            expired_alerts=expired_alerts,
            setup_mode=setup_mode,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass
        current_app.logger.error('Error rendering admin template: %s', exc)
        return "<h1>Admin Interface</h1><p>Admin panel loading...</p><p><a href='/'>← Back to Main</a></p>"


@dashboard_bp.route('/admin/user-accounts', methods=['GET'])
@require_permission('system.manage_users')
def user_accounts_page():
    """Render the administrator-accounts page.

    Deliberately a separate route from /admin/users below -- that one is a
    JSON-only API (GET returns a user list, POST creates), consumed by this
    page's own JS. The nav registry used to link "User Accounts" straight at
    /admin/users, which meant clicking it served a raw JSON blob instead of
    a page.
    """
    return render_template('admin/user_accounts.html')


@dashboard_bp.route('/admin/alert-management', methods=['GET'])
@require_permission('system.configure')
def alert_management_page():
    """Render the stored-alerts management page (edit/mark-expired/delete-expired)."""
    return render_template('admin/alert_management.html')


@dashboard_bp.route('/admin/data-management', methods=['GET'])
@require_permission('system.configure')
def data_management_page():
    """Render the boundary/zone-catalog data management page.

    Distinct from /admin/county_boundaries: that page manages NOAA
    county/zone *reference* lookup data (FIPS/SAME code resolution). This
    page manages general boundary polygons of any type (electric, fire,
    school districts, custom, ...) for map overlays and alert-intersection
    calculations, plus the separate NOAA zone .dbf catalog upload. Different
    data, different backend endpoints -- confirmed not a duplicate before
    extracting this from the Admin Dashboard's Data tab.
    """
    return render_template('admin/data_management.html')


@dashboard_bp.route('/admin/location-settings', methods=['GET'])
@require_permission('system.configure')
def location_settings_page():
    """Render the station location and alert-filtering (FIPS/zone) settings page.

    location_settings itself is available on every template via the global
    context processor (app_core/flask/context_processors.py); only the
    FIPS/zone reference data used by the county picker's JS is route-
    specific and needs to be passed explicitly here.
    """
    eas_state_tree = get_extended_state_county_tree()
    eas_lookup = get_extended_same_lookup()
    return render_template(
        'admin/location_settings.html',
        eas_fips_states=eas_state_tree,
        eas_fips_lookup=eas_lookup,
    )


@dashboard_bp.route('/admin/eas-encoder-settings', methods=['GET'])
@require_permission('system.configure')
def eas_encoder_settings_page():
    """Render the EAS/SAME encoder configuration page.

    Only EAS_EVENT_CODES is actually read by location-settings.js's EAS
    functions (initEasSettings/buildEasEventFilterUI/etc.) -- the current
    form values themselves are loaded client-side from GET
    /admin/eas_settings, not server-rendered. EAS_DEFAULTS/
    EAS_ORIGINATOR_DESCRIPTIONS/EAS_P_DIGIT_MEANINGS were computed and
    passed by the old /admin route but never actually read by any JS or
    template in the Broadcast tab -- confirmed dead before dropping them
    here rather than carrying the dead weight forward.
    """
    eas_event_options = [
        {'code': code, 'name': entry.get('name', code), 'product': entry.get('default_product', '')}
        for code, entry in EVENT_CODE_REGISTRY.items()
        if '?' not in code
    ]
    eas_event_options.sort(key=lambda item: item['code'])
    return render_template(
        'admin/eas_encoder_settings.html',
        eas_event_codes=eas_event_options,
    )


@dashboard_bp.route('/admin/users', methods=['GET', 'POST'])
@require_permission('system.manage_users')
def admin_users():
    if request.method == 'GET':
        users = AdminUser.query.order_by(AdminUser.username.asc()).all()
        return jsonify({'users': [user.to_safe_dict() for user in users]})

    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''

    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return jsonify({'error': 'Authentication required.'}), 401

    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400

    if not USERNAME_PATTERN.match(username):
        return jsonify({'error': 'Usernames must be 3-64 characters and may include letters, numbers, dots, underscores, and hyphens.'}), 400

    from app_core.auth.input_validation import InputValidator
    policy = _load_password_policy()
    valid, pw_error = InputValidator.validate_password_policy(password, **policy)
    if not valid:
        return jsonify({'error': pw_error}), 400

    existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
    if existing:
        return jsonify({'error': 'Username already exists.'}), 400

    # Ensure roles and permissions are initialized before creating first user
    if creating_first_user:
        from app_core.auth.roles import initialize_default_roles_and_permissions
        try:
            initialize_default_roles_and_permissions()
            db.session.flush()  # Flush to ensure roles are available
        except Exception as e:
            current_app.logger.warning(f"Error initializing roles (may already exist): {e}")

    # Get the admin role to assign to the new user
    admin_role = Role.query.filter_by(name='admin').first()
    if not admin_role:
        return jsonify({'error': 'Admin role not found. Database may not be properly initialized.'}), 500

    new_user = AdminUser(username=username)
    new_user.set_password(password)
    new_user.role_id = admin_role.id
    db.session.add(new_user)
    db.session.add(SystemLog(
        level='INFO',
        message='Administrator account created',
        module='auth',
        details={
            'username': new_user.username,
            'created_by': g.current_user.username if g.current_user else 'initial_setup',
        },
    ))
    db.session.commit()

    return jsonify({'message': 'User created successfully.', 'user': new_user.to_safe_dict()}), 201

@dashboard_bp.route('/admin/users/<int:user_id>', methods=['PATCH', 'DELETE'])
@require_permission('system.manage_users')
def admin_user_detail(user_id: int):
    user = AdminUser.query.get_or_404(user_id)

    if request.method == 'PATCH':
        payload = request.get_json(silent=True) or {}
        password = payload.get('password') or ''
        from app_core.auth.input_validation import InputValidator
        policy = _load_password_policy()
        valid, pw_error = InputValidator.validate_password_policy(password, **policy)
        if not valid:
            return jsonify({'error': pw_error}), 400

        user.set_password(password)
        db.session.add(user)
        db.session.add(SystemLog(
            level='INFO',
            message='Administrator password reset',
            module='auth',
            details={
                'username': user.username,
                'updated_by': g.current_user.username if g.current_user else None,
            },
        ))
        db.session.commit()
        return jsonify({'message': 'Password updated successfully.', 'user': user.to_safe_dict()})

    if user.id == getattr(g.current_user, 'id', None):
        return jsonify({'error': 'You cannot delete your own account while logged in.'}), 400

    active_users = AdminUser.query.filter(AdminUser.is_active.is_(True)).count()
    if user.is_active and active_users <= 1:
        return jsonify({'error': 'At least one active administrator account is required.'}), 400

    db.session.delete(user)
    db.session.add(SystemLog(
        level='WARNING',
        message='Administrator account deleted',
        module='auth',
        details={
            'username': user.username,
            'deleted_by': g.current_user.username if g.current_user else None,
        },
    ))
    db.session.commit()
    return jsonify({'message': 'User deleted successfully.'})

@dashboard_bp.route('/api/admin/sessions', methods=['GET'])
def api_admin_sessions():
    """List active and recent administrator sessions.

    Query params:
        active_only (bool, default true): if 'false', return last 100 sessions regardless of state.
    """
    # Reap idle sessions first so the list always reflects reality, even if no
    # user has triggered the inline heartbeat sweep recently.
    from app_core.auth.session_tracking import expire_stale_sessions
    expire_stale_sessions()

    active_only = request.args.get('active_only', 'true').lower() != 'false'
    if active_only:
        sessions = (
            AdminSession.query
            .filter_by(ended_at=None)
            .order_by(AdminSession.created_at.desc())
            .limit(100)
            .all()
        )
    else:
        sessions = (
            AdminSession.query
            .order_by(AdminSession.created_at.desc())
            .limit(100)
            .all()
        )
    return jsonify({'sessions': [s.to_dict() for s in sessions]})


@dashboard_bp.route('/api/admin/sessions/<int:session_id>', methods=['DELETE'])
@require_permission('system.manage_users')
def api_terminate_admin_session(session_id: int):
    """Terminate (force-end) an active administrator session."""
    sess = AdminSession.query.get_or_404(session_id)
    if sess.ended_at is not None:
        return jsonify({'error': 'Session is already ended.'}), 400
    sess.ended_at = func.now()
    sess.ended_reason = 'admin_terminated'
    db.session.add(SystemLog(
        level='WARNING',
        message='Administrator session terminated',
        module='auth',
        details={
            'terminated_user_id': sess.user_id,
            'terminated_by': g.current_user.username if g.current_user else None,
            'session_id': session_id,
        },
    ))
    db.session.commit()
    return jsonify({'message': 'Session terminated.', 'session': sess.to_dict()})


@dashboard_bp.route('/api/admin/sessions/terminate-bulk', methods=['POST'])
@require_permission('system.manage_users')
def api_terminate_admin_sessions_bulk():
    """Force-end many active sessions at once.

    JSON body ``{"scope": "others"|"all"}`` (default ``others``):
    * ``others`` - terminate every active session except the caller's own,
      so the admin clearing the backlog is not signed out.
    * ``all``    - terminate every active session, including the caller's.
    """
    data = request.get_json(silent=True) or {}
    scope = str(data.get('scope', 'others')).lower()
    if scope not in {'others', 'all'}:
        return jsonify({'error': "scope must be 'others' or 'all'."}), 400

    from app_core.auth.session_tracking import SESSION_ROW_KEY
    from flask import session as flask_session

    query = AdminSession.query.filter(AdminSession.ended_at.is_(None))
    current_session_id = flask_session.get(SESSION_ROW_KEY)
    if scope == 'others' and current_session_id is not None:
        query = query.filter(AdminSession.id != current_session_id)

    count = query.update(
        {AdminSession.ended_at: func.now(), AdminSession.ended_reason: 'admin_terminated'},
        synchronize_session=False,
    )
    db.session.add(SystemLog(
        level='WARNING',
        message='Administrator sessions terminated in bulk',
        module='auth',
        details={
            'scope': scope,
            'count': count,
            'terminated_by': g.current_user.username if g.current_user else None,
        },
    ))
    db.session.commit()
    return jsonify({'message': f'Terminated {count} session(s).', 'count': count})


@dashboard_bp.route('/admin/sessions')
def admin_sessions_page():
    """Active administrator session monitoring."""
    return render_template('admin/sessions.html')

@dashboard_bp.route('/admin/rbac')
def rbac_management():
    """RBAC management interface for roles, permissions, and user assignments"""
    return render_template('admin/rbac_management.html')

@dashboard_bp.route('/admin/audit-logs')
def audit_logs_page():
    """Audit logs are now part of the unified /logs hub.

    Redirects (302) to ``/logs?type=audit`` so existing bookmarks and
    inbound links continue to work after the consolidation.
    """
    from flask import redirect, url_for
    return redirect(url_for('logs', type='audit'), code=302)

@dashboard_bp.route('/admin/gpio/statistics')
def gpio_statistics_page():
    """GPIO activation statistics and analytics"""
    return render_template('admin/gpio_statistics.html')

@dashboard_bp.route('/admin/operations')
def admin_operations():
    """Admin operations dashboard for backup, upgrade, and database maintenance"""
    return render_template('admin/operations.html')

@dashboard_bp.route('/admin/intersections')
def admin_intersections():
    """Intersection management for alert-boundary calculations"""
    return render_template('admin/intersections.html')


__all__ = ['register_dashboard_routes']
