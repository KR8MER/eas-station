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

"""Admin UI for purging received alerts and configuring auto-purge."""

import logging

from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash
from sqlalchemy.exc import SQLAlchemyError

from app_core import alert_purge
from app_core.auth.decorators import require_auth
from app_core.auth.roles import get_current_user, require_permission
from app_core.extensions import db

logger = logging.getLogger(__name__)

alert_purge_bp = Blueprint('alert_purge', __name__, url_prefix='/admin/alert-purge')


def _actor() -> str:
    user = get_current_user()
    return getattr(user, 'username', None) or 'system'


@alert_purge_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def alert_purge_page():
    """Render the single Alert Purge management page."""
    try:
        stats = alert_purge.get_storage_stats()
        sources = alert_purge.get_sources()
        auto_settings = alert_purge.get_auto_purge_settings()
        return render_template(
            'admin/alert_purge.html',
            stats=stats,
            sources=sources,
            auto=auto_settings,
        )
    except SQLAlchemyError as exc:
        logger.error("Database error loading alert purge page: %s", exc)
        db.session.rollback()
        flash('Database error loading the alert purge page', 'danger')
        return redirect(url_for('dashboard.admin'))


@alert_purge_bp.route('/preview', methods=['POST'])
@require_auth
@require_permission('system.configure')
def alert_purge_preview():
    """Return how many alerts / how much audio the criteria would purge."""
    try:
        criteria = alert_purge.normalize_criteria(request.form.to_dict())
        result = alert_purge.preview_purge(criteria)
        return jsonify({'success': True, 'preview': result})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except SQLAlchemyError as exc:
        logger.error("Database error previewing purge: %s", exc)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error during preview'}), 500


@alert_purge_bp.route('/execute', methods=['POST'])
@require_auth
@require_permission('system.configure')
def alert_purge_execute():
    """Execute a manual purge with the supplied criteria."""
    try:
        criteria = alert_purge.normalize_criteria(request.form.to_dict())
        summary = alert_purge.execute_purge(
            criteria, actor=_actor(), trigger='manual'
        )
        return jsonify({
            'success': True,
            'message': (
                f"Purged {summary['rows_deleted']} record(s), stripped "
                f"{summary['audio_stripped']} audio blob(s), freed "
                f"{summary['audio_bytes_freed_human']}."
            ),
            'summary': summary,
            'stats': alert_purge.get_storage_stats(),
        })
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except SQLAlchemyError as exc:
        logger.error("Database error executing purge: %s", exc)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error during purge'}), 500


@alert_purge_bp.route('/auto', methods=['POST'])
@require_auth
@require_permission('system.configure')
def alert_purge_save_auto():
    """Save the automatic purge configuration."""
    try:
        updates = {
            'enabled': request.form.get('enabled', 'false'),
            'max_age_days': request.form.get('max_age_days', '30'),
            'scope': request.form.get('scope', 'full'),
            'decision_filter': request.form.get('decision_filter', 'not_forwarded'),
            'source_filter': request.form.get('source_filter', ''),
            'delete_generated_messages': request.form.get('delete_generated_messages', 'false'),
        }
        saved = alert_purge.update_auto_purge_settings(updates)
        logger.info("Auto-purge settings updated by %s: %s", _actor(), saved)
        return jsonify({
            'success': True,
            'message': 'Auto-purge settings saved.',
            'settings': saved,
        })
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except SQLAlchemyError as exc:
        logger.error("Database error saving auto-purge settings: %s", exc)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving settings'}), 500


@alert_purge_bp.route('/auto/run', methods=['POST'])
@require_auth
@require_permission('system.configure')
def alert_purge_run_auto():
    """Run the auto-purge immediately using the saved configuration."""
    try:
        summary = alert_purge.run_auto_purge()
        if summary.get('skipped'):
            return jsonify({
                'success': True,
                'skipped': True,
                'message': f"Auto-purge skipped: {summary.get('reason')}",
            })
        return jsonify({
            'success': True,
            'message': (
                f"Auto-purge complete: {summary['rows_deleted']} record(s) removed, "
                f"{summary['audio_bytes_freed_human']} freed."
            ),
            'summary': summary,
            'stats': alert_purge.get_storage_stats(),
        })
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except SQLAlchemyError as exc:
        logger.error("Database error running auto-purge: %s", exc)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error during auto-purge'}), 500
