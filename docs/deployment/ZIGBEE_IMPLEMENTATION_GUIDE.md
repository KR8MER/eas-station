# Zigbee Integration Implementation Guide for EAS Station

**Created:** 2025-11-20
**Status:** Implementation Ready
**Target:** Raspberry Pi 5 with Argon ONE V5 + Industria Zigbee Module

## Overview

This guide provides step-by-step instructions for integrating your **existing Argon40 Industria Zigbee module** with EAS Station. Since you already have the hardware (Argon ONE V5 case + OLED display + Zigbee module + M.2), this focuses entirely on software integration and configuration.

**Hardware Status:** ✅ Complete (Argon ONE V5 with Zigbee module installed)

**Software Tasks:**
1. Configure Zigbee coordinator (Zigbee2MQTT)
2. Create Python integration library
3. Connect alert processing to Zigbee devices
4. Add web dashboard controls
5. Deploy and test Zigbee devices

**Estimated Time:** 7-10 days development + testing

---

## Architecture Overview

### Current EAS Station Stack

```
┌─────────────────────────────────────┐
│     EAS Station (Docker Compose)     │
├─────────────────────────────────────┤
│  nginx  │  app  │  noaa-poller       │
│  certbot│ icecast│ ipaws-poller      │
│         │ alerts-db (PostgreSQL)     │
└─────────────────────────────────────┘
```

### New Zigbee Stack (To Add)

```
┌─────────────────────────────────────────────┐
│     EAS Station + Zigbee (Docker Compose)   │
├─────────────────────────────────────────────┤
│  nginx  │  app ──┐                          │
│  certbot│ icecast│                          │
│         │ alerts-db                         │
│         │         │                          │
│         │    [New Services]                  │
│         ├─────────┴──────────────────┐      │
│         │  mosquitto (MQTT Broker)   │      │
│         │  zigbee2mqtt (Coordinator) │      │
│         └────────────────────────────┘      │
└─────────────────────────────────────────────┘
              │
              ├─→ /dev/ttyAMA0 (Argon Zigbee)
              │
              └─→ Zigbee Mesh Network
                    ├─ Sirens (HS2WD-E)
                    ├─ Smart Lights (IKEA/Philips)
                    ├─ Smart Plugs (IKEA/Aqara)
                    └─ Sensors (Aqara Temp/Humidity)
```

### Data Flow

```
NOAA Alert Received
    ↓
cap_poller.py processes alert
    ↓
app_core/zigbee/controller.py
    ↓
MQTT Publish → zigbee2mqtt
    ↓
Zigbee Radio Transmission
    ↓
Devices Respond:
    • Sirens activate
    • Lights flash red
    • Notification sent
```

---

## Phase 1: Verify Hardware (30 minutes)

### Step 1.1: Confirm Zigbee Module Detected

SSH into your Raspberry Pi and run:

```bash
# Check if serial port exists
ls -la /dev/ttyAMA0

# Expected output:
# crw-rw---- 1 root dialout 204, 64 Nov 20 10:00 /dev/ttyAMA0
```

If `/dev/ttyAMA0` doesn't exist:

```bash
# Enable UART on Pi 5
sudo raspi-config
# Navigate to: Interface Options → Serial Port
# Login shell over serial: NO
# Serial port hardware enabled: YES
# Reboot: YES

sudo reboot
```

### Step 1.2: Test Serial Communication

```bash
# Install minicom for serial testing
sudo apt install minicom -y

# Test serial port (press Ctrl+A, then X to exit)
sudo minicom -D /dev/ttyAMA0 -b 115200

# You should see garbage or no output - that's expected (binary protocol)
# If you get "Device not found", check raspi-config settings
```

### Step 1.3: Check Antenna Connection

Visually inspect:
- SMA antenna connector on rear of Argon case is tight
- Antenna is securely attached
- Antenna cable not pinched inside case

**Status Check:** ✅ Serial port detected and accessible

---

## Phase 2: Deploy Zigbee Software Stack (2-3 hours)

### Step 2.1: Create Docker Compose Overlay

Create `docker-compose.zigbee.yml` in your EAS Station directory:

