# EAS Station Frontend Architecture & Display System

## Overview
EAS Station is a Flask-based Emergency Alert System with a sophisticated frontend for managing multiple display types (LED, VFD, OLED). The system uses a traditional client-server architecture with REST API endpoints for communication.

---

## 1. FRONTEND FRAMEWORK & TECHNOLOGY STACK

### Primary Framework
- **Backend**: Python Flask (v2.x)
- **Frontend**: Vanilla JavaScript (ES6+) with no SPA framework
- **HTML/CSS**: Jinja2 templates with Bootstrap 5.3.0

### Key Libraries
- **HTTP**: Fetch API (modern XMLHttpRequest replacement)
- **UI Framework**: Bootstrap 5.3.0 (CDN)
- **Icons**: Font Awesome 6.4.0 (CDN)
- **CSS**: Custom CSS framework with theming support

### Frontend Technologies
- **No SPA Framework** (Vue, React, Angular not used)
- **No Build Tool** (Webpack, Vite, etc.)
- **Vanilla JavaScript** in `/static/js/` directory
- **Jinja2 Template Engine** for server-side rendering

---

## 2. DISPLAY TYPES & SPECIFICATIONS

### A. OLED Display (SSD1306)
**File**: `/home/user/eas-station/app_core/oled.py`

**Specs**:
- **Controller**: Argon Industria SSD1306
- **Interface**: I2C (configurable bus/address)
- **Resolution**: 128x64 pixels (configurable: `OLED_WIDTH`, `OLED_HEIGHT`)
- **Communication**: I2C bus (default: bus 1, address 0x3C)
- **Color Support**: Monochrome (1-bit, on/off only)

**Configuration Environment Variables**:
```
OLED_ENABLED=true/false
OLED_WIDTH=128
OLED_HEIGHT=64
OLED_I2C_BUS=1
OLED_I2C_ADDRESS=0x3C
OLED_ROTATE=0/90/180/270
OLED_CONTRAST=0-255
OLED_DEFAULT_INVERT=true/false
OLED_FONT_PATH=/path/to/font.ttf
OLED_BUTTON_GPIO=4
OLED_BUTTON_HOLD_SECONDS=1.25
OLED_SCROLL_EFFECT=scroll_left|scroll_right|scroll_up|scroll_down|wipe_left|wipe_right|wipe_up|wipe_down|fade_in|static
OLED_SCROLL_SPEED=1-10 (pixels per frame)
OLED_SCROLL_FPS=5-60
```

**Font Sizes**:
- small: 11px
- medium: 14px
- large: 18px
- xlarge: 28px
- huge: 36px

**Scroll Effects**:
- SCROLL_LEFT, SCROLL_RIGHT
- SCROLL_UP, SCROLL_DOWN
- WIPE_LEFT, WIPE_RIGHT
- WIPE_UP, WIPE_DOWN
- FADE_IN, STATIC

**Hardware**:
- GPIO Button control (default GPIO 4)
- Contrast adjustable via API

---

### B. VFD Display (Noritake GU140x32F-7000B)
**Files**: 
- `/home/user/eas-station/app_core/vfd.py`
- `/home/user/eas-station/scripts/vfd_controller.py`

**Specs**:
- **Model**: Noritake GU140x32F-7000B Graphics
- **Interface**: Serial (RS-232/RS-485)
- **Port**: Configurable (default: `/dev/ttyUSB0`)
- **Baud Rate**: 38400 bps (configurable)
- **Resolution**: 140x32 pixels (monochrome graphics)
- **Color Support**: Monochrome

**Configuration Environment Variables**:
```
VFD_PORT=/dev/ttyUSB0
VFD_BAUDRATE=38400
```

**Brightness Levels**: 0-7 (8 levels)
**Font Options**: FONT_5x7, FONT_7x10, FONT_10x14

**Supported Drawing Operations**:
- Clear display
- Draw text at (x, y)
- Draw pixels
- Draw lines
- Draw rectangles (filled/unfilled)
- Draw progress bars
- Display images

---

### C. LED Sign (IP-based Network Display)
**Files**:
- `/home/user/eas-station/app_core/led.py`
- `/home/user/eas-station/scripts/led_sign_controller.py`

