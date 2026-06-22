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

"""Admin routes for managing local authority EAS access."""

import re
from typing import List

from flask import Blueprint, g, jsonify, render_template, request

from app_core.extensions import db
from app_core.models import AdminUser, LocalAuthority, SystemLog
from app_core.auth.roles import (
    Role,
    require_permission,
)
from app_utils.eas import PRIMARY_ORIGINATORS


local_authorities_bp = Blueprint("local_authorities", __name__)


def register_local_authority_routes(app, logger):
    """Register local authority management routes on the Flask app."""
    app.register_blueprint(local_authorities_bp)
    logger.info("Local authority management routes registered")


@local_authorities_bp.route('/admin/local-authorities')
@require_permission('system.manage_users')
def local_authorities_page():
    """Render the local authorities management page."""
    return render_template('admin/local_authorities.html')


@local_authorities_bp.route('/admin/local-authorities/list')
@require_permission('system.manage_users')
def list_authorities_json():
    """JSON list of all local authorities."""
    return _list_authorities()


@local_authorities_bp.route('/admin/local-authorities', methods=['POST'])
@require_permission('system.manage_users')
def create_authority():
    """Create a new local authority."""
    payload = request.get_json(silent=True) or {}

    user_id = payload.get('user_id')
    name = (payload.get('name') or '').strip()
    station_id = (payload.get('station_id') or '').strip().upper()
    originator = (payload.get('originator') or 'CIV').strip().upper()

    if not user_id:
        return jsonify({'error': 'A user account must be selected.'}), 400
    if not name:
        return jsonify({'error': 'Authority name is required.'}), 400
    if not station_id or len(station_id) > 8:
        return jsonify({'error': 'Station identifier must be 1-8 characters.'}), 400
    if not re.match(r'^[A-Z0-9/]{1,8}$', station_id):
        return jsonify({'error': 'Station identifier may only contain letters, digits, and "/".'}), 400
    if originator not in PRIMARY_ORIGINATORS:
        return jsonify({'error': f'Originator must be one of: {", ".join(PRIMARY_ORIGINATORS)}.'}), 400

    user = AdminUser.query.get(user_id)
    if not user:
        return jsonify({'error': 'Selected user account does not exist.'}), 404

    existing = LocalAuthority.query.filter_by(user_id=user_id).first()
    if existing:
        return jsonify({'error': f'User "{user.username}" already has a local authority assignment.'}), 400

    fips_codes = _parse_code_list(payload.get('authorized_fips_codes', []))
    event_codes = _parse_code_list(payload.get('authorized_event_codes', []))

    # Assign the local_authority role if available
    la_role = Role.query.filter_by(name='local_authority').first()
    if la_role and user.role_id != la_role.id:
        user.role_id = la_role.id

    authority = LocalAuthority(
        user_id=user.id,
        name=name,
        short_name=(payload.get('short_name') or '').strip() or None,
        station_id=station_id.ljust(8)[:8],
        originator=originator[:3],
        authorized_fips_codes=fips_codes,
        authorized_event_codes=event_codes,
        is_active=True,
        created_by=getattr(g.current_user, 'username', None),
    )

    db.session.add(authority)
    db.session.add(SystemLog(
        level='INFO',
        message=f'Local authority registered: {name} ({station_id})',
        module='local_authority',
        details={
            'authority_name': name,
            'station_id': station_id,
            'originator': originator,
            'user_id': user.id,
            'username': user.username,
            'created_by': getattr(g.current_user, 'username', None),
        },
    ))
    db.session.commit()

    return jsonify({'message': 'Local authority registered.', 'authority': authority.to_dict()}), 201


@local_authorities_bp.route('/admin/local-authorities/<int:authority_id>', methods=['GET'])
@require_permission('system.manage_users')
def get_authority(authority_id: int):
    """Get a single local authority by ID."""
    authority = LocalAuthority.query.get_or_404(authority_id)
    return jsonify({'authority': authority.to_dict()})


