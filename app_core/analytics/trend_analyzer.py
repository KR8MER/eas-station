"""Trend analysis with linear regression and statistical methods.

This module provides functionality to analyze trends in time-series metrics:
- Linear regression analysis
- Trend direction and strength classification
- Statistical significance testing
- Forecasting future values
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_

from app_core.extensions import db
from app_core.analytics.models import MetricSnapshot, TrendRecord
from app_utils import utc_now

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Analyzes trends in time-series metrics using statistical methods."""

    def __init__(self):
        """Initialize the trend analyzer."""
        self.logger = logger

    def analyze_all_metrics(
        self,
        window_days: int = 7,
        metric_categories: Optional[List[str]] = None,
    ) -> int:
        """Analyze trends for all metrics or specified categories.

        Args:
            window_days: Number of days to analyze
            metric_categories: Optional list of categories to analyze

        Returns:
            Number of trend records created
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

        trend_count = 0
        for category, name, entity_id in metrics:
            try:
                trend = self.analyze_metric_trend(
                    metric_category=category,
                    metric_name=name,
                    window_days=window_days,
                    entity_id=entity_id,
                )
                if trend:
                    trend_count += 1
            except Exception as e:
                self.logger.error(
                    "Failed to analyze trend for %s.%s: %s",
                    category,
                    name,
                    str(e),
                )

        self.logger.info("Analyzed %d metric trends", trend_count)
        return trend_count

    def analyze_metric_trend(
        self,
        metric_category: str,
        metric_name: str,
        window_days: int = 7,
        entity_id: Optional[str] = None,
        forecast_days: int = 7,
    ) -> Optional[TrendRecord]:
        """Analyze trend for a specific metric.

        Args:
            metric_category: Metric category
            metric_name: Metric name
            window_days: Number of days to analyze
            entity_id: Optional entity identifier
            forecast_days: Number of days ahead to forecast

        Returns:
            TrendRecord if analysis successful, None otherwise
        """
        now = utc_now()
        window_start = now - timedelta(days=window_days)

        # Get metric snapshots
        query = MetricSnapshot.query.filter(
            and_(
                MetricSnapshot.metric_category == metric_category,
                MetricSnapshot.metric_name == metric_name,
                MetricSnapshot.snapshot_time >= window_start,
                MetricSnapshot.snapshot_time <= now,
            )
        )

        if entity_id:
            query = query.filter(MetricSnapshot.entity_id == entity_id)

        snapshots = query.order_by(MetricSnapshot.snapshot_time).all()

        if len(snapshots) < 3:
            self.logger.debug(
                "Insufficient data for trend analysis: %s.%s (only %d points)",
                metric_category,
                metric_name,
                len(snapshots),
            )
            return None

        # Extract time series data
        times = [(s.snapshot_time - window_start).total_seconds() for s in snapshots]
        values = [s.value for s in snapshots]

        # Perform linear regression
        slope, intercept, r_squared = self._linear_regression(times, values)

        # Calculate statistical measures
        mean_val = sum(values) / len(values)
        median_val = self._calculate_median(values)
        stddev_val = self._calculate_stddev(values)
        min_val = min(values)
        max_val = max(values)

        # Classify trend direction and strength
        trend_direction, trend_strength = self._classify_trend(
            slope, stddev_val, mean_val, r_squared
        )

        # Calculate rate of change
        first_value = values[0]
        last_value = values[-1]
        absolute_change = last_value - first_value
        percent_change = (
            (absolute_change / first_value * 100) if first_value != 0 else 0
        )
        rate_per_day = absolute_change / window_days

        # Calculate forecast
        forecast_value = None
        forecast_confidence = None
        if forecast_days > 0:
            forecast_seconds = (
                (now + timedelta(days=forecast_days)) - window_start
            ).total_seconds()
            forecast_value = slope * forecast_seconds + intercept
            forecast_confidence = r_squared  # Use R² as confidence proxy

        # Calculate p-value (simplified)
        p_value = self._calculate_p_value(r_squared, len(values))

        # Create trend record
        trend = TrendRecord(
            metric_category=metric_category,
            metric_name=metric_name,
            analysis_time=now,
            window_start=window_start,
            window_end=now,
            window_days=window_days,
            entity_id=entity_id,
            entity_type=snapshots[0].entity_type if entity_id else None,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            slope=slope,
            intercept=intercept,
            r_squared=r_squared,
            p_value=p_value,
            data_points=len(snapshots),
            mean_value=mean_val,
            median_value=median_val,
            stddev_value=stddev_val,
            min_value=min_val,
            max_value=max_val,
            absolute_change=absolute_change,
            percent_change=percent_change,
            rate_per_day=rate_per_day,
            forecast_days_ahead=forecast_days if forecast_value else None,
            forecast_value=forecast_value,
            forecast_confidence=forecast_confidence,
        )

        db.session.add(trend)
        db.session.commit()

        self.logger.debug(
            "Analyzed trend for %s.%s: %s (%s) with R²=%.3f",
            metric_category,
            metric_name,
            trend_direction,
            trend_strength,
            r_squared,
        )

        return trend

    def get_latest_trends(
        self,
        metric_category: Optional[str] = None,
        metric_name: Optional[str] = None,
        window_days: Optional[int] = None,
        limit: int = 100,
    ) -> List[TrendRecord]:
        """Get the latest trend records.

        Args:
            metric_category: Optional category filter
            metric_name: Optional name filter
            window_days: Optional window days filter
            limit: Maximum number of records to return

        Returns:
            List of TrendRecord objects
        """
        query = TrendRecord.query

        if metric_category:
            query = query.filter(TrendRecord.metric_category == metric_category)

        if metric_name:
            query = query.filter(TrendRecord.metric_name == metric_name)

        if window_days:
            query = query.filter(TrendRecord.window_days == window_days)

        # Get latest trend for each unique metric
        subquery = (
            db.session.query(
                TrendRecord.metric_category,
                TrendRecord.metric_name,
                TrendRecord.entity_id,
                func.max(TrendRecord.analysis_time).label("max_time"),
            )
            .group_by(
                TrendRecord.metric_category,
                TrendRecord.metric_name,
                TrendRecord.entity_id,
            )
            .subquery()
        )

        query = query.join(
            subquery,
            and_(
                TrendRecord.metric_category == subquery.c.metric_category,
                TrendRecord.metric_name == subquery.c.metric_name,
                TrendRecord.analysis_time == subquery.c.max_time,
            ),
        )

        return query.order_by(TrendRecord.analysis_time.desc()).limit(limit).all()

    def _linear_regression(
        self, x: List[float], y: List[float]
    ) -> Tuple[float, float, float]:
        """Perform simple linear regression.

        Args:
            x: Independent variable (time)
            y: Dependent variable (metric values)

        Returns:
            Tuple of (slope, intercept, r_squared)
        """
        n = len(x)
        if n < 2:
            return 0.0, 0.0, 0.0

        # Calculate means
        x_mean = sum(x) / n
        y_mean = sum(y) / n

        # Calculate slope and intercept
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0, y_mean, 0.0

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # Calculate R²
        ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
        ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))

        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

        return slope, intercept, max(0.0, r_squared)

    def _classify_trend(
        self,
        slope: float,
        stddev: Optional[float],
        mean: float,
        r_squared: float,
    ) -> Tuple[str, str]:
        """Classify trend direction and strength.

        Args:
            slope: Linear regression slope
            stddev: Standard deviation of values
            mean: Mean value
            r_squared: R² value

        Returns:
            Tuple of (direction, strength)
        """
        # Determine direction
        if abs(slope) < 0.001:
            direction = "stable"
        elif slope > 0:
            direction = "rising"
        else:
            direction = "falling"

        # Determine strength based on R² and relative slope
        if direction == "stable":
            strength = "stable"
        elif r_squared < 0.3:
            strength = "weak"
        elif r_squared < 0.7:
            strength = "moderate"
        else:
            strength = "strong"

        # Adjust strength based on relative magnitude of slope
        if stddev and mean != 0:
            relative_slope = abs(slope) / (mean if mean != 0 else 1)
            if relative_slope < 0.01 and strength != "weak":
                strength = "weak"
            elif relative_slope > 0.1 and strength != "strong":
                strength = "strong"

        return direction, strength

    def _calculate_median(self, values: List[float]) -> float:
        """Calculate median of values.

        Args:
            values: List of numeric values

        Returns:
            Median value
        """
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 0:
            return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2
        else:
            return sorted_values[n // 2]

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

    def _calculate_p_value(self, r_squared: float, n: int) -> float:
        """Calculate approximate p-value for regression.

        This is a simplified p-value calculation. For production use,
        consider using scipy.stats for more accurate results.

        Args:
            r_squared: R² value
            n: Number of data points

        Returns:
            Approximate p-value
        """
        if n < 3 or r_squared >= 1.0:
            return 1.0

        # Simplified F-statistic approximation
        f_stat = (r_squared / (1 - r_squared)) * (n - 2)

        # Very rough p-value approximation
        if f_stat > 10:
            return 0.001
        elif f_stat > 5:
            return 0.01
        elif f_stat > 2:
            return 0.05
        else:
            return 0.1


__all__ = ["TrendAnalyzer"]
