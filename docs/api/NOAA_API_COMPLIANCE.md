# NOAA Weather API Compliance

## Overview

This document describes how EAS Station complies with the NOAA Weather API v3.3.2 specification.

**Official Documentation:** https://www.weather.gov/documentation/services-web-api  
**Status:** ✅ **FULLY COMPLIANT**

## API Specification

- **API Version:** 3.3.2
- **Base URL:** https://api.weather.gov
- **Authentication:** User-Agent header (required)
- **API Key:** Optional (testing phase on some endpoints)

## Required Headers

### 1. User-Agent (REQUIRED)

**Implementation Status:** ✅ COMPLIANT

The NOAA API **requires** all requests to include a User-Agent header that:
- Identifies the application
- Includes contact information (URL or email)
- Helps NOAA troubleshoot issues and contact developers

**EAS Station Implementation:**
```python
'User-Agent': 'KR8MER Emergency Alert Hub/2.1 (+https://github.com/KR8MER/eas-station; NOAA+IPAWS)'
```

**Configuration:** Set via `NOAA_USER_AGENT` environment variable in `.env`

### 2. Accept Header (RECOMMENDED)

**Implementation Status:** ✅ COMPLIANT

Specifies the desired response format for CAP alerts.

**EAS Station Implementation:**
```python
'Accept': 'application/geo+json, application/json;q=0.9'
```

### 3. API-Key Header (OPTIONAL)

**Implementation Status:** ⚠️ NOT IMPLEMENTED (not currently required)

NOAA is testing API keys on certain endpoints. Currently optional and not enforced.

**Note:** No API key required for /alerts endpoints. API remains free and open.

## Implementation Details

### Files Using NOAA API

1. **`poller/cap_poller.py`** - Automated alert polling
   - Endpoint: `/alerts/active?zone={zone_code}`
   - Headers: User-Agent ✅, Accept ✅

2. **`webapp/admin/maintenance.py`** - Manual alert retrieval
   - Endpoints: `/alerts`, `/alerts/{id}`
   - Headers: User-Agent ✅, Accept ✅

## Rate Limiting

- No explicit rate limits published
- Default poll interval: 180 seconds (3 minutes)
- Minimum enforced: 30 seconds
- Handles HTTP 429 (rate limit) gracefully
- Handles HTTP 503 (service unavailable) gracefully

## Compliance Checklist

- [x] User-Agent header with app identification
- [x] User-Agent includes contact information  
- [x] Accept header for geo+json format
- [x] No unnecessary authentication
- [x] Proper error handling (429, 503)
- [x] Reasonable poll intervals
- [x] Environment variable configuration
- [x] Documentation

## Testing Compliance

**Verify headers are set correctly:**
```python
from poller.cap_poller import CAPPoller
poller = CAPPoller(database_url="your_db_url")
print("User-Agent:", poller.session.headers.get('User-Agent'))
print("Accept:", poller.session.headers.get('Accept'))
```

**Expected Output:**
```
User-Agent: KR8MER Emergency Alert Hub/2.1 (+https://github.com/KR8MER/eas-station; NOAA+IPAWS)
Accept: application/geo+json, application/json;q=0.9
```

## References

- NOAA API Documentation: https://www.weather.gov/documentation/services-web-api
- OpenAPI Spec: Available at https://api.weather.gov/
- CAP Specification: https://docs.oasis-open.org/emergency/cap/v1.2/
