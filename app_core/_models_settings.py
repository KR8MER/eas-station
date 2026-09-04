"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

from __future__ import annotations

"""Configuration / settings models (location, hardware, TTS, EAS, etc.)."""

from ._models_base import (
    Any,
    DEFAULT_LOCATION_SETTINGS,
    Dict,
    JSONB,
    datetime,
    db,
    utc_now,
)
from .crypto import EncryptedString


class LocationSettings(db.Model):
    __tablename__ = "location_settings"

    id = db.Column(db.Integer, primary_key=True)
    county_name = db.Column(
        db.String(255),
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["county_name"],
    )
    state_code = db.Column(
        db.String(2),
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["state_code"],
    )
    timezone = db.Column(
        db.String(64),
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["timezone"],
    )
    map_center_lat = db.Column(
        db.Float,
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["map_center_lat"],
    )
    map_center_lng = db.Column(
        db.Float,
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["map_center_lng"],
    )
    map_default_zoom = db.Column(
        db.Integer,
        nullable=False,
        default=DEFAULT_LOCATION_SETTINGS["map_default_zoom"],
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "county_name": self.county_name,
            "state_code": self.state_code,
            "timezone": self.timezone,
            "map_center_lat": self.map_center_lat,
            "map_center_lng": self.map_center_lng,
            "map_default_zoom": self.map_default_zoom,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AlertFilterSettings(db.Model):
    __tablename__ = "alert_filter_settings"

    id = db.Column(db.Integer, primary_key=True)
    fips_codes = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["fips_codes"]),
    )
    zone_codes = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["zone_codes"]),
    )
    storage_zone_codes = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["storage_zone_codes"]),
    )
    area_terms = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["area_terms"]),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "fips_codes": list(self.fips_codes or []),
            "zone_codes": list(self.zone_codes or []),
            "storage_zone_codes": list(self.storage_zone_codes or []),
            "area_terms": list(self.area_terms or []),
            "same_codes": list(self.fips_codes or []),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HardwareSettings(db.Model):
    """Unified hardware settings stored in database.

    Replaces environment variables for peripheral hardware configuration.
    All hardware settings are stored in a single row (id=1).
    """
    __tablename__ = "hardware_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # GPIO Settings
    # ========================================================================
    gpio_enabled = db.Column(db.Boolean, nullable=False, default=False)
    gpio_pin_map = db.Column(JSONB, nullable=False, default=dict)
    gpio_behavior_matrix = db.Column(JSONB, nullable=False, default=dict)

    # ========================================================================
    # USB Tower Light Settings (Adafruit #5125 / ANDONT 7-colour stack light)
    # ========================================================================
    tower_light_enabled = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_serial_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB0')
    tower_light_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    # 'adafruit' = #5125 three-segment single-byte protocol;
    # 'andont' = 7-colour FF..AA framed protocol (one colour at a time)
    tower_light_protocol = db.Column(db.String(20), nullable=False, default='adafruit')
    tower_light_alert_buzzer = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_incoming_uses_yellow = db.Column(db.Boolean, nullable=False, default=True)
    tower_light_blink_on_alert = db.Column(db.Boolean, nullable=False, default=True)
    # State -> colour mapping. Adafruit supports red/yellow/green only;
    # ANDONT adds blue/cyan/magenta/white.
    tower_light_standby_color = db.Column(db.String(20), nullable=False, default='green')
    tower_light_incoming_color = db.Column(db.String(20), nullable=False, default='yellow')
    tower_light_alert_color = db.Column(db.String(20), nullable=False, default='red')
    # Master kill switch — the buzzer never sounds in any state when set
    tower_light_buzzer_disabled = db.Column(db.Boolean, nullable=False, default=False)
    # Extra states: test broadcasts (RWT/RMT/NPT/DMO) and system fault
    tower_light_test_color = db.Column(db.String(20), nullable=False, default='cyan')
    tower_light_fault_enabled = db.Column(db.Boolean, nullable=False, default=True)
    tower_light_fault_color = db.Column(db.String(20), nullable=False, default='magenta')
    # Pending Alerts: alerts held in the gated-alerts review queue
    tower_light_gate_pending_enabled = db.Column(db.Boolean, nullable=False, default=True)
    tower_light_gate_pending_color = db.Column(db.String(20), nullable=False, default='blue')
    # Severity-based alert colours (replace the single alert colour when enabled)
    tower_light_severity_colors = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_warning_color = db.Column(db.String(20), nullable=False, default='red')
    tower_light_watch_color = db.Column(db.String(20), nullable=False, default='yellow')
    tower_light_advisory_color = db.Column(db.String(20), nullable=False, default='white')
    # Quiet hours: standby light off on a schedule (alerts still show)
    tower_light_quiet_enabled = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_quiet_start = db.Column(db.String(5), nullable=False, default='22:00')
    tower_light_quiet_end = db.Column(db.String(5), nullable=False, default='07:00')

    # ========================================================================
    # Dead-air (silence) monitoring -- output half only
    # ------------------------------------------------------------------
    # Drives the tower light plus an optional rack alarm buzzer when any
    # monitored source is silent. The *detection* half (whether a given
    # source alarms on silence, and at what threshold) is per-source
    # config now, not here -- see AudioSourceConfigDB.config_params's
    # dead_air_* keys and app_core/audio/silence.py for why a level
    # threshold alone cannot detect an SDR whose station has gone off the
    # air (the receiver then emits full-scale hiss, which any level test
    # reads as "audio present"). This stays station-wide because there is
    # one tower light and one buzzer, not one per source.
    # ========================================================================
    # Rack alarm buzzer on a GPIO pin. Level-triggered for as long as the
    # condition holds (not the edge/watchdog path the alert relays use),
    # and silenced by an operator acknowledgement that leaves the tower
    # light lit until audio actually returns.
    dead_air_buzzer_enabled = db.Column(db.Boolean, nullable=False, default=False)
    dead_air_buzzer_gpio_pin = db.Column(db.Integer, nullable=True)
    # Tower-light indication for dead air.
    tower_light_silence_enabled = db.Column(db.Boolean, nullable=False, default=True)
    tower_light_silence_color = db.Column(db.String(20), nullable=False, default='magenta')
    tower_light_silence_buzzer = db.Column(db.Boolean, nullable=False, default=False)

    # ========================================================================
    # NeoPixel / WS2812B Addressable LED Strip Settings
    # ========================================================================
    neopixel_enabled = db.Column(db.Boolean, nullable=False, default=False)
    neopixel_gpio_pin = db.Column(db.Integer, nullable=False, default=18)
    neopixel_num_pixels = db.Column(db.Integer, nullable=False, default=1)
    neopixel_brightness = db.Column(db.Integer, nullable=False, default=128)   # 0-255
    neopixel_led_order = db.Column(db.String(10), nullable=False, default='GRB')
    neopixel_standby_color = db.Column(JSONB, nullable=False, default=lambda: {"r": 0, "g": 10, "b": 0})
    neopixel_alert_color = db.Column(JSONB, nullable=False, default=lambda: {"r": 255, "g": 0, "b": 0})
    neopixel_flash_on_alert = db.Column(db.Boolean, nullable=False, default=True)
    neopixel_flash_interval_ms = db.Column(db.Integer, nullable=False, default=500)

    # ========================================================================
    # OLED Display Settings (Argon Industria SSD1306)
    # ========================================================================
    oled_enabled = db.Column(db.Boolean, nullable=False, default=False)
    oled_i2c_bus = db.Column(db.Integer, nullable=False, default=1)
    oled_i2c_address = db.Column(db.Integer, nullable=False, default=0x3C)
    oled_width = db.Column(db.Integer, nullable=False, default=128)
    oled_height = db.Column(db.Integer, nullable=False, default=64)
    oled_rotate = db.Column(db.Integer, nullable=False, default=0)
    oled_contrast = db.Column(db.Integer, nullable=True)
    oled_font_path = db.Column(db.String(255), nullable=True)
    oled_default_invert = db.Column(db.Boolean, nullable=False, default=False)
    oled_button_gpio = db.Column(db.Integer, nullable=False, default=4)
    oled_button_hold_seconds = db.Column(db.Float, nullable=False, default=1.25)
    oled_button_active_high = db.Column(db.Boolean, nullable=False, default=False)
    oled_scroll_effect = db.Column(db.String(50), nullable=False, default='scroll_left')
    oled_scroll_speed = db.Column(db.Integer, nullable=False, default=4)
    oled_scroll_fps = db.Column(db.Integer, nullable=False, default=30)
    screens_auto_start = db.Column(db.Boolean, nullable=False, default=True)

    # ========================================================================
    # LED Sign Settings (BetaBrite/Alpha)
    # ========================================================================
    led_enabled = db.Column(db.Boolean, nullable=False, default=False)
    led_connection_type = db.Column(db.String(20), nullable=False, default='network')  # 'network' or 'serial'
    led_ip_address = db.Column(db.String(50), nullable=False, default='192.168.1.100')
    led_port = db.Column(db.Integer, nullable=False, default=10001)
    led_serial_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB1')
    led_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    led_serial_mode = db.Column(db.String(20), nullable=False, default='RS232')
    led_default_text = db.Column(db.Text, nullable=True)
    led_default_lines = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["led_default_lines"]),
    )

    # ========================================================================
    # VFD Display Settings (Noritake GU140x32F-7000B)
    # ========================================================================
    vfd_enabled = db.Column(db.Boolean, nullable=False, default=False)
    vfd_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB0')
    vfd_baudrate = db.Column(db.Integer, nullable=False, default=38400)

    # ========================================================================
    # Zigbee Coordinator Settings
    # ========================================================================
    zigbee_enabled = db.Column(db.Boolean, nullable=False, default=False)
    zigbee_port = db.Column(db.String(100), nullable=False, default='/dev/ttyAMA0')
    zigbee_baudrate = db.Column(db.Integer, nullable=False, default=115200)
    zigbee_channel = db.Column(db.Integer, nullable=False, default=15)
    zigbee_pan_id = db.Column(db.String(20), nullable=False, default='0x1A62')

    # ========================================================================
    # GPS / Time Source Settings
    # Default profile: Uputronics Raspberry Pi GPS/RTC Expansion Board
    # (u-blox MAX-M8Q multi-GNSS, PPS on BCM 18, DS3231 battery-backed RTC,
    # low-profile stacking header — coexists with I²C OLED on BCM 2/3 and
    # allows the Pi case to close).
    # The Adafruit Ultimate GPS HAT (#2324, PPS on BCM 4) is also supported;
    # set gps_pps_gpio_pin to 4 in that case.
    # ========================================================================
    gps_enabled = db.Column(db.Boolean, nullable=False, default=False)
    gps_serial_port = db.Column(db.String(100), nullable=False, default='/dev/serial0')
    gps_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    gps_pps_gpio_pin = db.Column(db.Integer, nullable=False, default=18)
    gps_use_for_location = db.Column(db.Boolean, nullable=False, default=False)
    gps_use_for_time = db.Column(db.Boolean, nullable=False, default=False)
    gps_min_satellites = db.Column(db.Integer, nullable=False, default=4)
    # Where the GPS Manager should get NMEA from. One of:
    #   "auto"   — prefer gpsd at gps_gpsd_host:gps_gpsd_port; fall back to
    #              opening gps_serial_port directly when gpsd isn't reachable.
    #              Default for new installs.
    #   "serial" — open gps_serial_port directly (the legacy behaviour).
    #              Required if you don't run gpsd, or if gpsd would conflict
    #              with another tool that needs the serial port.
    #   "gpsd"   — only use gpsd; refuse to start if it's not reachable.
    #              Useful when chrony also needs the GPS for stratum-1 PPS.
    gps_source = db.Column(db.String(16), nullable=False, default='auto')
    gps_gpsd_host = db.Column(db.String(100), nullable=False, default='127.0.0.1')
    gps_gpsd_port = db.Column(db.Integer, nullable=False, default=2947)

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            "id": self.id,
            # GPIO
            "gpio_enabled": self.gpio_enabled,
            "gpio_pin_map": self.gpio_pin_map or {},
            "gpio_behavior_matrix": self.gpio_behavior_matrix or {},
            # Tower Light
            "tower_light_enabled": self.tower_light_enabled,
            "tower_light_serial_port": self.tower_light_serial_port,
            "tower_light_baudrate": self.tower_light_baudrate,
            "tower_light_protocol": self.tower_light_protocol,
            "tower_light_alert_buzzer": self.tower_light_alert_buzzer,
            "tower_light_incoming_uses_yellow": self.tower_light_incoming_uses_yellow,
            "tower_light_blink_on_alert": self.tower_light_blink_on_alert,
            "tower_light_standby_color": self.tower_light_standby_color,
            "tower_light_incoming_color": self.tower_light_incoming_color,
            "tower_light_alert_color": self.tower_light_alert_color,
            "tower_light_buzzer_disabled": self.tower_light_buzzer_disabled,
            "tower_light_test_color": self.tower_light_test_color,
            "tower_light_fault_enabled": self.tower_light_fault_enabled,
            "tower_light_fault_color": self.tower_light_fault_color,
            "tower_light_gate_pending_enabled": self.tower_light_gate_pending_enabled,
            "tower_light_gate_pending_color": self.tower_light_gate_pending_color,
            "tower_light_severity_colors": self.tower_light_severity_colors,
            "tower_light_warning_color": self.tower_light_warning_color,
            "tower_light_watch_color": self.tower_light_watch_color,
            "tower_light_advisory_color": self.tower_light_advisory_color,
            "tower_light_quiet_enabled": self.tower_light_quiet_enabled,
            "tower_light_quiet_start": self.tower_light_quiet_start,
            "tower_light_quiet_end": self.tower_light_quiet_end,
            # NeoPixel
            "neopixel_enabled": self.neopixel_enabled,
            "neopixel_gpio_pin": self.neopixel_gpio_pin,
            "neopixel_num_pixels": self.neopixel_num_pixels,
            "neopixel_brightness": self.neopixel_brightness,
            "neopixel_led_order": self.neopixel_led_order,
            "neopixel_standby_color": self.neopixel_standby_color or {"r": 0, "g": 10, "b": 0},
            "neopixel_alert_color": self.neopixel_alert_color or {"r": 255, "g": 0, "b": 0},
            "neopixel_flash_on_alert": self.neopixel_flash_on_alert,
            "neopixel_flash_interval_ms": self.neopixel_flash_interval_ms,
            # OLED
            "oled_enabled": self.oled_enabled,
            "oled_i2c_bus": self.oled_i2c_bus,
            "oled_i2c_address": self.oled_i2c_address,
            "oled_width": self.oled_width,
            "oled_height": self.oled_height,
            "oled_rotate": self.oled_rotate,
            "oled_contrast": self.oled_contrast,
            "oled_font_path": self.oled_font_path,
            "oled_default_invert": self.oled_default_invert,
            "oled_button_gpio": self.oled_button_gpio,
            "oled_button_hold_seconds": self.oled_button_hold_seconds,
            "oled_button_active_high": self.oled_button_active_high,
            "oled_scroll_effect": self.oled_scroll_effect,
            "oled_scroll_speed": self.oled_scroll_speed,
            "oled_scroll_fps": self.oled_scroll_fps,
            "screens_auto_start": self.screens_auto_start,
            # LED
            "led_enabled": self.led_enabled,
            "led_connection_type": self.led_connection_type,
            "led_ip_address": self.led_ip_address,
            "led_port": self.led_port,
            "led_serial_port": self.led_serial_port,
            "led_baudrate": self.led_baudrate,
            "led_serial_mode": self.led_serial_mode,
            "led_default_text": self.led_default_text,
            "led_default_lines": list(self.led_default_lines or []),
            # VFD
            "vfd_enabled": self.vfd_enabled,
            "vfd_port": self.vfd_port,
            "vfd_baudrate": self.vfd_baudrate,
            # Zigbee
            "zigbee_enabled": self.zigbee_enabled,
            "zigbee_port": self.zigbee_port,
            "zigbee_baudrate": self.zigbee_baudrate,
            "zigbee_channel": self.zigbee_channel,
            "zigbee_pan_id": self.zigbee_pan_id,
            # GPS HAT (Uputronics GPS/RTC default; Adafruit #2324 also supported)
            "gps_enabled": self.gps_enabled,
            "gps_serial_port": self.gps_serial_port,
            "gps_baudrate": self.gps_baudrate,
            "gps_pps_gpio_pin": self.gps_pps_gpio_pin,
            "gps_use_for_location": self.gps_use_for_location,
            "gps_use_for_time": self.gps_use_for_time,
            "gps_min_satellites": self.gps_min_satellites,
            "gps_source": self.gps_source,
            "gps_gpsd_host": self.gps_gpsd_host,
            "gps_gpsd_port": self.gps_gpsd_port,
            # Metadata
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IcecastSettings(db.Model):
    """Icecast streaming server configuration stored in database.

    Replaces environment variables for Icecast configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "icecast_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Connection Settings
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    server = db.Column(db.String(255), nullable=False, default='localhost')
    port = db.Column(db.Integer, nullable=False, default=8000)
    external_port = db.Column(db.Integer, nullable=True)  # For browser access (optional)
    public_hostname = db.Column(db.String(255), nullable=True)  # Public hostname/IP

    # Authentication
    source_password = db.Column(EncryptedString, nullable=False, default='')
    admin_user = db.Column(db.String(255), nullable=True)
    admin_password = db.Column(EncryptedString, nullable=True)

    # Stream Settings
    default_mount = db.Column(db.String(255), nullable=False, default='monitor.mp3')
    stream_name = db.Column(db.String(255), nullable=False, default='EAS Station Audio')
    stream_description = db.Column(db.String(500), nullable=False, default='Emergency Alert System Audio Monitor')
    stream_genre = db.Column(db.String(100), nullable=False, default='Emergency')
    stream_bitrate = db.Column(db.Integer, nullable=False, default=128)
    stream_format = db.Column(db.String(10), nullable=False, default='mp3')  # mp3 or ogg
    stream_public = db.Column(db.Boolean, nullable=False, default=False)  # List in directory

    # Server Info (for Icecast XML config)
    server_hostname = db.Column(db.String(255), nullable=True)  # Server hostname for Icecast config
    server_location = db.Column(db.String(255), nullable=True)  # Server location
    admin_contact = db.Column(db.String(255), nullable=True)  # Admin contact email
    
    # Server Limits
    max_sources = db.Column(db.Integer, nullable=True)  # Max concurrent sources (None/0 = unlimited, default: 2)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "server": self.server,
            "port": self.port,
            "external_port": self.external_port,
            "public_hostname": self.public_hostname,
            "source_password": self.source_password,
            "admin_user": self.admin_user,
            "admin_password": self.admin_password,
            "default_mount": self.default_mount,
            "stream_name": self.stream_name,
            "stream_description": self.stream_description,
            "stream_genre": self.stream_genre,
            "stream_bitrate": self.stream_bitrate,
            "stream_format": self.stream_format,
            "stream_public": self.stream_public,
            "server_hostname": self.server_hostname,
            "server_location": self.server_location,
            "admin_contact": self.admin_contact,
            "max_sources": self.max_sources,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CertbotSettings(db.Model):
    """Certbot/Let's Encrypt SSL certificate configuration stored in database.

    Replaces environment variables for Certbot configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "certbot_settings"

    id = db.Column(db.Integer, primary_key=True)

    # General Settings
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    domain_name = db.Column(db.String(255), nullable=False, default='')
    email = db.Column(db.String(255), nullable=False, default='')

    # Certificate Settings
    staging = db.Column(db.Boolean, nullable=False, default=False)  # Use Let's Encrypt staging server
    auto_renew_enabled = db.Column(db.Boolean, nullable=False, default=True)
    renew_days_before_expiry = db.Column(db.Integer, nullable=False, default=30)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "domain_name": self.domain_name,
            "email": self.email,
            "staging": self.staging,
            "auto_renew_enabled": self.auto_renew_enabled,
            "renew_days_before_expiry": self.renew_days_before_expiry,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Fail2banSettings(db.Model):
    """fail2ban firewall-enforcement configuration stored in the database.

    EAS Station's application-level ban list (the ``ip_filters`` table, managed
    on the Security Center "Banned IPs" tab) is the single source of truth for
    who is banned. fail2ban is used purely as an optional *firewall actuator*:
    when enabled, every app-level ban/unban is mirrored to a dedicated
    ``eas-station`` fail2ban jail (``bantime = -1``) so the attacker is also
    dropped at the host firewall, before traffic ever reaches the web process.
    fail2ban does NOT independently scan the web log here — the application
    already detects malicious / brute-force / flood activity — so there is only
    one ban list to maintain.

    The optional ``sshd`` jail is the one exception: it protects the host SSH
    daemon (which the application cannot see) and is therefore managed entirely
    by fail2ban, separate from the web ban list.

    All settings are stored in a single row (id=1).
    """
    __tablename__ = "fail2ban_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Mirror application-level bans to the host firewall via fail2ban
    enabled = db.Column(db.Boolean, nullable=False, default=False)

    # Optional sshd jail to protect the host's SSH daemon (separate concern —
    # SSH bans are not part of the web application ban list)
    protect_ssh = db.Column(db.Boolean, nullable=False, default=False)
    ssh_maxretry = db.Column(db.Integer, nullable=False, default=5)
    ssh_bantime = db.Column(db.Integer, nullable=False, default=3600)   # seconds

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "protect_ssh": self.protect_ssh,
            "ssh_maxretry": self.ssh_maxretry,
            "ssh_bantime": self.ssh_bantime,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TTSSettings(db.Model):
    """Text-to-Speech configuration stored in database.

    Replaces environment variables for TTS configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "tts_settings"

    id = db.Column(db.Integer, primary_key=True)

    # General Settings
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    provider = db.Column(db.String(50), nullable=False, default='')  # '', 'azure_openai', 'azure', 'pyttsx3'

    # Azure OpenAI Settings
    azure_openai_endpoint = db.Column(db.String(500), nullable=True)
    azure_openai_key = db.Column(EncryptedString, nullable=True)
    azure_openai_model = db.Column(db.String(100), nullable=False, default='tts-1')
    azure_openai_voice = db.Column(db.String(50), nullable=False, default='alloy')
    azure_openai_speed = db.Column(db.Float, nullable=False, default=1.0)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary.

        azure_openai_key is a secret and must never reach the browser in
        plaintext (this dict feeds both the /api/tts/settings JSON response
        and, indirectly, page templates) - only a masked placeholder and a
        has-value flag are exposed. Callers that need the real key (the TTS
        engine itself) must read the `azure_openai_key` column directly.
        """
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "azure_openai_endpoint": self.azure_openai_endpoint,
            "azure_openai_key": "••••••••" if self.azure_openai_key else "",
            "azure_openai_key_set": bool(self.azure_openai_key),
            "azure_openai_model": self.azure_openai_model,
            "azure_openai_voice": self.azure_openai_voice,
            "azure_openai_speed": self.azure_openai_speed,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MapTileSettings(db.Model):
    """Basemap tile provider for the alert share-card map inset.

    Replaces environment variables for this configuration. All settings
    are stored in a single row (id=1). Defaults to plain OpenStreetMap
    raster tiles ('osm') so every install works with zero configuration;
    switching to 'carto_dark' requires a free CARTO API key (see
    https://carto.com/basemaps/apikey) and produces a noticeably cleaner
    card, since CARTO's Dark Matter style is authored as dark and minimal
    from the start rather than a light OSM tile darkened in post
    (see app_utils/image_export/map_style.py's tone_basemap()).
    """
    __tablename__ = "map_tile_settings"

    id = db.Column(db.Integer, primary_key=True)

    provider = db.Column(db.String(50), nullable=False, default='osm')  # 'osm', 'carto_dark'
    carto_api_key = db.Column(EncryptedString, nullable=True)

    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary.

        carto_api_key is a secret and must never reach the browser in
        plaintext -- only a masked placeholder and a has-value flag are
        exposed. Callers that need the real key (the tile fetcher itself)
        must read the `carto_api_key` column directly.
        """
        return {
            "provider": self.provider,
            "carto_api_key": "••••••••" if self.carto_api_key else "",
            "carto_api_key_set": bool(self.carto_api_key),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TTSPronunciationRule(db.Model):
    """User-configurable pronunciation overrides for the TTS narration pipeline.

    Many place names in Ohio (and elsewhere) are pronounced differently from
    their spelling would suggest to a generic TTS engine.  Each row maps an
    ``original_text`` pattern to a ``replacement_text`` that the engine will
    read phonetically correctly.

    Examples shipped as built-in defaults:
      Lima   → Lye-mah  (not LEE-mah)
      Cairo  → Kay-roh  (not KY-roh)
      Delphos → Del-fus

    Rules are applied with whole-word matching (regex ``\\b`` boundaries).
    Case-insensitive matching is used when ``match_case`` is False (default).
    """
    __tablename__ = "tts_pronunciation_rules"

    id = db.Column(db.Integer, primary_key=True)

    # The word or phrase to replace (matched with word-boundary anchors).
    original_text = db.Column(db.String(255), nullable=False)

    # The phonetic spelling that the TTS engine will read correctly.
    replacement_text = db.Column(db.String(255), nullable=False)

    # When True the replacement is skipped.
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    # When True the match is case-sensitive; False (default) ignores case.
    match_case = db.Column(db.Boolean, nullable=False, default=False)

    # Built-in entries are seeded automatically and shown with a visual badge.
    # Users may disable or edit them but cannot delete them via the UI.
    is_builtin = db.Column(db.Boolean, nullable=False, default=False)

    # Free-text note shown in the UI (e.g., "Lima, OH — county seat of Allen Co.")
    note = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "original_text": self.original_text,
            "replacement_text": self.replacement_text,
            "enabled": self.enabled,
            "match_case": self.match_case,
            "is_builtin": self.is_builtin,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Default pronunciation rules seeded on first startup.
# Each tuple is (original_text, replacement_text, note).
# These are Ohio place names that every TTS engine mispronounces out of the box.
# ---------------------------------------------------------------------------
TTS_BUILTIN_PRONUNCIATIONS = [
    ("Lima",    "Lye-mah",  "Lima, OH — county seat of Allen County (NOT like Lima, Peru)"),
    ("Cairo",   "Kay-roh",  "Cairo, OH — village in Allen County (NOT like Cairo, Egypt)"),
    ("Delphos", "Del-fus",  "Delphos, OH — city in Allen and Van Wert counties"),
    ("Versailles", "Ver-sales", "Versailles, OH — village in Darke County (NOT like Versailles, France)"),
    ("Russia",  "Roo-sha",  "Russia, OH — village in Shelby County"),
    ("Milan",   "My-lan",   "Milan, OH — village in Erie County (birthplace of Edison; NOT like Milan, Italy)"),
    ("Bellefontaine", "Bell-fountain", "Bellefontaine, OH — county seat of Logan County"),
    ("Piqua",   "Pik-way",  "Piqua, OH — city in Miami County"),
    ("Tiffin",  "Tif-in",   "Tiffin, OH — county seat of Seneca County"),
    ("Wapakoneta", "Wop-uh-kuh-nee-tuh", "Wapakoneta, OH — county seat of Auglaize County"),
]


class EASDecoderMonitorSettings(db.Model):
    """EAS Decoder Monitor Settings - configurable tap to listen to decoder input.
    
    Allows listening to the actual 16 kHz resampled audio fed to the EAS decoder
    to verify sample rate and audio quality.
    """
    __tablename__ = "eas_decoder_monitor_settings"

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    stream_name = db.Column(db.String(255), nullable=False, default="eas-decoder-monitor")
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "stream_name": self.stream_name,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EASSettings(db.Model):
    """EAS Broadcast configuration stored in database.

    Replaces environment variables for EAS encoder/broadcast configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "eas_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # EAS Broadcast Enable/Disable
    # ========================================================================
    broadcast_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for EAS broadcast functionality

    # ========================================================================
    # Station Identity
    # ========================================================================
    originator = db.Column(db.String(8), nullable=False, default='WXR')
    # Originator code: WXR (Weather Radio), EAS, PEP, CIV

    station_id = db.Column(db.String(8), nullable=False, default='EASNODES')
    # 8-character SAME callsign identifier

    # ========================================================================
    # Audio Generation Settings
    # ========================================================================
    output_dir = db.Column(db.String(255), nullable=False, default='static/eas_messages')
    # Directory for generated EAS audio files

    attention_tone_seconds = db.Column(db.Integer, nullable=False, default=8)
    # Duration of the attention tone in seconds (1-25)

    max_activation_seconds = db.Column(db.Integer, nullable=False, default=300)
    # Hard limit for total EAS activation duration in seconds (DASDEC-style cap).
    # After this duration the EOM is forced and playback stops. Default: 300.

    sample_rate = db.Column(db.Integer, nullable=False, default=16000)
    # Audio sample rate for GENERATED EAS alerts: 8000, 16000, 22050, 44100, 48000
    # NOTE: 16kHz is optimal for EAS - lower CPU overhead, adequate quality for SAME tones/voice

    audio_player = db.Column(db.String(255), nullable=False, default='aplay')
    # Command to play audio (aplay, paplay, etc.)

    endec_fingerprint = db.Column(db.Boolean, nullable=False, default=True)
    # Append 3 × 0xA9 trill bytes after each SAME burst to fingerprint this station

    # ========================================================================
    # Pre/Post-Alert Signals (system-level pre/post-broadcast signals)
    # ========================================================================
    pre_alert_chime = db.Column(db.String(16), nullable=False, default='none')
    # Chime sound played BEFORE the SAME header.
    # Allowed values: 'none', 'bell', 'beep', 'three_tone', 'qc2', 'dtmf'.

    post_alert_chime = db.Column(db.String(16), nullable=False, default='none')
    # Chime sound played AFTER the EOM sequence.
    # Allowed values: 'none', 'bell', 'beep', 'three_tone', 'qc2', 'dtmf'.

    pre_alert_chime_duration = db.Column(db.Float, nullable=False, default=2.0)
    # Duration in seconds for the pre-alert chime (0.1–10.0). Applies only
    # to free-form profiles (bell, beep, three_tone). Ignored for DTMF
    # (fixed 100 ms tone / 50 ms gap per digit) and QC-II (fixed 1 s + 3 s).

    post_alert_chime_duration = db.Column(db.Float, nullable=False, default=2.0)
    # Duration in seconds for the post-alert chime (0.1–10.0). See note above.

    qc2_tone_a_freq = db.Column(db.Float, nullable=False, default=1000.0)
    # QC-II Tone A frequency in Hz (typical range 288–3000 Hz).

    qc2_tone_b_freq = db.Column(db.Float, nullable=False, default=1500.0)
    # QC-II Tone B frequency in Hz (typical range 288–3000 Hz).

    qc2_long_tone_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # When True, a sustained tone at qc2_tone_b_freq is appended after the
    # standard QC-II A + B sequence.

    qc2_long_tone_seconds = db.Column(db.Float, nullable=False, default=10.0)
    # Duration in seconds for the optional QC-II long tone (1–120 s).
    # Ignored when qc2_long_tone_enabled is False.

    dtmf_sequence = db.Column(db.String(32), nullable=False, default='')
    # DTMF digit sequence to play when the chime profile is 'dtmf'.
    # Allowed characters: 0-9, A-D, *, #. Length 0–32.

    # ------------------------------------------------------------------
    # MDC1200 selective-calling settings (used when chime profile = 'mdc1200')
    # ------------------------------------------------------------------
    mdc1200_unit_id = db.Column(db.Integer, nullable=False, default=1)
    # 16-bit MDC1200 subscriber unit ID (1..65535).  This is the ID a
    # receiving Motorola radio displays as the "from" unit.

    mdc1200_op_code = db.Column(db.String(32), nullable=False, default='ptt_id_pre')
    # Symbolic preset name for the MDC1200 op-code/argument pair.
    # Recognised values: 'ptt_id_pre', 'ptt_id_post', 'emergency',
    # 'request_to_talk', 'remote_monitor', 'custom'.  When set to
    # 'custom', the raw fields below are used.

    mdc1200_op_code_raw = db.Column(db.SmallInteger, nullable=True)
    # Raw 8-bit op-code (0..255) used when mdc1200_op_code == 'custom'.
    # NULL means "use the symbolic preset".

    mdc1200_arg_raw = db.Column(db.SmallInteger, nullable=True)
    # Raw 8-bit argument byte (0..255) used when mdc1200_op_code == 'custom'.
    # NULL means "use the symbolic preset".

    mdc1200_target_unit_id = db.Column(db.Integer, nullable=True)
    # 16-bit MDC1200 *target* subscriber unit ID (1..65535) used by the
    # double-packet ops (Call Alert, Selective Call) to address a specific
    # receiver.  NULL or 0 forces single-packet emission, where
    # mdc1200_unit_id is the only ID on the wire.  For PTT-ID, Emergency,
    # Request-to-Talk, and Remote Monitor presets this column is ignored
    # because those op-codes are single-packet by design.

    # ========================================================================
    # Authorized Broadcast Areas
    # ========================================================================
    authorized_fips_codes = db.Column(JSONB, nullable=False, default=list)
    # FIPS codes authorized for manual EAS broadcasts

    authorized_event_codes = db.Column(JSONB, nullable=False, default=list)
    # Event codes authorized for manual broadcasts (RWT, RMT, etc.)

    forwarded_event_codes = db.Column(JSONB, nullable=False, default=list)
    # Event codes to auto-forward from CAP/OTA sources. Empty list = forward all.

    relay_narration_source = db.Column(db.String(16), nullable=False, default='auto')
    # Narration audio for relayed OTA alerts:
    #   'auto'     — use the captured off-air narration unless it is detected as
    #                gate-chopped/degraded, in which case synthesise local TTS
    #   'captured' — always relay the captured off-air narration (legacy)
    #   'tts'      — always synthesise local TTS narration
    # Degradation detection: app_utils/audio_quality.assess_narration_quality.

    # ========================================================================
    # Cross-Source Deduplication Windows
    # ========================================================================
    cross_source_dedup_minutes = db.Column(db.Integer, nullable=False, default=15)
    # Suppression window (minutes) for alerts matched by event code + full
    # FIPS set only (no usable SAME header — the CAP-only path). Was a
    # hardcoded constant (CROSS_SOURCE_DEDUP_WINDOW_MINUTES) in
    # app_core/audio/auto_forward.py; default 15 preserves prior behaviour.

    header_key_dedup_minutes = db.Column(db.Integer, nullable=False, default=1440)
    # Suppression window (minutes) for alerts matched by the callsign-
    # independent SAME-header key, which already encodes the issuer's
    # release time — an identical key is the same alert issuance
    # regardless of how far apart the copies arrive, so this can safely be
    # much longer than cross_source_dedup_minutes. Was a hardcoded
    # constant (HEADER_KEY_DEDUP_WINDOW_MINUTES); default 1440 (24h)
    # preserves prior behaviour.

    # ========================================================================
    # Audio Ingest Detection
    # ========================================================================
    min_log_confidence_percent = db.Column(db.Float, nullable=False, default=0.0)
    # Minimum decode confidence (0-100) required to store a received-audio
    # detection that has NO decoded event code (a partial/noise-triggered
    # SAME burst with an unresolved header). Detections that DO resolve to
    # a real event code are always stored regardless of confidence, since
    # those are genuine alerts -- this only trims log noise from
    # low-confidence non-decodes. 0 (default) stores everything, matching
    # prior behaviour.

    # ========================================================================
    # ENDEC Device Feeds (Sage-ENDEC-compatible serial/TCP output)
    # ========================================================================
    endec_feeds_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for the ENDEC device-feed TCP service.

    endec_feeds = db.Column(JSONB, nullable=False, default=list)
    # List of configured feeds. Each item is a dict:
    #   {"name": str, "format": str, "port": int, "enabled": bool}
    # where format is one of generic_cgen | news_feed | decoder | encoder.
    # See app_utils/endec_feeds.py and docs/reference/protocols/SAGE_ENDEC.md.

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "broadcast_enabled": self.broadcast_enabled,
            "originator": self.originator,
            "station_id": self.station_id,
            "output_dir": self.output_dir,
            "attention_tone_seconds": self.attention_tone_seconds,
            "max_activation_seconds": self.max_activation_seconds,
            "sample_rate": self.sample_rate,
            "audio_player": self.audio_player,
            "endec_fingerprint": self.endec_fingerprint,
            "pre_alert_chime": self.pre_alert_chime,
            "post_alert_chime": self.post_alert_chime,
            "pre_alert_chime_duration": float(self.pre_alert_chime_duration or 0.0),
            "post_alert_chime_duration": float(self.post_alert_chime_duration or 0.0),
            "qc2_tone_a_freq": float(self.qc2_tone_a_freq or 0.0),
            "qc2_tone_b_freq": float(self.qc2_tone_b_freq or 0.0),
            "qc2_long_tone_enabled": bool(self.qc2_long_tone_enabled),
            "qc2_long_tone_seconds": float(self.qc2_long_tone_seconds or 10.0),
            "dtmf_sequence": self.dtmf_sequence or '',
            "mdc1200_unit_id": int(self.mdc1200_unit_id or 1),
            "mdc1200_op_code": self.mdc1200_op_code or 'ptt_id_pre',
            "mdc1200_op_code_raw": (
                int(self.mdc1200_op_code_raw)
                if self.mdc1200_op_code_raw is not None else None
            ),
            "mdc1200_arg_raw": (
                int(self.mdc1200_arg_raw)
                if self.mdc1200_arg_raw is not None else None
            ),
            "mdc1200_target_unit_id": (
                int(self.mdc1200_target_unit_id)
                if self.mdc1200_target_unit_id is not None else None
            ),
            "authorized_fips_codes": list(self.authorized_fips_codes or []),
            "authorized_event_codes": list(self.authorized_event_codes or []),
            "forwarded_event_codes": list(self.forwarded_event_codes or []),
            "relay_narration_source": self.relay_narration_source or 'auto',
            "cross_source_dedup_minutes": int(self.cross_source_dedup_minutes or 15),
            "header_key_dedup_minutes": int(self.header_key_dedup_minutes or 1440),
            "min_log_confidence_percent": float(self.min_log_confidence_percent or 0.0),
            "endec_feeds_enabled": bool(self.endec_feeds_enabled),
            "endec_feeds": list(self.endec_feeds or []),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class NotificationSettings(db.Model):
    """Notification configuration stored in database.

    Replaces ENABLE_EMAIL_NOTIFICATIONS, ENABLE_SMS_NOTIFICATIONS, MAIL_URL,
    and COMPLIANCE_ALERT_EMAILS environment variables.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "notification_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # Email Notifications
    # ========================================================================
    email_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for email notifications

    smtp_host = db.Column(db.String(255), nullable=False, default='')
    # SMTP server hostname (e.g. smtp.gmail.com)

    smtp_port = db.Column(db.Integer, nullable=False, default=587)
    # SMTP server port (e.g. 587, 465, 25)

    smtp_username = db.Column(db.String(255), nullable=False, default='')
    # SMTP authentication username / login email

    smtp_password = db.Column(EncryptedString, nullable=False, default='')
    # SMTP authentication password

    smtp_security = db.Column(db.String(10), nullable=False, default='starttls')
    # Connection security: "none", "starttls", or "ssl"

    compliance_alert_emails = db.Column(JSONB, nullable=False, default=list)
    # List of email addresses for compliance/health alert notifications

    alert_emails = db.Column(JSONB, nullable=False, default=list)
    # List of email addresses for EAS alert notifications (separate from compliance emails)

    email_attach_audio = db.Column(db.Boolean, nullable=False, default=False)
    # Attach composite EAS audio file to alert notification emails

    email_html = db.Column(db.Boolean, nullable=False, default=True)
    # Send a styled HTML body (multipart/alternative) in addition to plain text

    email_include_map = db.Column(db.Boolean, nullable=False, default=True)
    # Render and embed a coverage-map image of the affected area in HTML emails

    email_audio_link = db.Column(db.Boolean, nullable=False, default=True)
    # Include a "listen / download" link to the broadcast audio (needs public_base_url)

    email_compress_audio = db.Column(db.Boolean, nullable=False, default=False)
    # Transcode the attached composite audio from WAV to MP3 to shrink the attachment

    public_base_url = db.Column(db.String(255), nullable=False, default='')
    # Externally reachable base URL of this station (e.g. https://eas.example.com),
    # used to build links in notifications. Empty disables link generation.

    # ========================================================================
    # SMS Notifications
    # ========================================================================
    sms_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for SMS notifications

    sms_provider = db.Column(db.String(50), nullable=False, default='twilio')
    # SMS gateway provider: 'twilio'

    sms_account_sid = db.Column(db.String(255), nullable=False, default='')
    # Twilio Account SID

    sms_auth_token = db.Column(EncryptedString, nullable=False, default='')
    # Twilio Auth Token

    sms_from_number = db.Column(db.String(50), nullable=False, default='')
    # Twilio sending phone number in E.164 format (e.g. +15555550100)

    sms_recipients = db.Column(JSONB, nullable=False, default=list)
    # List of destination phone numbers in E.164 format

    # ========================================================================
    # SNMP Trap Notifications
    # ========================================================================
    snmp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for SNMP trap notifications

    snmp_targets = db.Column(JSONB, nullable=False, default=list)
    # List of SNMP trap targets in "host:port" format (port defaults to 162)

    snmp_community = db.Column(EncryptedString, nullable=False, default='public')
    # SNMP community string for trap authentication

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "email_enabled": self.email_enabled,
            "smtp_host": self.smtp_host or "",
            "smtp_port": self.smtp_port or 587,
            "smtp_username": self.smtp_username or "",
            # smtp_password intentionally omitted from API responses
            "smtp_security": self.smtp_security or "starttls",
            "compliance_alert_emails": self.compliance_alert_emails or [],
            "alert_emails": self.alert_emails or [],
            "email_attach_audio": self.email_attach_audio,
            "email_html": self.email_html,
            "email_include_map": self.email_include_map,
            "email_audio_link": self.email_audio_link,
            "email_compress_audio": self.email_compress_audio,
            "public_base_url": self.public_base_url or "",
            "sms_enabled": self.sms_enabled,
            "sms_provider": self.sms_provider or "twilio",
            "sms_account_sid": self.sms_account_sid or "",
            # sms_auth_token intentionally omitted from API responses
            "sms_from_number": self.sms_from_number or "",
            "sms_recipients": self.sms_recipients or [],
            "snmp_enabled": self.snmp_enabled,
            "snmp_targets": self.snmp_targets or [],
            "snmp_community": self.snmp_community or "public",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ApplicationSettings(db.Model):
    """Application-level settings stored in database.

    Replaces LOG_LEVEL, LOG_FILE, and UPLOAD_FOLDER environment variables.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "application_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # Logging
    # ========================================================================
    log_level = db.Column(db.String(16), nullable=False, default='INFO')
    # Application logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL

    log_file = db.Column(db.String(255), nullable=False, default='logs/eas_station.log')
    # Path to the application log file

    # ========================================================================
    # File Storage
    # ========================================================================
    upload_folder = db.Column(db.String(255), nullable=False, default='/opt/eas-station/uploads')
    # Directory for uploaded files

    backup_dir = db.Column(db.String(255), nullable=False, default='/var/backups/eas-station')
    # Directory where create_backup.py writes snapshots and where the
    # auto-backup scheduler stores its config file.

    # ========================================================================
    # Dashboard Branding
    # ========================================================================
    dashboard_headline = db.Column(db.String(120), nullable=False, default='')
    # Optional headline (call letters, agency name, etc.) shown above the
    # main dashboard title. Empty string falls back to the default title.

    dashboard_subtitle = db.Column(db.String(160), nullable=False, default='')
    # Optional subtitle shown beneath the headline. Empty string falls
    # back to the configured county/state location line.

    # ========================================================================
    # Password Policy
    # ========================================================================
    password_min_length = db.Column(db.Integer, nullable=False, default=15)
    # Minimum number of characters required in a password

    password_require_uppercase = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one uppercase letter (A-Z)

    password_require_lowercase = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one lowercase letter (a-z)

    password_require_digits = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one digit (0-9)

    password_require_special = db.Column(db.Boolean, nullable=False, default=False)
    # Require at least one special character (!@#$%^&*...)

    password_expiration_days = db.Column(db.Integer, nullable=False, default=0)
    # Number of days before a password expires (0 = disabled)

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "log_level": self.log_level,
            "log_file": self.log_file,
            "upload_folder": self.upload_folder,
            "backup_dir": self.backup_dir,
            "dashboard_headline": self.dashboard_headline or "",
            "dashboard_subtitle": self.dashboard_subtitle or "",
            "password_min_length": self.password_min_length,
            "password_require_uppercase": self.password_require_uppercase,
            "password_require_lowercase": self.password_require_lowercase,
            "password_require_digits": self.password_require_digits,
            "password_require_special": self.password_require_special,
            "password_expiration_days": self.password_expiration_days,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RetentionSettings(db.Model):
    """Automated data-retention policy configuration stored in database.

    Controls how long on-disk artifacts (IQ captures, temp audio) and
    fast-growing database tables (stream metadata, audio alerts/metrics,
    received-alert audio blobs) are kept before the background
    :class:`app_core.retention.RetentionScheduler` prunes them.

    All settings are stored in a single row (id=1).
    Convention: ``0`` for any age field means "disabled / keep forever".
    """
    __tablename__ = "retention_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Master switch for the retention sweeper
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    # Days to keep raw IQ capture files (*.npy in RADIO_CAPTURE_DIR)
    iq_capture_max_age_days = db.Column(db.Integer, nullable=False, default=14)

    # Days to keep debug audio in /tmp/eas-audio (EAS_SAVE_AUDIO_FILES output)
    temp_audio_max_age_days = db.Column(db.Integer, nullable=False, default=7)

    # Days to keep ICY now-playing history rows (stream_metadata_log)
    stream_metadata_max_age_days = db.Column(db.Integer, nullable=False, default=90)

    # Days to keep audio source health events (audio_alerts)
    audio_alert_max_age_days = db.Column(db.Integer, nullable=False, default=90)

    # Days to keep per-batch audio level metrics (audio_source_metrics).
    # This table is append-only at several rows/sec across all sources
    # (1.5M+ rows / 2.8GB after less than a week in one real deployment).
    # Was 30 -- lowered to 3 (2026-08-31) after confirming nothing actually
    # reads raw samples older than a short troubleshooting window: the
    # "latest value" and "recent trend" endpoints only ever need the most
    # recent data, and app_core/analytics/aggregator.py already rolls raw
    # samples into the much smaller, permanent MetricSnapshot table for
    # long-term history. 30 days of raw per-sample data was pure bloat.
    audio_metrics_max_age_days = db.Column(db.Integer, nullable=False, default=3)

    # Days to keep raw_audio_data BYTEA blobs on received_eas_alerts.
    # Only the blob is stripped — the alert rows themselves are NEVER
    # deleted because they are compliance history.
    received_alert_audio_max_age_days = db.Column(db.Integer, nullable=False, default=30)

    # Days to keep operational system_log rows (INFO/WARNING/ERROR entries,
    # not compliance-relevant like eas_messages/received_eas_alerts). Added
    # 2026-08-31 after finding this table had no retention policy at all --
    # 1M+ rows / 850+ MB and growing forever.
    system_log_max_age_days = db.Column(db.Integer, nullable=False, default=90)

    # Metadata
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "enabled": self.enabled,
            "iq_capture_max_age_days": self.iq_capture_max_age_days,
            "temp_audio_max_age_days": self.temp_audio_max_age_days,
            "stream_metadata_max_age_days": self.stream_metadata_max_age_days,
            "audio_alert_max_age_days": self.audio_alert_max_age_days,
            "audio_metrics_max_age_days": self.audio_metrics_max_age_days,
            "received_alert_audio_max_age_days": self.received_alert_audio_max_age_days,
            "system_log_max_age_days": self.system_log_max_age_days,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AutoPurgeSettings(db.Model):
    """Automatic received-alert purge configuration stored in database.

    Drives the scheduled purge of rows in ``received_eas_alerts`` (the
    "Received Alerts" history captured from OTA / streaming monitors).  The
    raw WAV audio attached to those rows is the main storage cost, so the
    purge can either strip just the audio blob (``scope='audio'``) or remove
    the entire record (``scope='full'``).

    Unlike :class:`RetentionSettings` (which only ever strips audio and keeps
    the compliance row), this feature can delete whole records, so it ships
    disabled by default and defaults to only touching alerts that were NOT
    forwarded.  All settings live in a single row (id=1).
    """
    __tablename__ = "auto_purge_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Master switch for the scheduled auto-purge
    enabled = db.Column(db.Boolean, nullable=False, default=False)

    # Purge received alerts older than this many days. 0 = disabled.
    max_age_days = db.Column(db.Integer, nullable=False, default=30)

    # What to remove: 'audio' (strip raw_audio_data, keep the record) or
    # 'full' (delete the entire received_eas_alerts row).
    scope = db.Column(db.String(16), nullable=False, default="full")

    # Which alerts to act on by forwarding decision:
    # 'any', 'not_forwarded', 'forwarded', 'ignored', 'error'.
    decision_filter = db.Column(db.String(20), nullable=False, default="not_forwarded")

    # Optional source restriction (matches source_name or alert_source).
    # Blank/NULL means all sources.
    source_filter = db.Column(db.String(100), nullable=True)

    # When scope='full', also delete the generated EAS broadcast message
    # (and its on-disk audio files) that this alert produced, if any.
    delete_generated_messages = db.Column(db.Boolean, nullable=False, default=False)

    # Bookkeeping for the last automatic run
    last_run_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_run_summary = db.Column(JSONB, nullable=True)

    # Metadata
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "enabled": self.enabled,
            "max_age_days": self.max_age_days,
            "scope": self.scope,
            "decision_filter": self.decision_filter,
            "source_filter": self.source_filter or "",
            "delete_generated_messages": self.delete_generated_messages,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_run_summary": self.last_run_summary,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TailscaleSettings(db.Model):
    """Tailscale VPN configuration stored in database.

    Manages Tailscale daemon settings through the web UI.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "tailscale_settings"

    id = db.Column(db.Integer, primary_key=True)

    # ========================================================================
    # General Settings
    # ========================================================================
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch: when enabled, tailscaled will be started/maintained

    auth_key = db.Column(EncryptedString, nullable=False, default='')
    # Pre-authentication key from Tailscale admin console

    hostname = db.Column(db.String(255), nullable=False, default='')
    # Hostname to advertise on the tailnet (blank = system hostname)

    # ========================================================================
    # Network Settings
    # ========================================================================
    advertise_exit_node = db.Column(db.Boolean, nullable=False, default=False)
    # Offer this node as an exit node for the tailnet

    accept_routes = db.Column(db.Boolean, nullable=False, default=True)
    # Accept subnet routes advertised by other nodes

    advertise_routes = db.Column(db.String(1000), nullable=False, default='')
    # Comma-separated CIDR ranges to advertise (e.g. "192.168.1.0/24,10.0.0.0/8")

    shields_up = db.Column(db.Boolean, nullable=False, default=False)
    # Block all incoming connections (outbound-only mode)

    # ========================================================================
    # DNS Settings
    # ========================================================================
    accept_dns = db.Column(db.Boolean, nullable=False, default=True)
    # Accept DNS configuration from the tailnet

    # ========================================================================
    # Metadata
    # ========================================================================
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary.

        auth_key is a secret (a Tailscale pre-auth key) and must never reach
        the browser in plaintext -- only a masked placeholder and a
        has-value flag are exposed, matching TTSSettings.to_dict().
        """
        return {
            "enabled": self.enabled,
            "auth_key": "••••••••" if self.auth_key else "",
            "auth_key_set": bool(self.auth_key),
            "hostname": self.hostname,
            "advertise_exit_node": self.advertise_exit_node,
            "accept_routes": self.accept_routes,
            "advertise_routes": self.advertise_routes,
            "shields_up": self.shields_up,
            "accept_dns": self.accept_dns,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


