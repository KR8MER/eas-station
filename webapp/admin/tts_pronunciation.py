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

"""Admin routes for the TTS pronunciation dictionary."""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import TTSPronunciationRule, TTS_BUILTIN_PRONUNCIATIONS

logger = logging.getLogger(__name__)

pronunciation_bp = Blueprint("tts_pronunciation", __name__)


def _seed_builtins() -> None:
    """Insert missing built-in pronunciation rows (idempotent)."""
    for original, replacement, note in TTS_BUILTIN_PRONUNCIATIONS:
        exists = TTSPronunciationRule.query.filter_by(
            original_text=original, is_builtin=True
        ).first()
        if not exists:
            db.session.add(
                TTSPronunciationRule(
                    original_text=original,
                    replacement_text=replacement,
                    note=note,
                    enabled=True,
                    match_case=False,
                    is_builtin=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
    db.session.commit()


@pronunciation_bp.route("/tts/pronunciation")
@require_permission("system.configure")
def pronunciation_page():
    """Render the TTS pronunciation dictionary management page."""
    try:
        _seed_builtins()
        rules = (
            TTSPronunciationRule.query
            .order_by(
                TTSPronunciationRule.is_builtin.desc(),
                TTSPronunciationRule.original_text.asc(),
            )
            .all()
        )
        return render_template("admin/tts_pronunciation.html", rules=rules)
    except Exception as exc:
        logger.error("Failed to load pronunciation rules: %s", exc)
        return render_template("admin/tts_pronunciation.html", rules=[], error=str(exc))


@pronunciation_bp.route("/api/tts/pronunciation", methods=["GET"])
@require_permission("system.configure")
def list_rules():
    """Return all pronunciation rules as JSON."""
    try:
        _seed_builtins()
        rules = TTSPronunciationRule.query.order_by(
            TTSPronunciationRule.is_builtin.desc(),
            TTSPronunciationRule.original_text.asc(),
        ).all()
        return jsonify({"success": True, "rules": [r.to_dict() for r in rules]})
    except Exception as exc:
        logger.error("Failed to list pronunciation rules: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@pronunciation_bp.route("/api/tts/pronunciation", methods=["POST"])
@require_permission("system.configure")
def create_rule():
    """Create a new pronunciation rule."""
    try:
        data = request.get_json() or {}
        original = (data.get("original_text") or "").strip()
        replacement = (data.get("replacement_text") or "").strip()

        if not original or not replacement:
            return jsonify({"success": False, "error": "original_text and replacement_text are required"}), 400
        if len(original) > 255 or len(replacement) > 255:
            return jsonify({"success": False, "error": "Fields must be 255 characters or fewer"}), 400

        rule = TTSPronunciationRule(
            original_text=original,
            replacement_text=replacement,
            enabled=bool(data.get("enabled", True)),
            match_case=bool(data.get("match_case", False)),
            is_builtin=False,
            note=(data.get("note") or "").strip() or None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(rule)
        db.session.commit()
        logger.info("Created pronunciation rule: %r → %r", original, replacement)
        return jsonify({"success": True, "rule": rule.to_dict()}), 201
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to create pronunciation rule: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@pronunciation_bp.route("/api/tts/pronunciation/<int:rule_id>", methods=["PUT"])
@require_permission("system.configure")
def update_rule(rule_id: int):
    """Update an existing pronunciation rule."""
    try:
        rule = TTSPronunciationRule.query.get_or_404(rule_id)
        data = request.get_json() or {}

        if "original_text" in data:
            val = (data["original_text"] or "").strip()
            if not val:
                return jsonify({"success": False, "error": "original_text cannot be empty"}), 400
            rule.original_text = val[:255]

        if "replacement_text" in data:
            val = (data["replacement_text"] or "").strip()
            if not val:
                return jsonify({"success": False, "error": "replacement_text cannot be empty"}), 400
            rule.replacement_text = val[:255]

        if "enabled" in data:
            rule.enabled = bool(data["enabled"])

        if "match_case" in data:
            rule.match_case = bool(data["match_case"])

        if "note" in data:
            rule.note = (data["note"] or "").strip() or None

        rule.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info("Updated pronunciation rule %d: %r → %r", rule_id, rule.original_text, rule.replacement_text)
        return jsonify({"success": True, "rule": rule.to_dict()})
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to update pronunciation rule %d: %s", rule_id, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@pronunciation_bp.route("/api/tts/pronunciation/<int:rule_id>", methods=["DELETE"])
@require_permission("system.configure")
def delete_rule(rule_id: int):
    """Delete a pronunciation rule (built-in rules cannot be deleted)."""
    try:
        rule = TTSPronunciationRule.query.get_or_404(rule_id)
        if rule.is_builtin:
            return jsonify({"success": False, "error": "Built-in rules cannot be deleted. Disable them instead."}), 400
        original = rule.original_text
        db.session.delete(rule)
        db.session.commit()
        logger.info("Deleted pronunciation rule %d (%r)", rule_id, original)
        return jsonify({"success": True, "message": f"Rule for '{original}' deleted."})
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to delete pronunciation rule %d: %s", rule_id, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


def register_pronunciation_routes(app, logger_instance) -> None:
    """Register pronunciation routes under /admin."""
    app.register_blueprint(pronunciation_bp, url_prefix="/admin")
    logger_instance.info("TTS pronunciation routes registered")


__all__ = ["pronunciation_bp", "register_pronunciation_routes"]