```yaml
# docker-compose.zigbee.yml
# Zigbee integration overlay for EAS Station
#
# Usage:
#   docker compose -f docker-compose.yml -f docker-compose.zigbee.yml up -d

services:
  # MQTT Broker (required for Zigbee2MQTT)
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: eas-mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"  # MQTT
      - "9001:9001"  # WebSocket (optional)
    volumes:
      - mosquitto-data:/mosquitto/data
      - mosquitto-logs:/mosquitto/log
      - ./config/mosquitto:/mosquitto/config
    environment:
      - TZ=${DEFAULT_TIMEZONE:-America/New_York}
    networks:
      - default
    healthcheck:
      test: ["CMD", "mosquitto_sub", "-t", "$$SYS/#", "-C", "1", "-W", "3"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Zigbee2MQTT - Zigbee to MQTT bridge
  zigbee2mqtt:
    image: koenkk/zigbee2mqtt:latest
    container_name: eas-zigbee2mqtt
    restart: unless-stopped
    ports:
      - "8080:8080"  # Web UI
    volumes:
      - zigbee2mqtt-data:/app/data
      - /run/udev:/run/udev:ro  # For device detection
    devices:
      - /dev/ttyAMA0:/dev/ttyAMA0:rwm  # Argon Zigbee module
    environment:
      - TZ=${DEFAULT_TIMEZONE:-America/New_York}
      - ZIGBEE2MQTT_DATA=/app/data
    depends_on:
      mosquitto:
        condition: service_healthy
    networks:
      - default
    group_add:
      - dialout  # Grant access to serial port
    privileged: false  # Not needed for serial access

  # Extend main app service to depend on mosquitto
  app:
    depends_on:
      - mosquitto
    environment:
      # Add MQTT broker connection info
      - MQTT_BROKER=mosquitto
      - MQTT_PORT=1883
      - MQTT_USERNAME=${MQTT_USERNAME:-}
      - MQTT_PASSWORD=${MQTT_PASSWORD:-}

volumes:
  mosquitto-data:
  mosquitto-logs:
  zigbee2mqtt-data:
```

### Step 2.2: Create Mosquitto Configuration

Create directory and config file:

```bash
mkdir -p config/mosquitto
```

Create `config/mosquitto/mosquitto.conf`:

```conf
# Mosquitto MQTT Broker Configuration for EAS Station

# Listeners
listener 1883
protocol mqtt

listener 9001
protocol websockets

# Security
allow_anonymous true
# For production, set to false and configure users:
# allow_anonymous false
# password_file /mosquitto/config/passwords

# Persistence
persistence true
persistence_location /mosquitto/data/

# Logging
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information
log_timestamp true
log_timestamp_format %Y-%m-%dT%H:%M:%S

# Connection limits
max_connections -1
max_queued_messages 1000

# Message size limit (10 MB)
message_size_limit 10485760
```

### Step 2.3: Create Zigbee2MQTT Configuration

Create `config/zigbee2mqtt/configuration.yaml`:

```yaml
# Zigbee2MQTT Configuration for EAS Station Argon Zigbee Module

# Home Assistant integration (disable if not using)
homeassistant: false

# MQTT Settings
mqtt:
  base_topic: zigbee2mqtt
  server: 'mqtt://mosquitto:1883'
  # user: 'your_mqtt_user'  # Uncomment for auth
  # password: 'your_mqtt_password'

# Serial Port (Argon Industria Zigbee Module)
serial:
  port: /dev/ttyAMA0
  adapter: zstack  # CC2652P uses Z-Stack firmware
  baudrate: 115200
  rtscts: false

# Network Configuration
advanced:
  # Zigbee network settings
  pan_id: GENERATE  # Will auto-generate on first run
  network_key: GENERATE  # Will auto-generate secure key
  channel: 25  # Zigbee channel (11, 15, 20, 25 avoid WiFi)

  # Logging
  log_level: info  # Options: error, warn, info, debug
  log_output: ['console']

  # Network performance
  last_seen: 'ISO_8601'  # Timestamp format
  elapsed: true  # Show time since last message

  # Zigbee network strength
  transmit_power: 20  # dBm (max for CC2652P)

  # Device availability
  availability_timeout: 300  # Seconds before device marked offline
  availability_blocklist: []
  availability_passlist: []

# Device-specific options
device_options:
  # Template for configuring all devices
  legacy: false  # Use modern Zigbee 3.0 features

# Frontend (Web UI)
frontend:
  port: 8080
  host: 0.0.0.0
  # auth_token: 'your_secret_token'  # Uncomment to enable auth

# Permit joining (pairing mode)
permit_join: true  # Set to false after pairing all devices

# Devices (will be auto-populated as you pair)
devices: {}

# Groups (for controlling multiple devices together)
groups: {}
```

### Step 2.4: Deploy Stack

