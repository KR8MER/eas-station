# IPAWS Integration Setup Guide

## Overview

This system now supports **IPAWS (Integrated Public Alert & Warning System)** integration, providing access to ALL emergency alerts issued through FEMA's public alerting infrastructure, including:

- ✅ **State/Local Emergency Management Alerts**
- ✅ **AMBER Alerts** (missing children)
- ✅ **Blue Alerts** (law enforcement warnings)
- ✅ **Evacuation Orders**
- ✅ **Shelter-in-Place Notifications**
- ✅ **Hazmat Incidents**
- ✅ **Civil Emergency Messages**
- ✅ **Presidential/National Alerts** (EAN)
- ✅ **NOAA Weather Alerts** (also available via NOAA API)

## What's Different from NOAA-Only Mode?

| Feature | NOAA Only | NOAA + IPAWS |
|---------|-----------|--------------|
| Weather Alerts | ✅ | ✅ |
| Local Emergency Mgmt | ❌ | ✅ |
| AMBER Alerts | ❌ | ✅ |
| Evacuation Orders | ❌ | ✅ |
| State-Level Emergencies | ❌ | ✅ |
| Presidential Alerts | ❌ | ✅ |
| Alert Latency | ~1-2 min | < 1 second |
| Authentication Required | No | Yes (PIN) |

---

## Prerequisites

### 1. IPAWS Access (Required)

You **MUST** have an approved IPAWS Memorandum of Agreement (MOA) with FEMA.

**How to Get Access:**

1. **Email FEMA IPAWS Team:**
   - Email: `ipaws@fema.dhs.gov`
   - Subject: "Request for IPAWS All-Hazards Feed Access"

2. **Provide Your Information:**
   ```
   Organization: [Your Emergency Management Agency/Amateur Radio Group]
   Use Case: Emergency alert monitoring and redistribution for [Your County]
   Technical Contact: [Your Name, Email, Phone]
   Jurisdiction: [County, State]
   ```

3. **Complete MOA Application:**
   - FEMA will send MOA paperwork
   - Approval typically takes 2-4 weeks

4. **Receive Credentials:**
   - IPAWS Endpoint URL
   - IPAWS PIN (keep secret!)

**Note:** If you already have IPAWS access (you mentioned you do), skip to Step 2.

---

## Setup Instructions

### Step 1: Run Database Migration

Add the `source` column to your `cap_alerts` table:

```bash
# Option A: Using SQL directly
psql -U postgres -d alerts -f migrations/001_add_source_column.sql

# Option B: Using Python migration script
python3 migrations/migrate.py
```

**Expected Output:**
```
Running migration: 001_add_source_column.sql
NOTICE: Added source column to cap_alerts table
✓ Migration completed: 001_add_source_column.sql
```

### Step 2: Configure IPAWS Credentials

Edit your `.env` file and add your IPAWS credentials:

```bash
# IPAWS Configuration
IPAWS_ENABLED=true
IPAWS_ENDPOINT=https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public
IPAWS_PIN=your_pin_from_fema_here

# Your jurisdiction FIPS code
LOCATION_FIPS_CODE=039137  # Putnam County, OH

# Poll interval (60 seconds recommended for real-time alerts)
IPAWS_POLL_INTERVAL_SEC=60
```

**Finding Your FIPS Code:**

| County | FIPS Code |
|--------|-----------|
| Putnam County, OH | 039137 |
| Lucas County, OH | 039095 |
| Wood County, OH | 039173 |

Full list: https://www.census.gov/library/reference/code-lists/ansi.html

### Step 3: Test IPAWS Connection

Before running the full poller, test your IPAWS connection:

```bash
python3 poller/ipaws_poller.py
```

**Expected Output:**
```
============================================================
Testing IPAWS Connection
============================================================
Endpoint: https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public
Location: Putnam County, OH (FIPS: 039137)
============================================================

INFO - Fetching IPAWS alerts from: https://apps.fema.gov/...
INFO - Parsed 24 alerts from IPAWS feed
INFO - Filtered to 3 relevant alerts for PUTNAM COUNTY

============================================================
Retrieved 3 relevant IPAWS alerts
============================================================

1. Severe Thunderstorm Warning
   ID: urn:oid:2.49.0.1.840.0.abc123
   Severity: Severe / Urgency: Immediate
   Area: Putnam County
   Headline: Severe Thunderstorm Warning until 8:45 PM EDT
```

