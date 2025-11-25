# Custom Display Screens for LED and VFD

The EAS Station now supports custom display screen templates that can show dynamic content from API endpoints on both LED signs and VFD displays.

## Overview

The custom screen system allows you to:

- **Create reusable screen templates** with dynamic content
- **Fetch data from API endpoints** and populate templates
- **Display system metrics** (CPU, memory, disk, network)
- **Show alert information** (count, severity, descriptions)
- **Create VU meters** for audio levels on VFD
- **Rotate between multiple screens** automatically
- **Apply conditional logic** to show/hide screens based on data

## Features

### LED Display Capabilities

- 4 lines × 20 characters per line
- Full RGB color support
- Multiple display modes (FLASH, ROLL, SCROLL, HOLD, etc.)
- Per-line formatting options
- Dynamic variable substitution

### VFD Display Capabilities

- 140×32 pixel monochrome graphics
- Text rendering at any position
- Graphics primitives (lines, rectangles, pixels)
- Progress bars / VU meters
- Image display support

## Creating Custom Screens

### Using the API

Create a new screen via POST to `/api/screens`:

```json
{
  "name": "system_status",
  "description": "System health dashboard",
  "display_type": "led",
  "enabled": true,
  "priority": 2,
  "refresh_interval": 30,
  "duration": 10,
  "template_data": {
    "lines": [
      "SYSTEM STATUS",
      "Health: {status.status}",
      "CPU: {status.system_resources.cpu_usage_percent}%",
      "Alerts: {status.active_alerts_count}"
    ],
    "color": "GREEN",
    "mode": "HOLD",
    "speed": "SPEED_3"
  },
  "data_sources": [
    {
      "endpoint": "/api/system_status",
      "var_name": "status"
    }
  ]
}
```

### Template Variables

Templates support variable substitution using `{variable.path}` syntax:

#### System Status (`/api/system_status`)
- `{status.status}` - Overall health status
- `{status.active_alerts_count}` - Number of active alerts
- `{status.system_resources.cpu_usage_percent}` - CPU usage %
- `{status.system_resources.memory_usage_percent}` - Memory usage %
- `{status.system_resources.disk_usage_percent}` - Disk usage %
- `{status.database_status}` - Database connection status

#### Alerts (`/api/alerts`)
- `{alerts.features.length}` - Alert count
- `{alerts.features[0].properties.event}` - First alert event type
- `{alerts.features[0].properties.severity}` - Alert severity
- `{alerts.features[0].properties.description}` - Alert description
- `{alerts.features[0].properties.area_desc}` - Affected area

#### Network Info
- `{network.ip_address}` - System IP address
- `{network.uptime_human}` - System uptime (human readable)

#### Time/Date (built-in)
- `{now.time}` - Current time (12-hour format)
- `{now.time_24}` - Current time (24-hour format)
- `{now.date}` - Current date
- `{now.datetime}` - Current date and time

#### Radio Receivers (`/api/monitoring/radio`)
- `{receivers[0].display_name}` - Receiver name
- `{receivers[0].latest_status.signal_strength}` - Signal strength
- `{receivers[0].latest_status.locked}` - Lock status

## VFD Graphics Templates

For VFD displays, create graphics-based screens:

```json
{
  "name": "vfd_system_meters",
  "display_type": "vfd",
  "template_data": {
    "type": "graphics",
    "elements": [
      {
        "type": "text",
        "x": 2,
        "y": 1,
        "text": "SYSTEM RESOURCES"
      },
      {
        "type": "progress_bar",
        "x": 10,
        "y": 8,
        "width": 120,
        "height": 6,
        "value": "{status.system_resources.cpu_usage_percent}",
        "label": "CPU"
      },
      {
        "type": "progress_bar",
        "x": 10,
        "y": 17,
        "width": 120,
        "height": 6,
        "value": "{status.system_resources.memory_usage_percent}",
        "label": "MEM"
      }
    ]
  },
  "data_sources": [
    {
      "endpoint": "/api/system_status",
      "var_name": "status"
    }
  ]
}
```

### VFD Element Types

