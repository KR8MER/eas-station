"""Anomaly detection using statistical methods.

This module provides functionality to detect anomalies in time-series metrics:
- Z-score based outlier detection
- Spike and drop detection
- Trend break detection
- Pattern violation detection
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_

from app_core.extensions import db
from app_core.analytics.models import MetricSnapshot, TrendRecord, AnomalyRecord
from app_utils import utc_now

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detects anomalies in time-series metrics using statistical methods."""

    # Thresholds for anomaly classification
    Z_SCORE_THRESHOLD_CRITICAL = 3.5
    Z_SCORE_THRESHOLD_HIGH = 3.0
    Z_SCORE_THRESHOLD_MEDIUM = 2.5
    Z_SCORE_THRESHOLD_LOW = 2.0

    SPIKE_DROP_THRESHOLD = 0.5  # 50% change

    def __init__(self):
        """Initialize the anomaly detector."""
        self.logger = logger

    def detect_all_anomalies(
        self,
        baseline_days: int = 7,
        metric_categories: Optional[List[str]] = None,
    ) -> int:
        """Detect anomalies for all metrics or specified categories.

        Args:
            baseline_days: Number of days to use for baseline calculation
            metric_categories: Optional list of categories to check

        Returns:
            Number of anomalies detected
        """
        # Get unique metric combinations
        query = db.session.query(
            MetricSnapshot.metric_category,
            MetricSnapshot.metric_name,
            MetricSnapshot.entity_id,
        ).distinct()

        if metric_categories:
            query = query.filter(MetricSnapshot.metric_category.in_(metric_categories))

        metrics = query.all()

        anomaly_count = 0
        for category, name, entity_id in metrics:
            try:
                anomalies = self.detect_metric_anomalies(
                    metric_category=category,
                    metric_name=name,
                    baseline_days=baseline_days,
                    entity_id=entity_id,
                )
                anomaly_count += len(anomalies)
            except Exception as e:
                self.logger.error(
                    "Failed to detect anomalies for %s.%s: %s",
                    category,
                    name,
                    str(e),
                )

        self.logger.info("Detected %d anomalies", anomaly_count)
        return anomaly_count

    def detect_metric_anomalies(
        self,
        metric_category: str,
        metric_name: str,
        baseline_days: int = 7,
        entity_id: Optional[str] = None,
        lookback_hours: int = 24,
    ) -> List[AnomalyRecord]:
        """Detect anomalies for a specific metric.

        Args:
            metric_category: Metric category
            metric_name: Metric name
            baseline_days: Number of days for baseline calculation
            entity_id: Optional entity identifier
            lookback_hours: How far back to check for new anomalies

        Returns:
            List of detected AnomalyRecord objects
        """
        now = utc_now()
        baseline_start = now - timedelta(days=baseline_days)
        check_start = now - timedelta(hours=lookback_hours)

        # Get baseline snapshots (excluding the recent period we're checking)
        baseline_query = MetricSnapshot.query.filter(
            and_(
                MetricSnapshot.metric_category == metric_category,
                MetricSnapshot.metric_name == metric_name,
                MetricSnapshot.snapshot_time >= baseline_start,
                MetricSnapshot.snapshot_time < check_start,
            )
        )

        if entity_id:
            baseline_query = baseline_query.filter(MetricSnapshot.entity_id == entity_id)

        baseline_snapshots = baseline_query.order_by(MetricSnapshot.snapshot_time).all()

        if len(baseline_snapshots) < 5:
            self.logger.debug(
                "Insufficient baseline data for anomaly detection: %s.%s (only %d points)",
                metric_category,
                metric_name,
                len(baseline_snapshots),
            )
            return []

        # Calculate baseline statistics
        baseline_values = [s.value for s in baseline_snapshots]
        baseline_mean = sum(baseline_values) / len(baseline_values)
        baseline_stddev = self._calculate_stddev(baseline_values)

        if baseline_stddev is None or baseline_stddev == 0:
            self.logger.debug(
                "Zero standard deviation for %s.%s, skipping anomaly detection",
                metric_category,
                metric_name,
            )
            return []

        # Get recent snapshots to check
        check_query = MetricSnapshot.query.filter(
            and_(
                MetricSnapshot.metric_category == metric_category,
                MetricSnapshot.metric_name == metric_name,
                MetricSnapshot.snapshot_time >= check_start,
                MetricSnapshot.snapshot_time <= now,
            )
        )

        if entity_id:
            check_query = check_query.filter(MetricSnapshot.entity_id == entity_id)

        check_snapshots = check_query.order_by(MetricSnapshot.snapshot_time).all()

        anomalies = []

        # Check for Z-score based outliers
        for snapshot in check_snapshots:
            # Check if anomaly already recorded
            if self._anomaly_exists(
                metric_category,
                metric_name,
                snapshot.snapshot_time,
                entity_id,
            ):
                continue

            z_score = (snapshot.value - baseline_mean) / baseline_stddev
            abs_z_score = abs(z_score)

            # Classify severity based on Z-score
            if abs_z_score >= self.Z_SCORE_THRESHOLD_CRITICAL:
                severity = "critical"
                anomaly_type = "outlier"
            elif abs_z_score >= self.Z_SCORE_THRESHOLD_HIGH:
                severity = "high"
                anomaly_type = "outlier"
            elif abs_z_score >= self.Z_SCORE_THRESHOLD_MEDIUM:
                severity = "medium"
                anomaly_type = "outlier"
            elif abs_z_score >= self.Z_SCORE_THRESHOLD_LOW:
                severity = "low"
                anomaly_type = "outlier"
            else:
                continue  # Not an anomaly

            # Calculate additional metrics
            deviation = snapshot.value - baseline_mean
            expected_min = baseline_mean - (3 * baseline_stddev)
            expected_max = baseline_mean + (3 * baseline_stddev)

            # Calculate percentile (simplified)
            percentile = self._calculate_percentile(snapshot.value, baseline_values)

            # Create description
            direction = "above" if z_score > 0 else "below"
            description = (
                f"{metric_name} is {abs(deviation):.2f} {direction} baseline "
                f"(Z-score: {z_score:.2f})"
            )

            anomaly = AnomalyRecord(
                metric_category=metric_category,
                metric_name=metric_name,
                detected_at=now,
                metric_time=snapshot.snapshot_time,
                entity_id=entity_id,
                entity_type=snapshot.entity_type,
                anomaly_type=anomaly_type,
                severity=severity,
                observed_value=snapshot.value,
                expected_value=baseline_mean,
                expected_min=expected_min,
                expected_max=expected_max,
                deviation=deviation,
                z_score=z_score,
                percentile=percentile,
                confidence=min(abs_z_score / 4.0, 1.0),  # Scale to 0-1
                baseline_window_days=baseline_days,
                baseline_mean=baseline_mean,
                baseline_stddev=baseline_stddev,
                description=description,
            )

            db.session.add(anomaly)
            anomalies.append(anomaly)

        # Check for spikes and drops (sudden changes)
        if len(check_snapshots) >= 2:
            for i in range(1, len(check_snapshots)):
                prev_snapshot = check_snapshots[i - 1]
                curr_snapshot = check_snapshots[i]

                if self._anomaly_exists(
                    metric_category,
                    metric_name,
                    curr_snapshot.snapshot_time,
                    entity_id,
                ):
                    continue

                # Calculate percent change
                if prev_snapshot.value != 0:
                    percent_change = (
                        (curr_snapshot.value - prev_snapshot.value)
                        / abs(prev_snapshot.value)
                    )
                else:
                    continue

                # Check for spike or drop
                if abs(percent_change) >= self.SPIKE_DROP_THRESHOLD:
                    anomaly_type = "spike" if percent_change > 0 else "drop"

                    # Classify severity
                    if abs(percent_change) >= 1.0:  # 100% change
                        severity = "critical"
                    elif abs(percent_change) >= 0.75:  # 75% change
                        severity = "high"
                    elif abs(percent_change) >= 0.6:  # 60% change
                        severity = "medium"
                    else:
                        severity = "low"

                    description = (
                        f"{metric_name} {'increased' if percent_change > 0 else 'decreased'} "
                        f"by {abs(percent_change * 100):.1f}% in one period"
                    )

                    anomaly = AnomalyRecord(
                        metric_category=metric_category,
                        metric_name=metric_name,
                        detected_at=now,
                        metric_time=curr_snapshot.snapshot_time,
                        entity_id=entity_id,
                        entity_type=curr_snapshot.entity_type,
                        anomaly_type=anomaly_type,
                        severity=severity,
                        observed_value=curr_snapshot.value,
                        expected_value=prev_snapshot.value,
                        deviation=curr_snapshot.value - prev_snapshot.value,
                        confidence=min(abs(percent_change), 1.0),
                        baseline_window_days=baseline_days,
                        baseline_mean=baseline_mean,
                        baseline_stddev=baseline_stddev,
                        description=description,
                        metadata={
                            "percent_change": percent_change * 100,
                            "previous_value": prev_snapshot.value,
                        },
                    )

                    db.session.add(anomaly)
                    anomalies.append(anomaly)

        # Check for trend breaks (using existing trend records)
        trend_anomalies = self._detect_trend_breaks(
            metric_category,
            metric_name,
            entity_id,
            baseline_mean,
            baseline_stddev,
            baseline_days,
        )
        anomalies.extend(trend_anomalies)

        db.session.commit()

        if anomalies:
            self.logger.info(
                "Detected %d anomalies for %s.%s",
                len(anomalies),
                metric_category,
                metric_name,
            )

        return anomalies

    def get_active_anomalies(
        self,
        metric_category: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[AnomalyRecord]:
        """Get active (unresolved) anomalies.

        Args:
            metric_category: Optional category filter
            severity: Optional severity filter
            limit: Maximum number of records to return

        Returns:
            List of AnomalyRecord objects
        """
        query = AnomalyRecord.query.filter(
            AnomalyRecord.resolved == False  # noqa: E712
        )

        if metric_category:
            query = query.filter(AnomalyRecord.metric_category == metric_category)

        if severity:
            query = query.filter(AnomalyRecord.severity == severity)

        return query.order_by(AnomalyRecord.detected_at.desc()).limit(limit).all()

    def acknowledge_anomaly(
        self, anomaly_id: int, acknowledged_by: str
    ) -> Optional[AnomalyRecord]:
        """Acknowledge an anomaly.

        Args:
            anomaly_id: Anomaly record ID
            acknowledged_by: Username of person acknowledging

        Returns:
            Updated AnomalyRecord or None if not found
        """
        anomaly = AnomalyRecord.query.get(anomaly_id)
        if not anomaly:
            return None

        anomaly.acknowledged = True
        anomaly.acknowledged_by = acknowledged_by
        anomaly.acknowledged_at = utc_now()

        db.session.commit()
        return anomaly

    def resolve_anomaly(
        self,
        anomaly_id: int,
        resolved_by: str,
        resolution_notes: Optional[str] = None,
    ) -> Optional[AnomalyRecord]:
        """Resolve an anomaly.

        Args:
            anomaly_id: Anomaly record ID
            resolved_by: Username of person resolving
            resolution_notes: Optional notes about resolution

        Returns:
            Updated AnomalyRecord or None if not found
        """
        anomaly = AnomalyRecord.query.get(anomaly_id)
        if not anomaly:
            return None

        anomaly.resolved = True
        anomaly.resolved_by = resolved_by
        anomaly.resolved_at = utc_now()
        anomaly.resolution_notes = resolution_notes

        db.session.commit()
        return anomaly

    def mark_false_positive(
        self, anomaly_id: int, reason: Optional[str] = None
    ) -> Optional[AnomalyRecord]:
        """Mark an anomaly as a false positive.

        Args:
            anomaly_id: Anomaly record ID
            reason: Optional reason for false positive

        Returns:
            Updated AnomalyRecord or None if not found
        """
        anomaly = AnomalyRecord.query.get(anomaly_id)
        if not anomaly:
            return None

        anomaly.false_positive = True
        anomaly.false_positive_reason = reason

        # Also mark as resolved
        if not anomaly.resolved:
            anomaly.resolved = True
            anomaly.resolved_at = utc_now()
            anomaly.resolution_notes = "Marked as false positive"

        db.session.commit()
        return anomaly

    def _detect_trend_breaks(
        self,
        metric_category: str,
        metric_name: str,
        entity_id: Optional[str],
        baseline_mean: float,
        baseline_stddev: float,
        baseline_days: int,
    ) -> List[AnomalyRecord]:
        """Detect sudden changes in trend direction or magnitude.

        Args:
            metric_category: Metric category
            metric_name: Metric name
            entity_id: Optional entity identifier
            baseline_mean: Baseline mean value
            baseline_stddev: Baseline standard deviation
            baseline_days: Baseline window in days

        Returns:
            List of detected anomalies
        """
        anomalies = []
        now = utc_now()

        # Get recent trend records
        query = TrendRecord.query.filter(
            and_(
                TrendRecord.metric_category == metric_category,
                TrendRecord.metric_name == metric_name,
                TrendRecord.analysis_time >= now - timedelta(days=7),
            )
        )

        if entity_id:
            query = query.filter(TrendRecord.entity_id == entity_id)

        trends = query.order_by(TrendRecord.analysis_time.desc()).limit(2).all()

        if len(trends) < 2:
            return anomalies

        current_trend = trends[0]
        previous_trend = trends[1]

        # Check for trend direction reversal
        if (
            current_trend.trend_direction != previous_trend.trend_direction
            and current_trend.trend_direction != "stable"
            and previous_trend.trend_direction != "stable"
        ):
            description = (
                f"{metric_name} trend reversed from {previous_trend.trend_direction} "
                f"to {current_trend.trend_direction}"
            )

            # Check if we already recorded this anomaly
            if not self._anomaly_exists(
                metric_category,
                metric_name,
                current_trend.analysis_time,
                entity_id,
            ):
                anomaly = AnomalyRecord(
                    metric_category=metric_category,
                    metric_name=metric_name,
                    detected_at=now,
                    metric_time=current_trend.analysis_time,
                    entity_id=entity_id,
                    entity_type=current_trend.entity_type,
                    anomaly_type="trend_break",
                    severity="medium",
                    observed_value=current_trend.mean_value,
                    expected_value=previous_trend.mean_value,
                    deviation=current_trend.mean_value - previous_trend.mean_value,
                    confidence=0.7,
                    baseline_window_days=baseline_days,
                    baseline_mean=baseline_mean,
                    baseline_stddev=baseline_stddev,
                    description=description,
                    metadata={
                        "previous_direction": previous_trend.trend_direction,
                        "current_direction": current_trend.trend_direction,
                    },
                )

                db.session.add(anomaly)
                anomalies.append(anomaly)

        return anomalies

    def _anomaly_exists(
        self,
        metric_category: str,
        metric_name: str,
        metric_time: datetime,
        entity_id: Optional[str] = None,
    ) -> bool:
        """Check if an anomaly record already exists for this metric/time.

        Args:
            metric_category: Metric category
            metric_name: Metric name
            metric_time: Metric timestamp
            entity_id: Optional entity identifier

        Returns:
            True if anomaly exists
        """
        query = AnomalyRecord.query.filter(
            and_(
                AnomalyRecord.metric_category == metric_category,
                AnomalyRecord.metric_name == metric_name,
                AnomalyRecord.metric_time == metric_time,
            )
        )

        if entity_id:
            query = query.filter(AnomalyRecord.entity_id == entity_id)

        return query.first() is not None

    def _calculate_stddev(self, values: List[float]) -> Optional[float]:
        """Calculate standard deviation of values.

        Args:
            values: List of numeric values

        Returns:
            Standard deviation or None if insufficient data
        """
        if len(values) < 2:
            return None

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5

    def _calculate_percentile(self, value: float, baseline: List[float]) -> float:
        """Calculate percentile rank of value within baseline.

        Args:
            value: Value to rank
            baseline: Baseline values

        Returns:
            Percentile (0-100)
        """
        count_below = sum(1 for v in baseline if v < value)
        return (count_below / len(baseline)) * 100 if baseline else 50.0


__all__ = ["AnomalyDetector"]
