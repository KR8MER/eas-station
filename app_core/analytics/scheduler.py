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

"""Scheduled tasks for analytics aggregation and analysis.

This module provides scheduled background tasks for:
- Periodic metrics aggregation
- Trend analysis
- Anomaly detection
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from app_core.analytics.aggregator import MetricsAggregator
from app_core.analytics.trend_analyzer import TrendAnalyzer
from app_core.analytics.anomaly_detector import AnomalyDetector
from app_utils import utc_now

logger = logging.getLogger(__name__)


class AnalyticsScheduler:
    """Manages scheduled analytics tasks."""

    def __init__(
        self,
        metrics_interval_minutes: int = 60,
        trends_interval_minutes: int = 360,  # 6 hours
        anomalies_interval_minutes: int = 60,
    ):
        """Initialize the analytics scheduler.

        Args:
            metrics_interval_minutes: Interval for metrics aggregation (default: 60 min)
            trends_interval_minutes: Interval for trend analysis (default: 360 min)
            anomalies_interval_minutes: Interval for anomaly detection (default: 60 min)
        """
        self.metrics_interval = timedelta(minutes=metrics_interval_minutes)
        self.trends_interval = timedelta(minutes=trends_interval_minutes)
        self.anomalies_interval = timedelta(minutes=anomalies_interval_minutes)

        self.metrics_aggregator = MetricsAggregator()
        self.trend_analyzer = TrendAnalyzer()
        self.anomaly_detector = AnomalyDetector()

        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.last_metrics_run: Optional[datetime] = None
        self.last_trends_run: Optional[datetime] = None
        self.last_anomalies_run: Optional[datetime] = None

        self.logger = logger

    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            self.logger.warning("Scheduler is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logger.info("Analytics scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("Analytics scheduler stopped")

    def _run_loop(self):
        """Main scheduler loop."""
        while self.running:
            try:
                now = utc_now()

                # Check if metrics aggregation should run
                if self._should_run(self.last_metrics_run, self.metrics_interval):
                    self._run_metrics_aggregation()
                    self.last_metrics_run = now

                # Check if trend analysis should run
                if self._should_run(self.last_trends_run, self.trends_interval):
                    self._run_trend_analysis()
                    self.last_trends_run = now

                # Check if anomaly detection should run
                if self._should_run(self.last_anomalies_run, self.anomalies_interval):
                    self._run_anomaly_detection()
                    self.last_anomalies_run = now

                # Sleep for a minute before checking again
                time.sleep(60)

            except Exception as e:
                self.logger.error("Error in scheduler loop: %s", e, exc_info=True)
                time.sleep(60)  # Wait before retrying

    def _should_run(self, last_run: Optional[datetime], interval: timedelta) -> bool:
        """Check if a task should run based on last run time and interval.

        Args:
            last_run: Last run time
            interval: Run interval

        Returns:
            True if task should run
        """
        if last_run is None:
            return True

        return (utc_now() - last_run) >= interval

    def _run_metrics_aggregation(self):
        """Run metrics aggregation task."""
        try:
            self.logger.info("Starting metrics aggregation")

            # Aggregate hourly metrics for the last 24 hours
            snapshot_count = self.metrics_aggregator.aggregate_all_metrics(
                aggregation_period="hourly",
                lookback_hours=24,
            )

            self.logger.info(
                "Metrics aggregation completed: %d snapshots created",
                snapshot_count,
            )

        except Exception as e:
            self.logger.error("Failed to run metrics aggregation: %s", e, exc_info=True)

    def _run_trend_analysis(self):
        """Run trend analysis task."""
        try:
            self.logger.info("Starting trend analysis")

            # Analyze trends for the last 7 days
            trend_count = self.trend_analyzer.analyze_all_metrics(
                window_days=7,
            )

            self.logger.info(
                "Trend analysis completed: %d trends analyzed",
                trend_count,
            )

        except Exception as e:
            self.logger.error("Failed to run trend analysis: %s", e, exc_info=True)

    def _run_anomaly_detection(self):
        """Run anomaly detection task."""
        try:
            self.logger.info("Starting anomaly detection")

            # Detect anomalies with 7-day baseline
            anomaly_count = self.anomaly_detector.detect_all_anomalies(
                baseline_days=7,
            )

            self.logger.info(
                "Anomaly detection completed: %d anomalies detected",
                anomaly_count,
            )

        except Exception as e:
            self.logger.error("Failed to run anomaly detection: %s", e, exc_info=True)

    def run_now(self, task: str = "all"):
        """Manually trigger a task to run now.

        Args:
            task: Task to run ('metrics', 'trends', 'anomalies', or 'all')
        """
        if task in ("metrics", "all"):
            self._run_metrics_aggregation()

        if task in ("trends", "all"):
            self._run_trend_analysis()

        if task in ("anomalies", "all"):
            self._run_anomaly_detection()


# Global scheduler instance
_scheduler: Optional[AnalyticsScheduler] = None


def get_scheduler() -> AnalyticsScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AnalyticsScheduler()
    return _scheduler


def start_scheduler():
    """Start the global scheduler."""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """Stop the global scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None


__all__ = ["AnalyticsScheduler", "get_scheduler", "start_scheduler", "stop_scheduler"]
