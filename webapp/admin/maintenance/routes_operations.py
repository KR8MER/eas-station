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

"""Operation status, and the one-click backup and upgrade.

``get_operation_status`` is also imported directly by
``app_core/websocket_push.py`` to feed the admin status push, so it is part of
this package's public surface even though it is a route handler.
"""

import sys
from pathlib import Path
from typing import List

from flask import current_app, jsonify, request

from app_core.auth.roles import require_permission

from .blueprint import maintenance_bp
from .operations import (
    _sanitize_label,
    _serialize_all_operations,
    _serialize_operation_state,
    _start_background_operation,
)
from .paths import repo_root


# Route definitions

@maintenance_bp.route("/admin/operations/status", methods=["GET"])
def get_operation_status():
    return jsonify({"operations": _serialize_all_operations()})

@maintenance_bp.route("/admin/operations/backup", methods=["POST"])
@require_permission('system.configure')
def run_one_click_backup():
    payload = request.get_json(silent=True) or {}
    label_value = payload.get("label", "")
    sanitized_label = _sanitize_label(label_value) if isinstance(label_value, str) else ""
    extra_args: List[str] = []
    if sanitized_label:
        extra_args.extend(["--label", sanitized_label])
    output_dir = payload.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        candidate = output_dir.strip()
        # Reject control-character / argparse-confusing inputs; otherwise pass the
        # operator-supplied path through.  Backups commonly target USB drives,
        # NFS mounts, or arbitrary directories outside BACKUP_DIR, and the route
        # is already gated by admin auth — locking it to BACKUP_DIR breaks the
        # existing UI workflow (relative paths from the form would 400).
        if "\x00" in candidate or "\n" in candidate or "\r" in candidate or candidate.startswith("-"):
            return jsonify({"error": "Invalid output_dir"}), 400
        # If the user supplied a relative path, anchor it under BACKUP_DIR so
        # the form's placeholder ("Default location") behaves intuitively.
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            backup_base = Path(
                current_app.config.get("BACKUP_DIR", "/var/backups/eas-station")
            )
            candidate_path = backup_base / candidate_path
        extra_args.extend(["--output-dir", str(candidate_path)])
    python_executable = sys.executable or "python3"
    command = [python_executable, str(repo_root / "tools" / "create_backup.py"), *extra_args]
    try:
        _start_background_operation(
            "backup",
            command,
            cwd=repo_root,
            logger=current_app.logger,
            description="Backup",
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": str(exc), "operation": _serialize_operation_state("backup")}),
            409,
        )
    message = "Backup started."
    if sanitized_label:
        message = f"Backup started (label: {sanitized_label})."
    return jsonify({"message": message, "operation": _serialize_operation_state("backup")})

@maintenance_bp.route("/admin/operations/upgrade", methods=["POST"])
@require_permission('system.configure')
def run_one_click_upgrade():
    payload = request.get_json(silent=True) or {}
    python_executable = sys.executable or "python3"
    command = [python_executable, str(repo_root / "tools" / "inplace_upgrade.py")]
    checkout_value = payload.get("checkout")
    summary_bits = []
    if isinstance(checkout_value, str) and checkout_value.strip():
        checkout_clean = checkout_value.strip()
        command.extend(["--checkout", checkout_clean])
        summary_bits.append(f"checkout {checkout_clean}")
    if payload.get("skip_migrations"):
        command.append("--skip-migrations")
        summary_bits.append("skip migrations")
    if payload.get("allow_dirty"):
        command.append("--allow-dirty")
        summary_bits.append("allow dirty worktree")
    try:
        _start_background_operation(
            "upgrade",
            command,
            cwd=repo_root,
            logger=current_app.logger,
            description="Upgrade",
        )
    except RuntimeError as exc:
        return (
            jsonify({"error": str(exc), "operation": _serialize_operation_state("upgrade")}),
            409,
        )
    message = "Upgrade started."
    if summary_bits:
        message = f"Upgrade started ({', '.join(summary_bits)})."
    return jsonify({"message": message, "operation": _serialize_operation_state("upgrade")})
