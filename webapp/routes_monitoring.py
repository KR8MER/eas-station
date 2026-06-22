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

"""Public monitoring and utility endpoints for the Flask app."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any

from flask import Flask, jsonify, render_template, url_for
from sqlalchemy import text
from alembic import command, config as alembic_config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app_core.extensions import db
from app_core.models import RadioReceiver
from app_core.radio import ensure_radio_tables
from app_core.led import LED_AVAILABLE
from app_core.location import get_location_settings

try:
    from app_core.vfd import VFD_AVAILABLE
except Exception:  # pragma: no cover - defensive: optional hardware module
    VFD_AVAILABLE = False
try:
    from app_core.oled import OLED_AVAILABLE
except Exception:  # pragma: no cover - defensive: optional hardware module
    OLED_AVAILABLE = False
try:
    from app_core.audio.sources import RADIO_AVAILABLE
except Exception:  # pragma: no cover - defensive: optional hardware module
    RADIO_AVAILABLE = False
try:
    from app_core.audio.sources import ALSA_AVAILABLE, PULSE_AVAILABLE
except Exception:  # pragma: no cover - defensive
    ALSA_AVAILABLE = False
    PULSE_AVAILABLE = False
try:
    from app_core.auth.mfa import TOTP_AVAILABLE
except Exception:  # pragma: no cover - defensive
    TOTP_AVAILABLE = False
try:
    from app_core.radio.drivers import _SCIPY_AVAILABLE as SCIPY_AVAILABLE
except Exception:  # pragma: no cover - defensive
    SCIPY_AVAILABLE = False
try:
    from app_core.radio.demodulation import _NUMBA_AVAILABLE as NUMBA_AVAILABLE
except Exception:  # pragma: no cover - defensive
    NUMBA_AVAILABLE = False
from app_utils import get_location_timezone_name, local_now, utc_now
from app_utils.versioning import get_git_metadata, get_git_tree_state


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
        - Redis server
        - Icecast streaming service
        - Disk space
        - Configuration files
        - Alert forwarding pipeline (no alert may miss its forwarding decision)
        - CAP poller liveness
        """
        dependencies: Dict[str, Any] = {}
        overall_status = "healthy"

        # 1. PostgreSQL Database
        try:
            db.session.execute(text("SELECT 1")).fetchone()
            db_version = db.session.execute(text("SELECT version()")).fetchone()
            version_str = "unknown"
            if db_version and db_version[0]:
                parts = db_version[0].split(" ")
                version_str = parts[1] if len(parts) > 1 else parts[0] if parts else "unknown"
            dependencies["postgresql"] = {
                "status": "healthy",
                "message": "Database connected",
                "version": version_str,
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
            icecast_host = app.config.get("ICECAST_SERVER", "localhost")
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

        # 3. Redis Server
        redis_host = app.config.get("REDIS_HOST", "localhost")
        redis_port = app.config.get("REDIS_PORT", 6379)
        try:
            redis_client = get_redis_client()
            if redis_client and redis_client.ping():
                dependencies["redis"] = {
                    "status": "healthy",
                    "message": f"Redis connected at {redis_host}:{redis_port}",
                }
            else:
                dependencies["redis"] = {
                    "status": "degraded",
                    "message": f"Redis not responding at {redis_host}:{redis_port}",
                }
                overall_status = "degraded" if overall_status == "healthy" else overall_status
        except Exception as exc:
            dependencies["redis"] = {
                "status": "degraded",
                "message": f"Cannot connect to Redis: {exc}",
            }
            overall_status = "degraded" if overall_status == "healthy" else overall_status

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
        config_files = [".env"]
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

        # 6. Alert Forwarding Pipeline — a saved alert must always carry a
        # forwarding decision.  eas_forwarding_reason is written by every
        # exit path of auto_forward_cap_alert, so a NULL reason means the
        # ingest pipeline died before the decision; "Never evaluated…" is
        # the terminal stamp the poller's catch-up sweep writes when such an
        # alert expired before it could be retried (a missed broadcast).
        try:
            from datetime import timedelta
            from sqlalchemy import and_, or_
            from app_core.models import CAPAlert

            now = utc_now()
            pending_count = (
                CAPAlert.query
                .filter(CAPAlert.eas_forwarded.is_(False))
                .filter(CAPAlert.eas_forwarding_reason.is_(None))
                .filter(CAPAlert.expires.isnot(None))
                .filter(CAPAlert.expires > now)
                .filter(CAPAlert.created_at <= now - timedelta(minutes=3))
                .count()
            )
            missed_count = (
                CAPAlert.query
                .filter(CAPAlert.eas_forwarded.is_(False))
                .filter(CAPAlert.expires.isnot(None))
                .filter(CAPAlert.expires > now - timedelta(hours=24))
                .filter(or_(
                    CAPAlert.eas_forwarding_reason.ilike("Never evaluated%"),
                    and_(
                        CAPAlert.eas_forwarding_reason.is_(None),
                        CAPAlert.expires <= now,
                        CAPAlert.created_at < CAPAlert.expires,
                    ),
                ))
                .count()
            )
            if missed_count:
                dependencies["alert_forwarding"] = {
                    "status": "unhealthy",
                    "message": (
                        f"{missed_count} alert(s) in the last 24h expired without a "
                        f"forwarding decision — broadcast(s) missed; check the system "
                        f"log and poller journal"
                    ),
                    "missed_24h": missed_count,
                    "pending": pending_count,
                }
                overall_status = "unhealthy"
            elif pending_count:
                dependencies["alert_forwarding"] = {
                    "status": "degraded",
                    "message": (
                        f"{pending_count} unexpired alert(s) awaiting a forwarding "
                        f"decision for >3 min — catch-up sweep should retry on the "
                        f"next poll cycle"
                    ),
                    "missed_24h": 0,
                    "pending": pending_count,
                }
                overall_status = "degraded" if overall_status == "healthy" else overall_status
            else:
                dependencies["alert_forwarding"] = {
                    "status": "healthy",
                    "message": "Every saved alert has a forwarding decision",
                    "missed_24h": 0,
                    "pending": 0,
                }
        except Exception as exc:
            dependencies["alert_forwarding"] = {
                "status": "unknown",
                "message": f"Cannot check forwarding pipeline: {exc}",
            }

        # 7. CAP Poller Liveness — if the poller stops cycling, nothing is
        # ingested and nothing can air; surface that here instead of relying
        # on operators to notice an empty alerts page.
        try:
            from datetime import timedelta, timezone as _tz
            from app_core.models import PollHistory

            last_poll = (
                PollHistory.query.order_by(PollHistory.timestamp.desc()).first()
            )
            now = utc_now()
            last_ts = last_poll.timestamp if last_poll else None
            if last_ts is not None and last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=_tz.utc)
            if last_ts is None:
                dependencies["cap_poller"] = {
                    "status": "degraded",
                    "message": "No poll history recorded yet",
                }
                overall_status = "degraded" if overall_status == "healthy" else overall_status
            elif now - last_ts > timedelta(minutes=10):
                age_min = int((now - last_ts).total_seconds() // 60)
                dependencies["cap_poller"] = {
                    "status": "unhealthy",
                    "message": (
                        f"Last poll cycle completed {age_min} min ago — poller "
                        f"appears stalled; no alerts are being ingested"
                    ),
                    "last_poll": last_ts.isoformat(),
                }
                overall_status = "unhealthy"
            else:
                dependencies["cap_poller"] = {
                    "status": "healthy",
                    "message": f"Last poll cycle {last_ts.isoformat()}",
                    "last_poll": last_ts.isoformat(),
                }
        except Exception as exc:
            dependencies["cap_poller"] = {
                "status": "unknown",
                "message": f"Cannot check poller liveness: {exc}",
            }

        # 8. Backup Directory
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

    @app.route("/api/broadcast/state")
    def api_broadcast_state():
        """Current air-chain broadcast state.

        Returns the same payload pushed via the broadcast_state_update
        WebSocket event so clients can:
          1. Read the state immediately on page load (no waiting up to 1s
             for the next push), and
          2. Fall back to polling when the WebSocket connection drops.
        """
        try:
            from app_utils.eas import get_broadcast_state
            state = get_broadcast_state()
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("get_broadcast_state failed: %s", exc)
            state = {"active": False}

        active_alert_count = 0
        try:
            from datetime import datetime, timezone as _tz
            from app_core.models import CAPAlert
            now_utc = datetime.now(_tz.utc)
            active_alert_count = (
                CAPAlert.query.filter(CAPAlert.expires > now_utc).count()
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("active alert count failed: %s", exc)

        payload = dict(state)
        payload["active_alert_count"] = active_alert_count
        payload["timestamp"] = utc_now().timestamp()
        return jsonify(payload)

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
        import platform as _platform
        import socket as _socket
        import sys as _sys
        from app_utils.changelog_parser import parse_all_changelogs

        # Get repository root
        repo_root = Path(__file__).resolve().parents[1]
        current_version = _system_version()

        # Get git information
        git_info = get_git_metadata()

        # Parse changelogs
        try:
            changelogs = parse_all_changelogs(repo_root, current_version)
        except Exception as exc:
            route_logger.debug("Changelog parsing failed: %s", exc)
            changelogs = {}

        location = get_location_settings()
        try:
            _hostname = _socket.gethostname()
        except Exception:  # pragma: no cover - defensive
            _hostname = "unknown"
        version_data = {
            "version": current_version,
            "name": "EAS Station",
            "author": "EAS Station, LLC (KR8MER) / KR8MER Amateur Radio Emergency Communications",
            "description": (
                f"Emergency alert system for {location['county_name']}, "
                f"{location['state_code']}"
            ),
            "timezone": get_location_timezone_name(),
            "led_available": bool(LED_AVAILABLE),
            "vfd_available": bool(VFD_AVAILABLE),
            "oled_available": bool(OLED_AVAILABLE),
            "radio_available": bool(RADIO_AVAILABLE),
            "alsa_available": bool(ALSA_AVAILABLE),
            "pulse_available": bool(PULSE_AVAILABLE),
            "mfa_available": bool(TOTP_AVAILABLE),
            "scipy_available": bool(SCIPY_AVAILABLE),
            "numba_available": bool(NUMBA_AVAILABLE),
            "python_version": _sys.version.split()[0],
            "platform": _platform.platform(terse=True),
            "hostname": _hostname,
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

        git_info = get_git_metadata()
        git_clean = get_git_tree_state()

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
                    "commit": git_info.get("commit_hash_full", "unknown"),
                    "branch": git_info.get("branch", "unknown"),
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

        sitemap_url = None
        try:
            sitemap_url = url_for("sitemap", _external=True)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Unable to build sitemap URL for robots.txt: %s", exc)

        robots_lines = [
            "User-agent: *",
            "Disallow: /admin/",
            "Disallow: /api/",
            "Disallow: /debug/",
            "Allow: /",
        ]

        if sitemap_url:
            robots_lines.append(f"Sitemap: {sitemap_url}")

        return ("\n".join(robots_lines) + "\n", 200, {"Content-Type": "text/plain"})

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
