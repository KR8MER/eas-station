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

"""Tests for GPIO behavior matrix persistence via database settings."""

import json
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_utils.gpio as gpio


def test_gpio_behavior_matrix_database_save(monkeypatch):
    """Test that GPIO behavior matrix can be serialized and loaded from database settings."""
    from app_utils.gpio import (
        GPIOBehavior,
        load_gpio_behavior_matrix_from_db,
        serialize_gpio_behavior_matrix,
    )

    # Create a behavior matrix
    original_matrix = {
        17: {GPIOBehavior.DURATION_OF_ALERT},
        18: {GPIOBehavior.PLAYOUT, GPIOBehavior.FLASH},
        22: {GPIOBehavior.INCOMING_ALERT},
    }

    # Serialize it
    serialized = serialize_gpio_behavior_matrix(original_matrix)
    assert serialized
    assert isinstance(serialized, str)

    # Verify it's valid JSON
    parsed = json.loads(serialized)
    assert "17" in parsed
    assert "18" in parsed
    assert "22" in parsed

    # Mock database settings to return the serialized matrix
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(
        gpio,
        "get_gpio_settings",
        lambda: {"pin_map": {}, "behavior_matrix": parsed},
    )

    # Load it back
    loaded_matrix = load_gpio_behavior_matrix_from_db()

    # Verify all pins and behaviors are preserved
    assert 17 in loaded_matrix
    assert 18 in loaded_matrix
    assert 22 in loaded_matrix

    assert GPIOBehavior.DURATION_OF_ALERT in loaded_matrix[17]
    assert GPIOBehavior.PLAYOUT in loaded_matrix[18]
    assert GPIOBehavior.FLASH in loaded_matrix[18]
    assert GPIOBehavior.INCOMING_ALERT in loaded_matrix[22]


def test_gpio_behavior_matrix_empty_handling(monkeypatch):
    """Test that empty behavior matrix is handled correctly."""
    from app_utils.gpio import load_gpio_behavior_matrix_from_db

    # Test with empty dict from database
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(
        gpio,
        "get_gpio_settings",
        lambda: {"pin_map": {}, "behavior_matrix": {}},
    )
    matrix = load_gpio_behavior_matrix_from_db()
    assert matrix == {}

    # Test with None behavior_matrix
    monkeypatch.setattr(
        gpio,
        "get_gpio_settings",
        lambda: {"pin_map": {}, "behavior_matrix": None},
    )
    matrix = load_gpio_behavior_matrix_from_db()
    assert matrix == {}


def test_env_file_write_and_read():
    """Test that environment variables can be written and read from .env file."""
    from webapp.admin.environment import read_env_file, write_env_file

    # Create a temporary .env file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.env') as tmp:
        tmp_path = Path(tmp.name)
        tmp.write("# Test .env file\n")
        tmp.write("TEST_VAR=original_value\n")
        tmp.write("ANOTHER_VAR=another_value\n")

    try:
        # Mock the get_env_file_path to return our temp file
        import webapp.admin.environment as env_module
        original_get_path = env_module.get_env_file_path
        env_module.get_env_file_path = lambda: tmp_path

        # Read the file
        env_vars = read_env_file()
        assert env_vars["TEST_VAR"] == "original_value"
        assert env_vars["ANOTHER_VAR"] == "another_value"

        # Update a variable
        env_vars["TEST_VAR"] = "updated_value"
        env_vars["NEW_VAR"] = "new_value"

        # Write it back
        write_env_file(env_vars)

        # Read again to verify
        env_vars = read_env_file()
        assert env_vars["TEST_VAR"] == "updated_value"
        assert env_vars["ANOTHER_VAR"] == "another_value"
        assert env_vars["NEW_VAR"] == "new_value"

        # Verify the file still has comments
        with open(tmp_path, 'r') as f:
            content = f.read()
            assert "# Test .env file" in content

        # Restore original function
        env_module.get_env_file_path = original_get_path

    finally:
        # Clean up temp file
        if tmp_path.exists():
            tmp_path.unlink()


def test_gpio_behavior_matrix_with_single_behavior(monkeypatch):
    """Test behavior matrix with single behavior per pin (common case from UI)."""
    from app_utils.gpio import GPIOBehavior, load_gpio_behavior_matrix_from_db

    # Simulate what the UI sends - single behavior in array
    behavior_matrix = {"17": ["duration_of_alert"], "18": ["playout"]}

    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(
        gpio,
        "get_gpio_settings",
        lambda: {"pin_map": {}, "behavior_matrix": behavior_matrix},
    )

    matrix = load_gpio_behavior_matrix_from_db()

    assert 17 in matrix
    assert 18 in matrix
    assert GPIOBehavior.DURATION_OF_ALERT in matrix[17]
    assert GPIOBehavior.PLAYOUT in matrix[18]


def test_gpio_behavior_matrix_database_unavailable(monkeypatch):
    """Test that unavailable database settings returns empty dict gracefully."""
    from app_utils.gpio import load_gpio_behavior_matrix_from_db

    # Simulate database settings not available
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", False)

    matrix = load_gpio_behavior_matrix_from_db()
    assert matrix == {}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
