import pytest

from app_utils.setup_wizard import (
    PLACEHOLDER_SECRET_VALUES,
    WIZARD_SECTIONS,
    WIZARD_FIELDS,
    SetupValidationError,
    clean_submission,
    generate_secret_key,
    format_led_lines_for_display,
)


def _build_minimal_form(secret: str = None) -> dict:
    """Build minimal valid form with required fields only."""
    if secret is None:
        secret = "a" * 32
    return {
        "SECRET_KEY": secret,
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "alerts",
        "POSTGRES_USER": "alerts",
        "POSTGRES_PASSWORD": "password",
        "DEFAULT_TIMEZONE": "America/New_York",
        "DEFAULT_COUNTY_NAME": "Putnam County",
    }


def _build_full_form(secret: str = None) -> dict:
    """Build form with all fields populated."""
    form = _build_minimal_form(secret)
    form.update({
        "DEFAULT_STATE_CODE": "OH",
        "DEFAULT_ZONE_CODES": "OHZ016,OHC137",
        "EAS_BROADCAST_ENABLED": "true",
        "EAS_ORIGINATOR": "WXR",
        "EAS_STATION_ID": "KR8MER",
        "EAS_MANUAL_FIPS_CODES": "039137",
        "EAS_GPIO_PIN": "17",
        "AUDIO_INGEST_ENABLED": "true",
        "AUDIO_ALSA_ENABLED": "true",
        "AUDIO_ALSA_DEVICE": "hw:1,0",
        "AUDIO_SDR_ENABLED": "false",
        "EAS_TTS_PROVIDER": "pyttsx3",
        "DEFAULT_LED_LINES": "Line 1\nLine 2\nLine 3\nLine 4",
        "LED_SIGN_IP": "192.168.1.100",
        "VFD_PORT": "/dev/ttyUSB0",
    })
    return form


# ============================================================================
# Secret Key Tests
# ============================================================================

@pytest.mark.parametrize(
    "placeholder",
    [value for value in PLACEHOLDER_SECRET_VALUES if value],
)
def test_clean_submission_rejects_placeholder_secret(placeholder):
    """Reject placeholder secret keys from .env.example."""
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(_build_minimal_form(placeholder))
    assert "SECRET_KEY" in excinfo.value.errors


def test_clean_submission_rejects_short_secret():
    """Reject secret keys shorter than 32 characters."""
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(_build_minimal_form("tooshort"))
    assert "SECRET_KEY" in excinfo.value.errors
    assert "at least 32 characters" in excinfo.value.errors["SECRET_KEY"]


def test_clean_submission_accepts_valid_secret():
    """Accept valid secret key with sufficient length."""
    secret = "a" * 32
    cleaned = clean_submission(_build_minimal_form(secret))
    assert cleaned["SECRET_KEY"] == secret


def test_generate_secret_key_length():
    """Generated secret key should be 64 characters."""
    secret = generate_secret_key()
    assert len(secret) == 64


def test_generate_secret_key_uniqueness():
    """Generated secret keys should be unique."""
    secret1 = generate_secret_key()
    secret2 = generate_secret_key()
    assert secret1 != secret2


# ============================================================================
# Port Validation Tests
# ============================================================================

def test_clean_submission_validates_port_range():
    """Reject invalid port numbers."""
    form = _build_minimal_form()
    form["POSTGRES_PORT"] = "99999"
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(form)
    assert "POSTGRES_PORT" in excinfo.value.errors


def test_clean_submission_validates_port_numeric():
    """Reject non-numeric port values."""
    form = _build_minimal_form()
    form["POSTGRES_PORT"] = "not-a-number"
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(form)
    assert "POSTGRES_PORT" in excinfo.value.errors


def test_clean_submission_rejects_reserved_oled_pin():
    """Reject GPIO pins that belong to the Argon OLED enclosure block."""

    form = _build_full_form()
    form["EAS_GPIO_PIN"] = "4"  # BCM 4 (physical pin 7) reserved

    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(form)

    assert "EAS_GPIO_PIN" in excinfo.value.errors
    assert "reserved" in excinfo.value.errors["EAS_GPIO_PIN"].lower()


# ============================================================================
# Timezone Validation Tests
# ============================================================================

def test_clean_submission_validates_timezone_format():
    """Reject timezone without Region/City format."""
    form = _build_minimal_form()
    form["DEFAULT_TIMEZONE"] = "EST"
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(form)
    assert "DEFAULT_TIMEZONE" in excinfo.value.errors
    assert "Region/City" in excinfo.value.errors["DEFAULT_TIMEZONE"]


def test_clean_submission_accepts_valid_timezone():
    """Accept valid Region/City timezone."""
    form = _build_minimal_form()
    form["DEFAULT_TIMEZONE"] = "America/New_York"
    cleaned = clean_submission(form)
    assert cleaned["DEFAULT_TIMEZONE"] == "America/New_York"


# ============================================================================
# Boolean Validation Tests
# ============================================================================

def test_clean_submission_validates_boolean_values():
    """Reject invalid boolean values."""
    form = _build_full_form()
    form["EAS_BROADCAST_ENABLED"] = "yes"  # Should be "true" or "false"
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(form)
    assert "EAS_BROADCAST_ENABLED" in excinfo.value.errors


