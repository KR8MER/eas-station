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

"""Analytics and trend analysis routes for the Flask app."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from flask import Flask, g, jsonify, render_template, request

from app_core.analytics import (
    AnomalyDetector,
    AnomalyRecord,
    MetricsAggregator,
    MetricSnapshot,
    TrendAnalyzer,
    TrendRecord,
)
from app_core.auth import require_permission
from app_utils import utc_now


def register(app: Flask, logger) -> None:
    """Attach analytics routes to the Flask app."""

    route_logger = logger.getChild("routes_analytics")

    # Initialize analytics components
    metrics_aggregator = MetricsAggregator()
    trend_analyzer = TrendAnalyzer()
    anomaly_detector = AnomalyDetector()

    # ====================================================================
    # UI endpoints
    # ====================================================================

    @app.route("/analytics")
    def analytics_dashboard_page():
        """Display the analytics dashboard page."""
        return render_template("analytics_dashboard.html")

    # ====================================================================
    # Metrics endpoints
    # ====================================================================

    @app.route("/api/analytics/metrics", methods=["GET"])
    def get_metrics():
        """Get metric snapshots.

        Query parameters:
        - category: Metric category filter
        - name: Metric name filter
        - period: Aggregation period filter (hourly, daily, weekly)
        - entity_id: Entity identifier filter
        - days: Number of days to look back (default: 7)
        - limit: Maximum number of results (default: 100)
        """
        try:
            category = request.args.get("category")
            name = request.args.get("name")
            period = request.args.get("period")
            entity_id = request.args.get("entity_id")
            days = int(request.args.get("days", 7))
            limit = int(request.args.get("limit", 100))

            now = utc_now()
            start_time = now - timedelta(days=days)

            # Build query
            query = MetricSnapshot.query.filter(
                MetricSnapshot.snapshot_time >= start_time
            )

            if category:
                query = query.filter(MetricSnapshot.metric_category == category)
            if name:
                query = query.filter(MetricSnapshot.metric_name == name)
            if period:
                query = query.filter(MetricSnapshot.aggregation_period == period)
            if entity_id:
                query = query.filter(MetricSnapshot.entity_id == entity_id)

            snapshots = (
                query.order_by(MetricSnapshot.snapshot_time.desc()).limit(limit).all()
            )

            return jsonify(
                {
                    "success": True,
                    "count": len(snapshots),
                    "metrics": [s.to_dict() for s in snapshots],
                }
            )

        except Exception as exc:
            route_logger.error("Failed to get metrics: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/metrics/categories", methods=["GET"])
    def get_metric_categories():
        """Get list of available metric categories."""
        try:
            from sqlalchemy import distinct

            categories = (
                MetricSnapshot.query.with_entities(
                    distinct(MetricSnapshot.metric_category)
                )
                .order_by(MetricSnapshot.metric_category)
                .all()
            )

            return jsonify(
                {
                    "success": True,
                    "categories": [c[0] for c in categories if c[0]],
                }
            )

        except Exception as exc:
            route_logger.error("Failed to get metric categories: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/metrics/aggregate", methods=["POST"])
    @require_permission("analytics_manage")
    def aggregate_metrics():
        """Manually trigger metrics aggregation.

        Request body (JSON):
        - period: Aggregation period (hourly, daily, weekly) - default: hourly
        - lookback_hours: Hours to look back (default: 24)
        """
        try:
            data = request.get_json() or {}
            period = data.get("period", "hourly")
            lookback_hours = int(data.get("lookback_hours", 24))

            snapshot_count = metrics_aggregator.aggregate_all_metrics(
                aggregation_period=period,
                lookback_hours=lookback_hours,
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"Aggregated {snapshot_count} metric snapshots",
                    "snapshot_count": snapshot_count,
                }
            )

        except Exception as exc:
            route_logger.error("Failed to aggregate metrics: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ====================================================================
    # Trend analysis endpoints
    # ====================================================================

    @app.route("/api/analytics/trends", methods=["GET"])
    def get_trends():
        """Get trend analysis records.

        Query parameters:
        - category: Metric category filter
        - name: Metric name filter
        - window_days: Analysis window filter
        - entity_id: Entity identifier filter
        - limit: Maximum number of results (default: 100)
        """
        try:
            category = request.args.get("category")
            name = request.args.get("name")
            window_days = request.args.get("window_days")
            if window_days:
                window_days = int(window_days)
            limit = int(request.args.get("limit", 100))

            trends = trend_analyzer.get_latest_trends(
                metric_category=category,
                metric_name=name,
                window_days=window_days,
                limit=limit,
            )

            return jsonify(
                {
                    "success": True,
                    "count": len(trends),
                    "trends": [t.to_dict() for t in trends],
                }
            )

        except Exception as exc:
            route_logger.error("Failed to get trends: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/trends/analyze", methods=["POST"])
    @require_permission("analytics_manage")
    def analyze_trends():
        """Manually trigger trend analysis.

        Request body (JSON):
        - window_days: Analysis window in days (default: 7)
        - categories: Optional list of categories to analyze
        - metric_category: Optional single category to analyze
        - metric_name: Optional single metric name to analyze
        - entity_id: Optional entity identifier
        """
        try:
            data = request.get_json() or {}
            window_days = int(data.get("window_days", 7))

            # Single metric analysis
            if "metric_category" in data and "metric_name" in data:
                trend = trend_analyzer.analyze_metric_trend(
                    metric_category=data["metric_category"],
                    metric_name=data["metric_name"],
                    window_days=window_days,
                    entity_id=data.get("entity_id"),
                    forecast_days=int(data.get("forecast_days", 7)),
                )

                if trend:
                    return jsonify(
                        {
                            "success": True,
                            "message": "Trend analysis completed",
                            "trend": trend.to_dict(),
                        }
                    )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": "Insufficient data for trend analysis",
                        }
                    ), 400

            # Bulk analysis
            categories = data.get("categories")
            trend_count = trend_analyzer.analyze_all_metrics(
                window_days=window_days,
                metric_categories=categories,
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"Analyzed {trend_count} metric trends",
                    "trend_count": trend_count,
                }
            )

        except Exception as exc:
            route_logger.error("Failed to analyze trends: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ====================================================================
    # Anomaly detection endpoints
    # ====================================================================

    @app.route("/api/analytics/anomalies", methods=["GET"])
    def get_anomalies():
        """Get anomaly records.

        Query parameters:
        - category: Metric category filter
        - severity: Severity filter (low, medium, high, critical)
        - active: Only show active (unresolved) anomalies (default: true)
        - limit: Maximum number of results (default: 100)
        """
        try:
            category = request.args.get("category")
            severity = request.args.get("severity")
            active_only = request.args.get("active", "true").lower() == "true"
            limit = int(request.args.get("limit", 100))

            if active_only:
                anomalies = anomaly_detector.get_active_anomalies(
                    metric_category=category,
                    severity=severity,
                    limit=limit,
                )
            else:
                # Query all anomalies
                query = AnomalyRecord.query

                if category:
                    query = query.filter(AnomalyRecord.metric_category == category)
                if severity:
                    query = query.filter(AnomalyRecord.severity == severity)

                anomalies = (
                    query.order_by(AnomalyRecord.detected_at.desc()).limit(limit).all()
                )

            return jsonify(
                {
                    "success": True,
                    "count": len(anomalies),
                    "anomalies": [a.to_dict() for a in anomalies],
                }
            )

        except Exception as exc:
            route_logger.error("Failed to get anomalies: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/anomalies/detect", methods=["POST"])
    @require_permission("analytics_manage")
    def detect_anomalies():
        """Manually trigger anomaly detection.

        Request body (JSON):
        - baseline_days: Baseline window in days (default: 7)
        - categories: Optional list of categories to check
        - metric_category: Optional single category to check
        - metric_name: Optional single metric name to check
        - entity_id: Optional entity identifier
        """
        try:
            data = request.get_json() or {}
            baseline_days = int(data.get("baseline_days", 7))

            # Single metric detection
            if "metric_category" in data and "metric_name" in data:
                anomalies = anomaly_detector.detect_metric_anomalies(
                    metric_category=data["metric_category"],
                    metric_name=data["metric_name"],
                    baseline_days=baseline_days,
                    entity_id=data.get("entity_id"),
                )

                return jsonify(
                    {
                        "success": True,
                        "message": f"Detected {len(anomalies)} anomalies",
                        "anomaly_count": len(anomalies),
                        "anomalies": [a.to_dict() for a in anomalies],
                    }
                )

            # Bulk detection
            categories = data.get("categories")
            anomaly_count = anomaly_detector.detect_all_anomalies(
                baseline_days=baseline_days,
                metric_categories=categories,
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"Detected {anomaly_count} anomalies",
                    "anomaly_count": anomaly_count,
                }
            )

        except Exception as exc:
            route_logger.error("Failed to detect anomalies: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/anomalies/<int:anomaly_id>/acknowledge", methods=["POST"])
    @require_permission("analytics_manage")
    def acknowledge_anomaly(anomaly_id: int):
        """Acknowledge an anomaly.

        Request body (JSON):
        - acknowledged_by: Username (optional, will use current user)
        """
        try:
            data = request.get_json() or {}
            acknowledged_by = data.get("acknowledged_by", g.current_user.username if g.current_user else "unknown")

            anomaly = anomaly_detector.acknowledge_anomaly(anomaly_id, acknowledged_by)

            if not anomaly:
                return jsonify({"success": False, "error": "Anomaly not found"}), 404

            return jsonify(
                {
                    "success": True,
                    "message": "Anomaly acknowledged",
                    "anomaly": anomaly.to_dict(),
                }
            )

        except Exception as exc:
            route_logger.error("Failed to acknowledge anomaly: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/anomalies/<int:anomaly_id>/resolve", methods=["POST"])
    @require_permission("analytics_manage")
    def resolve_anomaly(anomaly_id: int):
        """Resolve an anomaly.

        Request body (JSON):
        - resolved_by: Username (optional, will use current user)
        - resolution_notes: Notes about the resolution
        """
        try:
            data = request.get_json() or {}
            resolved_by = data.get("resolved_by", g.current_user.username if g.current_user else "unknown")
            resolution_notes = data.get("resolution_notes")

            anomaly = anomaly_detector.resolve_anomaly(
                anomaly_id, resolved_by, resolution_notes
            )

            if not anomaly:
                return jsonify({"success": False, "error": "Anomaly not found"}), 404

            return jsonify(
                {
                    "success": True,
                    "message": "Anomaly resolved",
                    "anomaly": anomaly.to_dict(),
                }
            )

        except Exception as exc:
            route_logger.error("Failed to resolve anomaly: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/analytics/anomalies/<int:anomaly_id>/false-positive", methods=["POST"])
    @require_permission("analytics_manage")
    def mark_false_positive(anomaly_id: int):
        """Mark an anomaly as a false positive.

        Request body (JSON):
        - reason: Reason for false positive classification
        """
        try:
            data = request.get_json() or {}
            reason = data.get("reason")

            anomaly = anomaly_detector.mark_false_positive(anomaly_id, reason)

            if not anomaly:
                return jsonify({"success": False, "error": "Anomaly not found"}), 404

            return jsonify(
                {
                    "success": True,
                    "message": "Anomaly marked as false positive",
                    "anomaly": anomaly.to_dict(),
                }
            )

        except Exception as exc:
            route_logger.error("Failed to mark false positive: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ====================================================================
    # Dashboard endpoints
    # ====================================================================

    @app.route("/api/analytics/dashboard", methods=["GET"])
    def analytics_dashboard():
        """Get analytics dashboard summary.

        Returns overview of:
        - Recent trends
        - Active anomalies
        - Key metrics summary
        """
        try:
            # Get recent trends
            recent_trends = trend_analyzer.get_latest_trends(limit=10)

            # Get active anomalies
            active_anomalies = anomaly_detector.get_active_anomalies(limit=20)

            # Group anomalies by severity
            anomalies_by_severity: Dict[str, int] = {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            }
            for anomaly in active_anomalies:
                anomalies_by_severity[anomaly.severity] = (
                    anomalies_by_severity.get(anomaly.severity, 0) + 1
                )

            # Get key metrics (latest snapshots)
            key_metrics = []
            metric_names = [
                ("alert_delivery", "delivery_success_rate"),
                ("audio_health", "avg_health_score"),
                ("receiver_status", "availability_rate"),
                ("compliance", "test_relay_rate"),
            ]

            for category, name in metric_names:
                snapshot = (
                    MetricSnapshot.query.filter_by(
                        metric_category=category, metric_name=name
                    )
                    .order_by(MetricSnapshot.snapshot_time.desc())
                    .first()
                )

                if snapshot:
                    key_metrics.append(
                        {
                            "category": category,
                            "name": name,
                            "value": snapshot.value,
                            "timestamp": snapshot.snapshot_time.isoformat(),
                        }
                    )

            return jsonify(
                {
                    "success": True,
                    "summary": {
                        "active_anomalies": len(active_anomalies),
                        "anomalies_by_severity": anomalies_by_severity,
                        "recent_trends": len(recent_trends),
                    },
                    "trends": [t.to_dict() for t in recent_trends],
                    "anomalies": [a.to_dict() for a in active_anomalies],
                    "key_metrics": key_metrics,
                    "generated_at": utc_now().isoformat(),
                }
            )

        except Exception as exc:
            route_logger.error("Failed to get analytics dashboard: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
