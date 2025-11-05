# Analytics Module

The analytics module provides comprehensive trend analysis and anomaly detection capabilities for the EAS Station system.

## Features

### 1. Metrics Aggregation
- Collects and aggregates time-series data from various system components
- Supports multiple aggregation periods (hourly, daily, weekly)
- Tracks metrics including:
  - Alert delivery performance (success rate, latency)
  - Audio health and signal quality
  - Receiver status and availability
  - GPIO activation patterns
  - Compliance metrics

### 2. Trend Analysis
- Linear regression analysis of time-series data
- Trend direction classification (rising, falling, stable)
- Trend strength assessment (weak, moderate, strong)
- Statistical significance testing
- Forecasting future values

### 3. Anomaly Detection
- Z-score based outlier detection
- Spike and drop detection
- Trend break detection
- Configurable severity levels (low, medium, high, critical)
- False positive management

## Database Models

### MetricSnapshot
Stores time-series snapshots of aggregated metrics.

Fields:
- `metric_category`: Category of the metric (e.g., "alert_delivery", "audio_health")
- `metric_name`: Name of the metric (e.g., "delivery_success_rate")
- `snapshot_time`: Time of the snapshot
- `window_start`, `window_end`: Time window for aggregation
- `aggregation_period`: Period type (hourly, daily, weekly)
- `value`: Primary metric value
- `min_value`, `max_value`, `avg_value`: Statistical measures
- `stddev_value`: Standard deviation
- `sample_count`: Number of samples
- `entity_id`, `entity_type`: Optional entity identification

### TrendRecord
Stores computed trend analysis results.

Fields:
- `metric_category`, `metric_name`: Metric identification
- `analysis_time`: When the analysis was performed
- `window_start`, `window_end`, `window_days`: Analysis time window
- `trend_direction`: Direction (rising, falling, stable)
- `trend_strength`: Strength (weak, moderate, strong)
- `slope`, `intercept`, `r_squared`, `p_value`: Regression statistics
- `data_points`: Number of data points analyzed
- `mean_value`, `median_value`, `stddev_value`: Statistical measures
- `absolute_change`, `percent_change`, `rate_per_day`: Change metrics
- `forecast_value`, `forecast_confidence`: Forecast data

### AnomalyRecord
Stores detected anomalies.

Fields:
- `metric_category`, `metric_name`: Metric identification
- `detected_at`: Detection timestamp
- `metric_time`: Time of the anomalous value
- `anomaly_type`: Type (outlier, spike, drop, trend_break)
- `severity`: Severity level (low, medium, high, critical)
- `observed_value`, `expected_value`: Values
- `deviation`, `z_score`, `percentile`: Statistical measures
- `baseline_window_days`, `baseline_mean`, `baseline_stddev`: Baseline data
- `acknowledged`, `resolved`: Status tracking
- `false_positive`: False positive flag

## Components

### MetricsAggregator
Collects and aggregates metrics from various sources.

```python
from app_core.analytics import MetricsAggregator

aggregator = MetricsAggregator()

# Aggregate all metrics for the last 24 hours
snapshot_count = aggregator.aggregate_all_metrics(
    aggregation_period="hourly",
    lookback_hours=24,
)
```

### TrendAnalyzer
Analyzes trends in time-series metrics.

```python
from app_core.analytics import TrendAnalyzer

analyzer = TrendAnalyzer()

# Analyze trends for a specific metric
trend = analyzer.analyze_metric_trend(
    metric_category="alert_delivery",
    metric_name="delivery_success_rate",
    window_days=7,
    forecast_days=7,
)

# Get latest trends
trends = analyzer.get_latest_trends(limit=10)
```

### AnomalyDetector
Detects anomalies using statistical methods.

```python
from app_core.analytics import AnomalyDetector

detector = AnomalyDetector()

# Detect anomalies for a specific metric
anomalies = detector.detect_metric_anomalies(
    metric_category="audio_health",
    metric_name="avg_health_score",
    baseline_days=7,
)

# Get active anomalies
active_anomalies = detector.get_active_anomalies(severity="high")

# Acknowledge an anomaly
detector.acknowledge_anomaly(anomaly_id=1, acknowledged_by="admin")

# Resolve an anomaly
detector.resolve_anomaly(
    anomaly_id=1,
    resolved_by="admin",
    resolution_notes="Issue resolved by system restart",
)
```

### AnalyticsScheduler
Manages scheduled analytics tasks.