**Common Errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `401 Unauthorized` | Invalid PIN | Check `IPAWS_PIN` in `.env` |
| `403 Forbidden` | MOA not approved | Contact `ipaws@fema.dhs.gov` |
| `Timeout` | Endpoint URL wrong | Verify `IPAWS_ENDPOINT` |

### Step 4: Run Unified Poller

The unified poller fetches from both NOAA and IPAWS:

```bash
# Single poll (test)
python3 poller/unified_poller.py --once

# Continuous polling
python3 poller/unified_poller.py
```

**Expected Output:**
```
============================================================
Starting Unified Multi-Source Poll
============================================================
INFO - Polling NOAA Weather API...
INFO - ✓ NOAA: 5 alerts fetched
INFO - Polling IPAWS All-Hazards Feed...
INFO - ✓ IPAWS: 8 alerts fetched
INFO - Deduplication: 13 total → 11 unique (2 duplicates removed)
INFO - ✓ NEW (IPAWS): Evacuation Order - urn:oid:...
INFO - ✓ UPDATED (NOAA): Tornado Warning - NWS-...
============================================================
Poll Summary:
  NOAA fetched:       5
  IPAWS fetched:      8
  Duplicates removed: 2
  Alerts saved:       11
  Errors:             0
  Execution time:     3421ms
============================================================
```

---

## How Deduplication Works

When the same alert is issued through both NOAA and IPAWS:

1. **Identifier Matching:** Alerts with same `identifier` are considered duplicates
2. **Priority Ordering:** IPAWS alerts take priority over NOAA alerts
3. **Source Tagging:** Final alert shows `source='ipaws'` in database

**Example:**
```
NOAA:  Tornado Warning (identifier: NWS-123, source: noaa)
IPAWS: Tornado Warning (identifier: NWS-123, source: ipaws)

Result: Saved with source='ipaws' (IPAWS more authoritative)
```

---

## Alert Source Filtering

The system filters IPAWS alerts to your jurisdiction using multiple methods:

### 1. FIPS Code Match (Highest Priority)
```
Alert FIPS: 039137
Your FIPS:  039137
Result: ✓ ACCEPTED
```

### 2. State-Level Significant Alerts
```
Alert Area: Ohio
Your State: OH
Alert Type: AMBER Alert
Result: ✓ ACCEPTED (statewide significant alert)
```

### 3. County Name Match
```
Alert Area Description: "Putnam County"
Your County: "Putnam County"
Result: ✓ ACCEPTED
```

### 4. Nationwide Alerts
```
Alert Scope: NATIONAL
Alert Event: Emergency Action Notification (EAN)
Result: ✓ ACCEPTED (Presidential alert)
```

---

## Monitoring IPAWS Performance

### View Alert Sources in Database

```sql
-- Count alerts by source
SELECT source, COUNT(*) as count
FROM cap_alerts
GROUP BY source;

-- Recent IPAWS alerts
SELECT event, headline, sent, source
FROM cap_alerts
WHERE source = 'ipaws'
ORDER BY sent DESC
LIMIT 10;
```

### Check Polling Logs

```bash
# View unified poller logs
tail -f logs/noaa_alerts.log | grep IPAWS

# Count IPAWS vs NOAA alerts today
grep "$(date +%Y-%m-%d)" logs/noaa_alerts.log | grep -c "source=ipaws"
grep "$(date +%Y-%m-%d)" logs/noaa_alerts.log | grep -c "source=noaa"
```

---

## Troubleshooting

### No IPAWS Alerts Received

**Check 1: IPAWS Enabled?**
```bash
grep IPAWS_ENABLED .env
# Should show: IPAWS_ENABLED=true
```

**Check 2: Valid Credentials?**
```bash
python3 poller/ipaws_poller.py
# Should NOT show 401/403 errors
```

**Check 3: FIPS Code Correct?**
```bash
grep LOCATION_FIPS_CODE .env
# Verify against: https://www.census.gov/library/reference/code-lists/ansi.html
```

**Check 4: Are There Active Alerts?**

