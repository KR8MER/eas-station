# Alpha LED Sign Comprehensive Guide

> **Note (May 2026):** The runtime LED control surface is the generic `/led_control` page and the `/api/led/*` endpoints exposed by `webapp/routes_led.py` (e.g. `/api/led/send_message`, `/api/led/brightness`, `/api/led/clear`, `/api/led/status`, `/api/led/test`). The Alpha-specific dashboard and `/api/alpha/*` endpoints documented below in §3 and §4 describe a planned protocol-aware surface that has not yet been wired up — they remain in this guide as a reference for the M-Protocol features the underlying controller supports. Treat anything in those sections as forward-looking until the routes appear in `webapp/routes_led.py`.

## 1. Overview

EAS Station™ supports Alpha LED signs via the M-Protocol over a serial-to-Ethernet adapter (e.g., Waveshare). The integration provides full bidirectional control including message display, diagnostics, time/date synchronization, speaker control, brightness management, and file reading. All functions are accessible through the web UI dashboard or the Python API.

**Supported signs:**
- ✅ Alpha Premier (4-line)
- ✅ Alpha 9120C
- ✅ Most Alpha signs with M-Protocol firmware
- ✅ BetaBrite signs (may vary by model)

**Required environment variables:**
```bash
LED_SIGN_IP=192.168.8.122        # IP address of Waveshare adapter
LED_SIGN_PORT=10001              # TCP port (default: 10001)
LED_SIGN_ENABLED=true            # Enable LED sign controller
```

---

## 2. Web UI Configuration

**Complete web-based management interface for Alpha LED signs via M-Protocol**

---

### Accessing the Dashboard

**URL:** `https://your-eas-station/led_control` (the current generic dashboard; a planned Alpha-specific dashboard would live at `/alpha-sign`)

**Requirements:**
- Authenticated user account
- `hardware.manage` permission
- Alpha LED sign configured (LED_SIGN_IP and LED_SIGN_PORT set)

**Navigation:**
1. Log in to EAS Station™ web interface
2. Click **Hardware** in navigation menu
3. Select **Alpha LED Sign**

---

### Dashboard Sections

#### 1. Connection Status & Quick Actions

**Connection Status Panel:**
- Real-time connection indicator (Connected / Disconnected)
- Sign model information
- Firmware version
- Serial number
- Auto-refresh indicator (30-second intervals)

**Quick Actions:**
- **Sync Time with System** - Immediately synchronize sign time with EAS Station™
- **Refresh Diagnostics** - Manually trigger diagnostics refresh

#### 2. Sign Diagnostics

**Information Displayed:**
- Serial number
- Model number
- Firmware version

**Auto-Refresh:**
- Diagnostics automatically refresh every 30 seconds
- Manual refresh available via button
- Loading indicators during refresh

#### 3. System Health

**Metrics Monitored:**
- **Temperature**: Internal sign temperature (°F and °C)
- **Memory Usage**: Total and available memory

**Health Indicators:**
- Real-time temperature monitoring
- Memory statistics
- Alerts for abnormal conditions

#### 4. Time & Date Control

**Time Format Selection:**
- **12-Hour Format**: AM/PM display
- **24-Hour Format**: Military time

**Run Mode:**
- **Auto Mode**: Enable scheduled message rotation
- **Manual Mode**: Hold current message (useful during emergencies)

**Actions:**
- **Apply Settings**: Save time format and run mode
- **Sync Time**: Quick sync button in header

**Use Cases:**
- Keep sign synchronized with EAS Station™ time
- Switch to manual mode during emergency alerts
- Configure time format for user preference

#### 5. Speaker Control

**Settings:**
- **Enabled**: Speaker active for alerts
- **Disabled**: Silent operation (quiet hours)

**Testing:**
- **Test Beep**: Send 3 beeps to verify audio functionality
- Listen for beeps from physical sign

**Use Cases:**
- Enable speaker for emergency alerts
- Disable during night hours
- Test audio before critical alerts

#### 6. Brightness Control

**Manual Brightness:**
- **Interactive Slider**: 0-100% brightness
- **Real-time Value Display**: Shows current level
- **Instant Application**: Changes apply immediately

**Quick Presets:**
- **25%**: Night mode / Low brightness
- **50%**: Medium / Energy saving
- **75%**: Bright / Daytime
- **100%**: Full brightness / Emergencies

**Auto Brightness:**
- **Auto Mode**: Uses ambient light sensor (if equipped)
- Automatically adjusts to environmental conditions

**Use Cases:**
- Full brightness during emergencies
- Night mode for energy savings
- Business hours scheduling
- Light pollution reduction

#### 7. File Reader

**Functionality:**
- Read text content from sign file labels
- Support for files: 0-9 and A-Z
- Verify what's currently displayed

**File Labels:**
- **0**: Primary display file (default)
- **1-9**: Numbered text files
- **A-Z**: Lettered text files

**Process:**
1. Select file label from dropdown
2. Click "Read File" button
3. Content displays in textarea
4. Copy or verify as needed

**Use Cases:**
- Verify message delivery
- Read scheduled messages
- Audit sign content
- Troubleshoot display issues

#### 8. System Testing

**Comprehensive Test Suite:**
- Tests all M-Protocol functions (Phases 1-5)
- Real-time progress display
- Individual test results
- Pass/fail summary with percentage

**Tests Included:**
- Phase 1: Diagnostics (read serial, model, firmware, memory, temperature)
- Phase 2: Time/Date sync
- Phase 3: Speaker control
- Phase 4: Brightness control
- Phase 5: File reading

**Results Display:**
- ✅ Green checkmark: Test passed
- ❌ Red X: Test failed
- Detailed error messages for failures
- Overall pass percentage

**Use Cases:**
- Verify M-Protocol communication
- Troubleshoot connection issues
- Validate sign capabilities
- Pre-deployment testing

---

### API Endpoints

All endpoints require authentication and `hardware.manage` permission.

#### GET /api/alpha/diagnostics

**Description:** Read all sign diagnostics

**Response:**
```json
{
  "success": true,
  "diagnostics": {
    "serial_number": "A9120C-12345",
    "model": "Alpha 9120C",
    "firmware": "v2.15",
    "memory": "64K total, 32K free",
    "temperature": "72.0°F (22.2°C)"
  },
  "connection": {
    "host": "192.168.8.122",
    "port": 10001,
    "connected": true
  }
}
```

