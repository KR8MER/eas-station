"""Metrics aggregation for collecting and storing time-series data.

This module provides functionality to aggregate metrics from various sources:
- Alert delivery performance
- Audio health and signal quality
- Receiver status and availability
- GPIO activation patterns
- Compliance metrics
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func

from app_core.extensions import db
from app_core.models import (
    AlertDeliveryReport,
    AudioHealthStatus,
    AudioSourceMetrics,
    GPIOActivationLog,
    RadioReceiverStatus,
)
from app_core.analytics.models import MetricSnapshot
from app_core.eas_storage import collect_compliance_log_entries
from app_utils import utc_now

logger = logging.getLogger(__name__)


class MetricsAggregator:
    """Aggregates metrics from various sources into time-series snapshots."""

    def __init__(self):
        """Initialize the metrics aggregator."""
        self.logger = logger

    def aggregate_all_metrics(
        self,
        aggregation_period: str = "hourly",
        lookback_hours: int = 24,
    ) -> int:
        """Aggregate all available metrics for the specified period.

        Args:
            aggregation_period: The aggregation period ('hourly', 'daily', 'weekly')
            lookback_hours: How many hours back to aggregate

        Returns:
            Number of snapshots created
        """
        snapshot_count = 0

        # Aggregate alert delivery metrics
        snapshot_count += self.aggregate_alert_delivery_metrics(
            aggregation_period, lookback_hours
        )

        # Aggregate audio health metrics
        snapshot_count += self.aggregate_audio_health_metrics(
            aggregation_period, lookback_hours
        )

        # Aggregate receiver status metrics
        snapshot_count += self.aggregate_receiver_status_metrics(
            aggregation_period, lookback_hours
        )

        # Aggregate GPIO activation metrics
        snapshot_count += self.aggregate_gpio_metrics(
            aggregation_period, lookback_hours
        )

        # Aggregate compliance metrics
        snapshot_count += self.aggregate_compliance_metrics(
            aggregation_period, lookback_hours
        )

        self.logger.info(
            "Aggregated %d metric snapshots for period %s",
            snapshot_count,
            aggregation_period,
        )

        return snapshot_count

    def aggregate_alert_delivery_metrics(
        self,
        aggregation_period: str = "hourly",
        lookback_hours: int = 24,
    ) -> int:
        """Aggregate alert delivery performance metrics.

        Metrics collected:
        - Delivery success rate
        - Average delivery latency
        - Alert volume (count)
        """
        snapshot_count = 0
        now = utc_now()
        window_start = now - timedelta(hours=lookback_hours)

        # Get time windows to aggregate
        windows = self._get_time_windows(window_start, now, aggregation_period)

        for win_start, win_end in windows:
            # Check if snapshot already exists
            if self._snapshot_exists(
                "alert_delivery",
                "delivery_success_rate",
                win_end,
                aggregation_period,
            ):
                continue

            # Query delivery reports in this window
            reports = AlertDeliveryReport.query.filter(
                AlertDeliveryReport.timestamp >= win_start,
                AlertDeliveryReport.timestamp < win_end,
            ).all()

            if not reports:
                continue

            # Calculate success rate
            total_alerts = sum(r.expected_count for r in reports)
            delivered = sum(r.delivered_count for r in reports)
            success_rate = (delivered / total_alerts * 100) if total_alerts > 0 else 0

            # Calculate average latency
            latencies = [
                r.avg_latency_ms for r in reports if r.avg_latency_ms is not None
            ]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0

            # Create success rate snapshot
            snapshot = MetricSnapshot(
                metric_category="alert_delivery",
                metric_name="delivery_success_rate",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=success_rate,
                min_value=min(
                    (r.delivered_count / r.expected_count * 100)
                    if r.expected_count > 0
                    else 0
                    for r in reports
                ),
                max_value=max(
                    (r.delivered_count / r.expected_count * 100)
                    if r.expected_count > 0
                    else 0
                    for r in reports
                ),
                avg_value=success_rate,
                sample_count=len(reports),
            )
            db.session.add(snapshot)
            snapshot_count += 1

            # Create average latency snapshot
            if avg_latency > 0:
                snapshot = MetricSnapshot(
                    metric_category="alert_delivery",
                    metric_name="avg_delivery_latency_ms",
                    snapshot_time=win_end,
                    window_start=win_start,
                    window_end=win_end,
                    aggregation_period=aggregation_period,
                    value=avg_latency,
                    min_value=min(latencies),
                    max_value=max(latencies),
                    avg_value=avg_latency,
                    sample_count=len(latencies),
                )
                db.session.add(snapshot)
                snapshot_count += 1

            # Create alert volume snapshot
            snapshot = MetricSnapshot(
                metric_category="alert_delivery",
                metric_name="alert_volume",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=float(total_alerts),
                sample_count=len(reports),
            )
            db.session.add(snapshot)
            snapshot_count += 1

        db.session.commit()
        return snapshot_count

    def aggregate_audio_health_metrics(
        self,
        aggregation_period: str = "hourly",
        lookback_hours: int = 24,
    ) -> int:
        """Aggregate audio health and signal quality metrics.

        Metrics collected:
        - Average health score
        - Silence detection rate
        - Signal level (RMS)
        """
        snapshot_count = 0
        now = utc_now()
        window_start = now - timedelta(hours=lookback_hours)

        windows = self._get_time_windows(window_start, now, aggregation_period)

        for win_start, win_end in windows:
            if self._snapshot_exists(
                "audio_health",
                "avg_health_score",
                win_end,
                aggregation_period,
            ):
                continue

            # Query audio health status in this window
            health_records = AudioHealthStatus.query.filter(
                AudioHealthStatus.timestamp >= win_start,
                AudioHealthStatus.timestamp < win_end,
            ).all()

            if not health_records:
                continue

            # Calculate average health score
            health_scores = [r.health_score for r in health_records]
            avg_health = sum(health_scores) / len(health_scores)

            snapshot = MetricSnapshot(
                metric_category="audio_health",
                metric_name="avg_health_score",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=avg_health,
                min_value=min(health_scores),
                max_value=max(health_scores),
                avg_value=avg_health,
                stddev_value=self._calculate_stddev(health_scores),
                sample_count=len(health_records),
            )
            db.session.add(snapshot)
            snapshot_count += 1

            # Calculate silence detection rate
            silence_count = sum(1 for r in health_records if r.silence_detected)
            silence_rate = (silence_count / len(health_records) * 100)

            snapshot = MetricSnapshot(
                metric_category="audio_health",
                metric_name="silence_detection_rate",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=silence_rate,
                sample_count=len(health_records),
            )
            db.session.add(snapshot)
            snapshot_count += 1

            # Query audio metrics for signal levels
            audio_metrics = AudioSourceMetrics.query.filter(
                AudioSourceMetrics.timestamp >= win_start,
                AudioSourceMetrics.timestamp < win_end,
            ).all()

            if audio_metrics:
                rms_levels = [m.rms_level_db for m in audio_metrics]
                avg_rms = sum(rms_levels) / len(rms_levels)

                snapshot = MetricSnapshot(
                    metric_category="audio_health",
                    metric_name="avg_signal_level_db",
                    snapshot_time=win_end,
                    window_start=win_start,
                    window_end=win_end,
                    aggregation_period=aggregation_period,
                    value=avg_rms,
                    min_value=min(rms_levels),
                    max_value=max(rms_levels),
                    avg_value=avg_rms,
                    stddev_value=self._calculate_stddev(rms_levels),
                    sample_count=len(audio_metrics),
                )
                db.session.add(snapshot)
                snapshot_count += 1

        db.session.commit()
        return snapshot_count

    def aggregate_receiver_status_metrics(
        self,
        aggregation_period: str = "hourly",
        lookback_hours: int = 24,
    ) -> int:
        """Aggregate receiver status and availability metrics.

        Metrics collected:
        - Receiver availability rate
        - Average signal quality
        """
        snapshot_count = 0
        now = utc_now()
        window_start = now - timedelta(hours=lookback_hours)

        windows = self._get_time_windows(window_start, now, aggregation_period)

        for win_start, win_end in windows:
            if self._snapshot_exists(
                "receiver_status",
                "availability_rate",
                win_end,
                aggregation_period,
            ):
                continue

            # Query receiver status in this window
            status_records = RadioReceiverStatus.query.filter(
                RadioReceiverStatus.timestamp >= win_start,
                RadioReceiverStatus.timestamp < win_end,
            ).all()

            if not status_records:
                continue

            # Calculate availability rate (percentage of time receiver was active)
            active_count = sum(1 for r in status_records if r.is_active)
            availability_rate = (active_count / len(status_records) * 100)

            snapshot = MetricSnapshot(
                metric_category="receiver_status",
                metric_name="availability_rate",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=availability_rate,
                sample_count=len(status_records),
            )
            db.session.add(snapshot)
            snapshot_count += 1

        db.session.commit()
        return snapshot_count

    def aggregate_gpio_metrics(
        self,
        aggregation_period: str = "hourly",
        lookback_hours: int = 24,
    ) -> int:
        """Aggregate GPIO activation pattern metrics.

        Metrics collected:
        - Activation count
        - Average activation duration
        """
        snapshot_count = 0
        now = utc_now()
        window_start = now - timedelta(hours=lookback_hours)

        windows = self._get_time_windows(window_start, now, aggregation_period)

        for win_start, win_end in windows:
            if self._snapshot_exists(
                "gpio_activity",
                "activation_count",
                win_end,
                aggregation_period,
            ):
                continue

            # Query GPIO activations in this window
            activations = GPIOActivationLog.query.filter(
                GPIOActivationLog.activated_at >= win_start,
                GPIOActivationLog.activated_at < win_end,
            ).all()

            if not activations:
                continue

            # Create activation count snapshot
            snapshot = MetricSnapshot(
                metric_category="gpio_activity",
                metric_name="activation_count",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=float(len(activations)),
                sample_count=len(activations),
            )
            db.session.add(snapshot)
            snapshot_count += 1

            # Calculate average duration
            durations = [
                a.duration_seconds for a in activations if a.duration_seconds is not None
            ]
            if durations:
                avg_duration = sum(durations) / len(durations)

                snapshot = MetricSnapshot(
                    metric_category="gpio_activity",
                    metric_name="avg_activation_duration",
                    snapshot_time=win_end,
                    window_start=win_start,
                    window_end=win_end,
                    aggregation_period=aggregation_period,
                    value=avg_duration,
                    min_value=min(durations),
                    max_value=max(durations),
                    avg_value=avg_duration,
                    sample_count=len(durations),
                )
                db.session.add(snapshot)
                snapshot_count += 1

        db.session.commit()
        return snapshot_count

    def aggregate_compliance_metrics(
        self,
        aggregation_period: str = "daily",
        lookback_hours: int = 168,  # 7 days
    ) -> int:
        """Aggregate compliance metrics.

        Metrics collected:
        - Weekly test relay rate
        - Received vs relayed ratio
        """
        snapshot_count = 0
        now = utc_now()
        window_start = now - timedelta(hours=lookback_hours)

        windows = self._get_time_windows(window_start, now, aggregation_period)

        for win_start, win_end in windows:
            if self._snapshot_exists(
                "compliance",
                "test_relay_rate",
                win_end,
                aggregation_period,
            ):
                continue

            # Use existing compliance data collection
            window_days = int((win_end - win_start).total_seconds() / 86400)
            entries, _, _ = collect_compliance_log_entries(window_days)

            if not entries:
                continue

            # Calculate relay rate
            received_total = sum(1 for entry in entries if entry["category"] == "received")
            auto_relay_total = sum(1 for entry in entries if entry["category"] == "relayed")
            manual_relay_total = sum(1 for entry in entries if entry["category"] == "manual")
            relayed_total = auto_relay_total + manual_relay_total

            relay_rate = (relayed_total / received_total * 100) if received_total > 0 else 0

            snapshot = MetricSnapshot(
                metric_category="compliance",
                metric_name="test_relay_rate",
                snapshot_time=win_end,
                window_start=win_start,
                window_end=win_end,
                aggregation_period=aggregation_period,
                value=relay_rate,
                sample_count=received_total,
                metadata={
                    "received": received_total,
                    "relayed": relayed_total,
                    "auto_relayed": auto_relay_total,
                    "manual_relayed": manual_relay_total,
                },
            )
            db.session.add(snapshot)
            snapshot_count += 1

        db.session.commit()
        return snapshot_count

    def _get_time_windows(
        self,
        start_time: datetime,
        end_time: datetime,
        aggregation_period: str,
    ) -> List[Tuple[datetime, datetime]]:
        """Generate time windows for aggregation.

        Args:
            start_time: Start of the overall period
            end_time: End of the overall period
            aggregation_period: Period type ('hourly', 'daily', 'weekly')

        Returns:
            List of (window_start, window_end) tuples
        """
        windows = []

        if aggregation_period == "hourly":
            delta = timedelta(hours=1)
        elif aggregation_period == "daily":
            delta = timedelta(days=1)
        elif aggregation_period == "weekly":
            delta = timedelta(weeks=1)
        else:
            raise ValueError(f"Invalid aggregation period: {aggregation_period}")

        current = start_time
        while current < end_time:
            window_end = min(current + delta, end_time)
            windows.append((current, window_end))
            current = window_end

        return windows

    def _snapshot_exists(
        self,
        category: str,
        name: str,
        snapshot_time: datetime,
        aggregation_period: str,
        entity_id: Optional[str] = None,
    ) -> bool:
        """Check if a snapshot already exists.

        Args:
            category: Metric category
            name: Metric name
            snapshot_time: Snapshot time
            aggregation_period: Aggregation period
            entity_id: Optional entity identifier

        Returns:
            True if snapshot exists
        """
        query = MetricSnapshot.query.filter(
            MetricSnapshot.metric_category == category,
            MetricSnapshot.metric_name == name,
            MetricSnapshot.snapshot_time == snapshot_time,
            MetricSnapshot.aggregation_period == aggregation_period,
        )

        if entity_id:
            query = query.filter(MetricSnapshot.entity_id == entity_id)

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


__all__ = ["MetricsAggregator"]