**Specs**:
- **Interface**: Ethernet (TCP/IP)
- **IP Address**: Configurable (default: `192.168.1.100`)
- **Port**: Configurable (default: 10001)
- **Lines**: Up to 4 lines of text
- **Characters Per Line**: 20 max

**Configuration Environment Variables**:
```
LED_SIGN_IP=192.168.1.100
LED_SIGN_PORT=10001
```

**Display Properties**:
- **Colors**: AMBER, RED, GREEN, CYAN, YELLOW, WHITE, etc.
- **Fonts**: Multiple font sizes available
- **Display Modes** (Effects): HOLD, SCROLL, FLASH, TWINKLE, etc.
- **Scroll Speed**: SPEED_1 through SPEED_7
- **Message Priority**: EMERGENCY (0), URGENT (1), NORMAL (2), LOW (3)

**Serial Mode Support**:
- RS232 (default)
- RS485

**Canned Messages**: Pre-configured alert messages with formatting

---

## 3. DATABASE MODELS

### Display Screen Model
**File**: `/home/user/eas-station/app_core/models.py:1034`

```python
class DisplayScreen(db.Model):
    - id: Primary Key
    - name: String (unique)
    - description: Text
    - display_type: String ('led', 'vfd', 'oled')
    - enabled: Boolean
    - priority: Integer (0=emergency, 1=high, 2=normal, 3=low)
    - refresh_interval: Integer (seconds)
    - duration: Integer (seconds to display in rotation)
    - template_data: JSONB (layout, formatting, content template)
    - data_sources: JSONB (API endpoints to fetch data from)
    - conditions: JSONB (conditional logic for display)
    - display_count: Integer (statistics)
    - error_count: Integer (statistics)
    - last_error: Text
    - created_at, updated_at, last_displayed_at: DateTime
```

### Screen Rotation Model
**File**: `/home/user/eas-station/app_core/models.py:1093`

```python
class ScreenRotation(db.Model):
    - id: Primary Key
    - name: String (unique)
    - description: Text
    - display_type: String ('led', 'vfd', 'oled')
    - enabled: Boolean
    - screens: JSONB (array of screen configs with duration)
    - randomize: Boolean
    - skip_on_alert: Boolean
    - current_screen_index: Integer
    - last_rotation_at: DateTime
```

### LED Message Model
**File**: `/home/user/eas-station/app_core/models.py:769`

```python
class LEDMessage(db.Model):
    - id: Primary Key
    - message_type: String
    - content: Text
    - priority: Integer
    - color, font_size, effect, speed: String
    - display_time: Integer
    - scheduled_time, sent_at: DateTime
    - is_active: Boolean
    - alert_id: Foreign Key (to CAPAlert)
```

### VFD Display Model
**File**: `/home/user/eas-station/app_core/models.py:803`

```python
class VFDDisplay(db.Model):
    - id: Primary Key
    - content_type: String (text, image, alert, status)
    - content_data: Text (text content or path)
    - binary_data: LargeBinary (image data)
    - priority: Integer
    - x_position, y_position: Integer
    - duration_seconds: Integer
    - displayed_at: DateTime
    - is_active: Boolean
    - alert_id: Foreign Key
```

### Status Models
- **LEDSignStatus**: Connection, brightness, error tracking
- **VFDStatus**: Connection, brightness, content type tracking

---

## 4. API ENDPOINTS

### Screen Management Endpoints
**File**: `/home/user/eas-station/webapp/routes_screens.py`

#### Screens (CRUD)
```
GET    /api/screens
GET    /api/screens?display_type=led&enabled=true
GET    /api/screens/<id>
POST   /api/screens
PUT    /api/screens/<id>
DELETE /api/screens/<id>
GET    /api/screens/<id>/preview
POST   /api/screens/<id>/display (Display immediately)
```

#### Rotations (CRUD)
```
GET    /api/rotations
GET    /api/rotations?display_type=led&enabled=true
GET    /api/rotations/<id>
POST   /api/rotations
PUT    /api/rotations/<id>
DELETE /api/rotations/<id>
```

#### UI Routes
```
GET    /screens (Main screens management page)
GET    /vfd_control (VFD control dashboard)
GET    /led_control (LED control dashboard)
```

---

### VFD API Endpoints
**File**: `/home/user/eas-station/webapp/routes_vfd.py`