```bash
# Navigate to EAS Station directory
cd /path/to/eas-station

# Deploy with Zigbee overlay
docker compose -f docker-compose.yml -f docker-compose.zigbee.yml up -d

# Check logs
docker compose logs -f zigbee2mqtt

# Expected output:
# zigbee2mqtt  | Zigbee2MQTT:info  ... Starting Zigbee2MQTT version X.X.X
# zigbee2mqtt  | Zigbee2MQTT:info  ... Logging to console
# zigbee2mqtt  | Zigbee2MQTT:info  ... Starting zigbee-herdsman
# zigbee2mqtt  | Zigbee2MQTT:info  ... zigbee-herdsman started
# zigbee2mqtt  | Zigbee2MQTT:info  ... Coordinator firmware version: ...
# zigbee2mqtt  | Zigbee2MQTT:info  ... Currently 0 devices are joined
# zigbee2mqtt  | Zigbee2MQTT:info  ... Zigbee: allowing new devices to join
# zigbee2mqtt  | Zigbee2MQTT:info  ... Connecting to MQTT server at mqtt://mosquitto:1883
# zigbee2mqtt  | Zigbee2MQTT:info  ... Connected to MQTT server
# zigbee2mqtt  | Zigbee2MQTT:info  ... MQTT publish: topic 'zigbee2mqtt/bridge/state'
# zigbee2mqtt  | Zigbee2MQTT:info  ... Started frontend on port 8080
```

### Step 2.5: Access Zigbee2MQTT Web UI

Open browser to: `http://your-pi-address:8080`

You should see:
- Zigbee2MQTT dashboard
- "Coordinator" device listed
- "Permit join" toggle (should be ON)
- Empty devices list (ready to pair)

**Status Check:** ✅ Zigbee2MQTT running and connected to coordinator

---

## Phase 3: Pair Test Devices (1-2 hours)

### Step 3.1: Pair a Zigbee Siren

**Example: Heiman HS2WD-E**

1. **Enable Pairing Mode** (if not already on):
   - In Zigbee2MQTT UI, click "Permit join (All)" button
   - LED on coordinator should indicate pairing mode

2. **Reset Siren:**
   - Plug in siren to power
   - Press and hold reset button for 5-10 seconds
   - LED will flash rapidly (pairing mode)
   - Wait 10-30 seconds for pairing to complete

3. **Verify in UI:**
   - Device should appear in Zigbee2MQTT device list
   - Default name will be something like "0x00124b001f2a3b4c"
   - Click device → Rename to "exterior_siren_1"

4. **Test Control:**
   - In Zigbee2MQTT UI, go to device page
   - Find "Warning" control
   - Set: `mode: emergency`, `duration: 5`, `strobe: true`
   - Click "Send"
   - Siren should sound for 5 seconds with strobe

### Step 3.2: Pair Smart Bulbs

**Example: IKEA Trådfri Color Bulb**

1. **Reset Bulb:**
   - Install bulb in lamp
   - Turn on/off 6 times rapidly (on 1 sec, off 1 sec)
   - Bulb will dim and brighten (pairing mode)

2. **Verify and Rename:**
   - Appears in Zigbee2MQTT UI
   - Rename to "hallway_light_1"

3. **Test Control:**
   - Turn on/off
   - Change color to red
   - Set brightness to 100%

### Step 3.3: Pair Smart Plug

**Example: IKEA Trådfri Control Outlet**

1. **Reset Plug:**
   - Plug into outlet
   - Press pairing button 4 times rapidly
   - LED blinks (pairing mode)

2. **Verify and Rename:**
   - Appears in Zigbee2MQTT UI
   - Rename to "backup_transmitter_plug"

3. **Test Control:**
   - Turn on/off via UI
   - Verify device plugged into it powers on/off

### Step 3.4: Test MQTT Control

```bash
# Install mosquitto clients
sudo apt install mosquitto-clients -y

# Subscribe to all Zigbee messages
mosquitto_sub -h localhost -t 'zigbee2mqtt/#' -v

# In another terminal, trigger siren
mosquitto_pub -h localhost \
  -t 'zigbee2mqtt/exterior_siren_1/set' \
  -m '{"warning": {"mode": "emergency", "duration": 5, "strobe": true, "level": "very_high"}}'

# Expected: Siren sounds for 5 seconds

# Flash light red
mosquitto_pub -h localhost \
  -t 'zigbee2mqtt/hallway_light_1/set' \
  -m '{"state": "ON", "brightness": 255, "color": {"hex": "#FF0000"}}'

# Expected: Light turns on, full brightness, red color
```

**Status Check:** ✅ Devices paired and responding to MQTT commands

---

## Phase 4: Python Integration Library (2-3 days)

### Step 4.1: Install Python MQTT Client

Add to `requirements.txt`:

```
paho-mqtt==1.6.1
```

