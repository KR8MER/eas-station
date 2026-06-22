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

"""Web-traffic analytics routes (webalizer/awstats-style dashboard).

Exposes the Traffic Analytics page plus JSON endpoints that aggregate the
``web_request_logs`` table (and login activity from the audit log) into the
charts and tables the dashboard renders. Collection settings are read/written
here so the whole feature is configurable from the web UI.
"""

import os
from typing import Any, Dict

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from app_core.analytics import traffic_stats
from app_core.analytics.traffic_filters import TrafficFilters
from app_core.analytics.web_traffic import TrafficAnalyticsSettings
from app_core.auth import require_permission
from app_core.extensions import db

# Cap GeoIP uploads — GeoLite2-Country is ~6 MB, GeoLite2-City ~60 MB. 128 MB is
# a generous ceiling that still rejects obviously-wrong uploads.
_MAX_GEOIP_BYTES = 128 * 1024 * 1024

# Every MaxMind DB file ends with a metadata section introduced by this marker.
# We can recognise a valid .mmdb by its presence even when the `maxminddb`
# reader package isn't installed yet.
_MMDB_MAGIC = b"\xab\xcd\xefMaxMind.com"


def _has_maxmind_magic(data: bytes) -> bool:
    """Return ``True`` if *data* contains the MaxMind DB metadata marker."""
    # The marker lives near the end of the file; scan the tail for efficiency.
    return _MMDB_MAGIC in data[-262144:]

# Bounds so a crafted ?days= can't ask for an unbounded scan.
_MIN_DAYS = 1
_MAX_DAYS = 365


def _clamp_days(default: int = 30) -> int:
    try:
        days = int(request.args.get("days", default))
    except (TypeError, ValueError):
        return default
    return max(_MIN_DAYS, min(days, _MAX_DAYS))


