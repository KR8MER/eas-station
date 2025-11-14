"""
Security-related routes for MFA, RBAC, and audit logs.

Provides:
- MFA enrollment and management endpoints
- Role and permission management
- Audit log viewing and export
- User security settings
"""

from flask import Blueprint, request, jsonify, session, send_file, current_app, Response
from io import BytesIO, StringIO
import csv
from datetime import timedelta, datetime

from app_core.extensions import db
from app_core.models import AdminUser
from app_utils import utc_now
from app_core.eas_storage import format_local_datetime
from app_utils.pdf_generator import generate_pdf_document
from app_core.auth.roles import (
    Role, Permission, require_permission, has_permission,
    initialize_default_roles_and_permissions
)
from app_core.auth.mfa import (
    MFAManager, enroll_user_mfa, disable_user_mfa, verify_user_mfa
)
from app_core.auth.audit import AuditLog, AuditLogger, AuditAction


security_bp = Blueprint('security', __name__, url_prefix='/security')


# ============================================================================
# MFA Management Endpoints
# ============================================================================

@security_bp.route('/mfa/status', methods=['GET'])
def mfa_status():
    """Get current user's MFA status."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    user = AdminUser.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({
        'mfa_enabled': user.mfa_enabled,
        'mfa_enrolled_at': user.mfa_enrolled_at.isoformat() if user.mfa_enrolled_at else None,
    })


@security_bp.route('/mfa/enroll/start', methods=['POST'])
def mfa_enroll_start():
    """Start MFA enrollment by generating a secret and QR code."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    user = AdminUser.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if user.mfa_enabled:
        return jsonify({'error': 'MFA already enabled'}), 400

    try:
        # Generate new secret
        secret = MFAManager.generate_secret()
        user.mfa_secret = secret
        db.session.commit()

        # Generate provisioning URI and QR code
        provisioning_uri = MFAManager.generate_provisioning_uri(secret, user.username)

        # Store QR code data in session temporarily
        session['mfa_enrollment_pending'] = True

        return jsonify({
            'secret': secret,
            'provisioning_uri': provisioning_uri,
            'message': 'Scan the QR code with your authenticator app, then verify with a code'
        })

    except ImportError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.exception("MFA enrollment start failed")
        return jsonify({'error': 'Failed to start MFA enrollment'}), 500


@security_bp.route('/mfa/enroll/qr', methods=['GET'])
def mfa_enroll_qr():
    """Get QR code image for MFA enrollment."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    if not session.get('mfa_enrollment_pending'):
        return jsonify({'error': 'No MFA enrollment in progress'}), 400

    user = AdminUser.query.get(user_id)
    if not user or not user.mfa_secret:
        return jsonify({'error': 'MFA secret not found'}), 404

    try:
        provisioning_uri = MFAManager.generate_provisioning_uri(user.mfa_secret, user.username)
        qr_bytes = MFAManager.generate_qr_code(provisioning_uri)

        return send_file(
            BytesIO(qr_bytes),
            mimetype='image/png',
            as_attachment=False,
            download_name='mfa_qr.png'
        )

    except Exception as e:
        current_app.logger.exception("QR code generation failed")
        return jsonify({'error': 'Failed to generate QR code'}), 500


@security_bp.route('/mfa/enroll/verify', methods=['POST'])
def mfa_enroll_verify():
    """Complete MFA enrollment by verifying a TOTP code."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    if not session.get('mfa_enrollment_pending'):
        return jsonify({'error': 'No MFA enrollment in progress'}), 400

    user = AdminUser.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json()
    code = data.get('code', '').strip()

    if not code:
        return jsonify({'error': 'Verification code required'}), 400

    try:
        success, backup_codes = enroll_user_mfa(user, code)

        if success:
            session.pop('mfa_enrollment_pending', None)
            AuditLogger.log_mfa_enrolled(user.id, user.username)

            return jsonify({
                'success': True,
                'backup_codes': backup_codes,
                'message': 'MFA enrolled successfully. Save your backup codes in a secure location.'
            })
        else:
            return jsonify({'error': 'Invalid verification code'}), 400

    except Exception as e:
        current_app.logger.exception("MFA enrollment verification failed")
        return jsonify({'error': 'Failed to complete MFA enrollment'}), 500


