import pytest

from app_utils.setup_wizard import (
    PLACEHOLDER_SECRET_VALUES,
    SetupValidationError,
    clean_submission,
)


def _build_form(secret: str) -> dict:
    return {
        "SECRET_KEY": secret,
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "alerts",
        "POSTGRES_USER": "alerts",
        "POSTGRES_PASSWORD": "password",
        "DEFAULT_TIMEZONE": "America/New_York",
        "DEFAULT_COUNTY_NAME": "Putnam County",
        "DEFAULT_LED_LINES": "Line 1\nLine 2",
    }


@pytest.mark.parametrize(
    "placeholder",
    [value for value in PLACEHOLDER_SECRET_VALUES if value],
)
def test_clean_submission_rejects_placeholder_secret(placeholder):
    with pytest.raises(SetupValidationError) as excinfo:
        clean_submission(_build_form(placeholder))

    assert "SECRET_KEY" in excinfo.value.errors


def test_clean_submission_accepts_valid_secret():
    secret = "a" * 32
    cleaned = clean_submission(_build_form(secret))

    assert cleaned["SECRET_KEY"] == secret
    assert cleaned["DEFAULT_LED_LINES"] == "Line 1,Line 2"