#### POST /api/alpha/sync-time

**Description:** Sync sign time with EAS Station™ system time

**Request:** Empty POST

**Response:**
```json
{
  "success": true,
  "message": "Time synchronized successfully"
}
```

#### POST /api/alpha/set-time-format

**Description:** Set 12-hour or 24-hour time format

**Request:**
```json
{
  "format_24h": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Time format set to 24-hour"
}
```

#### POST /api/alpha/set-run-mode

**Description:** Set auto (scheduled) or manual (hold) run mode

**Request:**
```json
{
  "auto": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Run mode set to AUTO"
}
```

#### POST /api/alpha/speaker

**Description:** Enable or disable speaker

**Request:**
```json
{
  "enabled": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Speaker enabled"
}
```

#### POST /api/alpha/beep

**Description:** Make sign beep

**Request:**
```json
{
  "count": 3
}
```

**Response:**
```json
{
  "success": true,
  "message": "Beep command sent (3 beeps)"
}
```

#### POST /api/alpha/brightness

**Description:** Set brightness level (0-100%) or auto mode

**Request (Manual):**
```json
{
  "level": 75
}
```

**Request (Auto):**
```json
{
  "auto": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Brightness set to 75%"
}
```

#### GET /api/alpha/read-file/<label>

**Description:** Read text from file label (0-9, A-Z)

**Parameters:**
- `label`: File label (0-9 or A-Z)

**Response:**
```json
{
  "success": true,
  "label": "0",
  "content": "ALPHA LED TEST M-PROTOCOL INTEGRATION",
  "length": 37
}
```

#### POST /api/alpha/test-all

**Description:** Run comprehensive test suite of all M-Protocol functions

**Request:** Empty POST

**Response:**
```json
{
  "success": true,
  "results": {
    "phase1_diagnostics": {
      "success": true,
      "data": {
        "serial_number": "A9120C-12345",
        "model": "Alpha 9120C"
      }
    },
    "phase2_time_sync": {
      "success": true
    },
    "phase3_speaker": {
      "success": true
    },
    "phase4_brightness": {
      "success": true
    },
    "phase5_read_file": {
      "success": true,
      "content": "TEST MESSAGE"
    }
  },
  "summary": {
    "passed": 5,
    "total": 5,
    "percentage": 100.0
  }
}
```

---

### Configuration

**Required Environment Variables:**

```bash
# Alpha LED Sign Configuration
LED_SIGN_IP=192.168.8.122        # IP address of Waveshare adapter
LED_SIGN_PORT=10001              # TCP port (default: 10001)
LED_SIGN_ENABLED=true            # Enable LED sign controller
```

**Set via Web UI:**
1. Navigate to Settings → Environment Variables
2. Scroll to "LED Display" section
3. Set **LED Sign IP Address**: `192.168.8.122`
4. Set **LED Sign Port**: `10001`
5. Save Changes
6. Click "Restart Now" to apply

**Waveshare Adapter Requirements:**
- Mode: TCP Server
- Port: 10001
- TCP Timeout: 0 (critical for bidirectional communication)
- AutoFrame: Enable
- Socket Distribution: on

---

### Use Cases & Examples

#### Emergency Alert with Maximum Visibility

**Scenario:** Tornado warning - need maximum visibility and audio

**Steps:**
1. Navigate to Alpha Sign Dashboard
2. Speaker Control → Enable speaker
3. Brightness Control → Set to 100%
4. Apply settings
5. Use LED Control page to send emergency message

**Result:** Sign at full brightness with audio enabled

#### Night Mode Energy Saving

**Scenario:** Reduce brightness overnight to save energy

**Steps:**
1. Navigate to Alpha Sign Dashboard
2. Brightness Control → Click "25% (Night)" preset
3. Sign dims to 25% brightness

**Automation Option:**
- Create scheduled task to call `/api/alpha/brightness` with `level: 25` at 10 PM
- Restore to 100% at 6 AM

#### Verify Displayed Message

**Scenario:** Confirm what's actually shown on sign

**Steps:**
1. Navigate to Alpha Sign Dashboard
2. File Reader → Select "0 (Primary)"
3. Click "Read File"
4. Content displays in textarea

**Result:** See exact text currently on sign

#### Pre-Deployment Testing

**Scenario:** Test all functions before going live

**Steps:**
1. Navigate to Alpha Sign Dashboard
2. System Testing → Click "Run Full Test Suite"
3. Wait for results
4. Review pass/fail status
5. Address any failures

**Result:** Comprehensive validation of all M-Protocol functions

#### Time Synchronization

**Scenario:** Keep sign time accurate

**Steps:**
1. Navigate to Alpha Sign Dashboard
2. Click "Sync Time with System"
3. Confirmation toast appears

**Automation Option:**
- Time syncs automatically on hardware service restart
- Can schedule periodic sync via cron calling `/api/alpha/sync-time`

---

### Web UI Troubleshooting

#### Connection Shows "Disconnected"

**Possible Causes:**
- Waveshare adapter not powered
- IP address incorrect
- Network connectivity issue
- Port mismatch

**Solutions:**
1. Verify LED_SIGN_IP and LED_SIGN_PORT in Environment Variables
2. Test network: `ping 192.168.8.122`
3. Test TCP port: `nc -z -v 192.168.8.122 10001`
4. Check Hardware Service logs for errors
5. Verify Waveshare adapter configuration

#### Diagnostics Not Loading

**Possible Causes:**
- Sign doesn't support M-Protocol Type F
- Communication timeout
- Waveshare AutoFrame disabled

**Solutions:**
1. Verify sign model supports M-Protocol
2. Enable AutoFrame in Waveshare settings
3. Set TCP Timeout to 0 in Waveshare settings
4. Check logs for specific error messages

#### Speaker Control Not Working

**Possible Causes:**
- Sign has no speaker hardware
- Speaker disabled in sign settings
- Volume turned down

**Solutions:**
1. Verify sign has speaker capability
2. Check physical volume control on sign
3. Test beep function to verify hardware
4. Some Alpha signs don't support speaker control

#### Brightness Not Changing

**Possible Causes:**
- Sign brightness locked
- Hardware issue
- Communication failure