Rebuild app container:

```bash
docker compose build app
docker compose restart app
```

### Step 4.2: Create Zigbee Controller Module

Create `app_core/zigbee/__init__.py`:

```python
"""Zigbee device control integration for EAS Station."""

from .controller import ZigbeeController, ZigbeeConfig
from .devices import SirenMode, LightEffect, DeviceType

__all__ = [
    "ZigbeeController",
    "ZigbeeConfig",
    "SirenMode",
    "LightEffect",
    "DeviceType",
]
```

Create `app_core/zigbee/controller.py`:

```python
"""Zigbee device controller using MQTT/Zigbee2MQTT."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


@dataclass
class ZigbeeConfig:
    """Configuration for Zigbee2MQTT connection."""

    broker_host: str = "mosquitto"
    broker_port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    base_topic: str = "zigbee2mqtt"
    client_id: str = "eas_station"

    @classmethod
    def from_env(cls) -> ZigbeeConfig:
        """Load configuration from environment variables."""
        return cls(
            broker_host=os.getenv("MQTT_BROKER", "mosquitto"),
            broker_port=int(os.getenv("MQTT_PORT", "1883")),
            username=os.getenv("MQTT_USERNAME"),
            password=os.getenv("MQTT_PASSWORD"),
            base_topic=os.getenv("ZIGBEE_BASE_TOPIC", "zigbee2mqtt"),
            client_id=os.getenv("MQTT_CLIENT_ID", "eas_station"),
        )


class ZigbeeController:
    """Control Zigbee devices via Zigbee2MQTT."""

    def __init__(self, config: Optional[ZigbeeConfig] = None):
        """Initialize Zigbee controller.

        Args:
            config: Zigbee configuration (uses env vars if None)
        """
        self.config = config or ZigbeeConfig.from_env()
        self.client = mqtt.Client(client_id=self.config.client_id)
        self._connected = False
        self._lock = threading.Lock()
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

        # Set up MQTT callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Set up authentication if provided
        if self.config.username and self.config.password:
            self.client.username_pw_set(
                self.config.username, self.config.password
            )

        logger.info(
            "Zigbee controller initialized for %s:%d",
            self.config.broker_host,
            self.config.broker_port,
        )

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect to MQTT broker.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connected successfully
        """
        try:
            self.client.connect(
                self.config.broker_host,
                self.config.broker_port,
                keepalive=60,
            )
            self.client.loop_start()

            # Wait for connection
            start_time = time.time()
            while not self._connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            if self._connected:
                logger.info("Connected to Zigbee2MQTT broker")
                return True
            else:
                logger.error("Connection timeout after %.1f seconds", timeout)
                return False

        except Exception as e:
            logger.error("Failed to connect to MQTT broker: %s", e)
            return False

    def disconnect(self):
        """Disconnect from MQTT broker."""
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False
        logger.info("Disconnected from Zigbee2MQTT broker")

    def _on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection."""
        if rc == 0:
            self._connected = True
            # Subscribe to bridge state and all devices
            topics = [
                f"{self.config.base_topic}/bridge/state",
                f"{self.config.base_topic}/+",  # All device topics
            ]
            for topic in topics:
                client.subscribe(topic)
            logger.info("MQTT connected and subscribed to topics")
        else:
            logger.error("MQTT connection failed with code %d", rc)

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._connected = False
        if rc != 0:
            logger.warning("Unexpected MQTT disconnection (code %d)", rc)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            # Update device cache
            if topic.startswith(f"{self.config.base_topic}/"):
                device_name = topic.replace(f"{self.config.base_topic}/", "")
                if device_name not in ["bridge/state", "bridge/info"]:
                    with self._lock:
                        self._devices[device_name] = payload

                    # Notify callbacks
                    for callback in self._callbacks:
                        try:
                            callback(device_name, payload)
                        except Exception as e:
                            logger.error("Callback error: %s", e)

        except json.JSONDecodeError:
            logger.warning("Invalid JSON in MQTT message: %s", msg.payload)
        except Exception as e:
            logger.error("Error processing MQTT message: %s", e)

    def publish(self, device_name: str, command: Dict[str, Any]) -> bool:
        """Publish command to Zigbee device.

        Args:
            device_name: Device friendly name
            command: Command dictionary

        Returns:
            True if published successfully
        """
        if not self._connected:
            logger.error("Not connected to MQTT broker")
            return False

        topic = f"{self.config.base_topic}/{device_name}/set"
        payload = json.dumps(command)

        try:
            result = self.client.publish(topic, payload)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug("Published to %s: %s", topic, payload)
                return True
            else:
                logger.error("Publish failed with code %d", result.rc)
                return False
        except Exception as e:
            logger.error("Error publishing message: %s", e)
            return False

    def trigger_siren(
        self,
        device_name: str,
        duration: int = 60,
        mode: str = "emergency",
        strobe: bool = True,
        level: str = "very_high",
    ) -> bool:
        """Trigger a Zigbee siren.

        Args:
            device_name: Siren friendly name
            duration: Duration in seconds (0-65535)
            mode: Siren mode (emergency, burglar, fire, etc.)
            strobe: Enable strobe light
            level: Volume level (low, medium, high, very_high)

        Returns:
            True if command sent successfully
        """
        command = {
            "warning": {
                "mode": mode,
                "duration": duration,
                "strobe": strobe,
                "level": level,
            }
        }
        logger.info(
            "Triggering siren %s: mode=%s, duration=%d",
            device_name,
            mode,
            duration,
        )
        return self.publish(device_name, command)

    def flash_light(
        self,
        device_name: str,
        color: str = "#FF0000",
        brightness: int = 255,
        effect: str = "blink",
        duration: Optional[int] = None,
    ) -> bool:
        """Flash a smart light for visual alerting.

        Args:
            device_name: Light friendly name
            color: Hex color code (e.g., "#FF0000" for red)
            brightness: Brightness 0-255
            effect: Light effect (blink, breathe, okay, etc.)
            duration: Duration in seconds (None for indefinite)

        Returns:
            True if command sent successfully
        """
        command = {
            "state": "ON",
            "brightness": brightness,
            "color": {"hex": color},
            "effect": effect,
        }
        logger.info(
            "Flashing light %s: color=%s, effect=%s",
            device_name,
            color,
            effect,
        )
        success = self.publish(device_name, command)

        # Schedule turn off if duration specified
        if success and duration:
            threading.Timer(
                duration, self.turn_off_light, args=[device_name]
            ).start()

        return success

    def turn_off_light(self, device_name: str) -> bool:
        """Turn off a smart light.

        Args:
            device_name: Light friendly name

        Returns:
            True if command sent successfully
        """
        command = {"state": "OFF"}
        return self.publish(device_name, command)

    def control_plug(self, device_name: str, state: bool) -> bool:
        """Control a smart plug.

        Args:
            device_name: Plug friendly name
            state: True for ON, False for OFF

        Returns:
            True if command sent successfully
        """
        command = {"state": "ON" if state else "OFF"}
        logger.info("Setting plug %s to %s", device_name, command["state"])
        return self.publish(device_name, command)

    def get_device_state(self, device_name: str) -> Optional[Dict[str, Any]]:
        """Get cached state of a device.

        Args:
            device_name: Device friendly name

        Returns:
            Device state dictionary or None if not found
        """
        with self._lock:
            return self._devices.get(device_name)

    def list_devices(self) -> List[str]:
        """Get list of known device names.

        Returns:
            List of device friendly names
        """
        with self._lock:
            return list(self._devices.keys())

    def add_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Add callback for device state updates.

        Args:
            callback: Function to call with (device_name, state_dict)
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Remove state update callback.

        Args:
            callback: Callback function to remove
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)


# Convenience functions for common operations
ALERT_COLOR_MAP = {
    "TOR": "#FF0000",  # Tornado - Red
    "SVR": "#FFA500",  # Severe Storm - Orange
    "FFW": "#0000FF",  # Flood - Blue
    "SVS": "#FFFF00",  # Severe Weather Statement - Yellow
    "EWW": "#FF00FF",  # Extreme Wind - Magenta
    "EAS": "#FF0000",  # EAS Required Test - Red
    "RWT": "#FFFF00",  # Required Weekly Test - Yellow
}


def trigger_alert_devices(
    controller: ZigbeeController,
    alert_code: str,
    duration: int = 60,
    siren_devices: Optional[List[str]] = None,
    light_devices: Optional[List[str]] = None,
):
    """Trigger appropriate Zigbee devices for an alert.

    Args:
        controller: ZigbeeController instance
        alert_code: EAS alert code (TOR, SVR, etc.)
        duration: Alert duration in seconds
        siren_devices: List of siren device names
        light_devices: List of light device names
    """
    # Get alert color
    color = ALERT_COLOR_MAP.get(alert_code, "#FF0000")

    # Trigger sirens
    if siren_devices:
        for siren in siren_devices:
            controller.trigger_siren(siren, duration=duration)

    # Flash lights
    if light_devices:
        for light in light_devices:
            controller.flash_light(light, color=color, duration=duration)

    logger.info(
        "Alert %s triggered: %d sirens, %d lights",
        alert_code,
        len(siren_devices or []),
        len(light_devices or []),
    )
```