```python
from app_core.analytics import start_scheduler, stop_scheduler, get_scheduler

# Start the scheduler (runs in background thread)
start_scheduler()

# Manually trigger tasks
scheduler = get_scheduler()
scheduler.run_now("all")  # Run all tasks
scheduler.run_now("metrics")  # Run only metrics aggregation

# Stop the scheduler
stop_scheduler()
```

## API Endpoints

### Metrics Endpoints
- `GET /api/analytics/metrics` - Get metric snapshots
- `GET /api/analytics/metrics/categories` - Get available metric categories
- `POST /api/analytics/metrics/aggregate` - Manually trigger metrics aggregation

### Trend Analysis Endpoints
- `GET /api/analytics/trends` - Get trend analysis records
- `POST /api/analytics/trends/analyze` - Manually trigger trend analysis

### Anomaly Detection Endpoints
- `GET /api/analytics/anomalies` - Get anomaly records
- `POST /api/analytics/anomalies/detect` - Manually trigger anomaly detection
- `POST /api/analytics/anomalies/<id>/acknowledge` - Acknowledge an anomaly
- `POST /api/analytics/anomalies/<id>/resolve` - Resolve an anomaly
- `POST /api/analytics/anomalies/<id>/false-positive` - Mark as false positive

### Dashboard Endpoint
- `GET /api/analytics/dashboard` - Get analytics dashboard summary
- `GET /analytics` - View analytics dashboard UI

## Configuration

The scheduler can be configured with different intervals:

```python
from app_core.analytics import AnalyticsScheduler

scheduler = AnalyticsScheduler(
    metrics_interval_minutes=60,     # Run metrics aggregation every hour
    trends_interval_minutes=360,     # Run trend analysis every 6 hours
    anomalies_interval_minutes=60,   # Run anomaly detection every hour
)
scheduler.start()
```

## Database Migration

To create the analytics tables, run the migration:

```bash
flask db upgrade
```

This will create the following tables:
- `metric_snapshots`
- `trend_records`
- `anomaly_records`

## Usage Examples

### Example 1: Monitoring Alert Delivery Performance

```python
from app_core.analytics import MetricsAggregator, TrendAnalyzer, AnomalyDetector

# Aggregate recent metrics
aggregator = MetricsAggregator()
aggregator.aggregate_alert_delivery_metrics(
    aggregation_period="hourly",
    lookback_hours=24,
)

# Analyze trend
analyzer = TrendAnalyzer()
trend = analyzer.analyze_metric_trend(
    metric_category="alert_delivery",
    metric_name="delivery_success_rate",
    window_days=7,
)

print(f"Trend: {trend.trend_direction} ({trend.trend_strength})")
print(f"R²: {trend.r_squared:.3f}")
print(f"Change: {trend.percent_change:.2f}%")

# Detect anomalies
detector = AnomalyDetector()
anomalies = detector.detect_metric_anomalies(
    metric_category="alert_delivery",
    metric_name="delivery_success_rate",
    baseline_days=7,
)

for anomaly in anomalies:
    print(f"Anomaly detected: {anomaly.description} (Severity: {anomaly.severity})")
```

### Example 2: Automated Monitoring with Scheduler

```python
from app_core.analytics import start_scheduler

# Start the scheduler (runs in background)
start_scheduler()

# The scheduler will automatically:
# - Aggregate metrics every hour
# - Analyze trends every 6 hours
# - Detect anomalies every hour
```

## Performance Considerations

- Metrics aggregation runs queries on existing data tables, so performance depends on table sizes
- Trend analysis requires at least 3 data points; more data points improve accuracy
- Anomaly detection requires sufficient baseline data (recommended: at least 5 data points)
- The scheduler runs in a background thread and should not impact application performance
- Consider scheduling aggregation during off-peak hours for large datasets

## Future Enhancements

Potential future improvements:
- Machine learning-based anomaly detection
- Seasonal trend detection (SARIMA models)
- Correlation analysis between metrics
- Automated alerting and notifications
- Advanced forecasting models
- Custom metric definitions
- Multi-variate analysis
- Real-time streaming analytics

## Contributing

When adding new metrics:
1. Add data collection in the appropriate aggregator method
2. Define metric category and name constants
3. Update dashboard to display new metrics
4. Add documentation

When modifying detection algorithms:
1. Update threshold constants in AnomalyDetector
2. Add unit tests for edge cases
3. Update documentation with new behavior

## License

This module is part of the EAS Station system and follows the same license.