**Solutions:**
1. Try different brightness levels (0%, 50%, 100%)
2. Verify sign responds to other commands
3. Check sign manual for brightness lock feature
4. Test with physical brightness controls

#### File Reading Returns Empty

**Possible Causes:**
- File label has no content
- Wrong file label selected
- Sign doesn't support file reading

**Solutions:**
1. Try reading file "0" (primary display)
2. Send message to file first via LED Control page
3. Verify sign model supports M-Protocol Type B
4. Check Hardware Service logs for errors

#### Auto-Refresh Not Working

**Possible Causes:**
- JavaScript error
- Page not in focus
- Browser privacy settings

**Solutions:**
1. Check browser console for errors
2. Refresh the page
3. Ensure browser allows background updates
4. Try manual refresh button

---

### Security

**Authentication:**
- All endpoints require valid user session
- Login required before accessing dashboard

**Authorization:**
- `hardware.manage` permission required
- Enforced on all API endpoints and page access

**CSRF Protection:**
- All POST requests include CSRF token
- Automatic token injection via JavaScript
- Tokens validated server-side

**Input Validation:**
- Brightness: 0-100 range
- File labels: A-Z, 0-9 only
- Boolean values: true/false only
- JSON payload validation

**Error Handling:**
- Sensitive information sanitized
- No stack traces exposed to users
- Errors logged server-side
- User-friendly error messages

---

### Browser Compatibility

**Supported Browsers:**
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Mobile Support:**
- Responsive design for tablets and phones
- Touch-optimized controls
- Mobile-friendly layout

**Requirements:**
- JavaScript enabled
- Cookies enabled (for authentication)
- Modern CSS support (flexbox, grid)

---

### Performance

**Auto-Refresh:**
- Diagnostics refresh every 30 seconds
- Minimal server load
- Silent background refresh (no toasts)

**API Response Times:**
- Diagnostics: 1-3 seconds (depends on sign response)
- Write operations: <1 second (ACK/NAK)
- File reading: 1-2 seconds
- Test suite: 5-10 seconds

**Optimization:**
- Cached connection status
- Debounced brightness slider
- Lazy-loaded test results

---

## 3. Bidirectional Communication

**Alpha LED signs support full bidirectional (duplex) communication**, allowing you to:
- ✅ **Send commands** to the sign (display messages, set time, etc.)
- ✅ **Read responses** from the sign (ACK/NAK, status, configuration)
- ✅ **Query sign data** (current message, memory usage, etc.)
- ✅ **Set configuration** (time/date, brightness, etc.)

The EAS Station™ LED controller and Waveshare adapter **fully support bidirectional communication**.

---

### How It Works

#### Communication Flow

```
EAS Station™ ←→ TCP Socket ←→ Waveshare ←→ RS232 ←→ Alpha LED Sign
   (Python)                  (Network)    (Serial)      (M-Protocol)
```

#### Bidirectional Data

**Outbound (EAS → Sign):**
- Display text messages
- Set colors and modes
- Configure time/date
- Read memory/status commands

**Inbound (Sign → EAS):**
- ACK (0x06) - Command accepted
- NAK (0x15) - Command rejected  
- Status responses
- Configuration data
- Error codes

---

### EAS Station™ LED Controller Support

The LED controller (`scripts/led_sign_controller.py`) implements full bidirectional M-Protocol:

#### Sending Data

```python
def send_message(self, lines, color, mode, ...):
    # 1. Drain any pending input
    self._drain_input_buffer()
    
    # 2. Send M-Protocol message
    self.socket.sendall(message)
    
    # 3. Wait for acknowledgment
    ack = self._read_acknowledgement()
    
    # 4. Send EOT if ACK received
    if ack == self.ACK:
        self._send_eot()
```

#### Reading Responses

```python
def _read_acknowledgement(self) -> Optional[bytes]:
    """Read an ACK (0x06) or NAK (0x15) response from the sign."""
    
    self.socket.settimeout(2)  # 2 second timeout
    while True:
        chunk = self.socket.recv(1)  # Read one byte at a time
        if chunk in (self.ACK, self.NAK):
            return chunk
```

#### Key Features

- ✅ **Waits for ACK/NAK** after every command
- ✅ **Handles timeouts** gracefully (2 second default)
- ✅ **Drains input buffer** before sending (prevents stale data)
- ✅ **Completes transaction** with EOT after ACK
- ✅ **Full M-Protocol** compliance

---

### Waveshare Adapter Configuration

#### Critical Settings for Bidirectional

**Network A Settings:**
```
Mode: Server
Protocol: TCP
Port: 10001
TCP Time out: 0  ⭐ CRITICAL: Must be 0 or high for responses
```

**UART AutoFrame:**
```
UART AutoFrame: Enable  ⭐ CRITICAL: Frames responses properly
AutoFrame Time: 500 ms
AutoFrame Length: 512 bytes
```

**Socket Distribution:**
```
Socket Distribution: on  ⭐ CRITICAL: Enables bidirectional flow
```

**Flow Control:**
```
Flow Control: None  ⭐ IMPORTANT: Most Alpha signs don't use hardware flow control
```

#### Why These Settings Matter

**TCP Time out: 0**
- If set too low, connection drops before sign can respond
- Sign may take 100-500ms to process and respond
- Setting to 0 means "never timeout"

**UART AutoFrame: Enable**
- Captures complete responses from sign
- Prevents partial ACK/NAK packets
- Ensures EOT is sent after complete transaction

**Socket Distribution: on**
- Enables simultaneous TX and RX
- Required for duplex communication
- Without this, responses may be lost

---

### M-Protocol Bidirectional Commands

#### Commands That Expect Responses

**1. Write Text (Type A)**
```
Format: <NULL><NULL><NULL><NULL><NULL><ID><CMD><FILE><TEXT><EOT>
Send: Display message
Receive: ACK or NAK
```

**2. Read Text (Type B)**
```
Format: <NULL><NULL><NULL><NULL><NULL><ID><CMD><FILE><ETX>
Send: Request to read file
Receive: ACK + File contents or NAK
```

**3. Read Special Functions (Type E)**
```
Format: <NULL><NULL><NULL><NULL><NULL><ID><CMD><FUNCTION><ETX>
Send: Read memory, serial number, etc.
Receive: ACK + Function data or NAK
```