Create `app_core/zigbee/devices.py`:

```python
"""Zigbee device type definitions and constants."""

from enum import Enum


class SirenMode(str, Enum):
    """Siren warning modes."""

    STOP = "stop"
    BURGLAR = "burglar"
    FIRE = "fire"
    EMERGENCY = "emergency"
    POLICE_PANIC = "police_panic"
    FIRE_PANIC = "fire_panic"
    EMERGENCY_PANIC = "emergency_panic"


class SirenLevel(str, Enum):
    """Siren volume levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class LightEffect(str, Enum):
    """Smart light effects."""

    BLINK = "blink"
    BREATHE = "breathe"
    OKAY = "okay"
    CHANNEL_CHANGE = "channel_change"
    FINISH_EFFECT = "finish_effect"
    STOP_EFFECT = "stop_effect"


class DeviceType(str, Enum):
    """Zigbee device types."""

    SIREN = "siren"
    LIGHT = "light"
    PLUG = "plug"
    SENSOR = "sensor"
    CONTACT = "contact"
    MOTION = "motion"
    UNKNOWN = "unknown"
```

**Status Check:** ✅ Python library created and ready for integration

---

## Phase 5: Integrate with Alert Processing (1-2 days)

### Step 5.1: Initialize Zigbee Controller in App