```
GET    /api/vfd/status
POST   /api/vfd/clear
POST   /api/vfd/brightness (body: {level: 0-7})
POST   /api/vfd/text (body: {text, x, y})
POST   /api/vfd/image (multipart form-data or base64)
POST   /api/vfd/graphics/pixel (body: {x, y, state})
POST   /api/vfd/graphics/line (body: {x1, y1, x2, y2})
POST   /api/vfd/graphics/rectangle (body: {x1, y1, x2, y2, filled})
POST   /api/vfd/graphics/progress (body: {x, y, width, height, progress})
GET    /api/vfd/displays (history)
```

---

### LED API Endpoints
**File**: `/home/user/eas-station/webapp/routes_led.py`

```
GET    /api/led/send_message (POST body: {lines, color, mode, speed})
GET    /api/led/status
POST   /api/led/send_canned_message (body: {message_name})
GET    /api/led/messages (history)
POST   /api/led/brightness (body: {level})
```

---

## 5. REAL-TIME UPDATE MECHANISMS

### Polling Strategy
**Files**:
- `/home/user/eas-station/static/js/core/health.js`
- `/home/user/eas-station/static/js/audio_monitoring.js`

**Implementation**:
- Uses `setInterval()` for periodic updates
- Health checks: Every 5 seconds
- Metrics updates: Every 1 second
- Device monitoring: Every 10 seconds

**Example**:
```javascript
// Health check polling (core/health.js:66)
async function checkSystemHealth() {
    const response = await fetch('/api/system_status');
    const data = await response.json();
    // Update UI with health status
}

// Audio monitoring polling (audio_monitoring.js:28)
metricsUpdateInterval = setInterval(updateMetrics, 1000);
healthUpdateInterval = setInterval(loadAudioHealth, 5000);
deviceMonitorInterval = setInterval(monitorDeviceChanges, 10000);
```

### No WebSocket Implementation
- **WebSocket**: Not implemented
- **Socket.io**: Not used
- **Server-Sent Events (SSE)**: Not used
- **Real-time Updates**: Entirely polling-based via Fetch API

### Communication Method
- **HTTP Method**: Fetch API (modern XMLHttpRequest)
- **Data Format**: JSON (request/response)
- **CSRF Protection**: Automatic header injection in all state-changing requests
- **Authentication**: Session-based cookies

---

## 6. FRONTEND FILE STRUCTURE

### Static Assets
```
/static/
├── css/
│   ├── base.css
│   ├── layout.css
│   ├── accessibility.css
│   ├── responsive-enhancements.css
│   ├── loading-states.css
│   ├── error-handling.css
│   ├── components.css
│   └── design-system.css
├── js/
│   ├── core/
│   │   ├── api.js (CSRF token handling, fetch wrapper)
│   │   ├── health.js (System health polling)
│   │   ├── notifications.js
│   │   ├── theme.js (Dark/light mode)
│   │   └── utils.js
│   ├── charts/
│   │   └── alert_delivery.js
│   ├── audio_monitoring.js (Polling-based audio metrics)
│   ├── accessibility-utils.js
│   └── loading-error-utils.js
└── img/
    └── [icons, logos, images]
```

### Templates
```
/templates/
├── base.html (Main layout with navigation, CSRF setup)
├── screens.html (Display screens management UI)
├── vfd_control.html (VFD control dashboard)
├── led_control.html (LED control dashboard)
├── partials/
│   ├── navbar.html
│   ├── footer.html
│   └── common_head.html
└── [other pages]
```

---

## 7. KEY FRONTEND PAGES

### /screens (Screen Management)
**File**: `/home/user/eas-station/templates/screens.html`

Features:
- List all screens (LED/VFD/OLED)
- Create/edit/delete screens
- Preview rendered output
- Display screen immediately (override rotation)
- Manage screen rotations
- JSON template editor

API Calls:
```javascript
GET /api/screens
POST /api/screens
PUT /api/screens/<id>
DELETE /api/screens/<id>
GET /api/screens/<id>/preview
POST /api/screens/<id>/display
GET /api/rotations
POST /api/rotations
PUT /api/rotations/<id>
DELETE /api/rotations/<id>
```

### /vfd_control (VFD Dashboard)
**File**: `/home/user/eas-station/templates/vfd_control.html`

Features:
- Real-time VFD status display
- Text/image rendering
- Brightness control
- Graphics drawing tools
- Display history

