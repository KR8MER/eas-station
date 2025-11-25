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

from __future__ import annotations

"""Public-facing Flask routes extracted from the historical app module."""

import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, render_template, request, url_for, Response
from sqlalchemy import func, or_

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.eas_storage import get_eas_static_prefix, format_local_datetime
from app_core.extensions import db
from app_core.models import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    Boundary,
    CAPAlert,
    EASDecodedAudio,
    EASMessage,
    GPIOActivationLog,
    Intersection,
    ManualEASActivation,
    PollDebugRecord,
    PollHistory,
    SystemLog,
)
from app_core.system_health import get_system_health
from app_utils import format_bytes, format_uptime, utc_now
from webapp import documentation
from app_utils.pdf_generator import generate_pdf_document


def register(app: Flask, logger) -> None:
    """Attach public and operator-facing pages to the Flask app."""

    route_logger = logger.getChild("routes_public")
    policy_docs_root = Path(app.root_path) / "docs" / "policies"

    def _render_policy_page(doc_filename: str, page_title: str):
        policy_path = policy_docs_root / doc_filename
        try:
            with policy_path.open("r", encoding="utf-8") as md_file:
                markdown_content = md_file.read()
            html_content = documentation._markdown_to_html(markdown_content)
            structure = documentation._get_docs_structure()
            return render_template(
                "doc_viewer.html",
                title=page_title,
                content=html_content,
                doc_path=f"policies/{policy_path.stem}",
                structure=structure,
            )
        except FileNotFoundError:
            route_logger.error("Policy document not found: %s", policy_path)
        except Exception as exc:  # pragma: no cover - renderable fallback
            route_logger.error("Error rendering policy page %s: %s", doc_filename, exc)

        # Fallback to legacy static templates to keep the route available
        return render_template(f"{policy_path.stem}.html")

    @app.route("/")
    def index():
        try:
            return render_template("index.html")
        except Exception as exc:  # pragma: no cover - fallback rendering
            route_logger.error("Error rendering index template: %s", exc)
            return (
                "<h1>NOAA CAP Alerts System</h1><p>Map interface loading...</p>"
                "<p><a href='/stats'>📊 Statistics</a> | "
                "<a href='/alerts'>📝 Alerts History</a> | "
                "<a href='/admin'>⚙️ Admin</a></p>"
            )

    @app.route("/sitemap.xml")
    def sitemap():
        """Expose an XML sitemap for search engines and uptime robots."""

        urls: List[Dict[str, str]] = []
        today_iso = utc_now().date().isoformat()

        static_endpoints: List[Tuple[str, str, str]] = [
            ("index", "daily", "1.0"),
            ("stats", "daily", "0.8"),
            ("alerts", "hourly", "0.9"),
            ("help_page", "weekly", "0.5"),
            ("about_page", "weekly", "0.5"),
            ("privacy_page", "yearly", "0.3"),
            ("terms_page", "yearly", "0.3"),
            ("system_health_page", "hourly", "0.6"),
            ("logs", "hourly", "0.4"),
        ]

        for endpoint, changefreq, priority in static_endpoints:
            try:
                urls.append(
                    {
                        "loc": url_for(endpoint, _external=True),
                        "lastmod": today_iso,
                        "changefreq": changefreq,
                        "priority": priority,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive
                route_logger.debug("Skipping sitemap endpoint %s: %s", endpoint, exc)

        alert_entries: List[CAPAlert] = []
        try:
            alert_entries = (
                CAPAlert.query.order_by(CAPAlert.sent.desc())
                .limit(app.config.get("SITEMAP_ALERT_LIMIT", 50))
                .all()
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.warning("Unable to load alerts for sitemap: %s", exc)

        for alert in alert_entries:
            try:
                alert_url = url_for("api.alert_detail", alert_id=alert.id, _external=True)
            except Exception as exc:  # pragma: no cover - defensive
                route_logger.debug("Skipping alert %s in sitemap: %s", alert.id, exc)
                continue

            last_modified = alert.updated_at or alert.sent or utc_now()
            urls.append(
                {
                    "loc": alert_url,
                    "lastmod": last_modified.isoformat(),
                    "changefreq": "hourly",
                    "priority": "0.7",
                }
            )

        xml_lines = [
            "<?xml version='1.0' encoding='UTF-8'?>",
            "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>",
        ]

        for entry in urls:
            xml_lines.append("  <url>")
            xml_lines.append(f"    <loc>{escape(entry['loc'])}</loc>")
            if entry.get("lastmod"):
                xml_lines.append(f"    <lastmod>{escape(entry['lastmod'])}</lastmod>")
            xml_lines.append(f"    <changefreq>{entry['changefreq']}</changefreq>")
            xml_lines.append(f"    <priority>{entry['priority']}</priority>")
            xml_lines.append("  </url>")

        xml_lines.append("</urlset>")

        return Response("\n".join(xml_lines), mimetype="application/xml")

    @app.route("/stats")
    def stats():
        try:
            stats_data: Dict[str, Any] = {}

            try:
                stats_data.update(
                    {
                        "total_boundaries": Boundary.query.count(),
                        "total_alerts": CAPAlert.query.count(),
                        "active_alerts": get_active_alerts_query().count(),
                        "expired_alerts": get_expired_alerts_query().count(),
                    }
                )
            except Exception as exc:
                route_logger.error("Error getting basic counts: %s", exc)
                stats_data.update(
                    {
                        "total_boundaries": 0,
                        "total_alerts": 0,
                        "active_alerts": 0,
                        "expired_alerts": 0,
                    }
                )

            try:
                boundary_stats = (
                    db.session.query(
                        Boundary.type, func.count(Boundary.id).label("count")
                    )
                    .group_by(Boundary.type)
                    .all()
                )
                stats_data["boundary_stats"] = [
                    {"type": boundary_type, "count": count}
                    for boundary_type, count in boundary_stats
                ]
            except Exception as exc:
                route_logger.error("Error getting boundary stats: %s", exc)
                stats_data["boundary_stats"] = []

            try:
                alert_by_status = (
                    db.session.query(
                        CAPAlert.status, func.count(CAPAlert.id).label("count")
                    )
                    .group_by(CAPAlert.status)
                    .all()
                )
                stats_data["alert_by_status"] = [
                    {"status": status, "count": count}
                    for status, count in alert_by_status
                ]

                alert_by_severity = (
                    db.session.query(
                        CAPAlert.severity, func.count(CAPAlert.id).label("count")
                    )
                    .filter(CAPAlert.severity.isnot(None))
                    .group_by(CAPAlert.severity)
                    .all()
                )
                stats_data["alert_by_severity"] = [
                    {"severity": severity, "count": count}
                    for severity, count in alert_by_severity
                ]

                alert_by_event = (
                    db.session.query(
                        CAPAlert.event, func.count(CAPAlert.id).label("count")
                    )
                    .group_by(CAPAlert.event)
                    .order_by(func.count(CAPAlert.id).desc())
                    .limit(10)
                    .all()
                )
                stats_data["alert_by_event"] = [
                    {"event": event, "count": count}
                    for event, count in alert_by_event
                ]
            except Exception as exc:
                route_logger.error("Error getting alert category stats: %s", exc)
                stats_data.update(
                    {
                        "alert_by_status": [],
                        "alert_by_severity": [],
                        "alert_by_event": [],
                    }
                )

            try:
                alert_by_hour = (
                    db.session.query(
                        func.extract("hour", CAPAlert.sent).label("hour"),
                        func.count(CAPAlert.id).label("count"),
                    )
                    .group_by(func.extract("hour", CAPAlert.sent))
                    .all()
                )

                hourly_data = [0] * 24
                for hour, count in alert_by_hour:
                    if hour is not None:
                        hourly_data[int(hour)] = count
                stats_data["alert_by_hour"] = hourly_data

                alert_by_dow = (
                    db.session.query(
                        func.extract("dow", CAPAlert.sent).label("dow"),
                        func.count(CAPAlert.id).label("count"),
                    )
                    .group_by(func.extract("dow", CAPAlert.sent))
                    .all()
                )

                dow_data = [0] * 7
                for dow, count in alert_by_dow:
                    if dow is not None:
                        dow_data[int(dow)] = count
                stats_data["alert_by_dow"] = dow_data

                alert_by_month = (
                    db.session.query(
                        func.extract("month", CAPAlert.sent).label("month"),
                        func.count(CAPAlert.id).label("count"),
                    )
                    .group_by(func.extract("month", CAPAlert.sent))
                    .all()
                )

                monthly_data = [0] * 12
                for month, count in alert_by_month:
                    if month is not None:
                        monthly_data[int(month) - 1] = count
                stats_data["alert_by_month"] = monthly_data

                alert_by_year = (
                    db.session.query(
                        func.extract("year", CAPAlert.sent).label("year"),
                        func.count(CAPAlert.id).label("count"),
                    )
                    .group_by(func.extract("year", CAPAlert.sent))
                    .order_by(func.extract("year", CAPAlert.sent))
                    .all()
                )
                stats_data["alert_by_year"] = [
                    {"year": int(year), "count": count}
                    for year, count in alert_by_year
                    if year
                ]
            except Exception as exc:
                route_logger.error("Error getting time-based stats: %s", exc)
                stats_data.update(
                    {
                        "alert_by_hour": [0] * 24,
                        "alert_by_dow": [0] * 7,
                        "alert_by_month": [0] * 12,
                        "alert_by_year": [],
                    }
                )

            try:
                most_affected = (
                    db.session.query(
                        Boundary.name,
                        Boundary.type,
                        func.count(Intersection.id).label("alert_count"),
                    )
                    .join(Intersection, Boundary.id == Intersection.boundary_id)
                    .group_by(Boundary.id, Boundary.name, Boundary.type)
                    .order_by(func.count(Intersection.id).desc())
                    .limit(10)
                    .all()
                )
                stats_data["most_affected_boundaries"] = [
                    {"name": name, "type": b_type, "count": count}
                    for name, b_type, count in most_affected
                ]
            except Exception as exc:
                route_logger.error("Error getting affected boundaries: %s", exc)
                stats_data["most_affected_boundaries"] = []

            try:
                durations = (
                    db.session.query(
                        CAPAlert.event,
                        (
                            func.extract("epoch", CAPAlert.expires)
                            - func.extract("epoch", CAPAlert.sent)
                        ).label("duration_seconds"),
                    )
                    .filter(
                        CAPAlert.expires.isnot(None),
                        CAPAlert.sent.isnot(None),
                    )
                    .all()
                )

                duration_by_event: Dict[str, List[float]] = defaultdict(list)
                for event, duration in durations:
                    if duration and duration > 0:
                        duration_by_event[event].append(duration / 3600)

                stats_data["duration_stats"] = [
                    {
                        "event": event,
                        "count": len(values),
                        "average": round(sum(values) / len(values), 2) if values else 0,
                        "minimum": round(min(values), 2) if values else 0,
                        "maximum": round(max(values), 2) if values else 0,
                    }
                    for event, values in sorted(
                        duration_by_event.items(), key=lambda item: sum(item[1]), reverse=True
                    )
                ]
            except Exception as exc:
                route_logger.error("Error calculating duration stats: %s", exc)
                stats_data["duration_stats"] = []

            try:
                recent_alerts = (
                    db.session.query(
                        CAPAlert.id,
                        CAPAlert.identifier,
                        CAPAlert.sent,
                        CAPAlert.expires,
                        CAPAlert.severity,
                        CAPAlert.status,
                        CAPAlert.event,
                        CAPAlert.source,
                    )
                    .order_by(CAPAlert.sent.desc())
                    .limit(2500)
                    .all()
                )

                severities: set[str] = set()
                statuses: set[str] = set()
                events: set[str] = set()
                daily_totals: Dict[str, int] = defaultdict(int)
                hourly_matrix = [[0 for _ in range(24)] for _ in range(7)]
                alert_events: List[Dict[str, Any]] = []

                for (
                    alert_id,
                    identifier,
                    sent,
                    expires,
                    severity,
                    status,
                    event,
                    source,
                ) in recent_alerts:
                    if severity:
                        severities.add(severity)
                    if status:
                        statuses.add(status)
                    if event:
                        events.add(event)

                    if sent:
                        day_key = sent.date().isoformat()
                        daily_totals[day_key] += 1
                        dow_index = ((sent.weekday() + 1) % 7)
                        hour = sent.hour
                        hourly_matrix[dow_index][hour] += 1

                    alert_events.append(
                        {
                            "id": alert_id,
                            "identifier": identifier,
                            "sent": sent.isoformat() if sent else None,
                            "expires": expires.isoformat() if expires else None,
                            "severity": severity or "Unknown",
                            "status": status or "Unknown",
                            "event": event or "Unknown",
                            "source": source or "Unknown",
                        }
                    )

                sorted_daily = sorted(daily_totals.items())
                daily_alerts = [
                    {"date": day, "count": count} for day, count in sorted_daily
                ]

                stats_data["alert_events"] = alert_events
                stats_data["filter_options"] = {
                    "severities": sorted(severities),
                    "statuses": sorted(statuses),
                    "events": sorted(events),
                }
                stats_data["daily_alerts"] = daily_alerts
                stats_data["recent_by_day"] = daily_alerts[-30:]
                stats_data["dow_hour_matrix"] = hourly_matrix
            except Exception as exc:
                route_logger.error("Error preparing alert events for stats: %s", exc)
                stats_data["alert_events"] = []
                stats_data["filter_options"] = {
                    "severities": [],
                    "statuses": [],
                    "events": [],
                }
                stats_data["daily_alerts"] = []
                stats_data["recent_by_day"] = []
                stats_data["dow_hour_matrix"] = [[0 for _ in range(24)] for _ in range(7)]

            try:
                polling_records = (
                    PollHistory.query.order_by(PollHistory.timestamp.desc())
                    .limit(200)
                    .all()
                )
                if polling_records:
                    total_runs = len(polling_records)
                    success_values = {"success", "ok", "completed"}
                    successes = sum(
                        1
                        for record in polling_records
                        if (record.status or "").lower() in success_values
                        and not record.error_message
                    )
                    failures = sum(
                        1
                        for record in polling_records
                        if (record.status or "").lower() not in success_values
                        or bool(record.error_message)
                    )
                    avg_execution = (
                        sum(record.execution_time_ms or 0 for record in polling_records)
                        / total_runs
                    )
                    last_run = polling_records[0]
                    last_error = next(
                        (record for record in polling_records if record.error_message),
                        None,
                    )
                    recent_runs = [
                        {
                            "timestamp": record.timestamp.isoformat()
                            if record.timestamp
                            else None,
                            "status": record.status,
                            "alerts_fetched": record.alerts_fetched,
                            "alerts_new": record.alerts_new,
                            "alerts_updated": record.alerts_updated,
                            "error": record.error_message,
                            "execution_time_ms": record.execution_time_ms,
                            "data_source": record.data_source,
                        }
                        for record in polling_records[:10]
                    ]

                    stats_data["polling"] = {
                        "success_rate": successes / total_runs if total_runs else 0,
                        "total_runs": total_runs,
                        "failed_runs": failures,
                        "average_execution_ms": avg_execution,
                        "last_run_status": last_run.status if last_run else None,
                        "last_run_timestamp": last_run.timestamp.isoformat()
                        if last_run and last_run.timestamp
                        else None,
                        "last_error": last_error.error_message if last_error else None,
                        "last_error_timestamp": last_error.timestamp.isoformat()
                        if last_error and last_error.timestamp
                        else None,
                        "recent_runs": recent_runs,
                    }
                else:
                    stats_data["polling"] = {
                        "success_rate": 0,
                        "total_runs": 0,
                        "failed_runs": 0,
                        "recent_runs": [],
                    }
            except Exception as exc:
                route_logger.error("Error calculating polling metrics: %s", exc)
                stats_data["polling"] = {
                    "success_rate": 0,
                    "total_runs": 0,
                    "failed_runs": 0,
                    "recent_runs": [],
                }

            stats_data.setdefault("boundary_stats", [])
            stats_data.setdefault("alert_by_status", [])
            stats_data.setdefault("alert_by_severity", [])
            stats_data.setdefault("alert_by_event", [])
            stats_data.setdefault("alert_by_hour", [0] * 24)
            stats_data.setdefault("alert_by_dow", [0] * 7)
            stats_data.setdefault("alert_by_month", [0] * 12)
            stats_data.setdefault("alert_by_year", [])
            stats_data.setdefault("most_affected_boundaries", [])
            stats_data.setdefault("duration_stats", [])
            stats_data.setdefault("avg_durations", stats_data.get("duration_stats", []))
            stats_data.setdefault("recent_by_day", [])
            stats_data.setdefault("alert_events", [])
            stats_data.setdefault("daily_alerts", [])
            stats_data.setdefault("dow_hour_matrix", [[0] * 24 for _ in range(7)])
            stats_data.setdefault("lifecycle_timeline", [])
            stats_data.setdefault(
                "filter_options",
                {"severities": [], "statuses": [], "events": []},
            )
            stats_data.setdefault("polling", {})

            return render_template("stats.html", **stats_data)
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading statistics: %s", exc)
            return (
                "<h1>Error loading statistics</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/about")
    def about_page():
        try:
            return render_template("about.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering about page: %s", exc)
            return (
                "<h1>About</h1><p>Project documentation is available in docs/reference/ABOUT.md on the server.</p>"
            )

    @app.route("/help")
    def help_page():
        try:
            return render_template("help.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering help page: %s", exc)
            return (
                "<h1>Help</h1><p>Refer to docs/guides/HELP.md in the repository for the full operations guide.</p>"
            )

    @app.route("/terms")
    def terms_page():
        return _render_policy_page("TERMS_OF_USE.md", "Terms of Use")

    @app.route("/privacy")
    def privacy_page():
        return _render_policy_page("PRIVACY_POLICY.md", "Privacy Policy")

    @app.route("/system_health")
    def system_health_page():
        try:
            health_data = get_system_health(logger=route_logger)

            # Check if the backend returned an error instead of health data
            if "error" in health_data and "system" not in health_data:
                error_msg = health_data.get("error", "Unknown error")
                route_logger.error("System health backend error: %s", error_msg)
                return (
                    "<h1>Error loading system health</h1>"
                    f"<p>{error_msg}</p><p><a href='/'>← Back to Main</a></p>"
                )

            template_context = dict(health_data)
            template_context["format_bytes"] = format_bytes
            template_context["format_uptime"] = format_uptime
            template_context["health_data_json"] = json.dumps(health_data)
            return render_template("system_health.html", **template_context)
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading system health: %s", exc)
            return (
                "<h1>Error loading system health</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/alerts")
    def alerts():
        try:
            # Validate pagination parameters
            page = request.args.get("page", 1, type=int)
            page = max(1, page)  # Ensure page is at least 1
            per_page = request.args.get("per_page", 25, type=int)
            per_page = min(max(per_page, 10), 100)  # Clamp between 10 and 100

            search = request.args.get("search", "").strip()
            status_filter = request.args.get("status", "").strip()
            severity_filter = request.args.get("severity", "").strip()
            event_filter = request.args.get("event", "").strip()
            source_filter = request.args.get("source", "").strip()
            show_expired_raw = request.args.get("show_expired", "")
            show_expired = str(show_expired_raw).lower() in {
                "true",
                "1",
                "t",
                "yes",
                "on",
            }

            query = CAPAlert.query

            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        CAPAlert.headline.ilike(search_term),
                        CAPAlert.description.ilike(search_term),
                        CAPAlert.event.ilike(search_term),
                        CAPAlert.area_desc.ilike(search_term),
                    )
                )

            if status_filter:
                query = query.filter(CAPAlert.status == status_filter)
            if severity_filter:
                query = query.filter(CAPAlert.severity == severity_filter)
            if event_filter:
                query = query.filter(CAPAlert.event == event_filter)
            if source_filter:
                query = query.filter(CAPAlert.source == source_filter)

            if not show_expired:
                query = query.filter(
                    or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
                ).filter(CAPAlert.status != "Expired")

            query = query.order_by(CAPAlert.sent.desc())

            try:
                pagination = query.paginate(page=page, per_page=per_page, error_out=False)
                alerts_list = pagination.items
            except Exception as exc:
                route_logger.warning("Pagination error: %s", exc)
                total_count = query.count()
                offset = (page - 1) * per_page
                alerts_list = query.offset(offset).limit(per_page).all()

                class MockPagination:
                    def __init__(self, page_num: int, page_size: int, total: int, items):
                        self.page = page_num
                        self.per_page = page_size
                        self.total = total
                        self.items = items
                        self.pages = (
                            (total + page_size - 1) // page_size if page_size > 0 else 1
                        )
                        self.has_prev = page_num > 1
                        self.has_next = page_num < self.pages
                        self.prev_num = page_num - 1 if self.has_prev else None
                        self.next_num = page_num + 1 if self.has_next else None

                    def iter_pages(
                        self,
                        left_edge: int = 2,
                        left_current: int = 2,
                        right_current: int = 3,
                        right_edge: int = 2,
                    ):
                        last = self.pages
                        for num in range(1, last + 1):
                            if (
                                num <= left_edge
                                or (self.page - left_current - 1 < num < self.page + right_current)
                                or num > last - right_edge
                            ):
                                yield num
                            elif num == left_edge + 1 or num == self.page + right_current:
                                yield None

                pagination = MockPagination(page, per_page, total_count, alerts_list)

            audio_map: Dict[int, List[Dict[str, Any]]] = {}
            if alerts_list:
                alert_ids = [alert.id for alert in alerts_list if getattr(alert, "id", None)]
                if alert_ids:
                    try:
                        eas_messages = (
                            EASMessage.query
                            .filter(EASMessage.cap_alert_id.in_(alert_ids))
                            .order_by(EASMessage.created_at.desc())
                            .all()
                        )

                        static_prefix = get_eas_static_prefix()

                        def _static_path(filename: Optional[str]) -> Optional[str]:
                            if not filename:
                                return None
                            parts = [static_prefix, filename] if static_prefix else [filename]
                            return "/".join(part for part in parts if part)

                        for message in eas_messages:
                            if not message.cap_alert_id:
                                continue

                            audio_entries = audio_map.setdefault(message.cap_alert_id, [])

                            audio_url = url_for("eas_message_audio", message_id=message.id)
                            if message.text_payload:
                                text_url = url_for("eas_message_summary", message_id=message.id)
                            else:
                                text_path = _static_path(message.text_filename)
                                text_url = (
                                    url_for("static", filename=text_path) if text_path else None
                                )

                            audio_entries.append(
                                {
                                    "id": message.id,
                                    "created_at": message.created_at,
                                    "audio_url": audio_url,
                                    "text_url": text_url,
                                    "detail_url": url_for(
                                        "audio_detail", message_id=message.id
                                    ),
                                }
                            )
                    except Exception as exc:
                        route_logger.warning("Error loading EAS messages for alerts: %s", exc)

            manual_messages: List[ManualEASActivation] = []
            try:
                manual_messages = (
                    ManualEASActivation.query
                    .order_by(ManualEASActivation.created_at.desc())
                    .limit(10)
                    .all()
                )
            except Exception as exc:
                route_logger.warning("Error loading manual activations: %s", exc)

            current_filters = {
                "search": search,
                "status": status_filter,
                "severity": severity_filter,
                "event": event_filter,
                "source": source_filter,
                "per_page": per_page,
                "show_expired": show_expired,
            }

            return render_template(
                "alerts.html",
                alerts=alerts_list,
                pagination=pagination,
                audio_map=audio_map,
                manual_messages=manual_messages,
                current_filters=current_filters,
            )
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading alerts: %s", exc)
            return (
                "<h1>Error loading alerts</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/alerts/export.pdf")
    def alerts_export_pdf():
        """
        Export alerts list as PDF - server-side from database.

        This endpoint generates a PDF document containing filtered alerts from the
        alerts history page. It respects all current filters applied by the user and
        provides a tamper-proof, archival-quality export for compliance and reporting.

        Query Parameters:
            search (str): Text search across headline, description, event, area_desc
            status (str): Filter by alert status (Actual, Test, Exercise, etc.)
            severity (str): Filter by severity (Extreme, Severe, Moderate, Minor)
            event (str): Filter by event type (e.g., "Tornado Warning")
            source (str): Filter by alert source (e.g., "NWS")
            show_expired (bool): Include expired alerts (accepts: true, 1, t, yes, on)
            per_page (str): Pagination setting (informational, not used in PDF export)

        Returns:
            Response: PDF document with application/pdf mimetype
                     Includes Content-Disposition header for inline display
                     Filename format: alerts_export_YYYYMMDD.pdf

        Limits:
            - Maximum 500 alerts per PDF for performance
            - Descriptions truncated to 500 characters
            - Text-only export (no audio or multimedia)

        See Also:
            - /alerts route for main alerts page
            - /alerts/<id>/export.pdf for individual alert PDF export
            - docs/alerts-pdf-export.md for comprehensive documentation
        """
        try:
            from datetime import datetime

            # ============================================================
            # STEP 1: Parse and validate query parameters
            # ============================================================
            # Extract filter parameters from request - these mirror the
            # filters available on the main /alerts page to ensure
            # consistency between the UI and exported PDF

            search = request.args.get("search", "").strip()
            status_filter = request.args.get("status", "").strip()
            severity_filter = request.args.get("severity", "").strip()
            event_filter = request.args.get("event", "").strip()
            source_filter = request.args.get("source", "").strip()

            # Handle show_expired as boolean - accepts multiple formats
            # for maximum compatibility with different URL builders
            show_expired_raw = request.args.get("show_expired", "")
            show_expired = str(show_expired_raw).lower() in {
                "true",
                "1",
                "t",
                "yes",
                "on",
            }

            # per_page captured but not used - PDF export ignores pagination
            per_page = request.args.get("per_page", "25", type=str)

            # ============================================================
            # STEP 2: Build database query with filters
            # ============================================================
            # Uses same query logic as /alerts route to ensure exported
            # data matches what user sees in the UI

            query = CAPAlert.query

            # Text search: case-insensitive partial match across multiple fields
            # Uses OR logic so matching any field will include the alert
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        CAPAlert.headline.ilike(search_term),
                        CAPAlert.description.ilike(search_term),
                        CAPAlert.event.ilike(search_term),
                        CAPAlert.area_desc.ilike(search_term),
                    )
                )

            # Exact match filters: Apply each filter independently
            # Empty strings are treated as "no filter" (show all)
            if status_filter:
                query = query.filter(CAPAlert.status == status_filter)
            if severity_filter:
                query = query.filter(CAPAlert.severity == severity_filter)
            if event_filter:
                query = query.filter(CAPAlert.event == event_filter)
            if source_filter:
                query = query.filter(CAPAlert.source == source_filter)

            # Expired alerts filter: By default, exclude expired alerts
            # This matches the default behavior of the /alerts page
            if not show_expired:
                query = query.filter(
                    or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
                ).filter(CAPAlert.status != "Expired")

            # Order by sent timestamp descending (newest first)
            query = query.order_by(CAPAlert.sent.desc())

            # ============================================================
            # STEP 3: Execute query with performance limit
            # ============================================================
            # Hard limit of 500 alerts prevents excessive memory usage
            # and ensures reasonable PDF file size (typically 50-500KB)
            alerts_list = query.limit(500).all()

            # ============================================================
            # STEP 4: Format alert data for PDF output
            # ============================================================
            # Build structured text sections with all relevant alert details
            # Each alert is formatted as a text block with consistent field order

            sections = []
            alert_lines = []

            for alert in alerts_list:
                # Format timestamps with local time + UTC for compliance
                # Fallback to 'Unknown' if sent time is missing (shouldn't happen)
                sent_str = format_local_datetime(alert.sent, include_utc=True) if alert.sent else 'Unknown'
                expires_str = format_local_datetime(alert.expires, include_utc=True) if alert.expires else 'No expiration'

                # Core fields: Always included for every alert
                alert_block = [
                    f"Event: {alert.event}",
                    f"Severity: {alert.severity or 'N/A'}",
                    f"Status: {alert.status}",
                    f"Source: {alert.source or 'Unknown'}",
                    f"Sent: {sent_str}",
                    f"Expires: {expires_str}",
                ]

                # Optional fields: Only included if present
                if alert.headline:
                    alert_block.append(f"Headline: {alert.headline}")

                if alert.area_desc:
                    alert_block.append(f"Area: {alert.area_desc}")

                if alert.description:
                    # Truncate long descriptions to prevent excessively long PDFs
                    # Full description available in alert detail page
                    desc = alert.description[:500] + '...' if len(alert.description) > 500 else alert.description
                    alert_block.append(f"Description: {desc}")

                # Add alert block to output and separate with blank line
                alert_lines.extend(alert_block)
                alert_lines.append("")  # Empty line between alerts for readability

            # ============================================================
            # STEP 5: Build filter summary for PDF subtitle
            # ============================================================
            # Create human-readable summary of applied filters
            # This appears in the PDF subtitle for context and documentation

            filter_parts = []
            if search:
                filter_parts.append(f"Search: {search}")
            if status_filter:
                filter_parts.append(f"Status: {status_filter}")
            if severity_filter:
                filter_parts.append(f"Severity: {severity_filter}")
            if event_filter:
                filter_parts.append(f"Event: {event_filter}")
            if source_filter:
                filter_parts.append(f"Source: {source_filter}")
            if not show_expired:
                filter_parts.append("Active alerts only")

            # Join all filter parts with pipe separator, or show "All alerts" if no filters
            filter_summary = " | ".join(filter_parts) if filter_parts else "All alerts"

            # Add content section with heading showing alert count
            sections.append({
                'heading': f'Alerts Export ({len(alerts_list)} alerts)',
                'content': alert_lines if alert_lines else ['No alerts found'],
            })

            # ============================================================
            # STEP 6: Generate PDF using common utility
            # ============================================================
            # Uses shared pdf_generator module for consistency across all
            # PDF exports in the application (logs, audit logs, alerts, etc.)
            pdf_bytes = generate_pdf_document(
                title="Alerts Export",
                sections=sections,
                subtitle=filter_summary,
                footer_text="Generated by EAS Station - Emergency Alert System Platform"
            )

            # ============================================================
            # STEP 7: Return PDF response with proper headers
            # ============================================================
            # Content-Disposition: inline = display in browser (vs attachment = download)
            # Filename includes date for easy organization of saved PDFs
            response = Response(pdf_bytes, mimetype="application/pdf")
            response.headers["Content-Disposition"] = (
                f"inline; filename=alerts_export_{datetime.now().strftime('%Y%m%d')}.pdf"
            )
            return response

        except Exception as exc:
            # ============================================================
            # Error handling: Log and return user-friendly error page
            # ============================================================
            route_logger.error("Error generating alerts PDF: %s", exc)
            return (
                "<h1>Error generating PDF</h1>"
                f"<p>{exc}</p><p><a href='/alerts'>← Back to Alerts</a></p>"
            ), 500

    @app.route("/audio-monitor")
    def audio_monitoring():
        """Audio monitoring page with live audio playback."""
        try:
            return render_template("audio_monitoring.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading audio monitoring: %s", exc)
            return (
                "<h1>Error loading audio monitoring</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    def _load_logs_data(log_type: str, limit: int) -> Tuple[str, List[Dict[str, Any]]]:
        """Load the requested log data and metadata for rendering or export."""

        log_type_name = "System Logs"
        logs_data: List[Dict[str, Any]] = []

        if log_type == 'system':
            log_type_name = "System Logs"
            logs_result = (
                SystemLog.query
                .order_by(SystemLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': log.level,
                    'module': log.module or 'system',
                    'message': log.message,
                    'details': log.details,
                }
                for log in logs_result
            ]

        elif log_type == 'polling':
            log_type_name = "CAP Polling Logs"
            logs_result = (
                PollHistory.query
                .order_by(PollHistory.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': 'ERROR'
                    if log.error_message
                    else 'SUCCESS'
                    if (log.status or '').lower() == 'success'
                    else 'INFO',
                    'module': 'CAP Polling',
                    'message': (
                        f"Status: {log.status} | Fetched: {log.alerts_fetched} | "
                        f"New: {log.alerts_new} | Updated: {log.alerts_updated}"
                    ),
                    'details': {
                        'execution_time_ms': log.execution_time_ms,
                        'error': log.error_message,
                        'data_source': log.data_source,
                        'alerts_fetched': log.alerts_fetched,
                        'alerts_new': log.alerts_new,
                        'alerts_updated': log.alerts_updated,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'polling_debug':
            log_type_name = "Polling Debug Logs"
            logs_result = (
                PollDebugRecord.query
                .order_by(PollDebugRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            for record in logs_result:
                status_value = (record.poll_status or 'UNKNOWN').upper()
                identifier = record.alert_identifier or record.alert_event or 'Unknown alert'
                if not record.parse_success:
                    level = 'ERROR'
                elif record.is_relevant:
                    level = 'INFO'
                else:
                    level = 'WARNING'
                message = (
                    f"Run {record.poll_run_id}: {identifier} | Status {status_value} | "
                    f"Relevant: {'yes' if record.is_relevant else 'no'} | Saved: {'yes' if record.was_saved else 'no'}"
                )
                logs_data.append(
                    {
                        'timestamp': record.created_at,
                        'level': level,
                        'module': f"Polling Debug ({record.data_source or 'unknown'})",
                        'message': message,
                        'details': {
                            'poll_run_id': record.poll_run_id,
                            'poll_status': record.poll_status,
                            'data_source': record.data_source,
                            'alert_identifier': record.alert_identifier,
                            'alert_event': record.alert_event,
                            'alert_sent': record.alert_sent.isoformat()
                            if record.alert_sent
                            else None,
                            'created_at': record.created_at.isoformat()
                            if record.created_at
                            else None,
                            'is_relevant': record.is_relevant,
                            'relevance_reason': record.relevance_reason,
                            'relevance_matches': record.relevance_matches or [],
                            'ugc_codes': record.ugc_codes or [],
                            'area_desc': record.area_desc,
                            'was_saved': record.was_saved,
                            'was_new': record.was_new,
                            'alert_db_id': record.alert_db_id,
                            'parse_success': record.parse_success,
                            'parse_error': record.parse_error,
                            'polygon_count': record.polygon_count,
                            'geometry_type': record.geometry_type,
                            'raw_xml_present': record.raw_xml_present,
                            'notes': record.notes,
                        },
                    }
                )

        elif log_type == 'audio':
            log_type_name = "Audio System Logs"
            logs_result = (
                AudioAlert.query
                .order_by(AudioAlert.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': log.alert_level.upper(),
                    'module': f'Audio Alert: {log.source_name}',
                    'message': log.message,
                    'details': {
                        'alert_type': log.alert_type,
                        'acknowledged': log.acknowledged,
                        'cleared': log.cleared,
                        'created_at': log.created_at.isoformat() if log.created_at else None,
                        'updated_at': log.updated_at.isoformat() if log.updated_at else None,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'audio_metrics':
            log_type_name = "Audio Metrics Logs"
            logs_result = (
                AudioSourceMetrics.query
                .order_by(AudioSourceMetrics.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': 'WARNING'
                    if log.silence_detected or log.clipping_detected
                    else 'INFO',
                    'module': f'Audio Metrics: {log.source_name}',
                    'message': (
                        f"Peak: {log.peak_level_db:.1f}dB | RMS: {log.rms_level_db:.1f}dB | "
                        f"SR: {log.sample_rate}Hz"
                    ),
                    'details': {
                        'source_type': log.source_type,
                        'channels': log.channels,
                        'frames': log.frames_captured,
                        'silence': log.silence_detected,
                        'clipping': log.clipping_detected,
                        'buffer_utilization': log.buffer_utilization,
                        'stream_info': log.source_metadata,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'audio_health':
            log_type_name = "Audio Health Logs"
            logs_result = (
                AudioHealthStatus.query
                .order_by(AudioHealthStatus.timestamp.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.timestamp,
                    'level': 'ERROR'
                    if log.error_detected
                    else 'WARNING'
                    if not log.is_healthy
                    else 'INFO',
                    'module': f'Audio Health: {log.source_name}',
                    'message': (
                        f"Health Score: {log.health_score:.1f}/100 | Active: {log.is_active} | "
                        f"Uptime: {log.uptime_seconds:.1f}s"
                    ),
                    'details': {
                        'healthy': log.is_healthy,
                        'silence_detected': log.silence_detected,
                        'silence_duration': log.silence_duration_seconds,
                        'time_since_signal': log.time_since_last_signal_seconds,
                        'trend': (
                            f"{log.level_trend} ({log.trend_value_db:.1f}dB)"
                            if log.level_trend
                            else None
                        ),
                        'metadata': log.health_metadata,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'gpio':
            log_type_name = "GPIO Activation Logs"
            logs_result = (
                GPIOActivationLog.query
                .order_by(GPIOActivationLog.activated_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.activated_at,
                    'level': 'INFO',
                    'module': f'GPIO Pin {log.pin}',
                    'message': (
                        f"Type: {log.activation_type} | Operator: {log.operator or 'System'} | "
                        f"Duration: {log.duration_seconds or 'Active'}s"
                    ),
                    'details': {
                        'pin': log.pin,
                        'activation_type': log.activation_type,
                        'activated_at': log.activated_at.isoformat()
                        if log.activated_at
                        else None,
                        'deactivated_at': log.deactivated_at.isoformat()
                        if log.deactivated_at
                        else None,
                        'duration': log.duration_seconds,
                        'alert_id': log.alert_id,
                        'reason': log.reason,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'eas_messages':
            log_type_name = "EAS Messages Generated"
            logs_result = (
                EASMessage.query
                .order_by(EASMessage.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': 'INFO',
                    'module': 'EAS Message Generator',
                    'message': (
                        f"SAME: {log.same_header} | "
                        f"TTS Provider: {log.tts_provider or 'None'} | "
                        f"Audio: {log.audio_filename}"
                    ),
                    'details': {
                        'id': log.id,
                        'cap_alert_id': log.cap_alert_id,
                        'same_header': log.same_header,
                        'audio_filename': log.audio_filename,
                        'text_filename': log.text_filename,
                        'has_audio_data': log.audio_data is not None,
                        'has_eom_audio': log.eom_audio_data is not None,
                        'has_same_audio': log.same_audio_data is not None,
                        'has_attention_audio': log.attention_audio_data is not None,
                        'has_tts_audio': log.tts_audio_data is not None,
                        'tts_provider': log.tts_provider,
                        'tts_warning': log.tts_warning,
                        'text_payload': log.text_payload,
                        'metadata': log.metadata_payload,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'decoded_audio':
            log_type_name = "Decoded EAS Audio"
            logs_result = (
                EASDecodedAudio.query
                .order_by(EASDecodedAudio.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': 'INFO',
                    'module': 'EAS Audio Decoder',
                    'message': (
                        f"File: {log.original_filename or 'Unknown'} | "
                        f"SAME Headers: {len(log.same_headers or [])} | "
                        f"Type: {log.content_type or 'N/A'}"
                    ),
                    'details': {
                        'id': log.id,
                        'original_filename': log.original_filename,
                        'content_type': log.content_type,
                        'raw_text': log.raw_text,
                        'same_headers': log.same_headers or [],
                        'quality_metrics': log.quality_metrics or {},
                        'segment_metadata': log.segment_metadata or {},
                        'has_header_audio': log.header_audio_data is not None,
                        'has_attention_tone': log.attention_tone_audio_data is not None,
                        'has_narration': log.narration_audio_data is not None,
                        'has_eom_audio': log.eom_audio_data is not None,
                        'has_composite': log.composite_audio_data is not None,
                    },
                }
                for log in logs_result
            ]

        elif log_type == 'manual_activations':
            log_type_name = "Manual EAS Activations"
            logs_result = (
                ManualEASActivation.query
                .order_by(ManualEASActivation.created_at.desc())
                .limit(limit)
                .all()
            )
            logs_data = [
                {
                    'timestamp': log.created_at,
                    'level': 'WARNING' if log.status == 'ALERT' else 'INFO',
                    'module': 'Manual EAS Activation',
                    'message': (
                        f"Event: {log.event_name} ({log.event_code}) | "
                        f"Status: {log.status} | "
                        f"Type: {log.message_type}"
                    ),
                    'details': {
                        'id': log.id,
                        'identifier': log.identifier,
                        'event_code': log.event_code,
                        'event_name': log.event_name,
                        'status': log.status,
                        'message_type': log.message_type,
                        'same_header': log.same_header,
                        'same_locations': log.same_locations or [],
                        'tone_profile': log.tone_profile,
                        'tone_seconds': log.tone_seconds,
                        'includes_tts': log.includes_tts,
                        'tts_warning': log.tts_warning,
                        'sent_at': log.sent_at.isoformat() if log.sent_at else None,
                        'expires_at': log.expires_at.isoformat() if log.expires_at else None,
                        'headline': log.headline,
                        'message_text': log.message_text,
                        'instruction_text': log.instruction_text,
                        'duration_minutes': log.duration_minutes,
                        'storage_path': log.storage_path,
                        'archived_at': log.archived_at.isoformat() if log.archived_at else None,
                    },
                }
                for log in logs_result
            ]

        return log_type_name, logs_data

    @app.route("/logs")
    def logs():
        """Comprehensive log viewer with filtering by log type."""
        try:
            log_type = request.args.get('type', 'system')
            limit = min(int(request.args.get('limit', 100)), 500)  # Max 500 records

            # Get filter parameters
            search_query = request.args.get('search', '').strip()
            log_level_filter = request.args.get('level', '').strip().upper()
            date_from = request.args.get('date_from', '').strip()
            date_to = request.args.get('date_to', '').strip()

            log_type_name, logs_data = _load_logs_data(log_type, limit)

            # Apply filters
            if search_query:
                logs_data = [
                    log for log in logs_data
                    if (search_query.lower() in log.get('message', '').lower() or
                        search_query.lower() in log.get('module', '').lower() or
                        search_query.lower() in str(log.get('details', '')).lower())
                ]

            if log_level_filter:
                logs_data = [
                    log for log in logs_data
                    if log.get('level', '').upper() == log_level_filter
                ]

            if date_from:
                try:
                    from datetime import datetime
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
                    logs_data = [
                        log for log in logs_data
                        if log.get('timestamp') and log['timestamp'] >= date_from_obj
                    ]
                except ValueError:
                    pass

            if date_to:
                try:
                    from datetime import datetime, timedelta
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                    logs_data = [
                        log for log in logs_data
                        if log.get('timestamp') and log['timestamp'] < date_to_obj
                    ]
                except ValueError:
                    pass

            return render_template(
                "logs.html",
                logs=logs_data,
                log_type=log_type,
                limit=limit,
                log_type_name=log_type_name,
                search_query=search_query,
                log_level_filter=log_level_filter,
                date_from=date_from,
                date_to=date_to,
            )

        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading logs: %s", exc)
            return (
                "<h1>Error loading logs</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/logs/export.csv")
    def logs_export_csv():
        """Export logs as CSV file."""
        try:
            import csv
            import io
            from datetime import datetime

            log_type = request.args.get('type', 'system')
            limit = min(int(request.args.get('limit', 100)), 500)

            log_type_name, logs_data = _load_logs_data(log_type, limit)

            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow(['Timestamp', 'Level', 'Module', 'Message', 'Details'])

            # Write data
            for log_entry in logs_data:
                timestamp_str = format_local_datetime(
                    log_entry.get('timestamp'), include_utc=True
                ) if log_entry.get('timestamp') else 'N/A'
                level = log_entry.get('level', 'INFO')
                module = log_entry.get('module', 'System')
                message = log_entry.get('message', '')
                details = str(log_entry.get('details', ''))

                writer.writerow([timestamp_str, level, module, message, details])

            # Create response
            csv_data = output.getvalue()
            output.close()

            response = Response(csv_data, mimetype="text/csv")
            response.headers["Content-Disposition"] = (
                f"attachment; filename=logs_{log_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            return response

        except Exception as exc:
            route_logger.error('Error generating logs CSV: %s', exc)
            return (
                "<h1>Error generating CSV</h1>"
                f"<p>{exc}</p><p><a href='/logs'>← Back to Logs</a></p>"
            )

    @app.route("/logs/export.pdf")
    def logs_export_pdf():
        """Export system logs as PDF - server-side from database."""
        try:
            log_type = request.args.get('type', 'system')
            limit = min(int(request.args.get('limit', 100)), 500)

            from datetime import datetime

            log_type_name, logs_data = _load_logs_data(log_type, limit)

            sections = []

            log_lines: List[str] = []
            for log_entry in logs_data:
                timestamp_str = format_local_datetime(
                    log_entry.get('timestamp'), include_utc=True
                )
                level = log_entry.get('level', 'INFO')
                module = log_entry.get('module', 'System')
                message = log_entry.get('message', '')
                log_lines.append(f"[{timestamp_str}] [{level}] {module}: {message}")

            if not log_lines:
                log_lines.append('No log entries found')

            heading_name = log_type_name or 'Logs'
            sections.append(
                {
                    'heading': f"{heading_name} (Last {len(logs_data)} entries)",
                    'content': log_lines,
                }
            )

            pdf_bytes = generate_pdf_document(
                title=f"{heading_name} Export",
                sections=sections,
                subtitle=f"Showing last {limit} entries",
                footer_text="Generated by EAS Station - Emergency Alert System Platform",
            )

            response = Response(pdf_bytes, mimetype="application/pdf")
            response.headers["Content-Disposition"] = (
                f"inline; filename=logs_{log_type}_{datetime.now().strftime('%Y%m%d')}.pdf"
            )
            return response

        except Exception as exc:
            route_logger.error('Error generating logs PDF: %s', exc)
            return (
                "<h1>Error generating PDF</h1>"
                f"<p>{exc}</p><p><a href='/logs'>← Back to Logs</a></p>"
            )




__all__ = ["register"]