Modify `app_core/__init__.py`:

```python
"""Core application initialization."""

from flask import Flask

# Existing imports...
from .extensions import db, migrate

# Add Zigbee import
from .zigbee import ZigbeeController, ZigbeeConfig

# Global Zigbee controller instance
zigbee_controller: Optional[ZigbeeController] = None


def create_app(config_name="default"):
    """Create and configure Flask application."""
    app = Flask(__name__)

    # ... existing configuration ...

    with app.app_context():
        # ... existing initialization ...

        # Initialize Zigbee controller
        try:
            zigbee_config = ZigbeeConfig.from_env()
            global zigbee_controller
            zigbee_controller = ZigbeeController(zigbee_config)
            if zigbee_controller.connect():
                app.logger.info("Zigbee controller initialized successfully")
            else:
                app.logger.warning("Zigbee controller connection failed")
        except Exception as e:
            app.logger.error("Failed to initialize Zigbee controller: %s", e)

    return app
```

### Step 5.2: Add Zigbee Triggers to Alert Processing

Modify `poller/cap_poller.py` to trigger Zigbee devices when alerts are received:

```python
# Add to imports at top of file
from app_core import zigbee_controller
from app_core.zigbee import trigger_alert_devices

# Find the function that processes new alerts (around line 800-900)
# Add Zigbee trigger after database save:

def process_new_alert(alert_data):
    """Process and store new alert."""

    # ... existing database save logic ...

    # NEW: Trigger Zigbee devices
    if zigbee_controller and zigbee_controller._connected:
        try:
            # Get alert code (e.g., "TOR", "SVR")
            alert_code = alert_data.get("event_code", "UNKNOWN")

            # Define which devices to trigger (TODO: make configurable)
            siren_devices = ["exterior_siren_1", "exterior_siren_2"]
            light_devices = ["hallway_light_1", "office_light_1"]

            # Trigger devices
            trigger_alert_devices(
                zigbee_controller,
                alert_code=alert_code,
                duration=300,  # 5 minutes
                siren_devices=siren_devices,
                light_devices=light_devices,
            )

            logger.info("Triggered Zigbee devices for alert %s", alert_code)

        except Exception as e:
            logger.error("Failed to trigger Zigbee devices: %s", e)

    return alert_data
```

**Status Check:** ✅ Alerts now trigger Zigbee devices automatically

---

## Phase 6: Web Dashboard (2-3 days)

### Step 6.1: Create Zigbee Routes

Create `webapp/routes_zigbee.py`:

