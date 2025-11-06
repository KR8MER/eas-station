"""Helpers for onboarding configuration via the setup wizard.

This module centralises the logic for reading `.env.example`, merging it with
an existing `.env` file, and validating the subset of configuration fields that
bootstrap the application.  Both the web-based onboarding flow and the CLI tool
reuse these utilities to avoid divergent behaviour between environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import secrets
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_TEMPLATE_PATH = PROJECT_ROOT / ".env.example"
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
    """Validate EAS station ID (8 characters max, no dashes)."""
    if not value:
        return value
    if len(value) > 8:
        raise ValueError("EAS Station ID must be 8 characters or fewer.")
    if "-" in value:
        raise ValueError("EAS Station ID cannot contain dashes.")
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
    if value and not value.replace(",", "").isdigit():
        raise ValueError("FIPS codes must be numeric, comma-separated.")
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
        description="GPIO pin number for relay control (leave blank to disable).",
        required=False,
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
    ),
    WizardField(
        key="VFD_PORT",
        label="VFD Serial Port",
        description="Serial port for Noritake VFD display (e.g., /dev/ttyUSB0, leave blank to disable).",
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
