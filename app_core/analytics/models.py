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

"""Analytics database models for trend analysis and anomaly detection."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.dialects.postgresql import JSONB

from app_core.extensions import db
from app_utils import utc_now


class MetricSnapshot(db.Model):
    """Time-series snapshots of aggregated metrics for trend analysis.

    This model stores periodic snapshots of various system metrics including:
    - Alert delivery rates and latency
    - Audio health scores and signal quality
    - Receiver status and performance
    - GPIO activation patterns
    - Compliance metrics

    Snapshots are typically collected hourly or daily for historical analysis.
    """
    __tablename__ = "metric_snapshots"

    id = db.Column(db.Integer, primary_key=True)

    # Metric identification
    metric_category = db.Column(db.String(50), nullable=False, index=True)
    metric_name = db.Column(db.String(100), nullable=False, index=True)

    # Time window for this snapshot
    snapshot_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    window_start = db.Column(db.DateTime(timezone=True), nullable=False)
    window_end = db.Column(db.DateTime(timezone=True), nullable=False)

    # Aggregation type (hourly, daily, weekly, monthly)
    aggregation_period = db.Column(db.String(20), nullable=False, index=True)

    # Metric values
    value = db.Column(db.Float, nullable=False)
    min_value = db.Column(db.Float)
    max_value = db.Column(db.Float)
    avg_value = db.Column(db.Float)
    stddev_value = db.Column(db.Float)
    sample_count = db.Column(db.Integer)

    # Optional entity/source identifier (e.g., receiver name, audio source, originator)
    entity_id = db.Column(db.String(100), index=True)
    entity_type = db.Column(db.String(50))

    # Additional metadata (JSON)
    # NOTE: Using 'extra_metadata' instead of 'metadata' because 'metadata' is reserved by SQLAlchemy
    extra_metadata = db.Column(JSONB)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    # Composite index for efficient queries
    __table_args__ = (
        db.Index(
            'idx_metric_snapshots_composite',
            'metric_category',
            'metric_name',
            'aggregation_period',
            'snapshot_time',
        ),
        db.Index(
            'idx_metric_snapshots_entity',
            'entity_type',
            'entity_id',
            'metric_name',
            'snapshot_time',
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for API responses."""
        return {
            'id': self.id,
            'metric_category': self.metric_category,
            'metric_name': self.metric_name,
            'snapshot_time': self.snapshot_time.isoformat() if self.snapshot_time else None,
            'window_start': self.window_start.isoformat() if self.window_start else None,
            'window_end': self.window_end.isoformat() if self.window_end else None,
            'aggregation_period': self.aggregation_period,
            'value': self.value,
            'min_value': self.min_value,
            'max_value': self.max_value,
            'avg_value': self.avg_value,
            'stddev_value': self.stddev_value,
            'sample_count': self.sample_count,
            'entity_id': self.entity_id,
            'entity_type': self.entity_type,
            'metadata': self.extra_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TrendRecord(db.Model):
    """Computed trend analysis results for metrics over time.

    This model stores pre-computed trend analysis including:
    - Linear regression results (slope, intercept)
    - Trend direction (rising, falling, stable)
    - Statistical significance
    - Forecast values

    Trends are computed periodically (e.g., daily) for various metrics
    and time windows (e.g., last 7 days, 30 days).
    """
    __tablename__ = "trend_records"

    id = db.Column(db.Integer, primary_key=True)

    # Metric identification (matches MetricSnapshot)
    metric_category = db.Column(db.String(50), nullable=False, index=True)
    metric_name = db.Column(db.String(100), nullable=False, index=True)

    # Analysis time window
    analysis_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    window_start = db.Column(db.DateTime(timezone=True), nullable=False)
    window_end = db.Column(db.DateTime(timezone=True), nullable=False)
    window_days = db.Column(db.Integer, nullable=False)

    # Optional entity/source identifier
    entity_id = db.Column(db.String(100), index=True)
    entity_type = db.Column(db.String(50))

    # Trend classification
    trend_direction = db.Column(db.String(20), nullable=False)  # 'rising', 'falling', 'stable'
    trend_strength = db.Column(db.String(20))  # 'weak', 'moderate', 'strong'

    # Linear regression results
    slope = db.Column(db.Float)
    intercept = db.Column(db.Float)
    r_squared = db.Column(db.Float)  # Coefficient of determination
    p_value = db.Column(db.Float)     # Statistical significance

    # Statistical summary
    data_points = db.Column(db.Integer, nullable=False)
    mean_value = db.Column(db.Float)
    median_value = db.Column(db.Float)
    stddev_value = db.Column(db.Float)
    min_value = db.Column(db.Float)
    max_value = db.Column(db.Float)

    # Rate of change
    absolute_change = db.Column(db.Float)  # Change over period
    percent_change = db.Column(db.Float)   # Percentage change
    rate_per_day = db.Column(db.Float)     # Average daily rate of change

    # Forecast (optional)
    forecast_days_ahead = db.Column(db.Integer)
    forecast_value = db.Column(db.Float)
    forecast_confidence = db.Column(db.Float)  # 0.0 to 1.0

    # Additional metadata (JSON)
    # NOTE: Using 'extra_metadata' instead of 'metadata' because 'metadata' is reserved by SQLAlchemy
    extra_metadata = db.Column(JSONB)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    # Composite index for efficient queries
    __table_args__ = (
        db.Index(
            'idx_trend_records_composite',
            'metric_category',
            'metric_name',
            'window_days',
            'analysis_time',
        ),
        db.Index(
            'idx_trend_records_entity',
            'entity_type',
            'entity_id',
            'metric_name',
            'analysis_time',
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert trend record to dictionary for API responses."""
        return {
            'id': self.id,
            'metric_category': self.metric_category,
            'metric_name': self.metric_name,
            'analysis_time': self.analysis_time.isoformat() if self.analysis_time else None,
            'window_start': self.window_start.isoformat() if self.window_start else None,
            'window_end': self.window_end.isoformat() if self.window_end else None,
            'window_days': self.window_days,
            'entity_id': self.entity_id,
            'entity_type': self.entity_type,
            'trend_direction': self.trend_direction,
            'trend_strength': self.trend_strength,
            'slope': self.slope,
            'intercept': self.intercept,
            'r_squared': self.r_squared,
            'p_value': self.p_value,
            'data_points': self.data_points,
            'mean_value': self.mean_value,
            'median_value': self.median_value,
            'stddev_value': self.stddev_value,
            'min_value': self.min_value,
            'max_value': self.max_value,
            'absolute_change': self.absolute_change,
            'percent_change': self.percent_change,
            'rate_per_day': self.rate_per_day,
            'forecast_days_ahead': self.forecast_days_ahead,
            'forecast_value': self.forecast_value,
            'forecast_confidence': self.forecast_confidence,
            'metadata': self.extra_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AnomalyRecord(db.Model):
    """Detected anomalies in system metrics.

    This model stores detected anomalies including:
    - Statistical outliers (Z-score based)
    - Unexpected changes in trends
    - Deviation from normal patterns
    - Compliance violations

    Anomalies are automatically detected and can trigger alerts.
    """
    __tablename__ = "anomaly_records"

    id = db.Column(db.Integer, primary_key=True)

    # Metric identification
    metric_category = db.Column(db.String(50), nullable=False, index=True)
    metric_name = db.Column(db.String(100), nullable=False, index=True)

    # Detection time and context
    detected_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    metric_time = db.Column(db.DateTime(timezone=True), nullable=False)

    # Optional entity/source identifier
    entity_id = db.Column(db.String(100), index=True)
    entity_type = db.Column(db.String(50))

    # Anomaly classification
    anomaly_type = db.Column(db.String(50), nullable=False, index=True)  # 'outlier', 'spike', 'drop', 'trend_break', 'pattern_violation'
    severity = db.Column(db.String(20), nullable=False)  # 'low', 'medium', 'high', 'critical'

    # Anomaly details
    observed_value = db.Column(db.Float, nullable=False)
    expected_value = db.Column(db.Float)
    expected_min = db.Column(db.Float)
    expected_max = db.Column(db.Float)
    deviation = db.Column(db.Float)  # Absolute deviation from expected

    # Statistical measures
    z_score = db.Column(db.Float)
    percentile = db.Column(db.Float)
    confidence = db.Column(db.Float)  # 0.0 to 1.0

    # Analysis context
    baseline_window_days = db.Column(db.Integer)
    baseline_mean = db.Column(db.Float)
    baseline_stddev = db.Column(db.Float)

    # Description and notes
    description = db.Column(db.Text)
    notes = db.Column(db.Text)

    # Status tracking
    acknowledged = db.Column(db.Boolean, default=False, index=True)
    acknowledged_by = db.Column(db.String(100))
    acknowledged_at = db.Column(db.DateTime(timezone=True))

    resolved = db.Column(db.Boolean, default=False, index=True)
    resolved_by = db.Column(db.String(100))
    resolved_at = db.Column(db.DateTime(timezone=True))
    resolution_notes = db.Column(db.Text)

    # False positive tracking
    false_positive = db.Column(db.Boolean, default=False)
    false_positive_reason = db.Column(db.Text)

    # Additional metadata (JSON)
    # NOTE: Using 'extra_metadata' instead of 'metadata' because 'metadata' is reserved by SQLAlchemy
    extra_metadata = db.Column(JSONB)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Composite index for efficient queries
    __table_args__ = (
        db.Index(
            'idx_anomaly_records_composite',
            'metric_category',
            'metric_name',
            'detected_at',
        ),
        db.Index(
            'idx_anomaly_records_entity',
            'entity_type',
            'entity_id',
            'detected_at',
        ),
        db.Index(
            'idx_anomaly_records_status',
            'acknowledged',
            'resolved',
            'severity',
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert anomaly record to dictionary for API responses."""
        return {
            'id': self.id,
            'metric_category': self.metric_category,
            'metric_name': self.metric_name,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'metric_time': self.metric_time.isoformat() if self.metric_time else None,
            'entity_id': self.entity_id,
            'entity_type': self.entity_type,
            'anomaly_type': self.anomaly_type,
            'severity': self.severity,
            'observed_value': self.observed_value,
            'expected_value': self.expected_value,
            'expected_min': self.expected_min,
            'expected_max': self.expected_max,
            'deviation': self.deviation,
            'z_score': self.z_score,
            'percentile': self.percentile,
            'confidence': self.confidence,
            'baseline_window_days': self.baseline_window_days,
            'baseline_mean': self.baseline_mean,
            'baseline_stddev': self.baseline_stddev,
            'description': self.description,
            'notes': self.notes,
            'acknowledged': self.acknowledged,
            'acknowledged_by': self.acknowledged_by,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'resolved': self.resolved,
            'resolved_by': self.resolved_by,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolution_notes': self.resolution_notes,
            'false_positive': self.false_positive,
            'false_positive_reason': self.false_positive_reason,
            'metadata': self.extra_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


__all__ = ["MetricSnapshot", "TrendRecord", "AnomalyRecord"]