API Calls:
```javascript
GET /api/vfd/status
POST /api/vfd/text
POST /api/vfd/image
POST /api/vfd/brightness
POST /api/vfd/graphics/*
GET /api/vfd/displays
```

### /led_control (LED Dashboard)
**File**: `/home/user/eas-station/templates/led_control.html`

Features:
- Real-time LED status display
- Message sending (freeform & canned)
- Color/font/mode selection
- Message history
- Speed control

---

## 8. DATA FLOW & ARCHITECTURE DIAGRAM

```
┌─────────────────────────────────────────────────────────┐
│           Browser / Frontend (Vanilla JS)                │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  /screens.html          /vfd_control.html   /led_*.html │
│    │                         │                   │        │
│    ├─ Fetch /api/screens     ├─ Fetch /api/vfd/ │        │
│    ├─ Fetch /api/rotations   ├─ POST   /api/vfd │        │
│    └─ Polling (on demand)    └─ Polling (on demand)      │
│                                                           │
└────────────┬────────────────────────────────┬────────────┘
             │ JSON over HTTP/Fetch API       │
             │ (CSRF protected)               │
             │                                │
┌────────────▼────────────────────────────────▼────────────┐
│              Flask Backend (Python)                       │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  routes_screens.py       routes_vfd.py    routes_led.py │
│  ├─ /api/screens/*       ├─ /api/vfd/*     ├─ /api/led/*│
│  └─ /screens             └─ /vfd_control   └─ /led_*    │
│                                                           │
│  ScreenRenderer (script rendering engine)                │
│  - Fetches data from API endpoints                       │
│  - Substitutes variables in templates                    │
│  - Evaluates conditions                                  │
│  - Renders for each display type                         │
│                                                           │
└────────────┬────────────────────────────────┬────────────┘
             │                                │
             │ Database                      │ Hardware
             │ (PostgreSQL/SQLite)           │ Controllers
             │                                │
    ┌────────▼─────────┐      ┌──────────────▼──────────────┐
    │  DB Models:      │      │  Hardware Integration:      │
    │  - DisplayScreen │      │  ├─ OLED (I2C)             │
    │  - ScreenRotation│      │  ├─ VFD (Serial)            │
    │  - LEDMessage    │      │  └─ LED (Ethernet TCP)      │
    │  - VFDDisplay    │      │                             │
    │  - VFDStatus     │      │  Scripts:                   │
    │  - LEDSignStatus │      │  ├─ oled.py                │
    │                  │      │  ├─ vfd.py                 │
    │                  │      │  └─ led.py                 │
    └──────────────────┘      └─────────────────────────────┘
```

---

## 9. TECHNOLOGY SUMMARY TABLE

| Component | Technology | Details |
|-----------|-----------|---------|
| Backend Framework | Flask 2.x | Lightweight Python web framework |
| Frontend Framework | Vanilla JS | No SPA framework |
| HTTP Client | Fetch API | Modern XMLHttpRequest replacement |
| UI Framework | Bootstrap 5.3 | CDN-based CSS framework |
| Icons | Font Awesome 6.4 | CDN-based icon library |
| Template Engine | Jinja2 | Server-side HTML rendering |
| Database | PostgreSQL/SQLite | Persistent data storage |
| Real-time Updates | Polling via setInterval() | Client-side polling, no WebSocket |
| Communication | JSON over HTTP | REST API with CSRF protection |
| CSRF Protection | Custom middleware | Automatic header injection |
| Display Types | 3 (OLED, VFD, LED) | Different protocols & specs |
| Color Support | Mono (OLED/VFD), Multi (LED) | Display-dependent |

---

## 10. SECURITY & ARCHITECTURE NOTES

### CSRF Protection
- Implemented at global level (base.html)
- Automatic header injection for state-changing requests
- Token stored in `window.CSRF_TOKEN`

### API Validation
- Screen Renderer validates endpoints (SSRF prevention)
- Allowed prefixes: `/api/`, `/health`, `/ping`, `/version`
- No support for absolute URLs

### Display Isolation
- Each display type has dedicated controller
- Hardware communication isolated in separate modules
- Thread-safe with locks for resource access

### Real-time Architecture
- **Stateless polling**: Client initiates all requests
- **No persistent connections**: Each request is independent
- **Server scalability**: No need for WebSocket infrastructure
- **Browser compatible**: Works with all browsers (no special support needed)