**4. Write Special Functions (Type E)**
```
Format: <NULL><NULL><NULL><NULL><NULL><ID><CMD><FUNCTION><DATA><ETX>
Send: Set time, date, speaker, etc.
Receive: ACK or NAK
```

#### Response Codes

| Code | Value | Meaning |
|------|-------|---------|
| **ACK** | 0x06 | Command accepted and executed |
| **NAK** | 0x15 | Command rejected (error) |

---

### Testing Bidirectional Communication

#### Test 1: Send Message and Read ACK

Using the LED controller:

```python
from scripts.led_sign_controller import AlphaLEDController

# Create controller
led = AlphaLEDController(host='192.168.8.122', port=10001)

# Send message (controller automatically reads ACK)
result = led.send_message(
    lines=['TEST', 'MESSAGE', 'LINE 3', 'LINE 4'],
    color=led.Color.GREEN
)

# Check logs for ACK
# You should see: "Received ACK from sign"
```

#### Test 2: Manual Bidirectional Test with netcat

**Send command and read response:**

```bash
# Send test message and read response
(echo -ne '\x00\x00\x00\x00\x00\x01\x5A\x30\x30TEST\x04'; sleep 1) | nc 192.168.8.122 10001 | xxd

# Expected response: 06 (ACK)
```

#### Test 3: Python Socket Test

```python
import socket
import time

# Connect to Waveshare
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('192.168.8.122', 10001))

# Send simple Write Text command
# Format: <NULL>x5 <ID=01> <CMD=5A> <FILE=30> <TEXT> <EOT=04>
command = b'\x00\x00\x00\x00\x00\x01\x5A\x30\x30TEST\x04'
sock.sendall(command)

# Wait for response
sock.settimeout(2)
response = sock.recv(1)

if response == b'\x06':
    print("✅ Received ACK - Sign accepted command")
elif response == b'\x15':
    print("❌ Received NAK - Sign rejected command")
else:
    print(f"❓ Unexpected response: {response.hex()}")

sock.close()
```

#### Test 4: Check Waveshare Logs

Some Waveshare models have web UI logs showing bidirectional traffic:

1. Access: http://192.168.8.122
2. Navigate to: Status or Logs section
3. Look for:
   - Sent bytes (TX)
   - Received bytes (RX)
   - Verify RX shows ACK/NAK responses

---

### Advanced: Reading Sign Data

#### Read Current Message

**Command Structure:**
```
Read Text: <NULL>x5 <ID> <CMD=42> <FILE> <ETX>
```

**Example (read file 0x30):**
```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('192.168.8.122', 10001))

# Read Text command for file 0x30
command = b'\x00\x00\x00\x00\x00\x01\x42\x30\x03'
sock.sendall(command)

# Read response
sock.settimeout(2)
response = sock.recv(1024)

print(f"Sign response: {response}")
# Should contain ACK + message text

sock.close()
```

#### Set Time/Date

**Command Structure:**
```
Set Time: <NULL>x5 <ID> <CMD=45> <FUNCTION=20> <TIME> <ETX>
Time Format: 10 bytes ASCII (HH:MM:SS\x0DMM/DD/YY)
```

**Example:**
```python
import socket
from datetime import datetime

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('192.168.8.122', 10001))

# Get current time
now = datetime.now()
time_str = now.strftime("%H:%M:%S\r%m/%d/%y")

# Set Time command (0x45 0x20)
command = b'\x00\x00\x00\x00\x00\x01\x45\x20' + time_str.encode() + b'\x03'
sock.sendall(command)

# Read ACK/NAK
response = sock.recv(1)
if response == b'\x06':
    print("✅ Time set successfully")
else:
    print("❌ Failed to set time")

sock.close()
```

#### Read Sign Serial Number

**Command Structure:**
```
Read Serial: <NULL>x5 <ID> <CMD=45> <FUNCTION=24> <ETX>
```

**Example:**
```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('192.168.8.122', 10001))

# Read serial number command
command = b'\x00\x00\x00\x00\x00\x01\x45\x24\x03'
sock.sendall(command)

# Read response
sock.settimeout(2)
response = sock.recv(1024)

# Parse response (ACK + data)
if response[0:1] == b'\x06':
    serial = response[1:].decode('ascii', errors='ignore')
    print(f"Sign serial number: {serial}")

sock.close()
```

---

### Troubleshooting Bidirectional

#### No ACK Received

**Symptoms:**
- Commands seem to work (sign displays message)
- But logs show "No ACK/NAK received"

**Causes:**
1. ✅ TCP timeout too low on Waveshare
2. ✅ AutoFrame disabled
3. ✅ Socket Distribution off

**Solutions:**
```
1. Set TCP Time out: 0 (no timeout)
2. Enable UART AutoFrame
3. Enable Socket Distribution
4. Increase AutoFrame Time to 500-1000ms
```

#### Garbled Responses

**Symptoms:**
- Receive data but it's corrupted
- ACK/NAK not recognized

**Causes:**
1. ✅ Baud rate mismatch
2. ✅ AutoFrame settings too aggressive
3. ✅ Buffer overflow

**Solutions:**
```
1. Verify baud: 9600 on both sides
2. Increase AutoFrame Time: 500ms
3. Increase AutoFrame Length: 512 bytes
4. Check wiring: TX↔RX, RX↔TX, GND↔GND
```

#### Responses Timeout

**Symptoms:**
- First command works (receives ACK)
- Subsequent commands timeout

**Causes:**
1. ✅ Input buffer not drained
2. ✅ EOT not sent
3. ✅ Stale data in buffer

**Solutions:**
```
1. EAS controller drains buffer before send
2. Verify EOT sent after ACK
3. Power cycle sign to reset state
```

#### Connection Drops After Response

**Symptoms:**
- Receive ACK/NAK
- Then connection closes

**Causes:**
1. ✅ TCP timeout too aggressive
2. ✅ MAX TCP Num set to 0

**Solutions:**
```
1. Set TCP Time out: 0
2. Set MAX TCP Num: 1 or higher
3. Disable connection password
```

---

### Waveshare Settings Summary (Bidirectional)

