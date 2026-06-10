# Analytics and Reporting

EAS Station™ includes a built-in analytics engine that tracks alert trends, detects anomalies in alert patterns, and aggregates system metrics over time. This data is accessible from the analytics dashboard and via REST API.

---

## Accessing the Analytics Dashboard

Navigate to `/analytics` in the web interface (also linked from the main navigation as **Analytics**).

The dashboard displays:

- **Alert volume over time** — hourly, daily, and weekly alert counts
- **Severity distribution** — breakdown by Extreme / Severe / Moderate / Minor
- **Event type breakdown** — which event codes (TOR, FFW, SVR, etc.) are most frequent
- **Geographic coverage** — which FIPS codes appear most in received alerts
- **Anomaly indicators** — alerts that fall outside normal patterns
- **Trend lines** — moving averages showing whether alert activity is increasing or decreasing

---

## Understanding Metric Categories

The analytics engine aggregates data into three types:

| Category | Description |
|----------|-------------|
| `alert_volume` | Count of alerts received per time period |
| `alert_severity` | Distribution of alert severity levels |
| `alert_events` | Frequency of specific EAS event codes |

Metrics are rolled up at three periods: `hourly`, `daily`, and `weekly`.

---

## Trend Analysis

The **Trends** section shows whether alert activity is statistically rising, falling, or stable over recent periods.

**How to read trends:**

- **Upward trend** — Alert activity is above the historical baseline. This may indicate a developing weather pattern or a period of elevated hazards.
- **Downward trend** — Activity is below baseline. May reflect seasonal quiet periods.
- **Stable** — Activity is within normal range.

Trends are calculated using a linear regression over the selected time window (default: 7 days).

---

## Anomaly Detection

The anomaly detector flags alert patterns that deviate significantly from historical norms. Anomalies appear in the **Anomalies** tab of the analytics dashboard.

Examples of flagged anomalies:

- Sudden spike in alert volume (e.g., 5x the daily average)
- An unusual event code appearing for the first time
- Multiple alerts for the same FIPS code in a short window

**Anomaly severity levels:**

| Level | Description |
|-------|-------------|
| Low | Minor deviation, informational |
| Medium | Notable departure from baseline |
| High | Significant spike requiring attention |
| Critical | Extreme outlier — likely a real emergency event |

---

## API Access to Analytics Data

All analytics data is available via the REST API. Authenticate with an API key (see [API Key Management](API_KEY_MANAGEMENT.md)).

### Get Metric Snapshots

```
GET /api/analytics/metrics
```

**Query parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `category` | Metric category (`alert_volume`, `alert_severity`, etc.) | All |
| `name` | Metric name | All |
| `period` | Aggregation period (`hourly`, `daily`, `weekly`) | All |
| `days` | Lookback window in days | 7 |
| `limit` | Maximum results | 100 |

**Example:**

> **Note:** API-key authentication (`X-API-Key`) is **planned but not yet implemented** — see [API Key Management](API_KEY_MANAGEMENT.md). Until it ships, these endpoints require an authenticated browser session (log in first and reuse the session cookie).

```bash
curl -H "X-API-Key: <key>" \
  "https://your-eas-station.example.com/api/analytics/metrics?category=alert_volume&period=daily&days=30"
```

### Get Trend Data

```
GET /api/analytics/trends
```

Returns trend direction and slope for each metric category over the selected window.

### Get Detected Anomalies

```
GET /api/analytics/anomalies
```

**Query parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `days` | Lookback window | 7 |
| `severity` | Filter by severity level | All |
| `limit` | Maximum results | 50 |

---

## Compliance and Export Reports

### PDF Compliance Reports

Navigate to **Compliance** (`/admin/compliance`) to generate FCC-ready
documentation:

1. Select a date range using the date pickers.
2. Click **Export PDF** to download the **EAS Part 11 Compliance Log**, a
   paginated landscape report whose columns satisfy 47 CFR §§ 11.35(a) and
   11.54(a)(3):
   - Timestamp (local / UTC)
   - Category — `received` (CAP feeds), `relayed` (CAP→SAME), `off-air`
     (RF/stream-decoded EAS), or `manual`
   - Originator (ORG, 3-char SAME code + descriptive name)
   - Event Code (EEE)
   - Event (plain-language name)
   - FIPS Codes (PSSCCC list)
   - Station ID (LLLLLLLL, the 8-char identifier per § 11.31)
   - Action Taken (`Initiated` / `Relayed` / `Not relayed` / `Received` /
     `Decode error`)
   - Identifier (CAP URN or full SAME header)
   - Details (issue/purge times, forwarding reason, severity/urgency, etc.)

   Cells wrap to as many lines as needed, alternating row shading separates
   entries, and the trailing summary block breaks the totals out by
   category, originator, and action.

### CSV Export

The compliance log CSV (also exported from `/admin/compliance`) carries
the same FCC Part 11 columns as the PDF: Timestamp, Category, Originator,
Event Code, Event, FIPS Codes, Issue Time, Purge / Expires, Station ID,
Identifier, Status, Action Taken, Action Reason, and a JSON `Details`
blob for any category-specific metadata that did not get its own column.

To export raw CAP/alert history instead, go to **Alert History**
(`/admin/alerts`), apply filters, and click **Export CSV**.

### Statistics Tab

The **Statistics** tab on the dashboard provides a quick summary:
- Total alerts received (last 24 hours / 7 days / 30 days)
- Alert severity breakdown as a bar chart
- Top 10 event codes by frequency
- Top 5 FIPS codes by alert count

---

## Data Retention

Analytics metric snapshots are retained based on their aggregation period:

| Period | Default retention |
|--------|------------------|
| Hourly | 30 days |
| Daily | 365 days |
| Weekly | 5 years |

Raw alert records in the `cap_alerts` table are retained indefinitely until manually cleaned. Use **Admin → Maintenance → Cleanup** to purge old records.

---

## Integrating with External BI Tools

The REST API makes it straightforward to feed analytics data into external tools such as Grafana, Kibana, or Power BI.

**Grafana example using the Simple JSON datasource plugin:**

1. Install the [Infinity datasource plugin](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/) in Grafana.
2. Add a new datasource of type **Infinity**.
3. Set the base URL to `https://your-eas-station.example.com`.
4. Add a custom header: `X-API-Key` = `<your-key>`.
5. Create a panel using the `/api/analytics/metrics` endpoint with `period=daily`.

---

## Troubleshooting

### Dashboard shows "No data"

- Analytics data is populated by background workers. If the system was just installed, allow at least 24 hours for trend data to accumulate.
- Verify the poller service is running:
  ```bash
  sudo systemctl status eas-station-poller
  ```

### API returns empty `metrics` array

- Check the `days` parameter — default is 7. If the system has been running for less than 7 days, reduce this value.
- Confirm that alerts are being received (**Alert History** should have entries).

### Trends always show "stable" even during known events

- Trend calculations require a baseline of at least 7 days of data. During the first week of operation, trends may not reflect short-term spikes accurately.
