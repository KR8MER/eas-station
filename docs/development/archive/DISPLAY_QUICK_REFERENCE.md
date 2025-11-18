# Display System Quick Reference Guide

## Display Types at a Glance

### OLED (128x64 Monochrome)
- **File**: `/home/user/eas-station/app_core/oled.py`
- **Interface**: I2C (default: bus 1, address 0x3C)
- **Resolution**: 128x64 pixels
- **Control**: GPIO button (default GPIO 4)
- **Font Sizes**: small (11px), medium (14px), large (18px), xlarge (28px), huge (36px)
- **Scroll Effects**: scroll_left, scroll_right, scroll_up, scroll_down, wipe_*, fade_in, static
- **Speed**: 1-10 pixels/frame, 5-60 FPS

### VFD (140x32 Monochrome Graphics)
- **File**: `/home/user/eas-station/app_core/vfd.py`
- **Interface**: Serial RS-232/RS-485 (default: /dev/ttyUSB0, 38400 baud)
- **Resolution**: 140x32 pixels
- **Brightness**: 8 levels (0-7)
- **Operations**: text, lines, rectangles, pixels, progress bars, images

### LED (Ethernet Network Sign, 4 lines x 20 chars)
- **File**: `/home/user/eas-station/app_core/led.py`
- **Interface**: TCP/IP (default: 192.168.1.100:10001)
- **Lines**: Max 4 lines, 20 chars/line
- **Colors**: AMBER, RED, GREEN, CYAN, YELLOW, WHITE, etc.
- **Modes**: HOLD, SCROLL, FLASH, TWINKLE
- **Priority**: EMERGENCY (0), URGENT (1), NORMAL (2), LOW (3)

---

## Database Models

### DisplayScreen (for all display types)
```
display_screens table:
├─ id: Integer (PK)
├─ name: String (unique)
├─ display_type: 'led' | 'vfd' | 'oled'
├─ enabled: Boolean
├─ priority: 0-3 (0=emergency)
├─ template_data: JSONB (format varies by type)
├─ data_sources: JSONB (API endpoints to fetch)
├─ conditions: JSONB (conditional logic)
├─ refresh_interval: seconds
├─ duration: seconds (in rotation)
└─ statistics: display_count, error_count, last_error
```

### ScreenRotation (cycle through screens)
```
screen_rotations table:
├─ id: Integer (PK)
├─ name: String (unique)
├─ display_type: 'led' | 'vfd' | 'oled'
├─ screens: JSONB array [{screen_id, duration}, ...]
├─ enabled: Boolean
├─ randomize: Boolean
└─ skip_on_alert: Boolean
```

---

## API Endpoints Quick List

### Screens Management
```
GET    /api/screens
GET    /api/screens?display_type=led&enabled=true
GET    /api/screens/<id>
POST   /api/screens
PUT    /api/screens/<id>
DELETE /api/screens/<id>
GET    /api/screens/<id>/preview
POST   /api/screens/<id>/display
```

### Rotations Management
```
GET    /api/rotations
GET    /api/rotations?display_type=led
POST   /api/rotations
PUT    /api/rotations/<id>
DELETE /api/rotations/<id>
```

### VFD Display Commands
```
GET    /api/vfd/status
POST   /api/vfd/clear
POST   /api/vfd/brightness {level: 0-7}
POST   /api/vfd/text {text, x, y}
POST   /api/vfd/image {image_data or file}
POST   /api/vfd/graphics/pixel {x, y, state}
POST   /api/vfd/graphics/line {x1, y1, x2, y2}
POST   /api/vfd/graphics/rectangle {x1, y1, x2, y2, filled}
POST   /api/vfd/graphics/progress {x, y, width, height, progress}
```

### LED Display Commands
```
POST   /api/led/send_message {lines, color, mode, speed}
GET    /api/led/status
POST   /api/led/send_canned_message {message_name}
GET    /api/led/messages
```

---

## Frontend Files

### Key Templates
```
/templates/
├── screens.html (Main display management UI)
├── vfd_control.html (VFD dashboard)
└── led_control.html (LED dashboard)
```

### Key JavaScript
```
/static/js/
├── core/api.js (CSRF protection)
├── core/health.js (System status polling)
└── audio_monitoring.js (Example polling pattern)
```

---

## Template Data Format Examples

