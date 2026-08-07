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

"""The /stats dashboard."""

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.extensions import db
from app_core.models import (
    Boundary,
    CAPAlert,
    EASMessage,
    GPIOActivationLog,
    Intersection,
    ManualEASActivation,
    PollHistory,
    ReceivedEASAlert,
)
from app_utils import utc_now
from collections import defaultdict
from flask import render_template
from sqlalchemy import func
from typing import Any, Dict, List


def register(app, route_logger) -> None:
    """Attach the stats routes to the Flask app."""
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
                db.session.rollback()
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
                db.session.rollback()
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
                db.session.rollback()
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

                # Filter to only include years from the last 5 years to exclude
                # potentially corrupted data (e.g., 1970 from Unix epoch defaults)
                from datetime import datetime
                min_year = datetime.now().year - 5
                alert_by_year = (
                    db.session.query(
                        func.extract("year", CAPAlert.sent).label("year"),
                        func.count(CAPAlert.id).label("count"),
                    )
                    .filter(func.extract("year", CAPAlert.sent) >= min_year)
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
                db.session.rollback()
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
                db.session.rollback()
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
                db.session.rollback()
                route_logger.error("Error calculating duration stats: %s", exc)
                stats_data["duration_stats"] = []

            try:
                alert_by_urgency = (
                    db.session.query(
                        CAPAlert.urgency, func.count(CAPAlert.id).label("count")
                    )
                    .filter(CAPAlert.urgency.isnot(None))
                    .group_by(CAPAlert.urgency)
                    .all()
                )
                stats_data["alert_by_urgency"] = [
                    {"urgency": urgency, "count": count}
                    for urgency, count in alert_by_urgency
                ]

                alert_by_certainty = (
                    db.session.query(
                        CAPAlert.certainty, func.count(CAPAlert.id).label("count")
                    )
                    .filter(CAPAlert.certainty.isnot(None))
                    .group_by(CAPAlert.certainty)
                    .all()
                )
                stats_data["alert_by_certainty"] = [
                    {"certainty": certainty, "count": count}
                    for certainty, count in alert_by_certainty
                ]
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting urgency/certainty stats: %s", exc)
                stats_data["alert_by_urgency"] = []
                stats_data["alert_by_certainty"] = []

            try:
                eas_forwarded_count = CAPAlert.query.filter_by(eas_forwarded=True).count()
                total_for_eas = stats_data.get("total_alerts") or 0
                stats_data["eas_forwarding_stats"] = {
                    "forwarded": eas_forwarded_count,
                    "total": total_for_eas,
                    "rate": round(eas_forwarded_count / total_for_eas * 100, 1) if total_for_eas > 0 else 0,
                }
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting EAS forwarding stats: %s", exc)
                stats_data["eas_forwarding_stats"] = {"forwarded": 0, "total": 0, "rate": 0}

            try:
                stats_data["manual_activation_count"] = ManualEASActivation.query.count()
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting manual activation count: %s", exc)
                stats_data["manual_activation_count"] = 0

            try:
                stats_data["received_eas_stats"] = {
                    "total": ReceivedEASAlert.query.count(),
                    "forwarded": ReceivedEASAlert.query.filter_by(forwarding_decision="forwarded").count(),
                    "ignored": ReceivedEASAlert.query.filter_by(forwarding_decision="ignored").count(),
                }
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting received EAS stats: %s", exc)
                stats_data["received_eas_stats"] = {"total": 0, "forwarded": 0, "ignored": 0}

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
                db.session.rollback()
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
                        # Additional keys expected by the template
                        "total_polls": total_runs,
                        "successful_polls": successes,
                        "failed_polls": failures,
                        "avg_time_ms": avg_execution,
                    }
                else:
                    stats_data["polling"] = {
                        "success_rate": 0,
                        "total_runs": 0,
                        "failed_runs": 0,
                        "recent_runs": [],
                        "total_polls": 0,
                        "successful_polls": 0,
                        "failed_polls": 0,
                        "avg_time_ms": 0,
                    }
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error calculating polling metrics: %s", exc)
                stats_data["polling"] = {
                    "success_rate": 0,
                    "total_runs": 0,
                    "failed_runs": 0,
                    "recent_runs": [],
                    "total_polls": 0,
                    "successful_polls": 0,
                    "failed_polls": 0,
                    "avg_time_ms": 0,
                }

            try:
                alert_by_message_type = (
                    db.session.query(
                        CAPAlert.message_type, func.count(CAPAlert.id).label("count")
                    )
                    .filter(CAPAlert.message_type.isnot(None))
                    .group_by(CAPAlert.message_type)
                    .all()
                )
                stats_data["alert_by_message_type"] = [
                    {"message_type": mt, "count": count}
                    for mt, count in alert_by_message_type
                ]
                total_for_mt = stats_data.get("total_alerts") or 0
                cancel_count = sum(c for mt, c in alert_by_message_type if mt and mt.lower() in ("cancel", "allclear"))
                update_count = sum(c for mt, c in alert_by_message_type if mt and mt.lower() == "update")
                stats_data["cancellation_rate"] = round(cancel_count / total_for_mt * 100, 1) if total_for_mt > 0 else 0
                stats_data["update_rate"] = round(update_count / total_for_mt * 100, 1) if total_for_mt > 0 else 0
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting message type stats: %s", exc)
                stats_data["alert_by_message_type"] = []
                stats_data["cancellation_rate"] = 0
                stats_data["update_rate"] = 0

            try:
                alerts_with_coverage = (
                    db.session.query(func.count(func.distinct(Intersection.cap_alert_id)))
                    .scalar() or 0
                )
                total_for_cov = stats_data.get("total_alerts") or 0
                stats_data["coverage_overlap_rate"] = round(alerts_with_coverage / total_for_cov * 100, 1) if total_for_cov > 0 else 0
                stats_data["alerts_with_coverage"] = alerts_with_coverage
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting coverage overlap rate: %s", exc)
                stats_data["coverage_overlap_rate"] = 0
                stats_data["alerts_with_coverage"] = 0

            try:
                latency_result = (
                    db.session.query(
                        func.avg(
                            func.extract("epoch", EASMessage.created_at) - func.extract("epoch", CAPAlert.sent)
                        ).label("avg_seconds"),
                        func.min(
                            func.extract("epoch", EASMessage.created_at) - func.extract("epoch", CAPAlert.sent)
                        ).label("min_seconds"),
                        func.max(
                            func.extract("epoch", EASMessage.created_at) - func.extract("epoch", CAPAlert.sent)
                        ).label("max_seconds"),
                        func.count(EASMessage.id).label("total"),
                    )
                    .join(CAPAlert, EASMessage.cap_alert_id == CAPAlert.id)
                    .filter(CAPAlert.sent.isnot(None), EASMessage.created_at.isnot(None))
                    .first()
                )
                if latency_result and latency_result.avg_seconds is not None:
                    stats_data["broadcast_latency"] = {
                        "avg_seconds": round(float(latency_result.avg_seconds), 1),
                        "min_seconds": round(float(latency_result.min_seconds), 1),
                        "max_seconds": round(float(latency_result.max_seconds), 1),
                        "total_broadcasts": latency_result.total,
                    }
                else:
                    stats_data["broadcast_latency"] = None
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting broadcast latency stats: %s", exc)
                stats_data["broadcast_latency"] = None

            try:
                relay_by_type = (
                    db.session.query(
                        GPIOActivationLog.activation_type,
                        func.count(GPIOActivationLog.id).label("count"),
                        func.avg(GPIOActivationLog.duration_seconds).label("avg_duration"),
                    )
                    .group_by(GPIOActivationLog.activation_type)
                    .all()
                )
                relay_total = GPIOActivationLog.query.count()
                relay_success = GPIOActivationLog.query.filter_by(success=True).count()
                stats_data["relay_stats"] = {
                    "total": relay_total,
                    "success_rate": round(relay_success / relay_total * 100, 1) if relay_total > 0 else 0,
                    "by_type": [
                        {
                            "type": act_type or "unknown",
                            "count": count,
                            "avg_duration": round(float(avg_dur), 1) if avg_dur else 0,
                        }
                        for act_type, count, avg_dur in relay_by_type
                    ],
                }
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting relay activation stats: %s", exc)
                stats_data["relay_stats"] = {"total": 0, "success_rate": 0, "by_type": []}

            try:
                from datetime import timedelta
                _now = utc_now()
                _cutoff_7d = _now - timedelta(days=7)
                _cutoff_30d = _now - timedelta(days=30)
                _success_values = {"success", "ok", "completed"}

                _polls_7d = PollHistory.query.filter(PollHistory.timestamp >= _cutoff_7d).all()
                _polls_30d = PollHistory.query.filter(PollHistory.timestamp >= _cutoff_30d).all()

                def _poll_rate(polls):
                    if not polls:
                        return 0.0
                    s = sum(1 for p in polls if (p.status or "").lower() in _success_values and not p.error_message)
                    return round(s / len(polls) * 100, 1)

                _times = sorted(p.execution_time_ms for p in _polls_30d if p.execution_time_ms is not None)
                _p95 = _times[int(len(_times) * 0.95)] if _times else 0

                stats_data["polling_trend"] = {
                    "rate_7d": _poll_rate(_polls_7d),
                    "rate_30d": _poll_rate(_polls_30d),
                    "count_7d": len(_polls_7d),
                    "count_30d": len(_polls_30d),
                    "p95_execution_ms": _p95,
                }
            except Exception as exc:
                db.session.rollback()
                route_logger.error("Error getting polling trend: %s", exc)
                stats_data["polling_trend"] = {"rate_7d": 0, "rate_30d": 0, "count_7d": 0, "count_30d": 0, "p95_execution_ms": 0}

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
            stats_data.setdefault("alert_by_urgency", [])
            stats_data.setdefault("alert_by_certainty", [])
            stats_data.setdefault("eas_forwarding_stats", {"forwarded": 0, "total": 0, "rate": 0})
            stats_data.setdefault("manual_activation_count", 0)
            stats_data.setdefault("received_eas_stats", {"total": 0, "forwarded": 0, "ignored": 0})
            stats_data.setdefault("alert_by_message_type", [])
            stats_data.setdefault("cancellation_rate", 0)
            stats_data.setdefault("update_rate", 0)
            stats_data.setdefault("coverage_overlap_rate", 0)
            stats_data.setdefault("alerts_with_coverage", 0)
            stats_data.setdefault("broadcast_latency", None)
            stats_data.setdefault("relay_stats", {"total": 0, "success_rate": 0, "by_type": []})
            stats_data.setdefault("polling_trend", {"rate_7d": 0, "rate_30d": 0, "count_7d": 0, "count_30d": 0, "p95_execution_ms": 0})

            return render_template("stats.html", **stats_data)
        except Exception as exc:  # pragma: no cover - fallback content
            db.session.rollback()
            route_logger.error("Error loading statistics: %s", exc)
            return (
                "<h1>Error loading statistics</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )


__all__ = ["register"]