#### Text
```json
{
  "type": "text",
  "x": 10,
  "y": 5,
  "text": "Hello World"
}
```

#### Progress Bar / VU Meter
```json
{
  "type": "progress_bar",
  "x": 10,
  "y": 15,
  "width": 100,
  "height": 8,
  "value": "{variable}",
  "label": "CPU"
}
```

#### Rectangle
```json
{
  "type": "rectangle",
  "x1": 5,
  "y1": 5,
  "x2": 135,
  "y2": 30,
  "filled": false
}
```

#### Line
```json
{
  "type": "line",
  "x1": 0,
  "y1": 15,
  "x2": 140,
  "y2": 15
}
```

## Screen Rotation

Create automatic screen rotation cycles:

```json
{
  "name": "led_default_rotation",
  "description": "Default LED rotation",
  "display_type": "led",
  "enabled": true,
  "screens": [
    {"screen_id": 1, "duration": 10},
    {"screen_id": 2, "duration": 15},
    {"screen_id": 3, "duration": 10}
  ],
  "randomize": false,
  "skip_on_alert": true
}
```

### Rotation Options

- `screens` - Array of screen IDs with durations
- `randomize` - Randomize screen order
- `skip_on_alert` - Pause rotation when alerts are active

## Conditional Display

Show screens only when conditions are met:

```json
{
  "conditions": {
    "var": "alerts.features.length",
    "op": ">",
    "value": 0
  }
}
```

Supported operators: `==`, `!=`, `>`, `<`, `>=`, `<=`

## Example Templates

### LED Examples

#### System Status
```json
{
  "name": "led_system_status",
  "display_type": "led",
  "template_data": {
    "lines": [
      "SYSTEM STATUS",
      "Health: {status.status}",
      "Alerts: {status.active_alerts_count}",
      "DB: {status.database_status}"
    ],
    "color": "GREEN",
    "mode": "HOLD"
  },
  "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}]
}
```

#### Resource Usage
```json
{
  "name": "led_resources",
  "display_type": "led",
  "template_data": {
    "lines": [
      "SYSTEM RESOURCES",
      "CPU: {status.system_resources.cpu_usage_percent}%",
      "MEM: {status.system_resources.memory_usage_percent}%",
      "DISK: {status.system_resources.disk_usage_percent}%"
    ],
    "color": "AMBER",
    "mode": "HOLD"
  },
  "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}]
}
```

#### Network Info
```json
{
  "name": "led_network",
  "display_type": "led",
  "template_data": {
    "lines": [
      "NETWORK INFO",
      "IP: {network.ip_address}",
      "Uptime: {network.uptime_human}",
      "{now.time}"
    ],
    "color": "BLUE",
    "mode": "HOLD"
  },
  "data_sources": [{"endpoint": "/api/system_status", "var_name": "network"}]
}
```

### VFD Examples

#### System VU Meters
```json
{
  "name": "vfd_system_meters",
  "display_type": "vfd",
  "template_data": {
    "elements": [
      {"type": "text", "x": 2, "y": 1, "text": "SYSTEM RESOURCES"},
      {
        "type": "progress_bar",
        "x": 10, "y": 8, "width": 120, "height": 6,
        "value": "{status.system_resources.cpu_usage_percent}",
        "label": "CPU"
      },
      {
        "type": "progress_bar",
        "x": 10, "y": 17, "width": 120, "height": 6,
        "value": "{status.system_resources.memory_usage_percent}",
        "label": "MEM"
      }
    ]
  },
  "data_sources": [{"endpoint": "/api/system_status", "var_name": "status"}]
}
```

#### Alert Details
```json
{
  "name": "vfd_alert",
  "display_type": "vfd",
  "template_data": {
    "elements": [
      {"type": "rectangle", "x1": 0, "y1": 0, "x2": 139, "y2": 31, "filled": false},
      {"type": "text", "x": 5, "y": 3, "text": "ALERT! {alerts.features[0].properties.event}"},
      {"type": "line", "x1": 5, "y1": 11, "x2": 135, "y2": 11},
      {"type": "text", "x": 5, "y": 14, "text": "Severity: {alerts.features[0].properties.severity}"}
    ]
  },
  "data_sources": [{"endpoint": "/api/alerts", "var_name": "alerts"}],
  "conditions": {"var": "alerts.features.length", "op": ">", "value": 0}
}
```

