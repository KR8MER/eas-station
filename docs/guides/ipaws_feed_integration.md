# IPAWS Feed and Pub/Sub Integration Overview

This document distills guidance received from the IPAWS Program Management Office and
outlines concrete ways our NOAA Alerts System can leverage the provided feeds and the AWS
Simple Notification Service (SNS) pilot.

## Key Takeaways

- **No Authentication Required**: IPAWS provides publicly accessible REST feeds with no API keys,
  passwords, or registration required.
- **Feed Types**: IPAWS exposes feeds for Emergency Alert System (EAS), Non-Weather Emergency
  Messages (NWEM), Wireless Emergency Alerts (WEA), PUBLIC (all alerts), and PUBLIC_NON_EAS.
- **Polling Best Practices**: FEMA recommends polling **no more frequently than every 2 minutes
  (120 seconds)**. Cache responses on your server before redistributing to end users.
- **CAP XML Support**: Feeds return CAP 1.2 XML payloads. The poller automatically parses these
  documents (including polygons, circles, and SAME geocodes) into the existing alert ingestion
  workflow without requiring separate code paths.
- **Source Tracking**: Alerts stored in PostGIS are stamped with their originating feed
  (NOAA, IPAWS, or MANUAL) and the poller automatically deduplicates alerts across multi-feed runs.
- **Caching Implemented**: EAS Station uses PostgreSQL + PostGIS for persistent storage and Redis
  for runtime caching, ensuring efficient alert distribution and geographic queries.
- **SNS Push Option**: IPAWS is piloting AWS SNS topics for push-style integrations (email,
  HTTPS webhooks, Lambda, Kinesis). Currently only `EAS_PUBLIC_FEED` topic is available.

## REST Feed Consumption Strategy

### 1. Start in Staging (Testing Environment)

Use the **STAGING** environment during development and QA. These feeds contain test alerts:

| Feed Type | Staging URL |
|-----------|-------------|
| **PUBLIC** (All alerts) | `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}` |
| **EAS** | `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/eas/recent/{timestamp}` |
| **WEA** | `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/PublicWEA/recent/{timestamp}` |
| **NWEM** | `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/nwem/recent/{timestamp}` |
| **PUBLIC_NON_EAS** | `https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public_non_eas/recent/{timestamp}` |

**Configuration:**
```bash
# In .env file:
IPAWS_CAP_FEED_URLS=https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}
POLL_INTERVAL_SEC=120  # 2 minutes (FEMA recommended)
```

### 2. Transition to Production (Live Alerts)

After thorough testing in staging, switch to **PRODUCTION** endpoints for real alerts:

| Feed Type | Production URL |
|-----------|----------------|
| **PUBLIC** (All alerts) | `https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}` |
| **EAS** | `https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/eas/recent/{timestamp}` |
| **WEA** | `https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/PublicWEA/recent/{timestamp}` |
| **NWEM** | `https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/nwem/recent/{timestamp}` |
| **PUBLIC_NON_EAS** | `https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public_non_eas/recent/{timestamp}` |

**Configuration:**
```bash
# In .env file:
IPAWS_CAP_FEED_URLS=https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}
POLL_INTERVAL_SEC=120  # 2 minutes (FEMA recommended)
```

**Note:** The `{timestamp}` placeholder is automatically replaced by the poller using ISO-8601 format
based on `IPAWS_DEFAULT_LOOKBACK_HOURS` (default: 12 hours) or the most recent alert processed.

### 3. Polling and Caching (Already Implemented)

EAS Station implements FEMA's best practices:

- ✅ **2-Minute Polling**: Default interval is 120 seconds (configurable via `POLL_INTERVAL_SEC`)
- ✅ **Automatic Caching**: PostgreSQL + PostGIS for persistent storage, Redis for runtime cache
- ✅ **Deduplication**: Alerts are deduplicated by `identifier` + `sent` timestamp automatically
- ✅ **Source Tracking**: All alerts are stamped with source (NOAA/IPAWS/MANUAL) in database
- ✅ **Exponential Backoff**: On errors, polling backs off exponentially (60s → 120s → 240s → 300s)

### 4. Alert Distribution

Alerts are automatically distributed through:

- **Web Dashboard**: Real-time map display with alert details
- **REST API**: `/api/alerts` endpoint for programmatic access
- **WebSockets**: Real-time push to connected clients
- **LED/OLED Displays**: Physical alert indicators (if configured)
- **EAS Broadcast**: SAME/EAS encoding and audio generation (if enabled)
- **GPIO Triggers**: Hardware relay control for external systems

## SNS Pub/Sub Integration Strategy

1. **Subscription Setup**  
   - Request addition of our preferred endpoint (e.g., HTTPS webhook or Amazon Kinesis Data
     Firehose) to the `EAS_PUBLIC_FEED` topic via the IPAWS engineering team.
   - Ensure the endpoint can receive and acknowledge SNS subscription confirmation
     messages.

2. **Message Handling**  
   - SNS delivers the same payloads as the Public feed. Validate the message signature,
     parse the CAP alert, and persist it via our existing ingestion pipeline.
   - Consider using SNS as a trigger to accelerate pull-based refreshes when the polling
     interval is too coarse.

3. **Fallback and Monitoring**  
   - Keep the REST polling flow active as a fallback until SNS topics reach parity for all
     desired dissemination channels.
   - Instrument metrics on delivery latency, failures, and retry counts.

## Quick Start Guide

### 1. Configure IPAWS Feed

Edit your `.env` file (or `/app-config/.env` in persistent environments):

```bash
# Start with STAGING for testing
IPAWS_CAP_FEED_URLS=https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}
POLL_INTERVAL_SEC=120  # 2 minutes (FEMA recommended)

# After testing, switch to PRODUCTION
# IPAWS_CAP_FEED_URLS=https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}
```

### 2. Restart the IPAWS Poller

```bash
docker compose restart ipaws-poller
```

### 3. Monitor Alert Ingestion

Check the logs to verify alerts are being received:

```bash
docker compose logs -f ipaws-poller
```

You should see logs like:
```
Successfully fetched X alerts from IPAWS feed
Saved Y new alerts to database
```

### 4. View Alerts in Dashboard

Open your EAS Station web interface and navigate to the alerts dashboard to see incoming IPAWS alerts on the map.

## Optional: SNS Push Integration

For push-based alert delivery instead of polling:

1. Contact IPAWS Engineering Branch (fema-ipaws-eng@fema.dhs.gov) to request SNS topic subscription
2. Implement webhook endpoint (e.g., `/api/ipaws/sns`) to handle SNS notifications
3. Configure your endpoint to process both subscription confirmation and alert notification messages
4. Keep REST polling as a fallback during SNS testing

## Additional Resources

- [IPAWS All-Hazard Info Feed overview](https://www.fema.gov/about/offices/national-continuity-programs/integrated-public-alert-warning-system/open-platform-emergency-networks)
- [AWS SNS HTTP/HTTPS endpoint setup guide](https://docs.aws.amazon.com/sns/latest/dg/sns-http-https-endpoint-as-subscriber.html)

