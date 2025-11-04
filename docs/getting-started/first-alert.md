# Your First Alert

This guide walks you through setting up your first alert source and verifying that alerts are being received.

## Before You Begin

Ensure you have:

- ✅ Completed [installation](installation.md)
- ✅ Configured [environment variables](configuration.md)
- ✅ EAS Station running and accessible
- ✅ Database connected successfully

## Step 1: Access Admin Panel

Navigate to the admin panel:

```plaintext
http://localhost:5000/admin
```

You should see the main administration dashboard.

## Step 2: Configure Alert Source

### Add NOAA Weather Alerts

1. **Click** "Alert Sources" in the navigation menu
2. **Click** "Add Source" button
3. **Configure the source:**

    | Field | Value | Notes |
    |-------|-------|-------|
    | Name | NOAA Ohio Alerts | Descriptive name |
    | Type | NOAA CAP | Alert source type |
    | State | OH | Your state |
    | Enabled | Yes | Start polling immediately |
    | Poll Interval | 180 | Seconds (3 minutes) |

4. **Click** "Save"

### Verify Source Configuration

After saving, you should see:

- ✅ Source listed in "Alert Sources" table
- ✅ Status showing "Active"
- ✅ Last poll time (may show "Never" initially)

## Step 3: Wait for First Poll

EAS Station polls alert sources on the configured interval (default: 3 minutes).

### Monitor Polling Activity

Watch the logs in real-time:

```bash
docker compose logs -f eas-station
```

You should see:

```plaintext
INFO: Alert poller started
INFO: Polling NOAA Weather Service for OH...
INFO: Retrieved 12 alerts from https://api.weather.gov/alerts/active?area=OH
INFO: Processed 12 alerts, 8 new, 4 existing
INFO: Next poll in 180 seconds
```

## Step 4: Verify Alerts Received

### Check Dashboard

Navigate to the main dashboard:

```plaintext
http://localhost:5000
```

You should see:

- **Alert Map**: Active alerts displayed on interactive map
- **Alert Statistics**: Count of active, recent, and total alerts
- **Recent Alerts List**: Latest alerts with details

### View Alert Details

Click on any alert in the list to see:

- Full alert text
- Geographic coverage area
- SAME codes
- Effective/expiration times
- Event type and severity

## Step 5: Configure Geographic Filtering

By default, all alerts for your state are ingested. To filter by county:

### Add Boundary Filter

1. Navigate to **Admin** → **Boundaries**
2. Click **Add Boundary**
3. Configure:

    ```plaintext
    Name: My County Alerts
    Type: County
    State: OH
    County: Putnam
    Include in Alerts: Yes
    ```

4. Click **Save**

Now only alerts affecting your county will trigger actions.

### Test Boundary Filtering

1. Navigate to **Admin** → **Alert Sources**
2. Edit your NOAA source
3. Check **"Filter by Boundaries"**
4. Save changes

## Step 6: Test Alert Actions

### View Alert on Map

1. Go to dashboard
2. Click an alert marker on the map
3. Verify popup shows alert details

### Test SAME Encoding (Optional)

If you've enabled `EAS_BROADCAST_ENABLED=true`:

1. Navigate to **Admin** → **Manual Broadcast**
2. Select an active alert
3. Click **"Generate SAME Audio"**
4. Verify audio file is created in `static/eas_messages/`

!!! warning "Production Warning"
    Do not broadcast generated SAME tones without proper FCC authorization. Keep output isolated in test environment.

## Step 7: Configure Additional Sources

### Add IPAWS Alerts

For federal alerts (Presidential, AMBER, etc.):

1. **Admin** → **Alert Sources** → **Add Source**
2. Configure:

    ```plaintext
    Name: IPAWS National Alerts
    Type: IPAWS
    Feed URL: https://apps.fema.gov/IPAWS-Server/rest/public/
    Enabled: Yes
    ```

3. Click **Save**

### Add Custom CAP Feed

For third-party alert sources:

1. **Admin** → **Alert Sources** → **Add Source**
2. Configure:

    ```plaintext
    Name: Custom CAP Source
    Type: Custom CAP
    Feed URL: https://your-cap-feed.example.com/feed
    Enabled: Yes
    ```