## API Endpoints

### Screens

- `GET /api/screens` - List all screens
- `GET /api/screens?display_type=led&enabled=true` - Filter screens
- `GET /api/screens/<id>` - Get specific screen
- `POST /api/screens` - Create new screen
- `PUT /api/screens/<id>` - Update screen
- `DELETE /api/screens/<id>` - Delete screen
- `GET /api/screens/<id>/preview` - Preview rendered output
- `POST /api/screens/<id>/display` - Display screen immediately

### Rotations

- `GET /api/rotations` - List all rotations
- `GET /api/rotations/<id>` - Get specific rotation
- `POST /api/rotations` - Create new rotation
- `PUT /api/rotations/<id>` - Update rotation
- `DELETE /api/rotations/<id>` - Delete rotation

## Loading Example Templates

Run the example screen creation script:

```bash
# Provision all sample LED, VFD, and OLED templates
python3 scripts/create_example_screens.py

# Only install the OLED showcase rotation
python3 scripts/create_example_screens.py --display-type oled
```

This creates:

**LED Screens:**
- System Status
- Resource Usage (CPU/Memory/Disk)
- Network Information
- Alert Summary
- Time/Date Display
- Receiver Status

**VFD Screens:**
- System Resource VU Meters
- Audio VU Meter
- Alert Details (with graphics)
- Network Status (with graphics)
- Temperature Monitoring
- Dual Audio Channel VU Meters

## Screen Manager Service

The screen manager runs as a background service and:

- Automatically rotates screens based on configured schedules
- Fetches fresh data from API endpoints
- Respects screen priorities
- Pauses rotation during active alerts (if configured)
- Updates display statistics

The service starts automatically with the EAS Station application.

## Advanced Features

### Audio VU Meters

Create real-time VU meters showing audio levels:

```json
{
  "name": "vfd_audio_vu",
  "display_type": "vfd",
  "refresh_interval": 1,
  "template_data": {
    "elements": [
      {
        "type": "progress_bar",
        "x": 10, "y": 12, "width": 120, "height": 8,
        "value": "{audio.peak_level_linear}",
        "label": "PEAK"
      },
      {
        "type": "progress_bar",
        "x": 10, "y": 23, "width": 120, "height": 8,
        "value": "{audio.rms_level_linear}",
        "label": "RMS"
      }
    ]
  },
  "data_sources": [{"endpoint": "/api/audio/metrics/latest", "var_name": "audio"}]
}
```

### Multi-Source Data

Combine data from multiple API endpoints:

```json
{
  "data_sources": [
    {"endpoint": "/api/system_status", "var_name": "status"},
    {"endpoint": "/api/alerts", "var_name": "alerts"},
    {"endpoint": "/api/monitoring/radio", "var_name": "receivers"}
  ]
}
```

### Priority Override

Emergency screens can override rotation:

- Priority 0 = Emergency (always show)
- Priority 1 = High (show frequently)
- Priority 2 = Normal (regular rotation)
- Priority 3 = Low (show occasionally)

## Troubleshooting

### Screen Not Displaying

1. Check screen is enabled: `GET /api/screens/<id>`
2. Verify data sources return valid data
3. Check screen manager logs
4. Preview screen: `GET /api/screens/<id>/preview`

### Variables Not Substituting

1. Verify API endpoint returns expected data structure
2. Check variable path matches data structure
3. Use preview endpoint to debug

### VFD Graphics Not Appearing

1. Verify coordinates are within 140×32 bounds
2. Check VFD controller is connected
3. Test with simple text element first

## Migration and Setup

Run database migration:

```bash
alembic upgrade head
```

Or let the system auto-upgrade on startup.

## Web UI

Access the custom screens management interface at:

```
http://your-server:5000/screens
```

(Note: Web UI is planned for future release. Currently use API endpoints.)
