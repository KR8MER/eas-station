"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Backup and restore management routes."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request, send_file

from app_core.auth.decorators import require_auth, require_role


def register(app: Flask, logger) -> None:
    """Register backup management routes."""

    route_logger = logger.getChild("routes_backups")

    def get_backup_dir() -> Path:
        """Get configured backup directory."""
        backup_path = app.config.get("BACKUP_DIR", "/var/backups/eas-station")
        return Path(backup_path)

    def resolve_backup_path(backup_name: str) -> Path:
        """Resolve a backup name to a safe path within the backup directory.

        Rejects path traversal attempts (absolute paths, parent references, or
        nested components) and ensures the resolved path remains under the
        configured backup directory before using it in filesystem operations.
        """

        if not backup_name or backup_name != Path(backup_name).name:
            raise ValueError("Invalid backup name")

        backup_dir = get_backup_dir().resolve()
        candidate = (backup_dir / backup_name).resolve()

        if candidate == backup_dir or backup_dir not in candidate.parents:
            raise ValueError("Backup path must stay within the backup directory")

        return candidate

    def error_response(status: HTTPStatus, message: str, detail: str | None = None):
        """Return a standardized error response with professional metadata."""

        payload = {
            "success": False,
            "error": {
                "status": status.value,
                "title": status.phrase,
                "message": message,
            },
        }

        if detail:
            payload["error"]["detail"] = detail

        return jsonify(payload), status.value

    def run_script(script_name: str, args: list[str]) -> tuple[bool, str, str]:
        """Run a backup script and return results."""
        script_path = Path(__file__).parent.parent / "tools" / script_name
        if not script_path.exists():
            return False, "", f"Script not found: {script_name}"

        cmd = [sys.executable, str(script_path)] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Operation timed out after 1 hour"
        except Exception as exc:
            return False, "", str(exc)

    def parse_backup_metadata(backup_path: Path) -> Optional[dict]:
        """Parse metadata from a backup directory."""
        metadata_file = backup_path / "metadata.json"
        if not metadata_file.exists():
            return None

        try:
            return json.loads(metadata_file.read_text())
        except Exception:
            return None

    def list_backups() -> list[dict]:
        """List all available backups."""
        backup_dir = get_backup_dir()
        if not backup_dir.exists():
            return []

        backups = []
        for item in backup_dir.iterdir():
            if not item.is_dir() or not item.name.startswith("backup-"):
                continue

            metadata = parse_backup_metadata(item)
            if not metadata:
                # Create minimal metadata from directory
                metadata = {
                    "timestamp": item.name.split("-", 1)[1] if "-" in item.name else "unknown",
                    "label": None,
                }

            # Calculate size
            try:
                size_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                size_mb = size_bytes / (1024 * 1024)
            except Exception:
                size_mb = 0

            backups.append({
                "name": item.name,
                "path": str(item),
                "timestamp": metadata.get("timestamp"),
                "label": metadata.get("label"),
                "version": metadata.get("app_version", "unknown"),
                "size_mb": round(size_mb, 1),
                "summary": metadata.get("summary", {}),
            })

        # Sort by timestamp, newest first
        backups.sort(key=lambda x: x["timestamp"], reverse=True)
        return backups

    @app.route("/admin/backups")
    @require_auth
    @require_role("Admin", "Operator")
    def backup_management():
        """Backup and restore management page."""
        backups = list_backups()

        # Get health status
        health = {}
        try:
            backup_dir = get_backup_dir()
            health["backup_dir_exists"] = backup_dir.exists()
            health["backup_dir_writable"] = backup_dir.exists() and backup_dir.stat().st_mode & 0o200
            health["backup_count"] = len(backups)

            if backups:
                latest = backups[0]
                health["latest_backup"] = latest["timestamp"]
                health["latest_backup_size"] = latest["size_mb"]
        except Exception as exc:
            route_logger.error(f"Failed to get backup health: {exc}")
            health["error"] = str(exc)

        return render_template(
            "admin/backups.html",
            backups=backups,
            health=health,
            backup_dir=str(get_backup_dir()),
        )

    @app.route("/api/backups/list")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def api_list_backups():
        """API endpoint to list backups."""
        backups = list_backups()
        return jsonify({
            "success": True,
            "backups": backups,
            "count": len(backups),
        })

    @app.route("/api/backups/create", methods=["POST"])
    @require_auth
    @require_role("Admin", "Operator")
    def api_create_backup():
        """API endpoint to create a new backup."""
        data = request.get_json() or {}
        label = data.get("label", "manual")
        include_media = data.get("include_media", True)
        include_volumes = data.get("include_volumes", True)

        route_logger.info(f"Creating backup with label '{label}'")

        args = ["--output-dir", str(get_backup_dir()), "--label", label]
        if not include_media:
            args.append("--no-media")
        if not include_volumes:
            args.append("--no-volumes")

        success, stdout, stderr = run_script("create_backup.py", args)

        if success:
            route_logger.info(f"Backup created successfully: {label}")
            # Extract backup location from output
            backup_name = None
            for line in stdout.splitlines():
                if "backup-" in line and "Backup completed" not in line:
                    parts = line.split()
                    for part in parts:
                        if "backup-" in part:
                            backup_name = Path(part).name
                            break

            return jsonify({
                "success": True,
                "message": "Backup created successfully",
                "backup_name": backup_name,
                "output": stdout,
            })
        else:
            route_logger.error(f"Backup failed: {stderr}")
            return error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Backup failed",
                detail=stderr or "Unknown error",
            )

    @app.route("/api/backups/restore", methods=["POST"])
    @require_auth
    @require_role("Admin")  # Only admins can restore
    def api_restore_backup():
        """API endpoint to restore a backup."""
        data = request.get_json() or {}
        backup_name = data.get("backup_name")

        if not backup_name:
            return error_response(HTTPStatus.BAD_REQUEST, "Backup name is required")

        try:
            backup_path = resolve_backup_path(backup_name)
        except ValueError as exc:
            return error_response(HTTPStatus.BAD_REQUEST, str(exc))

        if not backup_path.exists():
            return error_response(
                HTTPStatus.NOT_FOUND,
                f"Backup not found: {backup_name}",
            )

        route_logger.warning(f"Restoring backup: {backup_name}")

        # Build restore command
        args = ["--backup-dir", str(backup_path), "--force"]

        if data.get("database_only"):
            args.append("--database-only")
        if data.get("skip_database"):
            args.append("--skip-database")
        if data.get("skip_media"):
            args.append("--skip-media")
        if data.get("skip_volumes"):
            args.append("--skip-volumes")

        success, stdout, stderr = run_script("restore_backup.py", args)

        if success:
            route_logger.info(f"Backup restored successfully: {backup_name}")
            return jsonify({
                "success": True,
                "message": "Backup restored successfully",
                "output": stdout,
            })
        else:
            route_logger.error(f"Restore failed: {stderr}")
            return error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Restore failed",
                detail=stderr or "Unknown error",
            )

    @app.route("/api/backups/delete", methods=["POST"])
    @require_auth
    @require_role("Admin")
    def api_delete_backup():
        """API endpoint to delete a backup."""
        data = request.get_json() or {}
        backup_name = data.get("backup_name")

        if not backup_name:
            return error_response(HTTPStatus.BAD_REQUEST, "Backup name is required")

        try:
            backup_path = resolve_backup_path(backup_name)
        except ValueError as exc:
            return error_response(HTTPStatus.BAD_REQUEST, str(exc))

        if not backup_path.exists():
            return error_response(
                HTTPStatus.NOT_FOUND,
                f"Backup not found: {backup_name}",
            )

        try:
            import shutil
            shutil.rmtree(backup_path)
            route_logger.info(f"Deleted backup: {backup_name}")

            return jsonify({
                "success": True,
                "message": f"Backup deleted: {backup_name}",
            })
        except Exception as exc:
            route_logger.error(f"Failed to delete backup: {exc}")
            return error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Failed to delete backup",
                detail=str(exc),
            )

    @app.route("/api/backups/download/<backup_name>")
    @require_auth
    @require_role("Admin", "Operator")
    def api_download_backup(backup_name: str):
        """API endpoint to download a backup as a tarball."""
        try:
            backup_path = resolve_backup_path(backup_name)
        except ValueError as exc:
            return error_response(HTTPStatus.BAD_REQUEST, str(exc))

        if not backup_path.exists():
            return error_response(
                HTTPStatus.NOT_FOUND,
                f"Backup not found: {backup_name}",
            )

        # Create a tarball of the backup
        import tarfile
        import tempfile

        try:
            temp_file = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
            with tarfile.open(temp_file.name, "w:gz") as tar:
                tar.add(backup_path, arcname=backup_name)

            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=f"{backup_name}.tar.gz",
                mimetype="application/gzip",
            )
        except Exception as exc:
            route_logger.error(f"Failed to create backup download: {exc}")
            return error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Failed to create download",
                detail=str(exc),
            )

    @app.route("/api/backups/validate/<backup_name>")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def api_validate_backup(backup_name: str):
        """API endpoint to validate a backup."""
        try:
            backup_path = resolve_backup_path(backup_name)
        except ValueError as exc:
            return error_response(HTTPStatus.BAD_REQUEST, str(exc))

        if not backup_path.exists():
            return error_response(
                HTTPStatus.NOT_FOUND,
                f"Backup not found: {backup_name}",
            )

        # Check for required files
        required_files = ["metadata.json", ".env"]
        missing_files = []
        for file in required_files:
            if not (backup_path / file).exists():
                missing_files.append(file)

        # Check database dump
        db_dump = backup_path / "alerts_database.sql"
        db_valid = db_dump.exists() and db_dump.stat().st_size > 0

        is_valid = len(missing_files) == 0 and db_valid

        return jsonify({
            "success": True,
            "valid": is_valid,
            "checks": {
                "metadata": (backup_path / "metadata.json").exists(),
                "config": (backup_path / ".env").exists(),
                "database": db_valid,
                "database_size_mb": round(db_dump.stat().st_size / (1024 * 1024), 1) if db_dump.exists() else 0,
            },
            "missing_files": missing_files,
        })

    @app.route("/api/backups/validate-system", methods=["POST"])
    @require_auth
    @require_role("Admin", "Operator")
    def api_validate_system():
        """API endpoint to validate system health after restore.
        
        This runs the post-restore validation script to check:
        - Web service availability
        - Health endpoint status
        - Database connectivity and migrations
        - External dependencies
        - Configuration integrity
        - GPIO/audio device availability
        - API endpoint accessibility
        """
        data = request.get_json() or {}
        wait_seconds = data.get("wait", 0)
        
        route_logger.info("Running post-restore system validation")
        
        # Build validation command
        args = []
        if wait_seconds > 0:
            args.extend(["--wait", str(wait_seconds)])
        
        # Run validation with localhost since we're in the same container/network
        args.extend(["--host", "localhost", "--port", "8080"])
        
        success, stdout, stderr = run_script("validate_restore.py", args)
        
        # Parse the output to extract validation results
        validation_results = {
            "passed": [],
            "failed": [],
            "total": 0,
        }
        
        # Simple parsing of the output
        for line in stdout.split("\n"):
            if "✓ PASS:" in line:
                check_name = line.split(":", 1)[1].split("-")[0].strip()
                validation_results["passed"].append(check_name)
                validation_results["total"] += 1
            elif "✗ FAIL:" in line:
                check_name = line.split(":", 1)[1].split("-")[0].strip()
                message = line.split("-", 1)[1].strip() if "-" in line.split(":", 1)[1] else "Failed"
                validation_results["failed"].append({
                    "check": check_name,
                    "message": message
                })
                validation_results["total"] += 1
        
        if success:
            route_logger.info(f"System validation passed: {len(validation_results['passed'])}/{validation_results['total']} checks")
            return jsonify({
                "success": True,
                "all_passed": len(validation_results["failed"]) == 0,
                "message": "System validation completed",
                "results": validation_results,
                "output": stdout,
            })
        else:
            route_logger.warning(f"System validation failed: {len(validation_results['failed'])} failed checks")
            return jsonify({
                "success": True,  # API call succeeded even if validation found issues
                "all_passed": False,
                "message": "System validation found issues",
                "results": validation_results,
                "output": stdout,
                "error": stderr,
            })


__all__ = ["register"]