**CRITICAL SETTINGS:**
```
Network A:
  Mode: Server
  Protocol: TCP
  Port: 10001
  TCP Time out: 0  ⭐ Must be 0 for responses

UART:
  Baudrate: 9600
  Data: 8-N-1
  Flow Control: None

AutoFrame:
  Enable: Yes  ⭐ Critical for responses
  Time: 500 ms
  Length: 512 bytes

Socket Distribution: on  ⭐ Required for duplex

Other:
  Registered Package: off
  Custom Heartbeat: off
  Modbus Polling: off
```

---

### EAS Station™ Configuration

**No changes needed!** The LED controller already:
- ✅ Sends data bidirectionally
- ✅ Reads ACK/NAK responses
- ✅ Handles timeouts
- ✅ Implements M-Protocol properly

**Just configure:**
```bash
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001
```

---

### Verification Checklist

Verify bidirectional communication is working:

- [ ] Sign displays messages (outbound works)
- [ ] Logs show "Received ACK from sign" (inbound works)
- [ ] No timeout errors in logs
- [ ] Sign responds to multiple commands without reconnecting
- [ ] Can set time/date successfully (advanced test)

---

### Reference: M-Protocol Response Format

**Write Command Response:**
```
ACK (0x06) - Success
NAK (0x15) - Failure
```

**Read Command Response:**
```
ACK (0x06) + Data + ETX (0x03)
NAK (0x15) - Failure
```

**Common NAK Causes:**
- Invalid sign ID
- File doesn't exist
- Invalid command
- Sign memory full
- Checksum error

---

## 4. Diagnostics — M-Protocol Phase 1

Phase 1 of the M-Protocol implementation adds comprehensive diagnostic capabilities for Alpha LED signs. You can now query the sign for status information, configuration, and health metrics.

### Read Functions (M-Protocol Type F)

The following read commands are now available:

| Method | Description | M-Protocol Function |
|--------|-------------|---------------------|
| `read_serial_number()` | Read sign serial number | Type F, 0x24 |
| `read_model_number()` | Read sign model | Type F, 0x25 |
| `read_firmware_version()` | Read firmware version | Type F, 0x26 |
| `read_memory_configuration()` | Query memory usage | Type F, 0x30 |
| `read_temperature()` | Read internal temperature | Type F, 0x35 |
| `get_diagnostics()` | Read all diagnostic data | Combined |

### Usage

#### Python API

```python
from scripts.led_sign_controller import Alpha9120CController

# Connect to sign
led = Alpha9120CController(host='192.168.8.122', port=10001)

# Read serial number
serial = led.read_serial_number()
print(f"Serial: {serial}")

# Read firmware version
firmware = led.read_firmware_version()
print(f"Firmware: {firmware}")

# Read temperature
temp = led.read_temperature()
print(f"Temperature: {temp}°F")

# Get all diagnostics at once
diagnostics = led.get_diagnostics()
for key, value in diagnostics.items():
    print(f"{key}: {value}")
```

#### Command Line Test Script

A test script is provided to verify functionality:

```bash
# Basic test
python3 scripts/test_alpha_diagnostics.py 192.168.8.122

# With custom port
python3 scripts/test_alpha_diagnostics.py 192.168.8.122 --port 10001
```

**Example Output:**

```
============================================================
Alpha LED Sign Diagnostics - M-Protocol Phase 1
============================================================

📋 Reading Sign Information...
------------------------------------------------------------
✅ Serial Number: A9120C-12345
✅ Model Number: Alpha 9120C
✅ Firmware Version: v2.15

💾 Reading Memory Configuration...
------------------------------------------------------------
✅ Memory Info:
   - raw_response: TOTAL 64K FREE 32K
   - total_memory: 64
   - free_memory: 32

🌡️  Reading Temperature Sensor...
------------------------------------------------------------
✅ Temperature: 72.0°F (22.2°C)

🔍 Comprehensive Diagnostics...
------------------------------------------------------------
✅ Complete diagnostic report:
   connected: True
   host: 192.168.8.122
   port: 10001
   serial_number: A9120C-12345
   model_number: Alpha 9120C
   firmware_version: v2.15
   memory_info:
      - raw_response: TOTAL 64K FREE 32K
      - total_memory: 64
      - free_memory: 32
   temperature: 72.0
```

### Integration with EAS Station™

#### Hardware Service Integration

The diagnostics functions integrate automatically with the hardware service:

```python
# In hardware_service.py or similar
from scripts.led_sign_controller import Alpha9120CController

led = Alpha9120CController(
    host=os.getenv('LED_SIGN_IP', '192.168.8.122'),
    port=int(os.getenv('LED_SIGN_PORT', '10001'))
)

# Periodically check sign health
diagnostics = led.get_diagnostics()
if diagnostics['temperature'] and diagnostics['temperature'] > 150:
    logger.warning(f"Sign temperature high: {diagnostics['temperature']}°F")
```

### Error Handling

All read functions return `None` if the command fails:

```python
serial = led.read_serial_number()

if serial is None:
    # Sign didn't respond or doesn't support this function
    print("Serial number not available")
else:
    print(f"Serial: {serial}")
```

Common failure reasons:
- Sign doesn't support the command (older firmware)
- Waveshare timeout too aggressive
- Network connection lost
- Sign returned NAK (command rejected)

### Sign Compatibility

**Tested:**
- ✅ Alpha Premier (4-line)
- ✅ Alpha 9120C

**Expected to work:**
- ✅ Most Alpha signs with M-Protocol firmware
- ✅ BetaBrite signs (may vary by model)

**May not support:**
- ⚠️ Older signs without Type F commands
- ⚠️ Non-Alpha signs using different protocols

If a function returns `None`, the sign may not support that specific command. This is normal for older models.

### Diagnostics Troubleshooting

#### No Response from Sign

**Symptom:** All read functions return `None`

**Check:**
1. ✅ Connection working: `led.connected == True`
2. ✅ Can send messages: `led.send_message(['TEST'])`
3. ✅ Waveshare TCP timeout = 0
4. ✅ Waveshare AutoFrame = Enable
5. ✅ Waveshare Socket Distribution = on

#### NAK Responses

**Symptom:** Logs show "Sign returned NAK"

**Reason:** Sign doesn't support this specific function

**Solution:** This is expected for some signs. The function will return `None` and you should handle that gracefully.

