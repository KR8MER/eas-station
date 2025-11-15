# OLED Sample Screens for 128x64 Display

This document contains sample screen templates you can use with your Argon OLED module.

## Screen Structure

Each screen is 128 pixels wide by 64 pixels tall, using the SSD1306 OLED driver.

**Available fonts:**
- `small` (11px) - Default, fits ~5-6 lines
- `medium` (14px) - Fits ~4 lines
- `large` (18px) - Fits ~3 lines

## Built-in Snapshot Screen

When you hold the OLED button (GPIO 4, pin 7) for 1.25 seconds, this screen displays:

```
┌────────────────────────────────┐
│ 2025-11-15 14:32:45           │  <- Current date/time
│ Status OK | Alerts 0           │  <- System status
│ All systems operational        │  <- Status summary
│ Alert                          │  <- Current alert (if any)
│ CPU 45%  MEM 62%              │  <- Resource usage
│ Audio Peak -12.5 dB            │  <- Live audio level
└────────────────────────────────┘
```

## Sample Screen 1: Welcome Screen

```json
{
  "name": "Welcome to EAS Station",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "EAS STATION",
        "font": "large",
        "y": 0,
        "wrap": false
      },
      {
        "text": "KR8MER",
        "font": "medium",
        "y": 22,
        "wrap": false
      },
      {
        "text": "Putnam County OH",
        "font": "small",
        "y": 40,
        "wrap": false
      },
      {
        "text": "Emergency Alert System",
        "font": "small",
        "y": 52,
        "wrap": false
      }
    ]
  }
}
```

**Renders as:**
```
┌────────────────────────────────┐
│                                │
│  EAS STATION                   │  <- Large font
│                                │
│  KR8MER                        │  <- Medium font
│                                │
│  Putnam County OH              │  <- Small font
│  Emergency Alert System        │  <- Small font
└────────────────────────────────┘
```

---

## Sample Screen 2: System Status

```json
{
  "name": "System Status",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "SYSTEM STATUS",
        "font": "medium",
        "y": 0,
        "wrap": false
      },
      {
        "text": "{now.time_only}",
        "font": "large",
        "y": 16,
        "wrap": false
      },
      {
        "text": "Alerts: {status.active_alerts_count}",
        "font": "small",
        "y": 38,
        "wrap": false
      },
      {
        "text": "{status.status_summary}",
        "font": "small",
        "y": 50,
        "wrap": true,
        "max_width": 124
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/system_status", "var_name": "status"}
  ]
}
```

**Renders as:**
```
┌────────────────────────────────┐
│  SYSTEM STATUS                 │
│                                │
│  14:32:45                      │  <- Large time
│                                │
│  Alerts: 0                     │
│  All systems operational       │
└────────────────────────────────┘
```

---

## Installing the Showcase Rotation

Deploy the curated OLED rotation (system overview, alerts, network, poll telemetry, and audio health) with:

```
python3 scripts/create_example_screens.py --display-type oled
```

The script is idempotent: it creates any missing OLED screen templates, adds them to the default rotation, and leaves your custom screens untouched.

### Included screens
- **`oled_system_overview`** – command-deck clock with status summary and CPU/MEM/Disk utilization.
- **`oled_alert_summary`** – highlighted event, severity, and area for the most urgent alert, plus an active alert count.
- **`oled_network_beacon`** – hostname, uptime, primary interface name, IPv4 address, and link speed from `/api/system_health`.
- **`oled_ipaws_poll_watch`** – timestamp, status, and fetch metrics for the last IPAWS poll run from `/api/system_status`.
- **`oled_audio_health_matrix`** – audio health score, active source count, and silence detection for the newest health record.
- **`oled_audio_telemetry`** – live peak/RMS readings for the busiest two audio sources.

Re-run the script any time you upgrade to ensure your rotation contains the newest templates.

---

## Sample Screen 3: Network Information

```json
{
  "name": "Network Info",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "NETWORK",
        "font": "medium",
        "y": 0,
        "wrap": false
      },
      {
        "text": "Hostname:",
        "font": "small",
        "y": 18,
        "wrap": false
      },
      {
        "text": "{status.hostname}",
        "font": "small",
        "y": 30,
        "wrap": false
      },
      {
        "text": "IP Address:",
        "font": "small",
        "y": 42,
        "wrap": false
      },
      {
        "text": "{status.ip_address}",
        "font": "small",
        "y": 54,
        "wrap": false
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/system_status", "var_name": "status"}
  ]
}
```