@local_authorities_bp.route('/admin/local-authorities/<int:authority_id>', methods=['PATCH'])
@require_permission('system.manage_users')
def update_authority(authority_id: int):
    """Update an existing local authority."""
    authority = LocalAuthority.query.get_or_404(authority_id)
    payload = request.get_json(silent=True) or {}

    if 'name' in payload:
        name = (payload['name'] or '').strip()
        if not name:
            return jsonify({'error': 'Authority name cannot be empty.'}), 400
        authority.name = name

    if 'short_name' in payload:
        authority.short_name = (payload['short_name'] or '').strip() or None

    if 'station_id' in payload:
        station_id = (payload['station_id'] or '').strip().upper()
        if not station_id or len(station_id) > 8:
            return jsonify({'error': 'Station identifier must be 1-8 characters.'}), 400
        if not re.match(r'^[A-Z0-9/]{1,8}$', station_id):
            return jsonify({'error': 'Station identifier may only contain letters, digits, and "/".'}), 400
        authority.station_id = station_id.ljust(8)[:8]

    if 'originator' in payload:
        originator = (payload['originator'] or '').strip().upper()
        if originator not in PRIMARY_ORIGINATORS:
            return jsonify({'error': f'Originator must be one of: {", ".join(PRIMARY_ORIGINATORS)}.'}), 400
        authority.originator = originator[:3]

    if 'authorized_fips_codes' in payload:
        authority.authorized_fips_codes = _parse_code_list(payload['authorized_fips_codes'])

    if 'authorized_event_codes' in payload:
        authority.authorized_event_codes = _parse_code_list(payload['authorized_event_codes'])

    if 'is_active' in payload:
        authority.is_active = bool(payload['is_active'])

    db.session.add(SystemLog(
        level='INFO',
        message=f'Local authority updated: {authority.name}',
        module='local_authority',
        details={
            'authority_id': authority.id,
            'updated_by': getattr(g.current_user, 'username', None),
        },
    ))
    db.session.commit()

    return jsonify({'message': 'Authority updated.', 'authority': authority.to_dict()})


@local_authorities_bp.route('/admin/local-authorities/<int:authority_id>', methods=['DELETE'])
@require_permission('system.manage_users')
def delete_authority(authority_id: int):
    """Remove a local authority assignment."""
    authority = LocalAuthority.query.get_or_404(authority_id)
    name = authority.name
    username = authority.user.username if authority.user else 'unknown'

    db.session.delete(authority)
    db.session.add(SystemLog(
        level='WARNING',
        message=f'Local authority removed: {name}',
        module='local_authority',
        details={
            'authority_name': name,
            'username': username,
            'deleted_by': getattr(g.current_user, 'username', None),
        },
    ))
    db.session.commit()

    return jsonify({'message': 'Authority removed.'})


@local_authorities_bp.route('/admin/local-authorities/available-users')
@require_permission('system.manage_users')
def available_users():
    """List user accounts that do not yet have a local authority assignment."""
    assigned_user_ids = {
        la.user_id for la in db.session.query(LocalAuthority.user_id).all()
    }
    users = AdminUser.query.filter(AdminUser.is_active.is_(True)).order_by(AdminUser.username).all()
    available = [
        u.to_safe_dict() for u in users if u.id not in assigned_user_ids
    ]
    return jsonify({'users': available})


def _list_authorities():
    """JSON list of all local authorities."""
    authorities = (
        LocalAuthority.query
        .order_by(LocalAuthority.name)
        .all()
    )
    return jsonify({'authorities': [a.to_dict() for a in authorities]})


def _parse_code_list(value) -> List[str]:
    """Parse a list of codes from various input formats."""
    if isinstance(value, str):
        codes = re.split(r'[,;\s]+', value)
    elif isinstance(value, (list, tuple)):
        codes = []
        for item in value:
            if item is not None:
                codes.extend(re.split(r'[,;\s]+', str(item)))
    else:
        return []
    return [c.strip().upper() for c in codes if c.strip()]