#### Timeout Errors

**Symptom:** "Timeout reading response"

**Solutions:**
1. Increase timeout in Waveshare (should be 0)
2. Check network latency
3. Verify sign is responding (test with basic message)

#### Garbled Responses

**Symptom:** Data contains unexpected characters

**Check:**
1. ✅ Baud rate: 9600 for Alpha signs
2. ✅ Data format: 8-N-1
3. ✅ AutoFrame settings: 500ms, 512 bytes

---

## 5. Time & Date Control — M-Protocol Phase 2

Phase 2 of the M-Protocol implementation adds complete time and date control for Alpha LED signs. You can now set the sign's time, date, day of week, time format, and run mode.

### Write Functions (M-Protocol Type E)

The following time/date control commands are now available:

| Method | Description | M-Protocol Function |
|--------|-------------|---------------------|
| `set_time_and_date()` | Set time and date | Type E, 0x20 |
| `set_day_of_week()` | Set day of week (0-6) | Type E, 0x22 |
| `set_time_format()` | Set 12h or 24h format | Type E, 0x27 |
| `set_run_mode()` | Set auto/manual mode | Type E, 0x2E |
| `sync_time_with_system()` | Sync with EAS Station™ | Combined |

### Usage

#### Python API

```python
from scripts.led_sign_controller import Alpha9120CController
from datetime import datetime

# Connect to sign
led = Alpha9120CController(host='192.168.8.122', port=10001)

# Sync time with system (recommended)
led.sync_time_with_system()

# Or set specific time/date
led.set_time_and_date(datetime(2025, 12, 25, 12, 0, 0))

# Set time format
led.set_time_format(format_24h=True)   # 24-hour
led.set_time_format(format_24h=False)  # 12-hour

# Set day of week (0=Sunday, 1=Monday, ..., 6=Saturday)
led.set_day_of_week(0)  # Sunday

# Set run mode
led.set_run_mode(auto=True)   # Auto mode (scheduled messages)
led.set_run_mode(auto=False)  # Manual mode (hold current)
```

#### Command Line Test Script

```bash
# Basic test
python3 scripts/test_alpha_timedate.py 192.168.8.122

# With custom port
python3 scripts/test_alpha_timedate.py 192.168.8.122 --port 10001
```

**Example Output:**

```
============================================================
Alpha LED Sign Time/Date Control - M-Protocol Phase 2
============================================================

🕐 Test 1: Sync Time with System
------------------------------------------------------------
✅ Sign synchronized to system time
   Current time: 2025-12-13 15:30:45 Friday

🕑 Test 2: Set Specific Time/Date
------------------------------------------------------------
✅ Time set to: 2025-12-25 12:00:00

🕒 Test 3: Restore Current Time
------------------------------------------------------------
✅ Time restored to: 2025-12-13 15:30:47

📅 Test 4: Set Day of Week
------------------------------------------------------------
✅ Day set to: Friday

🕓 Test 5: Set Time Format (24-hour)
------------------------------------------------------------
✅ Time format set to 24-hour

🕔 Test 6: Set Time Format (12-hour)
------------------------------------------------------------
✅ Time format set to 12-hour

⚙️  Test 7: Set Run Mode (Auto)
------------------------------------------------------------
✅ Run mode set to AUTO
   Sign will display scheduled messages

⚙️  Test 8: Set Run Mode (Manual)
------------------------------------------------------------
✅ Run mode set to MANUAL
   Sign will hold current message
```

### Integration with EAS Station™

#### Automatic Time Synchronization

Add to your hardware service to keep sign time synchronized:

```python
from scripts.led_sign_controller import Alpha9120CController
import schedule
import time

led = Alpha9120CController(
    host=os.getenv('LED_SIGN_IP'),
    port=int(os.getenv('LED_SIGN_PORT'))
)

# Sync time every hour
schedule.every().hour.do(led.sync_time_with_system)

while True:
    schedule.run_pending()
    time.sleep(60)
```

#### Displaying Time on Sign

```python
from datetime import datetime

# Update sign with current time every minute
def update_time_display():
    now = datetime.now()
    led.send_message(
        lines=[
            "CURRENT TIME",
            now.strftime("%I:%M %p"),
            now.strftime("%A"),
            now.strftime("%B %d, %Y")
        ]
    )

# Call periodically
```

### M-Protocol Details

#### Set Time and Date (0x20)

**Format:** `HH:MM:SS\rMM/DD/YY` (10 bytes ASCII)

**Example:**
- Input: `datetime(2025, 12, 13, 15, 30, 45)`
- Sent: `"15:30:45\r12/13/25"`

**Packet Structure:**
```
<NULL>x5 <ID> <0x45> <0x20> <TIME_DATE> <ETX>
```

#### Set Day of Week (0x22)

**Values:**
- 0 = Sunday
- 1 = Monday
- 2 = Tuesday
- 3 = Wednesday
- 4 = Thursday
- 5 = Friday
- 6 = Saturday

**Note:** Python's `datetime.weekday()` returns 0=Monday, so conversion is needed:
```python
alpha_day = (python_day + 1) % 7
```

#### Set Time Format (0x27)

**Values:**
- `'S'` = 24-hour format (standard/military time)
- `'M'` = 12-hour format (meridian AM/PM)

#### Set Run Mode (0x2E)

**Values:**
- `'A'` = Auto mode (sign displays scheduled messages)
- `'M'` = Manual mode (sign holds current message)

**Auto Mode:**
- Sign displays messages based on run time/day tables
- Allows scheduled content rotation
- Useful for automated operation

**Manual Mode:**
- Sign displays current message indefinitely
- Prevents automatic message changes
- Useful during emergencies or special events

### Use Cases

#### 1. Daily Time Sync

Keep sign synchronized with EAS Station™:

```python
# Run at system startup and daily at midnight
led.sync_time_with_system()
```

#### 2. Daylight Saving Time

Handle DST changes automatically:

```python
import datetime

# System handles DST, sign follows
led.sync_time_with_system()
```

#### 3. Emergency Override

Lock sign to manual mode during emergencies:

```python
# During emergency
led.set_run_mode(auto=False)
led.send_message(["TORNADO WARNING", "TAKE SHELTER", "IMMEDIATELY", ""])

# After emergency
led.set_run_mode(auto=True)  # Resume normal operation
```