**Renders as:**
```
┌────────────────────────────────┐
│  NETWORK                       │
│                                │
│  Hostname:                     │
│  omv.local                     │
│  IP Address:                   │
│  192.168.1.100                 │
└────────────────────────────────┘
```

---

## Sample Screen 4: Network Beacon

```json
{
  "name": "Network Beacon",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {"text": "◢ NETWORK BEACON ◣", "font": "medium", "invert": true, "wrap": false},
      {"text": "{health.system.hostname}", "font": "small", "y": 15, "wrap": false},
      {"text": "LAN {health.network.primary_interface_name}", "y": 27, "allow_empty": true},
      {"text": "{health.network.primary_ipv4}", "y": 39, "allow_empty": true},
      {
        "text": "Speed {health.network.primary_interface.speed_mbps} Mbps  MTU {health.network.primary_interface.mtu}",
        "y": 51,
        "allow_empty": true,
        "max_width": 124
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/system_health", "var_name": "health"}
  ]
}
```

**Renders as:**

```
┌────────────────────────────────┐
│◢ NETWORK BEACON ◣             │
│ argon-wxlab                   │
│ LAN eth0                      │
│ 192.168.1.87                  │
│ Speed 1000 Mbps  MTU 1500     │
└────────────────────────────────┘
```

---

## Sample Screen 5: IPAWS Poll Watch

```json
{
  "name": "IPAWS Poll Watch",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {"text": "◢ IPAWS POLLER ◣", "font": "medium", "invert": true},
      {
        "text": "Last {status.last_poll.local_timestamp}",
        "y": 17,
        "allow_empty": true,
        "max_width": 124
      },
      {"text": "Status {status.last_poll.status}", "y": 29, "allow_empty": true},
      {
        "text": "+{status.last_poll.alerts_new} new / {status.last_poll.alerts_fetched} fetched",
        "y": 41,
        "allow_empty": true,
        "max_width": 124
      },
      {
        "text": "Source {status.last_poll.data_source}",
        "y": 53,
        "allow_empty": true,
        "max_width": 124
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/system_status", "var_name": "status"}
  ]
}
```

**Renders as:**

```
┌────────────────────────────────┐
│◢ IPAWS POLLER ◣               │
│ Last 2025-11-15 18:00 EST     │
│ Status success                │
│ +0 new / 9 fetched            │
│ Source ipaws.gov              │
└────────────────────────────────┘
```

---

## Sample Screen 4: Active Alert Display

```json
{
  "name": "Active Alerts",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "ACTIVE ALERT",
        "font": "medium",
        "y": 0,
        "wrap": false,
        "invert": true
      },
      {
        "text": "{alerts.features[0].properties.event}",
        "font": "medium",
        "y": 18,
        "wrap": true,
        "max_width": 124,
        "allow_empty": true
      },
      {
        "text": "{alerts.features[0].properties.areaDesc}",
        "font": "small",
        "y": 38,
        "wrap": true,
        "max_width": 124,
        "allow_empty": true
      },
      {
        "text": "Expires: {alerts.features[0].properties.expires_relative}",
        "font": "small",
        "y": 52,
        "wrap": false,
        "allow_empty": true
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/alerts", "var_name": "alerts"}
  ]
}
```

**Renders as (when alert active):**
```
┌────────────────────────────────┐
│█ACTIVE ALERT██████████████████│  <- Inverted
│                                │
│  Severe Thunderstorm           │
│  Warning                       │
│                                │
│  Putnam County                 │
│  Expires: in 45 min            │
└────────────────────────────────┘
```

**Renders as (no alerts):**
```
┌────────────────────────────────┐
│█ACTIVE ALERT██████████████████│
│                                │
│                                │
│                                │
│                                │
│                                │
└────────────────────────────────┘
```

---

## Sample Screen 5: CPU & Memory Monitor