@security_bp.route('/mfa/disable', methods=['POST'])
def mfa_disable():
    """Disable MFA for current user."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401

    user = AdminUser.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not user.mfa_enabled:
        return jsonify({'error': 'MFA not enabled'}), 400

    data = request.get_json()
    password = data.get('password', '')

    # Require password confirmation to disable MFA
    if not user.check_password(password):
        AuditLogger.log(
            action=AuditAction.MFA_DISABLED,
            success=False,
            user_id=user.id,
            username=user.username,
            details={'reason': 'invalid_password'}
        )
        return jsonify({'error': 'Invalid password'}), 401

    try:
        disable_user_mfa(user)
        AuditLogger.log(
            action=AuditAction.MFA_DISABLED,
            user_id=user.id,
            username=user.username
        )
        return jsonify({
            'success': True,
            'message': 'MFA disabled successfully'
        })

    except Exception as e:
        current_app.logger.exception("MFA disable failed")
        return jsonify({'error': 'Failed to disable MFA'}), 500


# ============================================================================
# Role and Permission Management
# ============================================================================

@security_bp.route('/roles', methods=['GET'])
@require_permission('system.view_users')
def list_roles():
    """List all roles with their permissions."""
    roles = Role.query.all()
    return jsonify({
        'roles': [role.to_dict() for role in roles]
    })


@security_bp.route('/roles/<int:role_id>', methods=['GET'])
@require_permission('system.view_users')
def get_role(role_id):
    """Get a specific role with details."""
    role = Role.query.get_or_404(role_id)
    return jsonify(role.to_dict())


@security_bp.route('/roles', methods=['POST'])
@require_permission('system.manage_users')
def create_role():
    """Create a new role."""
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    permission_ids = data.get('permission_ids', [])

    if not name:
        return jsonify({'error': 'Role name required'}), 400

    if Role.query.filter_by(name=name).first():
        return jsonify({'error': 'Role already exists'}), 400

    try:
        role = Role(name=name, description=description)

        # Add permissions
        if permission_ids:
            permissions = Permission.query.filter(Permission.id.in_(permission_ids)).all()
            role.permissions.extend(permissions)

        db.session.add(role)
        db.session.commit()

        AuditLogger.log(
            action=AuditAction.ROLE_CREATED,
            resource_type='role',
            resource_id=str(role.id),
            details={'role_name': name, 'permissions': len(permission_ids)}
        )

        return jsonify({
            'success': True,
            'role': role.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Role creation failed")
        return jsonify({'error': 'Failed to create role'}), 500


@security_bp.route('/roles/<int:role_id>', methods=['PUT'])
@require_permission('system.manage_users')
def update_role(role_id):
    """Update a role's details and permissions."""
    role = Role.query.get_or_404(role_id)

    data = request.get_json()
    description = data.get('description')
    permission_ids = data.get('permission_ids')

    try:
        if description is not None:
            role.description = description

        if permission_ids is not None:
            # Replace permissions
            role.permissions.clear()
            permissions = Permission.query.filter(Permission.id.in_(permission_ids)).all()
            role.permissions.extend(permissions)

        db.session.commit()

        AuditLogger.log(
            action=AuditAction.ROLE_UPDATED,
            resource_type='role',
            resource_id=str(role.id),
            details={'role_name': role.name}
        )

        return jsonify({
            'success': True,
            'role': role.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Role update failed")
        return jsonify({'error': 'Failed to update role'}), 500


@security_bp.route('/permissions', methods=['GET'])
@require_permission('system.view_users')
def list_permissions():
    """List all available permissions."""
    permissions = Permission.query.all()
    return jsonify({
        'permissions': [perm.to_dict() for perm in permissions]
    })


@security_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@require_permission('system.manage_users')
def assign_user_role(user_id):
    """Assign a role to a user."""
    user = AdminUser.query.get_or_404(user_id)

    data = request.get_json()
    role_id = data.get('role_id')

    if role_id is None:
        return jsonify({'error': 'role_id required'}), 400

    role = Role.query.get(role_id)
    if not role:
        return jsonify({'error': 'Role not found'}), 404

    try:
        old_role = user.role.name if user.role else None
        user.role_id = role_id
        db.session.commit()

        AuditLogger.log(
            action=AuditAction.USER_ROLE_CHANGED,
            resource_type='user',
            resource_id=str(user.id),
            details={
                'username': user.username,
                'old_role': old_role,
                'new_role': role.name
            }
        )

        return jsonify({
            'success': True,
            'user': user.to_safe_dict()
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Role assignment failed")
        return jsonify({'error': 'Failed to assign role'}), 500


# ============================================================================
# Audit Log Endpoints
# ============================================================================

@security_bp.route('/audit-logs', methods=['GET'])
@require_permission('logs.view')
def list_audit_logs():
    """List audit logs with filtering."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 1000)  # Cap at 1000
    user_id = request.args.get('user_id', type=int)
    action = request.args.get('action')
    success = request.args.get('success', type=lambda v: v.lower() == 'true')
    days = request.args.get('days', 30, type=int)

    query = AuditLog.query

    # Apply filters
    if user_id:
        query = query.filter_by(user_id=user_id)

    if action:
        query = query.filter_by(action=action)

    if success is not None:
        query = query.filter_by(success=success)

    # Time filter
    cutoff = utc_now() - timedelta(days=days)
    query = query.filter(AuditLog.timestamp >= cutoff)

    # Order by timestamp descending
    query = query.order_by(AuditLog.timestamp.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'logs': [log.to_dict() for log in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    })


@security_bp.route('/audit-logs/export', methods=['GET'])
@require_permission('logs.export')
def export_audit_logs():
    """Export audit logs as CSV."""
    days = request.args.get('days', 90, type=int)
    user_id = request.args.get('user_id', type=int)

    query = AuditLog.query

    if user_id:
        query = query.filter_by(user_id=user_id)

    cutoff = utc_now() - timedelta(days=days)
    query = query.filter(AuditLog.timestamp >= cutoff)
    query = query.order_by(AuditLog.timestamp.desc())

    logs = query.all()

    # Create CSV (use StringIO for text mode)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Username', 'Action', 'Resource Type', 'Resource ID',
                     'IP Address', 'Success', 'Details'])

    for log in logs:
        writer.writerow([
            log.timestamp.isoformat(),
            log.username or '',
            log.action,
            log.resource_type or '',
            log.resource_id or '',
            log.ip_address or '',
            'Yes' if log.success else 'No',
            str(log.details) if log.details else ''
        ])

    # Convert to bytes for send_file
    output.seek(0)
    csv_bytes = BytesIO(output.getvalue().encode('utf-8'))

    AuditLogger.log(
        action=AuditAction.LOG_EXPORTED,
        details={'log_count': len(logs), 'days': days}
    )

    return send_file(
        csv_bytes,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'audit_logs_{utc_now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


@security_bp.route('/audit-logs/export.pdf', methods=['GET'])
@require_permission('logs.export')
def export_audit_logs_pdf():
    """Export audit logs as PDF - server-side from database."""
    days = request.args.get('days', 90, type=int)
    user_id = request.args.get('user_id', type=int)

    query = AuditLog.query

    if user_id:
        query = query.filter_by(user_id=user_id)

    cutoff = utc_now() - timedelta(days=days)
    query = query.filter(AuditLog.timestamp >= cutoff)
    query = query.order_by(AuditLog.timestamp.desc())

    logs = query.all()

    # Build PDF sections
    sections = []

    log_lines = []
    for log in logs:
        timestamp_str = format_local_datetime(log.timestamp, include_utc=True)
        username = log.username or 'Unknown'
        action = log.action
        success = 'Yes' if log.success else 'No'

        log_line = f"[{timestamp_str}] {username} - {action} (Success: {success})"
        if log.resource_type:
            log_line += f" | Resource: {log.resource_type}"
            if log.resource_id:
                log_line += f" #{log.resource_id}"
        if log.ip_address:
            log_line += f" | IP: {log.ip_address}"

        log_lines.append(log_line)

    sections.append({
        'heading': f'Audit Logs (Last {days} days, {len(logs)} entries)',
        'content': log_lines if log_lines else ['No audit log entries found'],
    })

    # Generate PDF
    pdf_bytes = generate_pdf_document(
        title="Audit Logs Export",
        sections=sections,
        subtitle=f"Generated from last {days} days of activity",
        footer_text="Generated by EAS Station - Emergency Alert System Platform"
    )

    AuditLogger.log(
        action=AuditAction.LOG_EXPORTED,
        details={'log_count': len(logs), 'days': days, 'format': 'pdf'}
    )

    # Return as downloadable PDF
    response = Response(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = (
        f"inline; filename=audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    return response


# ============================================================================
# Security Settings & Utilities
# ============================================================================

@security_bp.route('/init-roles', methods=['POST'])
@require_permission('system.manage_users')
def init_default_roles():
    """Initialize default roles and permissions (admin only)."""
    try:
        initialize_default_roles_and_permissions()
        return jsonify({
            'success': True,
            'message': 'Default roles and permissions initialized'
        })
    except Exception as e:
        current_app.logger.exception("Role initialization failed")
        return jsonify({'error': 'Failed to initialize roles'}), 500


@security_bp.route('/permissions/check', methods=['POST'])
def check_permission():
    """Check if current user has a specific permission."""
    data = request.get_json()
    permission_name = data.get('permission')

    if not permission_name:
        return jsonify({'error': 'Permission name required'}), 400

    result = has_permission(permission_name)

    return jsonify({
        'has_permission': result,
        'permission': permission_name
    })


# ============================================================================
# Web UI Routes
# ============================================================================

@security_bp.route('/settings', methods=['GET'])
def security_settings():
    """Security settings page for users."""
    from flask import g, render_template, redirect, url_for

    if not g.current_user:
        return redirect(url_for('auth.login'))

    return render_template(
        'security_settings.html',
        current_user=g.current_user,
        mfa_enabled=g.current_user.mfa_enabled,
        mfa_enrolled_at=g.current_user.mfa_enrolled_at
    )


# ============================================================================
# Blueprint Registration
# ============================================================================

def register(app, logger):
    """Register security blueprint with the Flask app."""
    app.register_blueprint(security_bp)
    logger.info("Security routes registered")
