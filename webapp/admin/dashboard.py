"""Admin dashboard and user management routes."""

from __future__ import annotations

import re
from typing import Dict, List

from flask import g, jsonify, render_template, request
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import AdminUser, Boundary, CAPAlert, EASMessage, SystemLog
from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.location import get_location_settings
from app_utils.eas import (
    ORIGINATOR_DESCRIPTIONS,
    PRIMARY_ORIGINATORS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    P_DIGIT_MEANINGS,
    manual_default_same_codes,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,64}$')


def register_dashboard_routes(app, logger, eas_config):
    """Register admin UI pages and user management endpoints."""

    @app.route('/admin')
    def admin():
        """Admin interface"""
        try:
            setup_mode = getattr(g, 'admin_setup_mode', None)
            if setup_mode is None:
                setup_mode = AdminUser.query.count() == 0
            total_boundaries = Boundary.query.count()
            total_alerts = CAPAlert.query.count()
            active_alerts = get_active_alerts_query().count()
            expired_alerts = get_expired_alerts_query().count()

            boundary_stats = db.session.query(
                Boundary.type, func.count(Boundary.id).label('count')
            ).group_by(Boundary.type).all()

            location_settings = get_location_settings()
            manual_same_defaults = manual_default_same_codes()
            location_settings_view: Dict[str, List[str]] = dict(location_settings)
            location_settings_view.setdefault('same_codes', manual_same_defaults)

            eas_enabled = app.config.get('EAS_BROADCAST_ENABLED', False)
            total_eas_messages = EASMessage.query.count() if eas_enabled else 0
            recent_eas_messages = []
            if eas_enabled:
                recent_eas_messages = (
                    EASMessage.query.order_by(EASMessage.created_at.desc()).limit(10).all()
                )

            eas_event_options = [
                {'code': code, 'name': entry.get('name', code)}
                for code, entry in EVENT_CODE_REGISTRY.items()
                if '?' not in code
            ]
            eas_event_options.sort(key=lambda item: item['code'])

            eas_state_tree = get_us_state_county_tree()
            eas_lookup = get_same_lookup()
            originator_choices = [
                {
                    'code': code,
                    'description': ORIGINATOR_DESCRIPTIONS.get(code, ''),
                }
                for code in PRIMARY_ORIGINATORS
            ]

            return render_template(
                'admin.html',
                total_boundaries=total_boundaries,
                total_alerts=total_alerts,
                active_alerts=active_alerts,
                expired_alerts=expired_alerts,
                boundary_stats=boundary_stats,
                location_settings=location_settings_view,
                eas_enabled=eas_enabled,
                eas_total_messages=total_eas_messages,
                eas_recent_messages=recent_eas_messages,
                eas_web_subdir=app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
                eas_event_codes=eas_event_options,
                eas_originator=eas_config.get('originator', 'WXR'),
                eas_station_id=eas_config.get('station_id', 'EASNODES'),
                eas_attention_seconds=eas_config.get('attention_tone_seconds', 8),
                eas_sample_rate=eas_config.get('sample_rate', 44100),
                eas_tts_provider=(eas_config.get('tts_provider') or '').strip().lower(),
                eas_fips_states=eas_state_tree,
                eas_fips_lookup=eas_lookup,
                eas_originator_descriptions=ORIGINATOR_DESCRIPTIONS,
                eas_originator_choices=originator_choices,
                eas_header_fields=SAME_HEADER_FIELD_DESCRIPTIONS,
                eas_p_digit_meanings=P_DIGIT_MEANINGS,
                eas_default_same_codes=manual_same_defaults,
                setup_mode=setup_mode,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            try:
                db.session.rollback()
            except Exception:  # pragma: no cover - defensive fallback
                pass
            logger.error('Error rendering admin template: %s', exc)
            return "<h1>Admin Interface</h1><p>Admin panel loading...</p><p><a href='/'>← Back to Main</a></p>"

    @app.route('/admin/users', methods=['GET', 'POST'])
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

        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

        existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
        if existing:
            return jsonify({'error': 'Username already exists.'}), 400

        new_user = AdminUser(username=username)
        new_user.set_password(password)
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

    @app.route('/admin/users/<int:user_id>', methods=['PATCH', 'DELETE'])
    def admin_user_detail(user_id: int):
        user = AdminUser.query.get_or_404(user_id)

        if request.method == 'PATCH':
            payload = request.get_json(silent=True) or {}
            password = payload.get('password') or ''
            if len(password) < 8:
                return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

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


__all__ = ['register_dashboard_routes']
