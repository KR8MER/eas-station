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

"""The ``.env`` editor behind Settings -> Environment."""

from pathlib import Path

from flask import current_app, jsonify, request

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import SystemLog
from app_utils import local_now, utc_now

from .blueprint import maintenance_bp
from .paths import repo_root


@maintenance_bp.route("/admin/env_config", methods=["GET", "POST"])
@require_permission('system.configure')
def env_config():
    """Read or update the environment configuration file (.env)."""

    # Check standard .env locations
    env_file_path = Path("/opt/eas-station/.env")
    if not env_file_path.exists():
        env_file_path = repo_root / ".env"

    if request.method == "GET":
        try:
            if not env_file_path.exists():
                return jsonify({"error": f"Environment file not found at {env_file_path}"}), 404

            with open(env_file_path, "r") as f:
                content = f.read()

            # Parse the env file to extract key-value pairs (excluding comments)
            env_vars = {}
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()

            return jsonify({
                "content": content,
                "env_vars": env_vars,
                "path": str(env_file_path),
            })

        except Exception as exc:
            current_app.logger.error("Failed to read env file: %s", exc)
            return jsonify({"error": f"Failed to read configuration: {exc}"}), 500

    # POST - Update the env file
    try:
        payload = request.get_json(silent=True) or {}
        new_content = payload.get("content", "")

        if not new_content:
            return jsonify({"error": "No content provided"}), 400

        # Initialize backup_path
        backup_path = None

        # Create backup of existing file
        if env_file_path.exists():
            backup_path = env_file_path.with_suffix(".env.backup")
            import shutil
            shutil.copy2(env_file_path, backup_path)
            current_app.logger.info("Created backup of %s at %s", env_file_path.name, backup_path)

        # Write new content
        with open(env_file_path, "w") as f:
            f.write(new_content)

        # Log the change
        log_entry = SystemLog(
            level="WARNING",
            message="Environment configuration file updated via admin interface",
            module="admin",
            details={
                "updated_at_utc": utc_now().isoformat(),
                "updated_at_local": local_now().isoformat(),
                "file_path": str(env_file_path),
                "backup_created": str(backup_path) if backup_path else None,
                "warning": "Application restart required for changes to take effect",
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        current_app.logger.warning("Environment configuration updated. Restart required for changes to take effect.")

        return jsonify({
            "message": "Configuration updated successfully. Restart the application for changes to take effect.",
            "backup_path": str(backup_path) if backup_path else None,
            "restart_required": True,
        })

    except Exception as exc:
        current_app.logger.error("Failed to update env file: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to update configuration: {exc}"}), 500