def test_clean_submission_accepts_boolean_true():
    """Accept 'true' as boolean value."""
    form = _build_full_form()
    form["EAS_BROADCAST_ENABLED"] = "true"
    cleaned = clean_submission(form)
    assert cleaned["EAS_BROADCAST_ENABLED"] == "true"


def test_clean_submission_accepts_boolean_false():
    """Accept 'false' as boolean value."""
    form = _build_full_form()
    form["EAS_BROADCAST_ENABLED"] = "false"
    cleaned = clean_submission(form)
    assert cleaned["EAS_BROADCAST_ENABLED"] == "false"


# ============================================================================
# FIPS Code Validation Tests
# ============================================================================

def test_clean_submission_validates_fips_numeric():
    """Reject non-numeric FIPS codes."""
    form = _build_full_form()
    form["EAS_MANUAL_FIPS_CODES"] = "ABC123"
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(form)
    assert "EAS_MANUAL_FIPS_CODES" in excinfo.value.errors


def test_clean_submission_accepts_valid_fips():
    """Accept valid numeric FIPS codes."""
    form = _build_full_form()
    form["EAS_MANUAL_FIPS_CODES"] = "039137,039001"
    cleaned = clean_submission(form)
    assert cleaned["EAS_MANUAL_FIPS_CODES"] == "039137,039001"


# ============================================================================
# LED Lines Normalization Tests
# ============================================================================

def test_clean_submission_normalizes_led_lines():
    """Normalize LED lines from newline-separated to comma-separated."""
    form = _build_minimal_form()
    form["DEFAULT_LED_LINES"] = "Line 1\nLine 2\nLine 3\nLine 4"
    cleaned = clean_submission(form)
    assert cleaned["DEFAULT_LED_LINES"] == "Line 1,Line 2,Line 3,Line 4"


def test_format_led_lines_for_display():
    """Convert comma-separated LED lines to newline-separated."""
    comma_sep = "Line 1,Line 2,Line 3,Line 4"
    newline_sep = format_led_lines_for_display(comma_sep)
    assert newline_sep == "Line 1\nLine 2\nLine 3\nLine 4"


def test_format_led_lines_handles_empty():
    """Handle empty LED lines string."""
    assert format_led_lines_for_display("") == ""


def test_format_led_lines_preserves_newlines():
    """Preserve existing newlines without double-conversion."""
    newline_sep = "Line 1\nLine 2"
    assert format_led_lines_for_display(newline_sep) == newline_sep


# ============================================================================
# Optional Fields Tests
# ============================================================================

def test_clean_submission_accepts_empty_optional_fields():
    """Accept minimal form with only required fields."""
    form = _build_minimal_form()
    cleaned = clean_submission(form)
    assert "SECRET_KEY" in cleaned
    assert "POSTGRES_HOST" in cleaned


def test_clean_submission_accepts_full_form():
    """Accept form with all fields populated."""
    form = _build_full_form()
    cleaned = clean_submission(form)
    assert len(cleaned) > len(_build_minimal_form())


# ============================================================================
# Wizard Structure Tests
# ============================================================================

def test_wizard_sections_exist():
    """Verify wizard sections are defined."""
    assert len(WIZARD_SECTIONS) > 0
    assert any(s.name == "core" for s in WIZARD_SECTIONS)


def test_wizard_sections_have_fields():
    """Each section should have at least one field."""
    for section in WIZARD_SECTIONS:
        assert len(section.fields) > 0
        assert section.title
        assert section.description


def test_wizard_fields_flattened():
    """WIZARD_FIELDS should contain all fields from all sections."""
    section_field_count = sum(len(s.fields) for s in WIZARD_SECTIONS)
    assert len(WIZARD_FIELDS) == section_field_count


def test_core_section_has_required_fields():
    """Core section should have required database and secret key fields."""
    core_section = next(s for s in WIZARD_SECTIONS if s.name == "core")
    field_keys = [f.key for f in core_section.fields]
    assert "SECRET_KEY" in field_keys
    assert "POSTGRES_HOST" in field_keys
    assert "POSTGRES_DB" in field_keys
    assert "POSTGRES_USER" in field_keys
    assert "POSTGRES_PASSWORD" in field_keys


# ============================================================================
# Partial Update Tests (Skipped Section Preservation)
# ============================================================================

def test_partial_form_preserves_unspecified_keys():
    """When only some fields are provided, unspecified keys should not be blanked."""
    # Simulate user only updating database password, not touching audio settings
    partial_form = {
        "SECRET_KEY": "a" * 32,
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "alerts",
        "POSTGRES_USER": "alerts",
        "POSTGRES_PASSWORD": "new_password",  # Changed
        "DEFAULT_TIMEZONE": "America/New_York",
        "DEFAULT_COUNTY_NAME": "Putnam County",
        # Note: Audio settings NOT included (simulating skipped section)
    }

    # This should not raise an error for missing optional fields
    cleaned = clean_submission(partial_form)

    # Required fields should be present
    assert cleaned["POSTGRES_PASSWORD"] == "new_password"
    assert cleaned["SECRET_KEY"] == "a" * 32

    # Optional fields that weren't provided should not be in the cleaned result
    # (they'll be preserved by the CLI tool from defaults)
    assert "AUDIO_ALSA_ENABLED" not in cleaned or cleaned["AUDIO_ALSA_ENABLED"] == ""
