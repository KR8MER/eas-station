# API Reference

REST API documentation for EAS Station.

## Overview

EAS Station provides a RESTful API for integration with external systems.

**Base URL**: `http://localhost:5000/api`

## API Endpoints

- [Alerts API](alerts.md) - Alert management and retrieval
- [Boundaries API](boundaries.md) - Geographic boundary operations
- [Audio Sources API](audio.md) - Audio source configuration
- [System API](system.md) - System health and status
- [Radio API](radio.md) - SDR receiver management
- [LED API](led.md) - LED sign control

## Authentication

Currently, API access follows web session authentication. API key support planned for future release.

## Response Format

All API responses use JSON:

```json
{
  "success": true,
  "data": {...},
  "message": "Operation successful"
}
```

## Error Handling

Error responses include:

```json
{
  "success": false,
  "error": "Error description",
  "code": 400
}
```

## Rate Limiting

No rate limiting currently enforced. Use reasonable request intervals.
