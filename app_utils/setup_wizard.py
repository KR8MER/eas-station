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
from typing import Callable, Dict, Iterable, List, Optional

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


def format_led_lines_for_display(value: str) -> str:
    """Convert comma-separated LED lines into a textarea-friendly format."""

    if not value:
        return ""
    if "\n" in value:
        return value
    return "\n".join(part.strip() for part in value.split(",") if part.strip())


WIZARD_FIELDS: List[WizardField] = [
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
    WizardField(
        key="DEFAULT_TIMEZONE",
        label="Default Timezone",
        description="Pre-populates the admin UI location settings.",
        validator=_validate_timezone,
    ),
    WizardField(
        key="DEFAULT_COUNTY_NAME",
        label="Default County Name",
        description="Displayed in the admin UI and LED signage defaults.",
    ),
    WizardField(
        key="DEFAULT_LED_LINES",
        label="Default LED Lines",
        description="Four comma-separated phrases shown on the LED sign when idle.",
        widget="textarea",
        normalizer=_normalise_led_lines,
    ),
]


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
    "WizardState",
    "WIZARD_FIELDS",
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