```python
"""Zigbee device management routes."""

from flask import Blueprint, jsonify, render_template, request

from app_core import zigbee_controller
from app_core.auth.decorators import login_required, admin_required

bp = Blueprint("zigbee", __name__, url_prefix="/zigbee")


@bp.route("/")
@login_required
def index():
    """Zigbee device management page."""
    return render_template("zigbee/index.html")


@bp.route("/api/devices")
@login_required
def list_devices():
    """Get list of Zigbee devices."""
    if not zigbee_controller or not zigbee_controller._connected:
        return jsonify({"error": "Zigbee controller not connected"}), 503

    devices = []
    for name in zigbee_controller.list_devices():
        state = zigbee_controller.get_device_state(name)
        devices.append({
            "name": name,
            "state": state,
        })

    return jsonify({"devices": devices})


@bp.route("/api/devices/<device_name>/trigger", methods=["POST"])
@admin_required
def trigger_device(device_name):
    """Manually trigger a device."""
    if not zigbee_controller or not zigbee_controller._connected:
        return jsonify({"error": "Zigbee controller not connected"}), 503

    data = request.get_json()
    device_type = data.get("type", "siren")

    if device_type == "siren":
        success = zigbee_controller.trigger_siren(
            device_name,
            duration=int(data.get("duration", 5)),
            mode=data.get("mode", "emergency"),
        )
    elif device_type == "light":
        success = zigbee_controller.flash_light(
            device_name,
            color=data.get("color", "#FF0000"),
            brightness=int(data.get("brightness", 255)),
        )
    elif device_type == "plug":
        success = zigbee_controller.control_plug(
            device_name,
            state=data.get("state", True),
        )
    else:
        return jsonify({"error": "Unknown device type"}), 400

    if success:
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Command failed"}), 500


@bp.route("/api/status")
@login_required
def get_status():
    """Get Zigbee controller status."""
    if not zigbee_controller:
        return jsonify({"connected": False, "error": "Controller not initialized"})

    return jsonify({
        "connected": zigbee_controller._connected,
        "device_count": len(zigbee_controller.list_devices()),
    })
```

Register blueprint in `app.py`:

```python
# Add to imports
from webapp import routes_zigbee

# Add to blueprint registration
app.register_blueprint(routes_zigbee.bp)
```

### Step 6.2: Create Web UI Template

Create `templates/zigbee/index.html`:

```html
{% extends "base.html" %}

{% block title %}Zigbee Devices - EAS Station{% endblock %}

{% block content %}
<div class="container-fluid">
    <h1><i class="fas fa-broadcast-tower"></i> Zigbee Devices</h1>

    <!-- Status Card -->
    <div class="row mb-4">
        <div class="col-md-12">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Controller Status</h5>
                    <p id="zigbee-status">
                        <span class="badge bg-secondary">Checking...</span>
                    </p>
                </div>
            </div>
        </div>
    </div>

    <!-- Devices List -->
    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Paired Devices</h5>
                    <div id="devices-list">
                        <p class="text-muted">Loading devices...</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
// Load Zigbee status
function loadStatus() {
    fetch('/zigbee/api/status')
        .then(r => r.json())
        .then(data => {
            const statusEl = document.getElementById('zigbee-status');
            if (data.connected) {
                statusEl.innerHTML = `
                    <span class="badge bg-success">Connected</span>
                    <span class="ms-2">${data.device_count} devices paired</span>
                `;
            } else {
                statusEl.innerHTML = `
                    <span class="badge bg-danger">Disconnected</span>
                    <span class="ms-2">${data.error || 'Not connected'}</span>
                `;
            }
        });
}

// Load devices list
function loadDevices() {
    fetch('/zigbee/api/devices')
        .then(r => r.json())
        .then(data => {
            const listEl = document.getElementById('devices-list');
            if (data.devices && data.devices.length > 0) {
                listEl.innerHTML = data.devices.map(device => `
                    <div class="card mb-2">
                        <div class="card-body">
                            <h6>${device.name}</h6>
                            <pre class="mb-0">${JSON.stringify(device.state, null, 2)}</pre>
                            <button class="btn btn-sm btn-warning mt-2" onclick="testDevice('${device.name}')">
                                <i class="fas fa-bolt"></i> Test Device
                            </button>
                        </div>
                    </div>
                `).join('');
            } else {
                listEl.innerHTML = '<p class="text-muted">No devices paired yet.</p>';
            }
        });
}

// Test device
function testDevice(deviceName) {
    if (!confirm(`Test device "${deviceName}"?`)) return;

    fetch(`/zigbee/api/devices/${deviceName}/trigger`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: 'siren',  // or detect from device state
            duration: 3,
            mode: 'emergency',
        }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            alert('Device triggered successfully');
        } else {
            alert('Failed to trigger device: ' + (data.error || 'Unknown error'));
        }
    });
}

// Load data on page load
loadStatus();
loadDevices();

// Refresh every 5 seconds
setInterval(() => {
    loadStatus();
    loadDevices();
}, 5000);
</script>
{% endblock %}
```

**Status Check:** ✅ Web UI for Zigbee device management complete

---

## Phase 7: Testing and Validation (2-3 days)

### Test Checklist

