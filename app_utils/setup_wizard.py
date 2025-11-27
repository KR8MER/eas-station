"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Helpers for onboarding configuration via the setup wizard.

This module centralises the logic for reading `.env.example`, merging it with
an existing `.env` file, and validating the subset of configuration fields that
bootstrap the application.  Both the web-based onboarding flow and the CLI tool
reuse these utilities to avoid divergent behaviour between environments.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
import os

import secrets
from dotenv import dotenv_values

from app_utils.pi_pinout import ARGON_OLED_RESERVED_BCM, ARGON_OLED_RESERVED_PHYSICAL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_TEMPLATE_PATH = PROJECT_ROOT / ".env.example"

# Use CONFIG_PATH if set (persistent volume), otherwise use default location
_config_path_override = os.environ.get('CONFIG_PATH')
if _config_path_override:
    ENV_OUTPUT_PATH = Path(_config_path_override)
else:
    ENV_OUTPUT_PATH = PROJECT_ROOT / ".env"

# Known placeholder values that should never be persisted as SECRET_KEY.
PLACEHOLDER_SECRET_VALUES = {
    "dev-key-change-in-production",
    "replace-with-a-long-random-string",
}

# Common US timezones for dropdown selection
US_TIMEZONES: List[Tuple[str, str]] = [
    ("America/New_York", "America/New_York (Eastern)"),
    ("America/Chicago", "America/Chicago (Central)"),
    ("America/Denver", "America/Denver (Mountain)"),
    ("America/Phoenix", "America/Phoenix (Arizona - no DST)"),
    ("America/Los_Angeles", "America/Los_Angeles (Pacific)"),
    ("America/Anchorage", "America/Anchorage (Alaska)"),
    ("America/Adak", "America/Adak (Hawaii-Aleutian)"),
    ("Pacific/Honolulu", "Pacific/Honolulu (Hawaii)"),
    ("America/Puerto_Rico", "America/Puerto_Rico (Atlantic)"),
    ("Pacific/Guam", "Pacific/Guam (Chamorro)"),
    ("Pacific/Pago_Pago", "Pacific/Pago_Pago (Samoa)"),
    ("America/Boise", "America/Boise (Mountain)"),
    ("America/Detroit", "America/Detroit (Eastern)"),
    ("America/Indiana/Indianapolis", "America/Indiana/Indianapolis (Eastern)"),
    ("America/Kentucky/Louisville", "America/Kentucky/Louisville (Eastern)"),
    ("America/Juneau", "America/Juneau (Alaska)"),
    ("America/Nome", "America/Nome (Alaska)"),
    ("America/Sitka", "America/Sitka (Alaska)"),
]

# US State codes with names
US_STATE_CODES: List[Tuple[str, str]] = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
    ("AS", "American Samoa"),
    ("GU", "Guam"),
    ("MP", "Northern Mariana Islands"),
    ("PR", "Puerto Rico"),
    ("VI", "U.S. Virgin Islands"),
]


class SetupWizardError(Exception):
    """Base exception for setup wizard problems."""


