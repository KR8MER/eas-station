"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
    led_default_lines = db.Column(
        JSONB,
        nullable=False,
        default=lambda: list(DEFAULT_LOCATION_SETTINGS["led_default_lines"]),
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
            "fips_codes": list(self.fips_codes or []),
            "zone_codes": list(self.zone_codes or []),
            "storage_zone_codes": list(self.storage_zone_codes or []),
            "area_terms": list(self.area_terms or []),
            "map_center_lat": self.map_center_lat,
            "map_center_lng": self.map_center_lng,
            "map_default_zoom": self.map_default_zoom,
            "led_default_lines": list(self.led_default_lines or []),
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
    # USB Tower Light Settings (Adafruit #5125 / CH34x serial stack light)
    # ========================================================================
    tower_light_enabled = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_serial_port = db.Column(db.String(100), nullable=False, default='/dev/ttyUSB0')
    tower_light_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    tower_light_alert_buzzer = db.Column(db.Boolean, nullable=False, default=False)
    tower_light_incoming_uses_yellow = db.Column(db.Boolean, nullable=False, default=True)
    tower_light_blink_on_alert = db.Column(db.Boolean, nullable=False, default=True)

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
    # GPS / Time Source Settings (Adafruit Ultimate GPS HAT #2324)
    # ========================================================================
    gps_enabled = db.Column(db.Boolean, nullable=False, default=False)
    gps_serial_port = db.Column(db.String(100), nullable=False, default='/dev/serial0')
    gps_baudrate = db.Column(db.Integer, nullable=False, default=9600)
    gps_pps_gpio_pin = db.Column(db.Integer, nullable=False, default=4)
    gps_use_for_location = db.Column(db.Boolean, nullable=False, default=False)
    gps_use_for_time = db.Column(db.Boolean, nullable=False, default=False)
    gps_min_satellites = db.Column(db.Integer, nullable=False, default=4)

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
            "tower_light_alert_buzzer": self.tower_light_alert_buzzer,
            "tower_light_incoming_uses_yellow": self.tower_light_incoming_uses_yellow,
            "tower_light_blink_on_alert": self.tower_light_blink_on_alert,
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
            # GPS HAT (Adafruit #2324)
            "gps_enabled": self.gps_enabled,
            "gps_serial_port": self.gps_serial_port,
            "gps_baudrate": self.gps_baudrate,
            "gps_pps_gpio_pin": self.gps_pps_gpio_pin,
            "gps_use_for_location": self.gps_use_for_location,
            "gps_use_for_time": self.gps_use_for_time,
            "gps_min_satellites": self.gps_min_satellites,
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
    source_password = db.Column(db.String(255), nullable=False, default='')
    admin_user = db.Column(db.String(255), nullable=True)
    admin_password = db.Column(db.String(255), nullable=True)

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
    azure_openai_key = db.Column(db.String(500), nullable=True)
    azure_openai_model = db.Column(db.String(100), nullable=False, default='tts-1')
    azure_openai_voice = db.Column(db.String(50), nullable=False, default='alloy')
    azure_openai_speed = db.Column(db.Float, nullable=False, default=1.0)

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "azure_openai_endpoint": self.azure_openai_endpoint,
            "azure_openai_key": self.azure_openai_key,
            "azure_openai_model": self.azure_openai_model,
            "azure_openai_voice": self.azure_openai_voice,
            "azure_openai_speed": self.azure_openai_speed,
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
    # Append 3 × 0xAA trill bytes after each SAME burst to fingerprint this station

    # ========================================================================
    # Authorized Broadcast Areas
    # ========================================================================
    authorized_fips_codes = db.Column(JSONB, nullable=False, default=list)
    # FIPS codes authorized for manual EAS broadcasts

    authorized_event_codes = db.Column(JSONB, nullable=False, default=list)
    # Event codes authorized for manual broadcasts (RWT, RMT, etc.)

    forwarded_event_codes = db.Column(JSONB, nullable=False, default=list)
    # Event codes to auto-forward from CAP/OTA sources. Empty list = forward all.

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
            "authorized_fips_codes": list(self.authorized_fips_codes or []),
            "authorized_event_codes": list(self.authorized_event_codes or []),
            "forwarded_event_codes": list(self.forwarded_event_codes or []),
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

    smtp_password = db.Column(db.String(255), nullable=False, default='')
    # SMTP authentication password

    smtp_security = db.Column(db.String(10), nullable=False, default='starttls')
    # Connection security: "none", "starttls", or "ssl"

    compliance_alert_emails = db.Column(JSONB, nullable=False, default=list)
    # List of email addresses for compliance/health alert notifications

    alert_emails = db.Column(JSONB, nullable=False, default=list)
    # List of email addresses for EAS alert notifications (separate from compliance emails)

    email_attach_audio = db.Column(db.Boolean, nullable=False, default=False)
    # Attach composite EAS audio file to alert notification emails

    # ========================================================================
    # SMS Notifications
    # ========================================================================
    sms_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch for SMS notifications

    sms_provider = db.Column(db.String(50), nullable=False, default='twilio')
    # SMS gateway provider: 'twilio'

    sms_account_sid = db.Column(db.String(255), nullable=False, default='')
    # Twilio Account SID

    sms_auth_token = db.Column(db.String(255), nullable=False, default='')
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

    snmp_community = db.Column(db.String(255), nullable=False, default='public')
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

    # ========================================================================
    # Password Policy
    # ========================================================================
    password_min_length = db.Column(db.Integer, nullable=False, default=8)
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
            "password_min_length": self.password_min_length,
            "password_require_uppercase": self.password_require_uppercase,
            "password_require_lowercase": self.password_require_lowercase,
            "password_require_digits": self.password_require_digits,
            "password_require_special": self.password_require_special,
            "password_expiration_days": self.password_expiration_days,
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

    auth_key = db.Column(db.String(500), nullable=False, default='')
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
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "auth_key": self.auth_key,
            "hostname": self.hostname,
            "advertise_exit_node": self.advertise_exit_node,
            "accept_routes": self.accept_routes,
            "advertise_routes": self.advertise_routes,
            "shields_up": self.shields_up,
            "accept_dns": self.accept_dns,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