#### 4. Business Hours Display

Different messages for different times:

```python
from datetime import datetime

def update_sign_for_time():
    hour = datetime.now().hour
    
    if 6 <= hour < 8:
        led.send_message(["GOOD MORNING", "..."])
    elif 17 <= hour < 22:
        led.send_message(["GOOD EVENING", "..."])
    else:
        led.send_message(["OVERNIGHT", "..."])
```

### Error Handling

All functions return `bool`:
- `True` = Command successful (ACK received)
- `False` = Command failed (NAK or no response)

```python
if led.set_time_and_date():
    print("Time set successfully")
else:
    print("Failed to set time - check sign compatibility")
```

### Time/Date Troubleshooting

#### Time Not Setting

**Symptom:** `set_time_and_date()` returns `False`

**Check:**
1. ✅ Connection active: `led.connected == True`
2. ✅ Basic commands work: `led.send_message(['TEST'])`
3. ✅ Sign supports Type E commands (check manual)
4. ✅ Waveshare bidirectional settings correct

#### Wrong Time Format

**Symptom:** Time displays incorrectly

**Check:**
1. ✅ Time format set correctly (12h vs 24h)
2. ✅ Date format matches sign expectations (MM/DD/YY)
3. ✅ Sign firmware supports time display

#### Day of Week Wrong

**Symptom:** Day doesn't match

**Check:**
1. ✅ Weekday conversion (Python 0=Monday, Alpha 0=Sunday)
2. ✅ Time zone settings on system
3. ✅ Sign and system clocks synchronized

---

## 6. Advanced Control — M-Protocol Phases 3-5

Phases 3-5 complete the M-Protocol implementation with speaker control, brightness management, and text file reading capabilities. Combined with Phases 1-2, this provides comprehensive control of Alpha LED signs.

### New Features

#### Phase 3: Speaker/Beep Control

| Method | Description | M-Protocol Function |
|--------|-------------|---------------------|
| `set_speaker()` | Enable/disable speaker | Type E, 0x23 |
| `beep()` | Make sign beep | Combined |

#### Phase 4: Brightness Control

| Method | Description | M-Protocol Function |
|--------|-------------|---------------------|
| `set_brightness()` | Set brightness 0-100% | Type E, 0x30 |

#### Phase 5: File Management

| Method | Description | M-Protocol Function |
|--------|-------------|---------------------|
| `read_text_file()` | Read text from file label | Type B, 0x42 |

### Usage

#### Python API

```python
from scripts.led_sign_controller import Alpha9120CController

# Connect to sign
led = Alpha9120CController(host='192.168.8.122', port=10001)

# === Phase 3: Speaker Control ===

# Enable speaker for alerts
led.set_speaker(True)

# Make sign beep
led.beep(1)

# Disable speaker
led.set_speaker(False)

# === Phase 4: Brightness Control ===

# Set full brightness
led.set_brightness(100)

# Set medium brightness
led.set_brightness(50)

# Set dim (night mode)
led.set_brightness(25)

# Enable auto brightness
led.set_brightness(0, auto=True)

# === Phase 5: File Reading ===

# Read text from file '0'
text = led.read_text_file('0')
print(f"File contains: {text}")

# Read from file 'A'
text = led.read_text_file('A')
```

#### Command Line Test Script

```bash
# Test all advanced features
python3 scripts/test_alpha_advanced.py 192.168.8.122

# With custom port
python3 scripts/test_alpha_advanced.py 192.168.8.122 --port 10001
```

**Example Output:**

```
============================================================
Alpha LED Sign Advanced Features - M-Protocol Phases 3-5
============================================================

🔊 Phase 3: Speaker/Beep Control
------------------------------------------------------------

🔊 Test 1: Enable Speaker
✅ Speaker enabled

🔔 Test 2: Test Beep
✅ Beep command sent (listen for beep)

🔇 Test 3: Disable Speaker
✅ Speaker disabled

💡 Phase 4: Brightness Control
------------------------------------------------------------

💡 Test 4: Set Brightness to 100% (Full)
✅ Brightness set to 100% (full)

🌓 Test 5: Set Brightness to 50% (Medium)
✅ Brightness set to 50% (medium)
   Sign should dim slightly

🌙 Test 6: Set Brightness to 25% (Night Mode)
✅ Brightness set to 25% (dim)
   Sign should be dim (night mode)

☀️  Test 7: Restore Full Brightness
✅ Brightness restored to 100%

📁 Phase 5: Text File Reading
------------------------------------------------------------

📖 Test 10: Read Text File '0'
✅ Successfully read file '0':
   Content: ALPHA LED TEST M-PROTOCOL PHASES 3-5 COMPLETE
   Length: 45 characters
```

### Integration Examples

#### Emergency Alert with Audio and Visual

```python
from scripts.led_sign_controller import Alpha9120CController

led = Alpha9120CController(host='192.168.8.122', port=10001)

def send_emergency_alert(message: str):
    """Send emergency alert with maximum visibility."""
    
    # Enable speaker for audio alert
    led.set_speaker(True)
    
    # Set full brightness
    led.set_brightness(100)
    
    # Send message with red flashing
    led.send_flashing_message(
        lines=[
            "⚠ EMERGENCY ALERT ⚠",
            message,
            "TAKE SHELTER NOW",
            "DO NOT DELAY"
        ]
    )
    
    # Beep for attention
    led.beep(3)
    
    print("Emergency alert sent with audio and visual")

# Usage
send_emergency_alert("TORNADO WARNING")
```

#### Auto-Dim for Night Operation

```python
from datetime import datetime

def adjust_brightness_for_time():
    """Auto-adjust brightness based on time of day."""
    
    hour = datetime.now().hour
    
    if 6 <= hour < 8:
        # Morning - medium brightness
        led.set_brightness(75)
    elif 8 <= hour < 20:
        # Daytime - full brightness
        led.set_brightness(100)
    elif 20 <= hour < 22:
        # Evening - dim
        led.set_brightness(50)
    else:
        # Night - very dim or off
        led.set_brightness(25)
    
    print(f"Brightness adjusted for {hour}:00")

# Run periodically
import schedule
schedule.every().hour.do(adjust_brightness_for_time)
```