3. Click **Save**

## Troubleshooting

### No Alerts Appearing

**Possible causes:**

1. **Poll hasn't run yet** - Wait 3-5 minutes for first poll
2. **No active alerts** - Check [NWS Alerts](https://alerts.weather.gov/) for your state
3. **Network issues** - Verify internet connectivity
4. **Wrong state code** - Check configuration
5. **Boundary filtering too restrictive** - Temporarily disable filters

**Check logs:**

```bash
docker compose logs eas-station | grep -i "poll\|alert\|error"
```

### Alerts Not Filtered Correctly

1. Verify boundary configuration:
    ```bash
    docker compose exec eas-station python -c "
    from app_core.models import Boundary
    from app_core import db
    print([b.name for b in Boundary.query.all()])
    "
    ```

2. Check that "Filter by Boundaries" is enabled on alert source

3. Verify SAME codes match your county

### Database Errors

```bash
# Check database connection
docker compose exec eas-station python -c "
from app_core.models import db
from sqlalchemy import text
result = db.session.execute(text('SELECT version()'))
print(result.fetchone())
"
```

### API Errors

If you see `HTTP 403` or `429` errors:

1. **Rate limiting** - Increase `POLL_INTERVAL_SEC`
2. **Invalid user agent** - Check `NOAA_USER_AGENT` configuration
3. **API outage** - Check [NWS Status](https://www.weather.gov/notification/)

## Verifying Alert Pipeline

### End-to-End Test

1. **Poll** - Verify polling logs show successful retrieval
2. **Store** - Check database for alerts:
    ```bash
    docker compose exec alerts-db psql -U postgres -d alerts -c "SELECT COUNT(*) FROM alerts;"
    ```
3. **Display** - Confirm alerts appear on dashboard
4. **Filter** - Verify boundary filtering works
5. **Encode** - Test SAME generation (if enabled)

### System Health Check

Navigate to:

```plaintext
http://localhost:5000/system_health
```

Verify all indicators are green:

- ✅ Database connection
- ✅ Alert poller status
- ✅ Last poll time < 5 minutes ago
- ✅ No critical errors

## Next Steps

Now that alerts are flowing:

<div class="grid cards" markdown>

-   :material-map-marker-radius:{ .lg .middle } **Geographic Boundaries**

    ---

    Fine-tune alert filtering with custom boundaries

    [:octicons-arrow-right-24: Boundaries Guide](../user-guide/boundaries.md)

-   :material-radio:{ .lg .middle } **Hardware Integration**

    ---

    Connect SDR receivers and GPIO relays

    [:octicons-arrow-right-24: Hardware Setup](../user-guide/hardware/index.md)

-   :material-volume-high:{ .lg .middle } **Audio Generation**

    ---

    Configure SAME encoding and text-to-speech

    [:octicons-arrow-right-24: Audio Sources](../user-guide/audio-sources.md)

-   :material-book-open:{ .lg .middle } **Learn the Interface**

    ---

    Explore all dashboard features

    [:octicons-arrow-right-24: Dashboard Guide](../user-guide/dashboard.md)

</div>

## Best Practices

### Alert Source Configuration

- **Multiple sources**: Add both NOAA and IPAWS for comprehensive coverage
- **Reasonable intervals**: 3-5 minutes for weather, 1 minute for IPAWS
- **Monitor logs**: Watch for API errors and rate limiting
- **Test regularly**: Verify alerts during active weather

### Geographic Filtering

- **Start broad**: Begin with state-wide, then add county filters
- **Multiple boundaries**: Create separate boundaries for different alert types
- **Test filtering**: Verify alerts match your coverage area
- **Update regularly**: Keep boundaries synchronized with service area changes

### System Monitoring

- **Check health daily**: Visit `/system_health`
- **Review logs**: Look for errors or warnings
- **Monitor database**: Watch for storage growth
- **Test end-to-end**: Periodically verify full alert pipeline

---

**Congratulations!** 🎉 You've successfully configured your first alert source. Continue to the [User Guide](../user-guide/index.md) to learn all features.