### LED Screen Template
```json
{
  "display_type": "led",
  "template_data": {
    "lines": ["Line 1", "Line 2", "Line 3", "Line 4"],
    "color": "AMBER",
    "mode": "SCROLL",
    "speed": "SPEED_3",
    "font": "FONT_7x9"
  }
}
```

### VFD Screen Template
```json
{
  "display_type": "vfd",
  "template_data": {
    "elements": [
      {
        "type": "text",
        "text": "Status: {status.state}",
        "x": 0,
        "y": 0
      },
      {
        "type": "progress_bar",
        "x": 10,
        "y": 20,
        "width": 120,
        "height": 8,
        "value": "{metrics.cpu_percent}",
        "label": "CPU"
      }
    ]
  }
}
```

### OLED Screen Template
```json
{
  "display_type": "oled",
  "template_data": {
    "lines": [
      {"text": "Alert: {alert.event}", "font": "large", "wrap": true},
      {"text": "Location: {alert.area}", "font": "small"},
      {"text": "{now.time}", "font": "medium", "y": 50}
    ],
    "scroll_effect": "scroll_left",
    "scroll_speed": 4,
    "scroll_fps": 30
  }
}
```

---

## Real-time Communication

### Polling Strategy (No WebSocket)
- **Type**: Client-side polling via `setInterval()`
- **Method**: Fetch API (JSON over HTTP)
- **CSRF**: Automatic header injection (`X-CSRF-Token`)
- **Examples**:
  - Health check: `fetch('/api/system_status')` every 5 seconds
  - Metrics: `fetch('/api/audio/metrics')` every 1 second
  - Device changes: `fetch('/api/audio/devices')` every 10 seconds

---

## Configuration Environment Variables

### OLED
```
OLED_ENABLED=true/false
OLED_WIDTH=128
OLED_HEIGHT=64
OLED_I2C_BUS=1
OLED_I2C_ADDRESS=0x3C
OLED_ROTATE=0|90|180|270
OLED_CONTRAST=0-255
OLED_SCROLL_EFFECT=scroll_left
OLED_SCROLL_SPEED=4
OLED_SCROLL_FPS=60
OLED_BUTTON_GPIO=4
OLED_BUTTON_HOLD_SECONDS=1.25
```

### VFD
```
VFD_PORT=/dev/ttyUSB0
VFD_BAUDRATE=38400
```

### LED
```
LED_SIGN_IP=192.168.1.100
LED_SIGN_PORT=10001
```

---

## File Structure Summary

```
/home/user/eas-station/
├── app.py (Main Flask app)
├── app_core/
│   ├── oled.py (OLED controller)
│   ├── vfd.py (VFD wrapper)
│   ├── led.py (LED wrapper)
│   ├── models.py (DB models: DisplayScreen, ScreenRotation, etc.)
│   └── extensions.py (Flask extensions: db, csrf, etc.)
├── webapp/
│   ├── routes_screens.py (Screen CRUD API)
│   ├── routes_vfd.py (VFD control API)
│   ├── routes_led.py (LED control API)
│   └── __init__.py (Route registration)
├── scripts/
│   ├── screen_renderer.py (Template rendering engine)
│   ├── vfd_controller.py (VFD hardware driver)
│   ├── led_sign_controller.py (LED hardware driver)
│   └── screen_manager.py (Rotation manager)
├── static/
│   ├── css/ (Styling)
│   └── js/ (Client-side logic)
└── templates/
    ├── screens.html (Screen management UI)
    ├── vfd_control.html (VFD UI)
    ├── led_control.html (LED UI)
    └── base.html (Layout template with CSRF)
```

---

## Quick Development Tips

1. **Add new API endpoint**: Create function in `webapp/routes_*.py`, register with `@app.route()`
2. **Add screen type**: Create template in `DisplayScreen.template_data`, add renderer to `ScreenRenderer`
3. **Add polling**: Use `setInterval(async () => { await fetch(...) }, interval)` pattern
4. **CSRF handling**: Automatic via `base.html` script; no manual token injection needed
5. **Display content**: POST to `/api/screens/<id>/display` to show screen immediately
6. **Template variables**: Use `{var_name}` syntax; fetched from `data_sources` API endpoints
7. **Conditional display**: Set `conditions` JSONB with simple `{var, op, value}` comparison

