"""Public-facing Flask routes extracted from the historical app module."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from flask import Flask, render_template, request, url_for
from sqlalchemy import func, or_

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.eas_storage import get_eas_static_prefix
from app_core.extensions import db
from app_core.models import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    Boundary,
    CAPAlert,
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


def register(app: Flask, logger) -> None:
    """Attach public and operator-facing pages to the Flask app."""

    route_logger = logger.getChild("routes_public")

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
        try:
            return render_template("terms.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering terms page: %s", exc)
            return (
                "<h1>Terms of Use</h1><p>Refer to docs/policies/TERMS_OF_USE.md in the repository for the full terms.</p>"
            )

    @app.route("/privacy")
    def privacy_page():
        try:
            return render_template("privacy.html")
        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error rendering privacy page: %s", exc)
            return (
                "<h1>Privacy Policy</h1><p>Refer to docs/policies/PRIVACY_POLICY.md in the repository for the full policy.</p>"
            )

    @app.route("/system_health")
    def system_health_page():
        try:
            health_data = get_system_health(logger=route_logger)
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

    @app.route("/logs")
    def logs():
        """Comprehensive log viewer with filtering by log type."""
        try:
            # Get filter parameters
            log_type = request.args.get('type', 'system')
            limit = min(int(request.args.get('limit', 100)), 500)  # Max 500 records

            logs_data = []

            if log_type == 'system':
                # System logs
                logs_result = (
                    SystemLog.query
                    .order_by(SystemLog.timestamp.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.timestamp,
                    'level': log.level,
                    'module': log.module or 'system',
                    'message': log.message,
                    'details': log.details
                } for log in logs_result]

            elif log_type == 'polling':
                # CAP polling logs
                logs_result = (
                    PollHistory.query
                    .order_by(PollHistory.timestamp.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.timestamp,
                    'level': 'ERROR' if log.error_message else 'SUCCESS' if log.status == 'success' else 'INFO',
                    'module': 'CAP Polling',
                    'message': f"Status: {log.status} | Fetched: {log.alerts_fetched} | New: {log.alerts_new} | Updated: {log.alerts_updated}",
                    'details': {
                        'execution_time_ms': log.execution_time_ms,
                        'error': log.error_message,
                        'data_source': log.data_source
                    }
                } for log in logs_result]

            elif log_type == 'polling_debug':
                # Detailed polling debug logs
                logs_result = (
                    PollDebugRecord.query
                    .order_by(PollDebugRecord.timestamp.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.timestamp,
                    'level': 'DEBUG',
                    'module': 'Polling Debug',
                    'message': f"Alert: {log.alert_identifier} | Relevant: {log.is_relevant}",
                    'details': {
                        'alert_id': log.alert_id,
                        'parse_success': log.parse_success,
                        'geometry_valid': log.geometry_valid,
                        'relevance_reason': log.relevance_reason,
                        'zone_matches': log.zone_matches,
                        'county_matches': log.county_matches
                    }
                } for log in logs_result]

            elif log_type == 'audio':
                # Audio system alerts
                logs_result = (
                    AudioAlert.query
                    .order_by(AudioAlert.created_at.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.created_at,
                    'level': log.alert_level.upper(),
                    'module': f'Audio: {log.source_name}',
                    'message': f"[{log.alert_type}] {log.message}",
                    'details': {
                        'source': log.source_name,
                        'type': log.alert_type,
                        'threshold': log.threshold_value,
                        'actual': log.actual_value,
                        'acknowledged': log.acknowledged,
                        'resolved': log.resolved,
                        'metadata': log.alert_metadata
                    }
                } for log in logs_result]

            elif log_type == 'audio_metrics':
                # Audio source metrics
                logs_result = (
                    AudioSourceMetrics.query
                    .order_by(AudioSourceMetrics.timestamp.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.timestamp,
                    'level': 'WARNING' if log.silence_detected or log.clipping_detected else 'INFO',
                    'module': f'Audio Metrics: {log.source_name}',
                    'message': f"Peak: {log.peak_level_db:.1f}dB | RMS: {log.rms_level_db:.1f}dB | SR: {log.sample_rate}Hz",
                    'details': {
                        'source_type': log.source_type,
                        'channels': log.channels,
                        'frames': log.frames_captured,
                        'silence': log.silence_detected,
                        'clipping': log.clipping_detected,
                        'buffer_utilization': log.buffer_utilization,
                        'stream_info': log.source_metadata  # Using the mapped column name
                    }
                } for log in logs_result]

            elif log_type == 'audio_health':
                # Audio health status
                logs_result = (
                    AudioHealthStatus.query
                    .order_by(AudioHealthStatus.timestamp.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.timestamp,
                    'level': 'ERROR' if log.error_detected else 'WARNING' if not log.is_healthy else 'INFO',
                    'module': f'Audio Health: {log.source_name}',
                    'message': f"Health Score: {log.health_score:.1f}/100 | Active: {log.is_active} | Uptime: {log.uptime_seconds:.1f}s",
                    'details': {
                        'healthy': log.is_healthy,
                        'silence_detected': log.silence_detected,
                        'silence_duration': log.silence_duration_seconds,
                        'time_since_signal': log.time_since_last_signal_seconds,
                        'trend': f"{log.level_trend} ({log.trend_value_db:.1f}dB)" if log.level_trend else None,
                        'metadata': log.health_metadata
                    }
                } for log in logs_result]

            elif log_type == 'gpio':
                # GPIO activation logs
                logs_result = (
                    GPIOActivationLog.query
                    .order_by(GPIOActivationLog.activated_at.desc())
                    .limit(limit)
                    .all()
                )
                logs_data = [{
                    'timestamp': log.activated_at,
                    'level': 'INFO',
                    'module': f'GPIO Pin {log.pin}',
                    'message': f"Type: {log.activation_type} | Operator: {log.operator or 'System'} | Duration: {log.duration_seconds or 'Active'}s",
                    'details': {
                        'pin': log.pin,
                        'activation_type': log.activation_type,
                        'activated_at': log.activated_at.isoformat() if log.activated_at else None,
                        'deactivated_at': log.deactivated_at.isoformat() if log.deactivated_at else None,
                        'duration': log.duration_seconds,
                        'alert_id': log.alert_id,
                        'reason': log.reason
                    }
                } for log in logs_result]

            return render_template(
                "logs.html",
                logs=logs_data,
                log_type=log_type,
                limit=limit
            )

        except Exception as exc:  # pragma: no cover - fallback content
            route_logger.error("Error loading logs: %s", exc)
            return (
                "<h1>Error loading logs</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )


__all__ = ["register"]
