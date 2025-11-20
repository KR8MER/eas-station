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
