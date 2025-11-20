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

"""Pytest configuration and shared fixtures for EAS Station tests.

This module provides common fixtures, test utilities, and configuration
that can be used across all test modules.
"""
import os
import sys
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, MagicMock

import pytest

# Add project root to Python path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Session-level fixtures
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir(project_root: Path) -> Path:
    """Return the test data directory."""
    data_dir = project_root / "tests" / "test_data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


@pytest.fixture(scope="session")
def test_logs_dir(project_root: Path) -> Path:
    """Return the test logs directory."""
    logs_dir = project_root / "tests" / "logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir


# ============================================================================
# Function-level fixtures
# ============================================================================

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test use.
    
    The directory is automatically cleaned up after the test.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_file(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary file for test use.
    
    The file is automatically cleaned up after the test.
    """
    tmp_file = temp_dir / "test_file.tmp"
    tmp_file.touch()
    yield tmp_file


@pytest.fixture
def mock_env(monkeypatch) -> dict:
    """Provide a clean environment with common test variables.
    
    Returns a dictionary that can be modified to set environment variables.
    All changes are automatically reverted after the test.
    """
    env = {
        "TESTING": "true",
        "SECRET_KEY": "test-secret-key-not-for-production",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test_eas_station",
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_password",
        "EAS_BROADCAST_ENABLED": "false",
        "GPIO_ENABLED": "false",
    }
    
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    
    return env


# ============================================================================
# Mocked component fixtures
# ============================================================================

@pytest.fixture
def mock_database():
    """Provide a mock database connection."""
    mock_db = Mock()
    mock_db.connect.return_value = True
    mock_db.execute = Mock()
    mock_db.fetchall = Mock(return_value=[])
    mock_db.fetchone = Mock(return_value=None)
    mock_db.commit = Mock()
    mock_db.rollback = Mock()
    mock_db.close = Mock()
    return mock_db


@pytest.fixture
def mock_gpio_controller():
    """Provide a mock GPIO controller for testing without hardware."""
    from unittest.mock import MagicMock
    
    mock_gpio = MagicMock()
    mock_gpio.add_pin = Mock()
    mock_gpio.set_high = Mock()
    mock_gpio.set_low = Mock()
    mock_gpio.get_state = Mock(return_value="inactive")
    mock_gpio.get_all_states = Mock(return_value={})
    mock_gpio.cleanup = Mock()
    
    return mock_gpio


@pytest.fixture
def mock_audio_source():
    """Provide a mock audio source for testing."""
    mock_source = Mock()
    mock_source.start = Mock()
    mock_source.stop = Mock()
    mock_source.read_frames = Mock(return_value=b'\x00' * 1024)
    mock_source.get_status = Mock(return_value={
        "status": "active",
        "peak_db": -20.0,
        "rms_db": -30.0,
    })
    return mock_source


@pytest.fixture
def mock_radio_receiver():
    """Provide a mock radio receiver for testing."""
    mock_receiver = Mock()
    mock_receiver.start = Mock()
    mock_receiver.stop = Mock()
    mock_receiver.get_frequency = Mock(return_value=162550000)
    mock_receiver.set_frequency = Mock()
    mock_receiver.get_signal_strength = Mock(return_value=-40.0)
    mock_receiver.get_status = Mock(return_value={
        "frequency": 162550000,
        "signal_strength": -40.0,
        "locked": True,
    })
    return mock_receiver


# ============================================================================
# Test data fixtures
# ============================================================================

@pytest.fixture
def sample_wav_header() -> bytes:
    """Provide a minimal valid WAV file header.
    
    This creates a 1-second, 44100 Hz, mono, 16-bit PCM file header.
    """
    return bytes([
        0x52, 0x49, 0x46, 0x46,  # "RIFF"
        0x24, 0x00, 0x00, 0x00,  # File size - 8
        0x57, 0x41, 0x56, 0x45,  # "WAVE"
        0x66, 0x6D, 0x74, 0x20,  # "fmt "
        0x10, 0x00, 0x00, 0x00,  # Subchunk size
        0x01, 0x00,              # Audio format (PCM)
        0x01, 0x00,              # Channels (mono)
        0x44, 0xAC, 0x00, 0x00,  # Sample rate (44100)
        0x88, 0x58, 0x01, 0x00,  # Byte rate
        0x02, 0x00,              # Block align
        0x10, 0x00,              # Bits per sample
        0x64, 0x61, 0x74, 0x61,  # "data"
        0x00, 0x00, 0x00, 0x00,  # Data size
    ])


@pytest.fixture
def sample_env_config(temp_dir: Path) -> Path:
    """Create a sample .env configuration file for testing.
    
    Returns the path to the created .env file.
    """
    env_file = temp_dir / ".env"
    env_content = """
# Test Configuration
SECRET_KEY=test-secret-key-12345
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=test_eas_station
POSTGRES_USER=test_user
POSTGRES_PASSWORD=test_password
DEFAULT_COUNTY_NAME=Test County
DEFAULT_STATE_CODE=XX
EAS_BROADCAST_ENABLED=false
GPIO_ENABLED=false
"""
    env_file.write_text(env_content.strip())
    return env_file


# ============================================================================
# Test markers and utilities
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Register custom markers
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, no external dependencies)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (may use mocks)"
    )
    config.addinivalue_line(
        "markers", "functional: Functional tests (complete workflows)"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take more than 1 second"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers automatically."""
    for item in items:
        # Add 'unit' marker to tests without any marker
        if not any(item.iter_markers()):
            item.add_marker(pytest.mark.unit)
        
        # Mark tests in integration modules
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        
        # Mark tests that involve specific components
        if "audio" in item.nodeid.lower():
            item.add_marker(pytest.mark.audio)
        
        if "gpio" in item.nodeid.lower():
            item.add_marker(pytest.mark.gpio)
        
        if "radio" in item.nodeid.lower():
            item.add_marker(pytest.mark.radio)


# ============================================================================
# Test session hooks
# ============================================================================

def pytest_sessionstart(session):
    """Called before test session starts."""
    # Create test directories if they don't exist
    project_root = Path(__file__).resolve().parents[1]
    
    test_data_dir = project_root / "tests" / "test_data"
    test_data_dir.mkdir(exist_ok=True)
    
    test_logs_dir = project_root / "tests" / "logs"
    test_logs_dir.mkdir(exist_ok=True)


def pytest_sessionfinish(session, exitstatus):
    """Called after test session finishes."""
    # Clean up any temporary test data if needed
    pass
