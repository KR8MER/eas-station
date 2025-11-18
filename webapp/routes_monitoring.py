"""Public monitoring and utility endpoints for the Flask app."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any

from flask import Flask, jsonify, render_template
from sqlalchemy import text
from alembic import command, config as alembic_config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app_core.extensions import db
from app_core.models import RadioReceiver
from app_core.radio import ensure_radio_tables
from app_core.led import LED_AVAILABLE
from app_core.location import get_location_settings
from app_utils import get_location_timezone_name, local_now, utc_now


def register(app: Flask, logger) -> None:
    """Attach monitoring and utility routes to the Flask app."""

    route_logger = logger.getChild("routes_monitoring")

    def _system_version() -> str:
        return str(app.config.get("SYSTEM_VERSION", "unknown"))

    @app.route("/health")
    def health_check():
        """Simple health check endpoint."""

        try:
            db.session.execute(text("SELECT 1")).fetchone()

            try:
                ensure_radio_tables(route_logger)
                receiver_total = RadioReceiver.query.count()
            except Exception as radio_exc:  # pragma: no cover - defensive
                route_logger.debug("Radio table check failed: %s", radio_exc)
                receiver_total = None

            return jsonify(
                {
                    "status": "healthy",
                    "timestamp": utc_now().isoformat(),
                    "local_timestamp": local_now().isoformat(),
                    "version": _system_version(),
                    "database": "connected",
                    "led_available": LED_AVAILABLE,
                    "radio_receivers": receiver_total,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Health check failed: %s", exc)
            return (
                jsonify(
                    {
                        "status": "unhealthy",
                        "error": str(exc),
                        "timestamp": utc_now().isoformat(),
                        "local_timestamp": local_now().isoformat(),
                    }
                ),
                500,
            )

    @app.route("/api/health")
    def api_health_check():
        """API health check endpoint (alias for /health)."""
        # Delegate to the main health check
        return health_check()

    @app.route("/health/dependencies")
    def health_dependencies():
        """Comprehensive dependency health check endpoint.

        Checks the health of all critical services and dependencies:
        - PostgreSQL database
        - Icecast streaming service
        - Docker daemon
        - Disk space
        - Configuration files
        """
        dependencies: Dict[str, Any] = {}
        overall_status = "healthy"

        # 1. PostgreSQL Database
        try:
            db.session.execute(text("SELECT 1")).fetchone()
            db_version = db.session.execute(text("SELECT version()")).fetchone()
            dependencies["postgresql"] = {
                "status": "healthy",
                "message": "Database connected",
                "version": db_version[0].split(" ")[1] if db_version else "unknown",
            }
        except Exception as exc:
            dependencies["postgresql"] = {
                "status": "unhealthy",
                "message": str(exc),
            }
            overall_status = "unhealthy"

        # 2. Icecast Service
        icecast_enabled = app.config.get("ICECAST_ENABLED", False)
        if icecast_enabled:
            icecast_host = app.config.get("ICECAST_SERVER", "icecast")
            icecast_port = app.config.get("ICECAST_PORT", 8000)
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((icecast_host, int(icecast_port)))
                sock.close()

                if result == 0:
                    dependencies["icecast"] = {
                        "status": "healthy",
                        "message": f"Icecast reachable at {icecast_host}:{icecast_port}",
                    }
                else:
                    dependencies["icecast"] = {
                        "status": "degraded",
                        "message": f"Icecast not reachable at {icecast_host}:{icecast_port}",
                    }
                    overall_status = "degraded" if overall_status == "healthy" else overall_status
            except Exception as exc:
                dependencies["icecast"] = {
                    "status": "degraded",
                    "message": f"Cannot check Icecast: {exc}",
                }
                overall_status = "degraded" if overall_status == "healthy" else overall_status
        else:
            dependencies["icecast"] = {
                "status": "disabled",
                "message": "Icecast streaming not enabled",
            }

        # 3. Docker Daemon
        docker_cmd = shutil.which("docker")
        if docker_cmd:
            try:
                result = subprocess.run(
                    [docker_cmd, "info"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    dependencies["docker"] = {
                        "status": "healthy",
                        "message": "Docker daemon accessible",
                    }
                else:
                    dependencies["docker"] = {
                        "status": "degraded",
                        "message": "Docker daemon not responding",
                    }
                    overall_status = "degraded" if overall_status == "healthy" else overall_status
            except Exception as exc:
                dependencies["docker"] = {
                    "status": "degraded",
                    "message": f"Cannot check Docker: {exc}",
                }
                overall_status = "degraded" if overall_status == "healthy" else overall_status
        else:
            dependencies["docker"] = {
                "status": "unknown",
                "message": "Docker command not found",
            }

        # 4. Disk Space
        try:
            repo_root = Path(__file__).resolve().parents[1]
            stat = shutil.disk_usage(repo_root)
            used_percent = (stat.used / stat.total) * 100
            free_gb = stat.free / (1024 ** 3)

            disk_status = "healthy"
            if used_percent > 90:
                disk_status = "unhealthy"
                overall_status = "unhealthy"
            elif used_percent > 80:
                disk_status = "degraded"
                overall_status = "degraded" if overall_status == "healthy" else overall_status

            dependencies["disk_space"] = {
                "status": disk_status,
                "message": f"{used_percent:.1f}% used, {free_gb:.1f} GB free",
                "used_percent": round(used_percent, 1),
                "free_gb": round(free_gb, 1),
                "total_gb": round(stat.total / (1024 ** 3), 1),
            }
        except Exception as exc:
            dependencies["disk_space"] = {
                "status": "unknown",
                "message": f"Cannot check disk space: {exc}",
            }

        # 5. Critical Configuration Files
        config_files = [".env", "docker-compose.yml"]
        config_status = []
        for config_file in config_files:
            config_path = Path(config_file)
            if config_path.exists():
                config_status.append(f"{config_file}: present")
            else:
                config_status.append(f"{config_file}: MISSING")
                overall_status = "degraded" if overall_status == "healthy" else overall_status

        dependencies["configuration"] = {
            "status": "healthy" if all("present" in s for s in config_status) else "degraded",
            "message": ", ".join(config_status),
        }

        # 6. Backup Directory
        backup_dir = Path("backups")
        if backup_dir.exists():
            try:
                backup_count = sum(1 for p in backup_dir.iterdir() if p.is_dir() and p.name.startswith("backup-"))
                dependencies["backups"] = {
                    "status": "healthy",
                    "message": f"{backup_count} backup(s) available",
                    "count": backup_count,
                }
            except Exception as exc:
                dependencies["backups"] = {
                    "status": "unknown",
                    "message": f"Cannot check backups: {exc}",
                }
        else:
            dependencies["backups"] = {
                "status": "warning",
                "message": "No backup directory found",
            }

        # Prepare response
        http_status = 200
        if overall_status == "unhealthy":
            http_status = 503  # Service Unavailable
        elif overall_status == "degraded":
            http_status = 200  # Still functional, but degraded

        return jsonify(
            {
                "status": overall_status,
                "timestamp": utc_now().isoformat(),
                "local_timestamp": local_now().isoformat(),
                "version": _system_version(),
                "dependencies": dependencies,
            }
        ), http_status

    @app.route("/ping")
    def ping():
        """Simple ping endpoint."""

        return jsonify(
            {
                "pong": True,
                "timestamp": utc_now().isoformat(),
                "local_timestamp": local_now().isoformat(),
            }
        )

    @app.route("/version")
    def version():
        """Version information endpoint."""

        location = get_location_settings()
        return jsonify(
            {
                "version": _system_version(),
                "name": "NOAA CAP Alerts System",
                "author": "KR8MER Amateur Radio Emergency Communications",
                "description": (
                    f"Emergency alert system for {location['county_name']}, "
                    f"{location['state_code']}"
                ),
                "timezone": get_location_timezone_name(),
                "led_available": LED_AVAILABLE,
                "timestamp": utc_now().isoformat(),
                "local_timestamp": local_now().isoformat(),
            }
        )

    @app.route("/help/version")
    def help_version():
        """Version information page with user-friendly HTML display."""
        import json
        from app_utils.changelog_parser import parse_all_changelogs

        # Get repository root
        repo_root = Path(__file__).resolve().parents[1]
        current_version = _system_version()

        # Get git information
        git_info = {}
        try:
            # Current commit hash
            git_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            git_info["commit_hash"] = git_hash[:8] if git_hash else "unknown"
            git_info["commit_hash_full"] = git_hash if git_hash else "unknown"

            # Current branch
            git_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            git_info["branch"] = git_branch if git_branch else "unknown"

            # Commit date
            git_date = subprocess.run(
                ["git", "log", "-1", "--format=%ci"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            git_info["commit_date"] = git_date if git_date else "unknown"

            # Commit message
            git_message = subprocess.run(
                ["git", "log", "-1", "--format=%s"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            git_info["commit_message"] = git_message if git_message else "unknown"

        except Exception as exc:
            route_logger.debug("Git info retrieval failed: %s", exc)
            git_info = {
                "commit_hash": "unknown",
                "commit_hash_full": "unknown",
                "branch": "unknown",
                "commit_date": "unknown",
                "commit_message": "unknown",
            }

        # Parse changelogs
        try:
            changelogs = parse_all_changelogs(repo_root, current_version)
        except Exception as exc:
            route_logger.debug("Changelog parsing failed: %s", exc)
            changelogs = {}

        location = get_location_settings()
        version_data = {
            "version": current_version,
            "name": "NOAA CAP Alerts System",
            "author": "KR8MER Amateur Radio Emergency Communications",
            "description": (
                f"Emergency alert system for {location['county_name']}, "
                f"{location['state_code']}"
            ),
            "timezone": get_location_timezone_name(),
            "led_available": LED_AVAILABLE,
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
        }

        # Pretty-print JSON for display
        version_json = json.dumps(version_data, indent=2)

        return render_template(
            "version.html",
            version_info=version_data,
            version_json=version_json,
            git_info=git_info,
            changelogs=changelogs
        )

    @app.route("/api/release-manifest")
    def release_manifest():
        """Release manifest endpoint for deployment auditing and version tracking.

        Reports the running version, git commit hash, database migration level,
        and deployment metadata to aid in audit trails and troubleshooting.
        """

        # Read version from VERSION file and determine repository root
        try:
            repo_root = Path(__file__).resolve().parents[1]
            version_path = repo_root / "VERSION"
            version = version_path.read_text(encoding="utf-8").strip()
        except Exception:
            version = _system_version()
            repo_root = Path(__file__).resolve().parents[1]  # Still needed for git commands

        # Get current git commit hash
        try:
            git_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            if not git_hash:
                git_hash = "unknown"
        except Exception:
            git_hash = "unknown"

        # Get git branch
        try:
            git_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            if not git_branch:
                git_branch = "unknown"
        except Exception:
            git_branch = "unknown"

        # Get git status (clean/dirty)
        try:
            git_status_output = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                cwd=repo_root,
            ).stdout.strip()
            git_clean = not bool(git_status_output)
        except Exception:
            git_clean = None

        # Get current database migration revision
        migration_revision = "unknown"
        migration_description = "unknown"
        pending_migrations = []

        try:
            # Get current revision from database
            with db.engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_rev = context.get_current_revision()
                migration_revision = current_rev or "none"

            # Load Alembic configuration
            alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
            if alembic_ini.exists():
                config = alembic_config.Config(str(alembic_ini))
                script = ScriptDirectory.from_config(config)

                # Get description of current revision
                if current_rev:
                    try:
                        rev_obj = script.get_revision(current_rev)
                        if rev_obj:
                            migration_description = rev_obj.doc or "No description"
                    except Exception as exc:
                        route_logger.debug("Failed to get revision description for %s: %s", current_rev, exc)

                # Check for pending migrations
                try:
                    head_rev = script.get_current_head()
                    if current_rev != head_rev:
                        # There are pending migrations
                        for rev in script.iterate_revisions(head_rev, current_rev):
                            if rev.revision != current_rev:
                                pending_migrations.append({
                                    "revision": rev.revision,
                                    "description": rev.doc or "No description",
                                })
                except Exception as exc:
                    route_logger.debug("Failed to check pending migrations: %s", exc)

        except Exception as exc:
            route_logger.debug("Failed to get migration info: %s", exc)

        return jsonify(
            {
                "version": version,
                "git": {
                    "commit": git_hash,
                    "branch": git_branch,
                    "clean": git_clean,
                },
                "database": {
                    "current_revision": migration_revision,
                    "revision_description": migration_description,
                    "pending_migrations": pending_migrations,
                    "pending_count": len(pending_migrations),
                },
                "system": {
                    "led_available": LED_AVAILABLE,
                    "timezone": get_location_timezone_name(),
                },
                "timestamp": utc_now().isoformat(),
                "local_timestamp": local_now().isoformat(),
            }
        )

    @app.route("/favicon.ico")
    def favicon():
        """Serve favicon."""

        return "", 204

    @app.route("/robots.txt")
    def robots():
        """Robots.txt for web crawlers."""

        return (
            """User-agent: *