class SetupValidationError(SetupWizardError):
    """Raised when submitted configuration fails validation."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Submitted configuration was invalid")
        self.errors = errors


@dataclass(frozen=True)
class WizardField:
    """Metadata describing a field managed by the setup wizard."""

    key: str
    label: str
    description: str
    placeholder: Optional[str] = None
    required: bool = True
    input_type: str = "text"
    widget: str = "input"
    validator: Optional[Callable[[str], str]] = None
    normalizer: Optional[Callable[[str], str]] = None
    options: Optional[List[Dict[str, str]]] = None  # For select widgets: [{"value": "...", "label": "..."}]

    def clean(self, value: str) -> str:
        """Validate and normalise the provided value."""

        trimmed = value.strip()
        if not trimmed:
            if self.required:
                raise ValueError("This field is required.")
            return ""

        if self.validator is not None:
            trimmed = self.validator(trimmed)

        if self.normalizer is not None:
            trimmed = self.normalizer(trimmed)

        return trimmed


@dataclass(frozen=True)
class WizardState:
    """Current environment/template snapshot used by the wizard."""

    template_lines: List[str]
    template_values: Dict[str, str]
    current_values: Dict[str, str]
    env_file_present: bool

    @property
    def defaults(self) -> Dict[str, str]:
        combined = dict(self.template_values)
        combined.update(self.current_values)
        return combined

    @property
    def env_exists(self) -> bool:
        return self.env_file_present


def _parse_env_lines(lines: Iterable[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        values[key.strip()] = raw_val.strip()
    return values


def _validate_port(value: str) -> str:
    try:
        port = int(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("Port must be an integer between 1 and 65535") from exc

    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    return str(port)


def _validate_timezone(value: str) -> str:
    if "/" not in value:
        raise ValueError("Use the canonical Region/City timezone format, e.g. 'America/New_York'.")
    return value


def _normalise_led_lines(value: str) -> str:
    lines = [segment.strip() for segment in value.replace("\r", "").splitlines()]
    cleaned = [segment for segment in lines if segment]
    if not cleaned:
        raise ValueError("Provide at least one LED display line.")
    return ",".join(cleaned)


def _validate_secret_key(value: str) -> str:
    if len(value) < 32:
        raise ValueError("SECRET_KEY should be at least 32 characters long.")
    if value in PLACEHOLDER_SECRET_VALUES:
        raise ValueError("SECRET_KEY must be replaced with a securely generated value.")
    return value


def _validate_station_id(value: str) -> str:
    """Validate EAS station ID (8 characters max, uppercase letters/numbers/forward slash only)."""
    import re
    if not value:
        return value
    if len(value) > 8:
        raise ValueError("EAS Station ID must be 8 characters or fewer.")
    # Must contain only uppercase letters, numbers, and forward slash
    if not re.match(r'^[A-Z0-9/]+$', value.upper()):
        raise ValueError("EAS Station ID must contain only uppercase letters (A-Z), numbers (0-9), and forward slash (/). No hyphens or lowercase letters.")
    return value.upper()


def _validate_state_code(value: str) -> str:
    """Validate state code is a valid 2-letter US state abbreviation."""
    if not value:
        return value
    if len(value) != 2:
        raise ValueError("State code must be exactly 2 characters.")
    return value.upper()


def format_led_lines_for_display(value: str) -> str:
    """Convert comma-separated LED lines into a textarea-friendly format."""

    if not value:
        return ""
    if "\n" in value:
        return value
    return "\n".join(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class WizardSection:
    """Logical grouping of related wizard fields."""

    name: str
    title: str
    description: str
    fields: List[WizardField]


def _validate_bool(value: str) -> str:
    """Validate boolean values. Empty strings are allowed for optional fields."""
    # Empty/whitespace is allowed for optional fields
    if not value or not value.strip():
        return ""
    value_lower = value.lower().strip()
    if value_lower not in {"true", "false"}:
        raise ValueError("Must be 'true' or 'false'.")
    return value_lower


def _validate_fips(value: str) -> str:
    """Validate FIPS codes (numeric only)."""
    if value and not value.replace(",", "").replace(" ", "").isdigit():
        raise ValueError("FIPS codes must be numeric, comma-separated.")
    return value


def _validate_ipv4(value: str) -> str:
    """Validate IPv4 address format."""
    import re
    if not value:
        return value
    # IPv4 pattern
    ipv4_pattern = r'^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\b){4}$'
    if not re.match(ipv4_pattern, value):
        raise ValueError("Must be a valid IPv4 address (e.g., 192.168.1.100).")
    return value


def _validate_gpio_pin(value: str) -> str:
    """Validate GPIO pin number (Raspberry Pi BCM numbering: 2-27)."""
    if not value:
        return value
    try:
        pin = int(value)
    except ValueError:
        raise ValueError("GPIO pin must be a number.")
    if not 2 <= pin <= 27:
        raise ValueError("GPIO pin must be between 2 and 27 (Raspberry Pi BCM numbering).")
    if pin in ARGON_OLED_RESERVED_BCM:
        physical = ", ".join(str(p) for p in sorted(ARGON_OLED_RESERVED_PHYSICAL))
        reserved_bcm = ", ".join(str(p) for p in sorted(ARGON_OLED_RESERVED_BCM))
        raise ValueError(
            "Pins {bcm} (physical pins {physical}) are reserved for the Argon OLED enclosure and "
            "cannot be reassigned.".format(bcm=reserved_bcm, physical=physical)
        )
    return str(pin)


def _validate_non_negative_int(value: str) -> str:
    """Validate that a value is an integer >= 0."""

    if not value:
        return value
    try:
        number = int(value, 10)
    except ValueError:
        raise ValueError("Value must be an integer.")
    if number < 0:
        raise ValueError("Value must be zero or greater.")
    return str(number)


def _validate_positive_int(value: str) -> str:
    """Validate that a value is a positive integer."""

    if not value:
        return value
    try:
        number = int(value, 10)
    except ValueError:
        raise ValueError("Value must be an integer.")
    if number <= 0:
        raise ValueError("Value must be greater than zero.")
    return str(number)


def _validate_oled_rotation(value: str) -> str:
    """Validate OLED rotation values (0/90/180/270)."""

    if not value:
        return value
    allowed = {"0", "90", "180", "270"}
    if value not in allowed:
        raise ValueError("Rotation must be one of 0, 90, 180, or 270 degrees.")
    return value


def _validate_icecast_password(value: str) -> str:
    """Validate Icecast password (ASCII-only, no Unicode characters)."""
    if not value:
        return value

    # Check for minimum length
    if len(value) < 8:
        raise ValueError("Password should be at least 8 characters long.")

    # Check for ASCII-only (Icecast requirement)
    try:
        value.encode('ascii')
    except UnicodeEncodeError:
        raise ValueError(
            "Icecast passwords must use ASCII characters only. "
            "No emoji, Unicode bullets, or non-Latin characters allowed. "
            "Use only: a-z, A-Z, 0-9, and symbols like !@#$%^&*()-_=+"
        )

    # Warn about default passwords
    if value in {'changeme', 'changeme_admin', 'changeme_source', 'hackme', 'password'}:
        raise ValueError(
            "Please use a secure password. Default/common passwords are not allowed."
        )

    return value


# Core section - Required settings
CORE_FIELDS = [
    WizardField(
        key="SECRET_KEY",
        label="Flask Secret Key",
        description="Required for session security. Generate a unique 64 character token.",
        validator=_validate_secret_key,
    ),
    WizardField(
        key="POSTGRES_HOST",
        label="PostgreSQL Host",
        description="Hostname or IP address of the PostGIS database server.",
    ),
    WizardField(
        key="POSTGRES_PORT",
        label="PostgreSQL Port",
        description="Default PostgreSQL port is 5432.",
        validator=_validate_port,
    ),
    WizardField(
        key="POSTGRES_DB",
        label="Database Name",
        description="Database schema that stores CAP alerts and station data.",
    ),
    WizardField(
        key="POSTGRES_USER",
        label="Database Username",
        description="Account used by the application to connect to the database.",
    ),
    WizardField(
        key="POSTGRES_PASSWORD",
        label="Database Password",
        description="Password for the configured database user.",
        input_type="password",
    ),
]

# Location section
LOCATION_FIELDS = [
    WizardField(
        key="DEFAULT_TIMEZONE",
        label="Default Timezone",
        description="Pre-populates the admin UI location settings. Used for timestamps and scheduling.",
        validator=_validate_timezone,
        widget="select",
        options=[{"value": "", "label": "-- Select Timezone --"}] +
                [{"value": tz[0], "label": tz[1]} for tz in US_TIMEZONES],
    ),
    WizardField(
        key="DEFAULT_COUNTY_NAME",
        label="Default County Name",
        description="Displayed in the admin UI and LED signage defaults.",
    ),
    WizardField(
        key="DEFAULT_STATE_CODE",
        label="Default State Code",
        description="Two-letter state abbreviation for your primary location.",
        required=False,
        validator=_validate_state_code,
        widget="select",
        options=[{"value": "", "label": "-- Select State --"}] +
                [{"value": state[0], "label": f"{state[0]} — {state[1]}"} for state in US_STATE_CODES],
    ),
    WizardField(
        key="DEFAULT_ZONE_CODES",
        label="Default Zone Codes",
        description="Comma-separated NWS zone codes for your area (e.g., OHZ016,OHC137). Leave blank to auto-derive from county FIPS codes.",
        required=False,
    ),
]

# EAS Broadcast section
EAS_FIELDS = [
    WizardField(
        key="EAS_BROADCAST_ENABLED",
        label="Enable EAS Broadcast",
        description="Enable SAME header generation and audio playout (true/false).",
        validator=_validate_bool,
        required=False,
    ),
    WizardField(
        key="EAS_ORIGINATOR",
        label="EAS Originator Code",
        description="Three-letter originator code identifying who initiated the alert.",
        required=False,
        widget="select",
        options=[
            {"value": "", "label": "-- Select --"},
            {"value": "WXR", "label": "WXR — National Weather Service"},
            {"value": "EAS", "label": "EAS — EAS Participant / broadcaster"},
            {"value": "CIV", "label": "CIV — Civil authorities"},
            {"value": "PEP", "label": "PEP — National Public Warning System (PEP)"},
        ],
    ),
    WizardField(
        key="EAS_STATION_ID",
        label="EAS Station ID",
        description="Eight-character maximum station callsign or identifier. No dashes allowed (e.g., WXYZ1234, not WXYZ-1234).",
        required=False,
        validator=_validate_station_id,
    ),
    WizardField(
        key="EAS_MANUAL_FIPS_CODES",
        label="Authorized FIPS Codes",
        description="FIPS codes authorized for manual broadcasts (comma-separated).",
        validator=_validate_fips,
        required=False,
    ),
    WizardField(
        key="EAS_GPIO_PIN",
        label="GPIO Relay Pin",
        description=(
            "GPIO pin number for relay control (2-27, leave blank to disable). "
            "Pins 2, 3, 4, and 14 are reserved for the Argon OLED enclosure."
        ),
        required=False,
        validator=_validate_gpio_pin,
    ),
]

# Audio Ingest section
AUDIO_INGEST_FIELDS = [
    WizardField(
        key="AUDIO_INGEST_ENABLED",
        label="Enable Audio Ingest",
        description="Enable audio capture pipeline for SDR and line-level sources (true/false).",
        validator=_validate_bool,
        required=False,
    ),
    WizardField(
        key="AUDIO_ALSA_ENABLED",
        label="Enable ALSA Audio Source",
        description="Capture from ALSA device (true/false).",
        validator=_validate_bool,
        required=False,
    ),
    WizardField(
        key="AUDIO_ALSA_DEVICE",
        label="ALSA Device Name",
        description="ALSA device identifier (e.g., 'default', 'hw:0,0').",
        required=False,
    ),
    WizardField(
        key="AUDIO_SDR_ENABLED",
        label="Enable SDR Audio Source",
        description="Capture audio from SDR receiver (true/false).",
        validator=_validate_bool,
        required=False,
    ),
]

# Icecast streaming section
ICECAST_FIELDS = [
    WizardField(
        key="ICECAST_ENABLED",
        label="Enable Icecast Streaming",
        description="Enable automatic Icecast streaming for all audio sources.",
        required=False,
        widget="select",
        options=[
            {"value": "true", "label": "Enabled"},
            {"value": "false", "label": "Disabled"},
        ],
    ),
    WizardField(
        key="ICECAST_PUBLIC_HOSTNAME",
        label="Public Hostname/IP",
        description="CRITICAL: Server's public IP or hostname for external access (e.g., 207.148.11.5). Required for remote listeners.",
        required=False,
        placeholder="e.g., 207.148.11.5 or easstation.com",
    ),
    WizardField(
        key="ICECAST_EXTERNAL_PORT",
        label="External Port",
        description="Icecast external port for browser/remote access (default: 8001).",
        required=False,
        validator=_validate_port,
    ),
    WizardField(
        key="ICECAST_LOCATION",
        label="Station Location",
        description="Location name shown in Icecast stream metadata.",
        required=False,
    ),
    WizardField(
        key="ICECAST_ADMIN",
        label="Admin Contact Email",
        description="Contact email shown in Icecast admin interface.",
        required=False,
    ),
    WizardField(
        key="ICECAST_MAX_CLIENTS",
        label="Max Listeners",
        description="Maximum concurrent stream listeners (default: 100).",
        required=False,
        validator=_validate_positive_int,
    ),
    WizardField(
        key="ICECAST_SOURCE_PASSWORD",
        label="Source Password",
        description="Password for publishing audio streams to Icecast. Must be ASCII-only.",
        input_type="password",
        validator=_validate_icecast_password,
        required=False,
    ),
    WizardField(
        key="ICECAST_RELAY_PASSWORD",
        label="Relay Password",
        description="Password for relay connections (cascading Icecast servers). Must be ASCII-only.",
        input_type="password",
        validator=_validate_icecast_password,
        required=False,
    ),
    WizardField(
        key="ICECAST_ADMIN_PASSWORD",
        label="Admin Password",
        description="Password for Icecast admin interface. Must be ASCII-only.",
        input_type="password",
        validator=_validate_icecast_password,
        required=False,
    ),
]

# TTS section
TTS_FIELDS = [
    WizardField(
        key="EAS_TTS_PROVIDER",
        label="TTS Provider",
        description="Text-to-speech provider for voice synthesis of alert announcements.",
        required=False,
        widget="select",
        options=[
            {"value": "", "label": "-- None (Disable TTS) --"},
            {"value": "pyttsx3", "label": "pyttsx3 — Local offline TTS (default)"},
            {"value": "azure", "label": "azure — Azure Cognitive Services TTS"},
            {"value": "azure_openai", "label": "azure_openai — Azure OpenAI TTS"},
        ],
    ),
    WizardField(
        key="AZURE_OPENAI_ENDPOINT",
        label="Azure OpenAI Endpoint",
        description="Azure OpenAI endpoint URL (if using azure_openai TTS).",
        required=False,
    ),
    WizardField(
        key="AZURE_OPENAI_KEY",
        label="Azure OpenAI Key",
        description="Azure OpenAI API key (if using azure_openai TTS).",
        input_type="password",
        required=False,
    ),
]

# Hardware section
HARDWARE_FIELDS = [
    WizardField(
        key="DEFAULT_LED_LINES",
        label="Default LED Lines",
        description="Four comma-separated phrases shown on the LED sign when idle.",
        widget="textarea",
        normalizer=_normalise_led_lines,
        required=False,
    ),
    WizardField(
        key="LED_SIGN_IP",
        label="LED Sign IP Address",
        description="IP address of Alpha protocol LED sign (leave blank to disable).",
        required=False,
        validator=_validate_ipv4,
    ),
    WizardField(
        key="VFD_PORT",
        label="VFD Serial Port",
        description="Serial port for Noritake VFD display (e.g., /dev/ttyUSB0, leave blank to disable).",
        required=False,
    ),
    WizardField(
        key="OLED_ENABLED",
        label="Enable OLED Module",
        description="Drive the Argon Industria OLED status display (true/false).",
        validator=_validate_bool,
        required=False,
    ),
    WizardField(
        key="OLED_I2C_BUS",
        label="OLED I2C Bus",
        description="Linux I2C bus number (default 1 on Raspberry Pi).",
        validator=_validate_non_negative_int,
        required=False,
    ),
    WizardField(
        key="OLED_I2C_ADDRESS",
        label="OLED I2C Address",
        description="I2C address for the OLED module (default 0x3C, leave blank to use default).",
        required=False,
    ),
    WizardField(
        key="OLED_WIDTH",
        label="OLED Width (pixels)",
        description="Logical width of the OLED panel (default 128).",
        validator=_validate_positive_int,
        required=False,
    ),
    WizardField(
        key="OLED_HEIGHT",
        label="OLED Height (pixels)",
        description="Logical height of the OLED panel (default 64).",
        validator=_validate_positive_int,
        required=False,
    ),
    WizardField(
        key="OLED_ROTATE",
        label="OLED Rotation",
        description="Rotation to match enclosure orientation (0, 90, 180, 270).",
        validator=_validate_oled_rotation,
        required=False,
    ),
    WizardField(
        key="OLED_DEFAULT_INVERT",
        label="OLED Invert Colours",
        description="Invert the OLED colours (true/false).",
        validator=_validate_bool,
        required=False,
    ),
    WizardField(
        key="OLED_FONT_PATH",
        label="OLED Font Path",
        description="Optional TTF font path used for rendering (leave blank for default).",
        required=False,
    ),
]

# Organize all fields into sections
WIZARD_SECTIONS = [
    WizardSection(
        name="core",
        title="Core Settings",
        description="Essential database and security configuration",
        fields=CORE_FIELDS,
    ),
    WizardSection(
        name="location",
        title="Location Settings",
        description="Geographic and timezone information",
        fields=LOCATION_FIELDS,
    ),
    WizardSection(
        name="eas",
        title="EAS Broadcast",
        description="SAME encoder and broadcast settings",
        fields=EAS_FIELDS,
    ),
    WizardSection(
        name="audio_ingest",
        title="Audio Ingest",
        description="Audio capture from SDR and line-level sources",
        fields=AUDIO_INGEST_FIELDS,
    ),
    WizardSection(
        name="icecast",
        title="Icecast Streaming",
        description="Audio streaming server passwords (must be ASCII-only, no Unicode/emoji)",
        fields=ICECAST_FIELDS,
    ),
    WizardSection(
        name="tts",
        title="Text-to-Speech",
        description="Voice synthesis for alert announcements",
        fields=TTS_FIELDS,
    ),
    WizardSection(
        name="hardware",
        title="Hardware Integration",
        description="LED signs, VFD displays, and GPIO",
        fields=HARDWARE_FIELDS,
    ),
]

# Flatten all fields for backward compatibility
WIZARD_FIELDS: List[WizardField] = []
for section in WIZARD_SECTIONS:
    WIZARD_FIELDS.extend(section.fields)


def load_wizard_state() -> WizardState:
    """Load template and existing environment values for the wizard."""

    if not ENV_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            ".env.example is missing. Ensure the repository includes the template before running the wizard."
        )

    template_lines = ENV_TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
    template_values = _parse_env_lines(template_lines)

    env_file_present = ENV_OUTPUT_PATH.exists()
    current_values: Dict[str, str] = {}
    if env_file_present:
        raw_values = dotenv_values(str(ENV_OUTPUT_PATH))
        current_values = {key: (value or "") for key, value in raw_values.items() if value is not None}

    return WizardState(
        template_lines=template_lines,
        template_values=template_values,
        current_values=current_values,
        env_file_present=env_file_present,
    )


def generate_secret_key() -> str:
    """Generate a 64-character hex token suitable for Flask's SECRET_KEY."""

    return secrets.token_hex(32)