IPAWS only sends active alerts. If your area has no emergencies, the feed will be empty. Test with a broader FIPS code:

```bash
# Temporarily test with state-level FIPS (Ohio = 39)
LOCATION_FIPS_CODE=39
```

### IPAWS Alerts Not Matching Your Area

**Problem:** IPAWS feed contains alerts, but none match your jurisdiction.

**Solution:** Check filtering logic:

```python
# Test your FIPS code
from poller.ipaws_poller import IPAWSPoller

poller = IPAWSPoller(
    ipaws_endpoint="...",
    ipaws_pin="...",
    location_fips="039137",  # Your FIPS
    location_state="OH",
    location_county="PUTNAM COUNTY"
)

# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

poller.fetch_ipaws_alerts()
```

Look for log lines:
```
DEBUG - ✗ IPAWS ALERT REJECTED: Evacuation Order - FIPS: [123456], Area: Lucas County
```

### High Duplicate Count

**Normal:** 5-10% duplicates (weather alerts appear in both NOAA and IPAWS)

**High:** 50%+ duplicates indicates an issue:

1. **Check UGC codes:** IPAWS might be using UGC codes that match your NOAA zone codes
2. **Review logs:** Look for `Dedup: Preferring IPAWS over NOAA` messages
3. **Adjust filtering:** Tighten IPAWS filtering to reduce overlaps

---

## Security Best Practices

### 1. Protect Your IPAWS PIN

**DO:**
- Store PIN in `.env` file (gitignored)
- Use environment variables in production
- Rotate PIN periodically (request new PIN from FEMA)

**DON'T:**
- Commit PIN to Git
- Share PIN publicly
- Hardcode PIN in source code

### 2. Validate Alert Authenticity

IPAWS alerts are digitally signed by FEMA. The parser validates:
- ✅ XML schema compliance (CAP v1.2)
- ✅ Required fields present
- ✅ FIPS code format

### 3. Rate Limiting

IPAWS feed is rate-limited by FEMA:
- **Recommended:** 60-second poll interval
- **Maximum:** 1 request per 10 seconds
- **Exceeding limits:** May result in temporary ban

---

## Migration from NOAA-Only to NOAA+IPAWS

### Existing Alerts

All existing alerts in your database will be tagged with `source='noaa'` by the migration script.

### Backwards Compatibility

The system remains fully compatible with NOAA-only mode:

```bash
# Disable IPAWS, revert to NOAA-only
IPAWS_ENABLED=false
```

The unified poller will automatically skip IPAWS and only poll NOAA.

---

## Support

### IPAWS Access Issues

- Email: `ipaws@fema.dhs.gov`
- IPAWS Help: https://www.fema.gov/emergency-managers/practitioners/integrated-public-alert-warning-system

### Technical Issues

- GitHub Issues: https://github.com/KR8MER/noaa_alerts_systems/issues
- Include logs and configuration (redact IPAWS PIN!)

### Community

- IPAWS User Guide: https://www.fema.gov/media-library-data/IPAWS_User_Guide.pdf
- CAP v1.2 Specification: http://docs.oasis-open.org/emergency/cap/v1.2/

---

## Testing Checklist

Before deploying to production, verify:

- [ ] Database migration completed successfully
- [ ] IPAWS credentials configured in `.env`
- [ ] `python3 poller/ipaws_poller.py` runs without errors
- [ ] `python3 poller/unified_poller.py --once` fetches both sources
- [ ] Alerts appear in database with correct `source` field
- [ ] UI displays alert source badges (see UI section)
- [ ] Deduplication working (check logs for duplicate count)
- [ ] No 401/403 authentication errors
- [ ] Poll interval configured appropriately (60s recommended)

---

## Next Steps

1. **Enable IPAWS:** Set `IPAWS_ENABLED=true` in `.env`
2. **Run migration:** `python3 migrations/migrate.py`
3. **Test connection:** `python3 poller/ipaws_poller.py`
4. **Deploy unified poller:** Update your systemd/docker service to use `unified_poller.py`
5. **Monitor logs:** Watch for IPAWS alerts and deduplication stats

Congratulations! Your system now monitors ALL emergency alerts for your jurisdiction, not just weather! 🚨