Disallow: /admin/
Disallow: /api/
Disallow: /debug/
Allow: /
""",
            200,
            {"Content-Type": "text/plain"},
        )

    @app.route("/api/monitoring/radio")
    def monitoring_radio():
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Radio table validation failed: %s", exc)

        receivers = (
            RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        )

        payload = []
        for receiver in receivers:
            latest = receiver.latest_status()
            payload.append(
                {
                    "id": receiver.id,
                    "identifier": receiver.identifier,
                    "display_name": receiver.display_name,
                    "driver": receiver.driver,
                    "frequency_hz": receiver.frequency_hz,
                    "sample_rate": receiver.sample_rate,
                    "gain": receiver.gain,
                    "channel": receiver.channel,
                    "auto_start": receiver.auto_start,
                    "enabled": receiver.enabled,
                    "notes": receiver.notes,
                    "latest_status": (
                        {
                            "reported_at": latest.reported_at.isoformat() if latest and latest.reported_at else None,
                            "locked": bool(latest.locked) if latest else None,
                            "signal_strength": latest.signal_strength if latest else None,
                            "last_error": latest.last_error if latest else None,
                            "capture_mode": latest.capture_mode if latest else None,
                            "capture_path": latest.capture_path if latest else None,
                        }
                        if latest
                        else None
                    ),
                }
            )

        return jsonify({"receivers": payload, "count": len(payload)})


__all__ = ["register"]