def create_env_backup() -> Path:
    """Create a timestamped backup of the current .env file."""

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_path = ENV_OUTPUT_PATH.with_suffix(f".backup-{timestamp}")
    data = ENV_OUTPUT_PATH.read_bytes()
    backup_path.write_bytes(data)
    return backup_path


def build_env_content(
    *,
    state: WizardState,
    updates: Dict[str, str],
) -> str:
    """Render environment content using the template with updated values."""

    baseline = state.defaults
    merged_updates = {key: value for key, value in updates.items() if value is not None}

    result_lines: List[str] = []
    seen_keys = set()
    for raw in state.template_lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            result_lines.append(raw)
            continue
        key, _ = raw.split("=", 1)
        key = key.strip()
        seen_keys.add(key)
        new_value = merged_updates.get(key, baseline.get(key, ""))
        result_lines.append(f"{key}={new_value}")

    for key, value in merged_updates.items():
        if key not in seen_keys:
            result_lines.append(f"{key}={value}")

    return "\n".join(result_lines) + "\n"


def write_env_file(*, state: WizardState, updates: Dict[str, str], create_backup: bool) -> Path:
    """Persist updates to the .env file, optionally writing a backup first."""

    backup_path: Optional[Path] = None
    if create_backup and ENV_OUTPUT_PATH.exists():
        backup_path = create_env_backup()

    content = build_env_content(state=state, updates=updates)
    ENV_OUTPUT_PATH.write_text(content, encoding="utf-8")
    return backup_path if backup_path is not None else ENV_OUTPUT_PATH


def clean_submission(raw_form: Dict[str, str]) -> Dict[str, str]:
    """Validate and normalise form values from the wizard."""

    errors: Dict[str, str] = {}
    cleaned: Dict[str, str] = {}

    for field in WIZARD_FIELDS:
        raw_value = raw_form.get(field.key, "")
        try:
            cleaned[field.key] = field.clean(raw_value)
        except ValueError as exc:
            errors[field.key] = str(exc)

    if errors:
        raise SetupValidationError(errors)

    return cleaned


__all__ = [
    "ENV_OUTPUT_PATH",
    "ENV_TEMPLATE_PATH",
    "PLACEHOLDER_SECRET_VALUES",
    "WizardField",
    "WizardSection",
    "WizardState",
    "WIZARD_FIELDS",
    "WIZARD_SECTIONS",
    "SetupWizardError",
    "SetupValidationError",
    "build_env_content",
    "clean_submission",
    "create_env_backup",
    "format_led_lines_for_display",
    "generate_secret_key",
    "load_wizard_state",
    "write_env_file",
]