#### Read Current Display

```python
def verify_message_displayed():
    """Verify what's currently displayed on sign."""
    
    # Read file 0 (default display file)
    current_text = led.read_text_file('0')
    
    if current_text:
        print(f"Sign is displaying: {current_text}")
        return current_text
    else:
        print("Could not read current display")
        return None

# Usage
verify_message_displayed()
```

#### Business Hours Automation

```python
from datetime import datetime

def business_hours_automation():
    """Fully automated sign operation."""
    
    hour = datetime.now().hour
    is_weekend = datetime.now().weekday() >= 5
    
    if is_weekend:
        # Weekend - low brightness, speaker off
        led.set_brightness(50)
        led.set_speaker(False)
        led.send_message(["WEEKEND", "CLOSED", "", ""])
    elif 8 <= hour < 17:
        # Business hours - full brightness, speaker on
        led.set_brightness(100)
        led.set_speaker(True)
        led.send_message(["OPEN", "WELCOME", "8AM - 5PM", ""])
    else:
        # After hours - dim, speaker off
        led.set_brightness(25)
        led.set_speaker(False)
        led.send_message(["CLOSED", "OPEN TOMORROW", "8:00 AM", ""])

# Run every hour
schedule.every().hour.do(business_hours_automation)
```

### M-Protocol Details

#### Speaker Control (0x23)

**Enable/Disable:**
- `'E'` = Enable speaker (beep on messages)
- `'D'` = Disable speaker (silent operation)

**Use Cases:**
- Emergency alerts (enable)
- Quiet hours (disable)
- Night operation (disable)

#### Brightness Control (0x30)

**Manual Brightness:**
- 0-100% range mapped to sign's brightness levels
- 0 = Off
- 25 = Dim (night mode)
- 50 = Medium
- 75 = Bright
- 100 = Full brightness

**Auto Mode:**
- Set `auto=True` to enable automatic brightness
- Sign adjusts based on ambient light (if sensor equipped)

#### Read Text File (0x42)

**File Labels:**
- Single ASCII character: '0'-'9', 'A'-'Z'
- File '0' is typically the default display file
- Files 'A'-'Z' are user-defined storage

**Response Format:**
- ACK (0x06) + Text Data + ETX (0x03)
- Returns `None` if file doesn't exist or NAK received
- Returns empty string `""` if file exists but empty

### Sign Compatibility

**Full Support:**
- ✅ Alpha Premier 4-line
- ✅ Alpha 9120C
- ✅ Most Alpha signs with M-Protocol

**Feature Support Varies:**
- Speaker: Most Alpha signs support
- Brightness: Most Alpha signs support
- File Reading: May vary by model/firmware
- Auto Brightness: Requires ambient light sensor

**Graceful Degradation:**
- All functions return `False` or `None` if not supported
- No exceptions thrown
- Check return values and handle accordingly

### Error Handling

```python
# Speaker control
if led.set_speaker(True):
    print("Speaker enabled")
else:
    print("Speaker not supported or failed")

# Brightness control
if led.set_brightness(50):
    print("Brightness set to 50%")
else:
    print("Brightness control not supported")

# File reading
text = led.read_text_file('0')
if text is not None:
    print(f"File contains: {text}")
else:
    print("Could not read file")
```

### Complete Feature Summary

With all 5 phases implemented, you now have:

#### Phase 1: Diagnostics (Read)
- Read serial number, model, firmware
- Query memory and temperature
- Comprehensive diagnostics

#### Phase 2: Time/Date Control (Write)
- Set time, date, day of week
- Set time format (12h/24h)
- Set run mode (auto/manual)
- Sync with system time

#### Phase 3: Speaker Control (Write)
- Enable/disable speaker
- Beep for alerts

#### Phase 4: Brightness Control (Write)
- Manual brightness (0-100%)
- Auto brightness mode

#### Phase 5: File Management (Read)
- Read text files by label

### Hardware Service Integration

```python
# In hardware_service.py
from scripts.led_sign_controller import Alpha9120CController
import os

led = Alpha9120CController(
    host=os.getenv('LED_SIGN_IP'),
    port=int(os.getenv('LED_SIGN_PORT'))
)

# Auto-adjust brightness by time
def adjust_brightness_schedule():
    hour = datetime.now().hour
    if 22 <= hour or hour < 6:
        led.set_brightness(25)  # Night mode
    else:
        led.set_brightness(100)  # Day mode

# Enable speaker for emergency alerts only
def send_alert(alert_data):
    if alert_data['severity'] == 'Extreme':
        led.set_speaker(True)
        led.set_brightness(100)
    else:
        led.set_speaker(False)
    
    led.send_message(format_alert(alert_data))
```

### Advanced Troubleshooting

#### Speaker Not Working

**Symptoms:** No beep sound

**Check:**
1. ✅ Sign has speaker hardware
2. ✅ Speaker cable connected
3. ✅ Volume not muted (check sign manual)
4. ✅ `set_speaker(True)` returns `True`

#### Brightness Not Changing

**Symptoms:** Brightness stays same

**Check:**
1. ✅ Sign supports brightness control
2. ✅ Not in auto mode (override with manual)
3. ✅ Ambient light sensor not overriding (if equipped)

#### Cannot Read Files

**Symptoms:** `read_text_file()` returns `None`

**Check:**
1. ✅ File exists on sign
2. ✅ Correct file label ('0', 'A', etc.)
3. ✅ Sign supports Type B read commands
4. ✅ Waveshare bidirectional settings correct

---

## Reference

- **M-Protocol Specification:** https://alpha-american.com/alpha-manuals/M-Protocol.pdf
- **Serial-to-Ethernet Adapters:** `docs/hardware/SERIAL_TO_ETHERNET_ADAPTERS.md`
- **Waveshare Setup Guide:** `docs/hardware/WAVESHARE_RS232_WIFI_SETUP.md`

## Support

- **Test Scripts:** `scripts/test_alpha_diagnostics.py`, `scripts/test_alpha_timedate.py`, `scripts/test_alpha_advanced.py`
- **LED Controller:** `scripts/led_sign_controller.py`
- **GitHub Issues:** https://github.com/KR8MER/eas-station/issues
- **Check Hardware Service logs:** `sudo journalctl -u eas-station-hardware.target -f`