- [ ] **Basic Connectivity**
  - [ ] Zigbee2MQTT connects to coordinator
  - [ ] MQTT broker accessible
  - [ ] Web UI loads at :8080

- [ ] **Device Pairing**
  - [ ] Can pair siren successfully
  - [ ] Can pair smart bulb successfully
  - [ ] Can pair smart plug successfully
  - [ ] Devices appear in Zigbee2MQTT UI

- [ ] **Manual Control**
  - [ ] Can trigger siren via MQTT command
  - [ ] Can control lights via MQTT command
  - [ ] Can control plugs via MQTT command
  - [ ] EAS Station web UI shows devices

- [ ] **Alert Integration**
  - [ ] Receive test alert (RWT)
  - [ ] Verify sirens activate
  - [ ] Verify lights flash correct color
  - [ ] Check alert processing logs
  - [ ] Verify devices turn off after duration

- [ ] **Range Testing**
  - [ ] Test devices at various distances
  - [ ] Identify coverage dead zones
  - [ ] Add repeaters if needed
  - [ ] Document final coverage map

- [ ] **Error Handling**
  - [ ] Disconnect MQTT broker → verify graceful degradation
  - [ ] Unplug Zigbee device → verify offline detection
  - [ ] Send invalid command → verify error logging

---

## Phase 8: Production Deployment (3-5 days)

### Deployment Checklist

- [ ] **Device Installation**
  - [ ] Mount exterior sirens at strategic locations
  - [ ] Install smart bulbs in key areas (hallways, offices)
  - [ ] Deploy smart plugs for critical equipment
  - [ ] Test all devices at installed locations

- [ ] **Configuration**
  - [ ] Disable "permit_join" in Zigbee2MQTT (security)
  - [ ] Configure device → alert mappings
  - [ ] Set up device groups for bulk control
  - [ ] Document device locations and names

- [ ] **Monitoring**
  - [ ] Add Zigbee status to health checks
  - [ ] Set up alerts for offline devices
  - [ ] Monitor MQTT broker health
  - [ ] Log device activation history

- [ ] **Documentation**
  - [ ] Create device inventory spreadsheet
  - [ ] Document alert → device mapping
  - [ ] Write troubleshooting guide
  - [ ] Train operators on manual controls

- [ ] **Backup and Recovery**
  - [ ] Backup Zigbee2MQTT configuration
  - [ ] Backup MQTT broker config
  - [ ] Document recovery procedures
  - [ ] Test restoration process

---

## Troubleshooting

### Common Issues

**Issue: Serial port not found**
- Check `/dev/ttyAMA0` exists
- Verify UART enabled in `raspi-config`
- Check Zigbee module properly seated in case

**Issue: Devices won't pair**
- Verify "permit_join" is enabled
- Check device is in pairing mode (LED flashing)
- Try resetting device and retry
- Check Zigbee channel not congested (try channel 25)

**Issue: Poor range or dropped messages**
- Verify antenna connected properly
- Change Zigbee channel to avoid WiFi interference
- Add AC-powered devices as repeaters
- Check for physical obstructions (metal, concrete)

**Issue: Commands not working**
- Verify MQTT broker running (`docker ps`)
- Check Zigbee2MQTT logs (`docker logs eas-zigbee2mqtt`)
- Test MQTT with `mosquitto_pub/sub`
- Verify device is online in Zigbee2MQTT UI

---

## Next Steps

After completing this implementation, consider:

1. **Home Assistant Integration**
   - Connect Zigbee2MQTT to Home Assistant
   - Create advanced automation scenes
   - Add voice control via Alexa/Google

2. **Additional Devices**
   - Environmental sensors (temperature, humidity)
   - Water leak detectors (near equipment)
   - Door/window sensors (facility monitoring)
   - Motion sensors (security)

3. **Advanced Features**
   - Device groups for bulk control
   - Scenes for different alert types
   - Scheduling (automatic tests)
   - Integration with external systems

4. **Cellular Backup**
   - Add cellular HAT for internet redundancy
   - Complete bulletproof emergency alerting system
   - See [CELLULAR_HAT_EVALUATION.md](CELLULAR_HAT_EVALUATION.md)

---

## Support and Resources

- **Zigbee2MQTT Docs:** https://www.zigbee2mqtt.io/
- **Supported Devices:** https://www.zigbee2mqtt.io/supported-devices/
- **MQTT Protocol:** https://mqtt.org/
- **EAS Station Issues:** https://github.com/KR8MER/eas-station/issues

---

**Document Status:** Implementation Ready
**Last Updated:** 2025-11-20
**Maintainer:** Claude (AI Assistant)
