"""Public monitoring and utility endpoints for the Flask app."""

from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Flask, jsonify
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

    @app.route("/api/release-manifest")
    def release_manifest():
        """Release manifest endpoint for deployment auditing and version tracking.

        Reports the running version, git commit hash, database migration level,
        and deployment metadata to aid in audit trails and troubleshooting.
        """

        # Read version from VERSION file
        try:
            version_path = Path(__file__).resolve().parents[1] / "VERSION"
            version = version_path.read_text(encoding="utf-8").strip()
        except Exception:
            version = _system_version()

        # Get current git commit hash
        try:
            git_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
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
                    except Exception:
                        pass

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