```json
{
  "name": "Resource Monitor",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "RESOURCES",
        "font": "medium",
        "y": 0,
        "wrap": false
      },
      {
        "text": "CPU Usage",
        "font": "small",
        "y": 18,
        "wrap": false
      },
      {
        "text": "{status.system_resources.cpu_usage_percent}%",
        "font": "large",
        "y": 28,
        "wrap": false
      },
      {
        "text": "Memory: {status.system_resources.memory_usage_percent}%  Disk: {status.system_resources.disk_usage_percent}%",
        "font": "small",
        "y": 52,
        "wrap": false,
        "max_width": 124
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/system_status", "var_name": "status"}
  ]
}
```

**Renders as:**
```
┌────────────────────────────────┐
│  RESOURCES                     │
│                                │
│  CPU Usage                     │
│  45%                           │  <- Large percentage
│                                │
│  Memory: 62%  Disk: 38%        │
└────────────────────────────────┘
```

---

## Sample Screen 6: Audio Levels

```json
{
  "name": "Audio Monitor",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "AUDIO LEVELS",
        "font": "medium",
        "y": 0,
        "wrap": false
      },
      {
        "text": "SDR Input",
        "font": "small",
        "y": 18,
        "wrap": false
      },
      {
        "text": "Peak: {audio.live_metrics[0].peak_level_db} dB",
        "font": "small",
        "y": 30,
        "wrap": false,
        "allow_empty": true
      },
      {
        "text": "RMS: {audio.live_metrics[0].rms_level_db} dB",
        "font": "small",
        "y": 42,
        "wrap": false,
        "allow_empty": true
      },
      {
        "text": "{audio.live_metrics[0].status}",
        "font": "small",
        "y": 54,
        "wrap": false,
        "allow_empty": true
      }
    ]
  },
  "data_sources": [
    {"endpoint": "/api/audio/metrics", "var_name": "audio"}
  ]
}
```

**Renders as:**
```
┌────────────────────────────────┐
│  AUDIO LEVELS                  │
│                                │
│  SDR Input                     │
│  Peak: -12.5 dB                │
│  RMS: -18.2 dB                 │
│  Signal detected               │
└────────────────────────────────┘
```

---

## Sample Screen 7: Date & Time Large

```json
{
  "name": "Clock Display",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "{now.time_only}",
        "font": "large",
        "y": 10,
        "wrap": false
      },
      {
        "text": "{now.date_short}",
        "font": "medium",
        "y": 35,
        "wrap": false
      },
      {
        "text": "{now.timezone_abbrev}",
        "font": "small",
        "y": 52,
        "wrap": false
      }
    ]
  }
}
```

**Renders as:**
```
┌────────────────────────────────┐
│                                │
│                                │
│  14:32:45                      │  <- Large time
│                                │
│  Nov 15, 2025                  │  <- Medium date
│                                │
│  EST                           │  <- Timezone
└────────────────────────────────┘
```

---

## Sample Screen 8: Idle/Ready Screen

```json
{
  "name": "Ready Screen",
  "display_type": "oled",
  "enabled": true,
  "template_data": {
    "clear": true,
    "lines": [
      {
        "text": "READY",
        "font": "large",
        "y": 8,
        "wrap": false
      },
      {
        "text": "No Active Alerts",
        "font": "small",
        "y": 30,
        "wrap": false
      },
      {
        "text": "System monitoring...",
        "font": "small",
        "y": 42,
        "wrap": false
      },
      {
        "text": "{now.time_only}",
        "font": "small",
        "y": 54,
        "wrap": false
      }
    ]
  }
}
```

**Renders as:**
```
┌────────────────────────────────┐
│                                │
│  READY                         │  <- Large
│                                │
│  No Active Alerts              │
│  System monitoring...          │
│  14:32:45                      │
└────────────────────────────────┘
```

---

## Screen Rotation Example

You can set up automatic rotation through the web UI or database. Here's a sample rotation:

```json
{
  "display_type": "oled",
  "enabled": true,
  "randomize": false,
  "skip_on_alert": false,
  "screens": [
    {"screen_id": 1, "duration": 10},  // Welcome screen - 10 seconds
    {"screen_id": 2, "duration": 5},   // System status - 5 seconds
    {"screen_id": 3, "duration": 5},   // Network info - 5 seconds
    {"screen_id": 5, "duration": 5},   // CPU/Memory - 5 seconds
    {"screen_id": 6, "duration": 5},   // Audio levels - 5 seconds
    {"screen_id": 7, "duration": 10}   // Clock - 10 seconds
  ]
}
```