def register(app: Flask, logger) -> None:
    """Attach traffic-analytics routes to the Flask app."""

    route_logger = logger.getChild("routes_traffic")

    # ------------------------------------------------------------------ UI
    @app.route("/traffic")
    @require_permission("logs.view")
    def traffic_dashboard_page():
        """Legacy route — the dashboard now lives in the unified Security
        Center (Traffic tab). Redirect so old links/bookmarks keep working
        and traffic has exactly one home."""
        return redirect(url_for("security.view_security_center") + "#traffic")

    # ------------------------------------------------------------------ data
    @app.route("/api/traffic/dashboard", methods=["GET"])
    @require_permission("logs.view")
    def traffic_dashboard_data():
        """Return the full dashboard payload.

        Honours ``?days=`` (preset window) or an explicit ``?start=&end=``
        custom range, plus any drill-down dimensions (``?path=``, ``?ip=``,
        ``?country=``, ``?status_family=``, ``?browser=``, ``?os=``,
        ``?method=``) — see :class:`TrafficFilters`.
        """
        try:
            flt = TrafficFilters.from_request(request.args)
            data = traffic_stats.get_full_dashboard(
                self_hosts=_self_hosts(), filters=flt, use_cache=True
            )
            return jsonify({"success": True, "days": flt.days, **data})
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to build traffic dashboard: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/anomalies", methods=["GET"])
    @require_permission("logs.view")
    def traffic_anomalies():
        """Return detected traffic anomalies for the active window/filters."""
        try:
            from app_core.analytics.traffic_anomalies import detect_anomalies

            flt = TrafficFilters.from_request(request.args)
            return jsonify(
                {
                    "success": True,
                    "anomalies": detect_anomalies(filters=flt),
                    "filter_meta": flt.to_query_meta(),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to detect traffic anomalies: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/recent", methods=["GET"])
    @require_permission("logs.view")
    def traffic_recent_requests():
        """Return the most recent recorded requests (honouring any filters)."""
        try:
            try:
                limit = int(request.args.get("limit", 50))
            except (TypeError, ValueError):
                limit = 50
            limit = max(1, min(limit, 500))
            flt = TrafficFilters.from_request(request.args)
            return jsonify(
                {
                    "success": True,
                    "requests": traffic_stats.get_recent_requests(limit, filters=flt),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to load recent requests: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ------------------------------------------------------------------ privacy
    @app.route("/api/traffic/privacy/purge", methods=["POST"])
    @require_permission("system.configure")
    def traffic_privacy_purge():
        """Permanently delete every recorded request for a visitor IP (GDPR)."""
        try:
            payload: Dict[str, Any] = request.get_json(silent=True) or {}
            ip = (payload.get("ip") or "").strip()
            if not ip:
                return jsonify({"success": False, "error": "An IP address is required"}), 400
            from app_core.analytics.traffic_privacy import purge_ip

            result = purge_ip(ip)
            route_logger.info("Traffic privacy: purged %s rows for %s", result["deleted"], ip)
            return jsonify({"success": True, "ip": ip, **result})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Failed to purge traffic for IP: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/privacy/anonymize", methods=["POST"])
    @require_permission("system.configure")
    def traffic_privacy_anonymize():
        """Mask the IP (and clear hostname) on every recorded request for an IP."""
        try:
            payload: Dict[str, Any] = request.get_json(silent=True) or {}
            ip = (payload.get("ip") or "").strip()
            if not ip:
                return jsonify({"success": False, "error": "An IP address is required"}), 400
            from app_core.analytics.traffic_privacy import anonymize_ip

            result = anonymize_ip(ip)
            route_logger.info(
                "Traffic privacy: anonymized %s rows for %s -> %s",
                result["updated"], ip, result["masked"],
            )
            return jsonify({"success": True, "ip": ip, **result})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Failed to anonymize traffic for IP: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ------------------------------------------------------------------ purge all
    @app.route("/api/traffic/purge-all", methods=["POST"])
    @require_permission("system.configure")
    def traffic_purge_all():
        """Permanently delete EVERY recorded request (full analytics reset).

        Wipes the ``web_request_logs`` table to reclaim space and speed up the
        dashboard. Collection settings and any GeoIP databases are preserved —
        only the recorded rows are removed. There is no undo.
        """
        try:
            from app_core.analytics.traffic_privacy import purge_all

            result = purge_all()
            route_logger.warning(
                "Traffic analytics: purged ALL recorded rows (%s deleted)",
                result["deleted"],
            )
            return jsonify({"success": True, **result})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Failed to purge all traffic: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ------------------------------------------------------------------ beacon
    @app.route("/api/traffic/client", methods=["GET"])
    def traffic_client_beacon():
        """Record client-only attributes (screen resolution) in the session.

        Screen resolution isn't available in HTTP headers, so a tiny script on
        every page reports it here once per browser session. The value is stashed
        in the session cookie and rides along on subsequent requests, where
        ``_record_traffic`` persists it. Public + GET so every visitor (even
        unauthenticated) contributes, and to avoid CSRF friction for a harmless,
        non-sensitive value.
        """
        try:
            width = request.args.get("w", type=int)
            height = request.args.get("h", type=int)
            if width and height and 0 < width <= 20000 and 0 < height <= 20000:
                session["client_screen"] = f"{width}x{height}"
            return jsonify({"success": True})
        except Exception:  # pragma: no cover - beacon must never error loudly
            return jsonify({"success": False}), 200

    # ------------------------------------------------------------------ settings
    @app.route("/api/traffic/settings", methods=["GET"])
    @require_permission("logs.view")
    def traffic_get_settings():
        """Return the current traffic-collection settings."""
        try:
            settings = TrafficAnalyticsSettings.get_settings()
            return jsonify(
                {
                    "success": True,
                    "settings": settings.to_dict(),
                    "geoip_status": _geoip_status(settings),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to load traffic settings: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/settings", methods=["POST"])
    @require_permission("system.configure")
    def traffic_update_settings():
        """Persist updated traffic-collection settings."""
        try:
            payload: Dict[str, Any] = request.get_json(silent=True) or {}
            settings = TrafficAnalyticsSettings.get_settings()

            if "enabled" in payload:
                settings.enabled = _to_bool(payload["enabled"])
            if "log_api_requests" in payload:
                settings.log_api_requests = _to_bool(payload["log_api_requests"])
            if "log_authenticated_only" in payload:
                settings.log_authenticated_only = _to_bool(payload["log_authenticated_only"])
            if "exclude_bots" in payload:
                settings.exclude_bots = _to_bool(payload["exclude_bots"])
            if "resolve_hostnames" in payload:
                settings.resolve_hostnames = _to_bool(payload["resolve_hostnames"])
            if "exclude_loopback" in payload:
                settings.exclude_loopback = _to_bool(payload["exclude_loopback"])
            if "excluded_paths" in payload:
                raw = payload.get("excluded_paths")
                settings.excluded_paths = (raw or "").strip()[:4000] or None
            if "anonymize_ip" in payload:
                settings.anonymize_ip = _to_bool(payload["anonymize_ip"])
            if "anomaly_detection_enabled" in payload:
                settings.anomaly_detection_enabled = _to_bool(
                    payload["anomaly_detection_enabled"]
                )
            for key, lo, hi in (
                ("anomaly_error_rate_pct", 1, 100),
                ("anomaly_5xx_threshold", 1, 100000),
                ("anomaly_failed_login_threshold", 1, 100000),
                ("anomaly_scanner_threshold", 1, 100000),
            ):
                if key in payload:
                    try:
                        value = int(payload[key])
                    except (TypeError, ValueError):
                        return jsonify(
                            {"success": False, "error": f"{key} must be a number"}
                        ), 400
                    setattr(settings, key, max(lo, min(value, hi)))
            if "retention_days" in payload:
                try:
                    retention = int(payload["retention_days"])
                except (TypeError, ValueError):
                    return jsonify(
                        {"success": False, "error": "retention_days must be a number"}
                    ), 400
                settings.retention_days = max(1, min(retention, 3650))
            if "geoip_database_path" in payload:
                raw_path = payload.get("geoip_database_path")
                new_path = (raw_path or "").strip()[:512] or None
                if new_path != settings.geoip_database_path:
                    # Drop cached readers so the new database is picked up.
                    from app_core.analytics.geo import reset_readers

                    reset_readers()
                settings.geoip_database_path = new_path
            if "geoip_asn_database_path" in payload:
                raw_path = payload.get("geoip_asn_database_path")
                new_path = (raw_path or "").strip()[:512] or None
                if new_path != settings.geoip_asn_database_path:
                    from app_core.analytics.geo import reset_readers

                    reset_readers()
                settings.geoip_asn_database_path = new_path

            db.session.commit()
            route_logger.info("Traffic analytics settings updated")
            return jsonify({"success": True, "settings": settings.to_dict()})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Failed to update traffic settings: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/geoip/upload", methods=["POST"])
    @require_permission("system.configure")
    def traffic_upload_geoip():
        """Upload a MaxMind GeoLite2 ``.mmdb`` file from the browser.

        Saves the database under ``data/geoip/`` and points the Traffic
        Analytics settings at it — so an operator never needs shell access to
        enable country/flag resolution. The upload is validated by opening it
        with the ``maxminddb`` reader before it is accepted.
        """
        try:
            if "file" not in request.files:
                return jsonify({"success": False, "error": "No file uploaded"}), 400
            upload = request.files["file"]
            if not upload.filename:
                return jsonify({"success": False, "error": "No file selected"}), 400
            if not upload.filename.lower().endswith(".mmdb"):
                return jsonify(
                    {"success": False, "error": "File must be a MaxMind .mmdb database"}
                ), 400

            data = upload.read()
            if not data:
                return jsonify({"success": False, "error": "Uploaded file is empty"}), 400
            if len(data) > _MAX_GEOIP_BYTES:
                return jsonify(
                    {"success": False, "error": "File exceeds the 128 MB limit"}
                ), 400

            geoip_dir = os.path.join(app.root_path, "data", "geoip")
            os.makedirs(geoip_dir, exist_ok=True)
            tmp_path = os.path.join(geoip_dir, "_upload.mmdb.tmp")
            with open(tmp_path, "wb") as fh:
                fh.write(data)

            # Validate + detect the database TYPE before committing. Prefer the
            # real `maxminddb` reader (which exposes the type via metadata); if the
            # package isn't installed yet, fall back to the file's magic marker so
            # the upload still works (assuming Country — the common case).
            reader_available = True
            note = None
            db_type = "GeoLite2-Country"
            try:
                import maxminddb

                with maxminddb.open_database(tmp_path) as r:
                    db_type = r.metadata().database_type or db_type
            except ImportError:
                reader_available = False
                if not _has_maxmind_magic(data):
                    _safe_remove(tmp_path)
                    return jsonify(
                        {"success": False, "error": "File is not a MaxMind .mmdb database"}
                    ), 400
                note = (
                    "Database stored (assumed Country — type can't be detected "
                    "until 'geoip2' is installed). Run pip install -r "
                    "requirements.txt and restart for resolution to work."
                )
            except Exception as exc:
                _safe_remove(tmp_path)
                return jsonify(
                    {"success": False, "error": f"Not a valid GeoIP database: {exc}"}
                ), 400

            # Route the file to a canonical name + the matching setting based on
            # its type, so Country/City share the location DB slot and ASN gets
            # its own slot. Re-uploads of the same type replace the old file.
            settings = TrafficAnalyticsSettings.get_settings()
            if "ASN" in db_type:
                dest_path = os.path.join(geoip_dir, "GeoLite2-ASN.mmdb")
                kind = "ASN (network operator / ISP)"
            elif "City" in db_type:
                dest_path = os.path.join(geoip_dir, "GeoLite2-City.mmdb")
                kind = "City (country, region, city)"
            else:
                dest_path = os.path.join(geoip_dir, "GeoLite2-Country.mmdb")
                kind = "Country"
            os.replace(tmp_path, dest_path)

            if "ASN" in db_type:
                settings.geoip_asn_database_path = dest_path
            else:
                settings.geoip_database_path = dest_path

            # Drop cached readers so the new database is picked up.
            from app_core.analytics.geo import reset_readers

            db.session.commit()
            reset_readers()

            route_logger.info(
                "GeoIP database uploaded to %s (type=%s, reader_available=%s)",
                dest_path,
                db_type,
                reader_available,
            )
            payload = {
                "success": True,
                "path": dest_path,
                "kind": kind,
                "settings": settings.to_dict(),
            }
            if note:
                payload["note"] = note
            return jsonify(payload)
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Failed to upload GeoIP database: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500


def _self_hosts() -> set:
    """Hostnames to treat as 'internal' for referrer filtering (own host ± www)."""
    from flask import request

    hosts = set()
    try:
        host = (request.host or "").split(":")[0].lower()
        if host:
            hosts.add(host)
            hosts.add("www." + host if not host.startswith("www.") else host[4:])
    except Exception:
        pass
    return hosts


def _geoip_status(settings) -> Dict[str, Any]:
    """Report whether country/flag resolution is actually working.

    Surfaces three facts so the operator can diagnose missing flags from the UI:
    the reader package is importable, a database file is configured & present,
    and a sample public-IP lookup resolves to a country.
    """
    status: Dict[str, Any] = {
        "reader_installed": False,
        "database_configured": bool(settings.geoip_database_path),
        "database_present": False,
        "resolves": False,
        "sample": None,
        "message": "",
    }
    try:
        import geoip2  # noqa: F401
        import maxminddb  # noqa: F401

        status["reader_installed"] = True
    except Exception:
        status["message"] = "geoip2 not installed — run pip install -r requirements.txt and restart."
        return status

    path = settings.geoip_database_path
    if not path:
        status["message"] = "No GeoIP database configured — upload a GeoLite2 .mmdb above."
        return status
    if not os.path.exists(path):
        status["message"] = f"Database path not found: {path}"
        return status
    status["database_present"] = True

    try:
        from app_core.analytics.geo import classify_location, resolve_asn

        result = classify_location("8.8.8.8", path)
        if result.get("country_code"):
            status["resolves"] = True
            city = result.get("city")
            sample = f"8.8.8.8 → {result['label']} ({result['country_code']})"
            if city:
                sample += f", {city}"
            status["sample"] = sample
            status["message"] = (
                "Active — public IPs resolve to "
                + ("country/city/flags." if city else "countries/flags.")
            )
        else:
            status["message"] = "Database loaded but did not resolve a sample IP (is it a Country/City DB?)."

        # ASN status (separate database).
        asn_path = settings.geoip_asn_database_path
        status["asn_configured"] = bool(asn_path)
        if asn_path and os.path.exists(asn_path):
            org = resolve_asn("8.8.8.8", asn_path)
            if org:
                status["asn_resolves"] = True
                status["asn_sample"] = f"8.8.8.8 → {org}"
    except Exception as exc:  # pragma: no cover - defensive
        status["message"] = f"Lookup failed: {exc}"
    return status


def _safe_remove(path: str) -> None:
    """Delete *path* if present, ignoring errors (cleanup of a rejected upload)."""
    try:
        os.remove(path)
    except OSError:
        pass


def _to_bool(value: Any) -> bool:
    """Coerce assorted truthy representations (JSON bool, "true", 1) to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False
