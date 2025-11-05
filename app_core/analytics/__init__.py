"""Analytics module for trend analysis and anomaly detection.

This module provides comprehensive analytics capabilities including:
- Time-series metric aggregation and snapshots
- Trend analysis with linear regression
- Anomaly detection using statistical methods
- Historical data analysis for compliance and system health
"""

from app_core.analytics.models import MetricSnapshot, TrendRecord, AnomalyRecord
from app_core.analytics.aggregator import MetricsAggregator
from app_core.analytics.trend_analyzer import TrendAnalyzer
from app_core.analytics.anomaly_detector import AnomalyDetector
from app_core.analytics.scheduler import (
    AnalyticsScheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)

__all__ = [
    "MetricSnapshot",
    "TrendRecord",
    "AnomalyRecord",
    "MetricsAggregator",
    "TrendAnalyzer",
    "AnomalyDetector",
    "AnalyticsScheduler",
    "get_scheduler",
    "start_scheduler",
    "stop_scheduler",
]