This cycles through 6 screens, spending 40 seconds total before looping.

---

## Available Template Variables

Use these variables in your screen templates:

### Time/Date
- `{now.datetime}` - Full date and time
- `{now.time_only}` - Time only (14:32:45)
- `{now.date_short}` - Short date (Nov 15, 2025)
- `{now.timezone_abbrev}` - Timezone (EST, EDT, etc.)

### System Status
- `{status.status}` - OK, WARNING, ERROR
- `{status.active_alerts_count}` - Number of active alerts
- `{status.status_summary}` - Text summary
- `{status.hostname}` - System hostname
- `{status.ip_address}` - Primary IP address

### Resources
- `{status.system_resources.cpu_usage_percent}` - CPU %
- `{status.system_resources.memory_usage_percent}` - Memory %
- `{status.system_resources.disk_usage_percent}` - Disk %

### Alerts
- `{alerts.features[0].properties.event}` - Alert type
- `{alerts.features[0].properties.areaDesc}` - Affected area
- `{alerts.features[0].properties.expires_relative}` - Time until expiration

### Audio
- `{audio.live_metrics[0].peak_level_db}` - Peak audio level
- `{audio.live_metrics[0].rms_level_db}` - RMS audio level
- `{audio.live_metrics[0].status}` - Audio status text

---

## Creating Custom Screens via Web UI

1. Navigate to **Displays → Screens** in the web interface
2. Click **Create New Screen**
3. Select **OLED** as display type
4. Enter screen name
5. Add lines with text and positioning
6. Configure data sources if using dynamic data
7. Save and add to rotation

---

## OLED Button Controls

- **Short press** (< 1.25s): Advance to next screen in rotation
- **Long press** (≥ 1.25s): Show snapshot screen with system status

The button is on GPIO 4 (physical pin 7).

---

## Tips for Best Display Quality

1. **Keep text concise** - 128px width limits characters per line
2. **Use large fonts sparingly** - Only 3 lines of large text fit
3. **Leave spacing** - Add Y offset between lines for readability
4. **Test wrapping** - Enable `wrap: true` for long text
5. **Use invert for headers** - Makes section titles stand out
6. **Limit data sources** - Too many API calls slow refresh rate
7. **Set realistic durations** - Give users time to read (5-10 seconds)

---

## Physical Display Layout

```
   Pin 7 (Button)
       ↓
    [●]═════════════════════════════╗
    ║  ┌─────────────────────────┐ ║
    ║  │                         │ ║
    ║  │    128 x 64 pixels      │ ║
    ║  │    OLED Display         │ ║
    ║  │    (Argon Industria)    │ ║
    ║  │                         │ ║
    ║  └─────────────────────────┘ ║
    ╚════════════════════════════════
    Pin 1 (3.3V) → Pin 8 (GPIO 14)
```

Pins 1-8 are reserved for OLED module (power, I2C, button, heartbeat).

---

## Troubleshooting Display Issues

**Problem: Text doesn't fit**
- Reduce font size or shorten text
- Enable wrapping: `"wrap": true`
- Reduce max_width to force earlier wrapping

**Problem: Text overlaps**
- Increase Y spacing between lines
- Calculate: Y = previous_Y + font_size + spacing

**Problem: Screen is blank**
- Check `OLED_ENABLED=true` in config
- Verify I2C address: `i2cdetect -y 1` should show 3c
- Check logs for OLED initialization errors

**Problem: Text is too dim**
- Increase contrast: `OLED_CONTRAST=255` in .env
- Check power supply (needs stable 3.3V or 5V)

**Problem: Screen is upside down**
- Set `OLED_ROTATE=180` in .env

---

## ASCII Preview Tool

You can preview how text will look using character counts:

- Small font (11px): ~21 characters per line @ 128px width
- Medium font (14px): ~16 characters per line
- Large font (18px): ~12 characters per line
- Height: 64px ÷ font_size = number of lines (plus spacing)

Example:
```
Small (11px):  "This is exactly 21ch"  <- Full width
Medium (14px): "Fits 16 chars"         <- Full width
Large (18px):  "12 chars max"          <- Full width
```

---

For more information on OLED configuration, see `OLED_GPIO_TROUBLESHOOTING.md`.
