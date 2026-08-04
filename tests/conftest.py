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

"""Pytest configuration and shared fixtures for EAS Station tests.

This module provides common fixtures, test utilities, and configuration
that can be used across all test modules.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Generator
from unittest.mock import Mock, MagicMock

import pytest

# Add project root to Python path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Import-time environment defaults
# ============================================================================
# Several test modules do a module-level ``from app import ...`` to assert on
# module constants (allowlists, route tables). Importing ``app`` raises
# ValueError unless DATABASE_URL is already set, so a fixture cannot help —
# the import happens during collection, before any fixture runs. conftest.py is
# imported before the test modules it covers, so seeding the defaults here makes
# a bare ``pytest`` invocation work with no external services, exactly as
# tests/README.md documents. setdefault() keeps any real values the caller
# exported (e.g. a CI job pointing at a live PostgreSQL service container).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")
os.environ.setdefault("SKIP_DB_INIT", "1")
os.environ.setdefault("TESTING", "true")


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
# Authentication helpers
# ============================================================================

def make_stub_user(role_name: str = "admin", user_id: int = 1):
    """Build a stand-in for an authenticated AdminUser.

    Only the attributes the auth decorators actually touch are provided:
    ``is_active``, ``id``, ``role.name`` and ``role.has_permission()``.
    """
    role = SimpleNamespace(
        name=role_name,
        has_permission=lambda _permission_name: True,
    )
    return SimpleNamespace(id=user_id, is_active=True, role=role)


@pytest.fixture
def authenticated_user(monkeypatch):
    """Satisfy the deny-by-default auth gate with an active stub user.

    Routes are guarded by ``require_auth`` / ``require_role`` /
    ``require_permission``. All three resolve the caller through
    ``app_core.auth.roles.get_current_user()``, which reads
    ``session['user_id']`` and then loads an AdminUser row from the database.
    Tests running against an empty in-memory SQLite database cannot satisfy
    that, so every protected route returned 401 regardless of what the test was
    actually trying to assert.

    The lookup is patched in both modules that hold a reference to it —
    ``roles`` (where it is defined and where ``has_permission`` calls it) and
    ``decorators`` (which did ``from .roles import get_current_user`` at import
    time, binding its own name).

    Patching the lookup is deliberate rather than seeding a real user row:
    these tests exercise route behaviour, not the authentication chain itself.
    The gate has its own dedicated coverage in ``test_public_pages_authz.py``
    and the RBAC suite, which must keep exercising the real code path — so do
    not reach for this fixture there.

    Yields the stub user so a test can adjust it, e.g.::

        def test_something(authenticated_user, client):
            authenticated_user.role.name = "operator"
    """
    from app_core.auth import decorators as auth_decorators
    from app_core.auth import roles as auth_roles

    user = make_stub_user()

    # Patch the module objects rather than dotted-path strings: monkeypatch
    # resolves a string path by walking attributes from the top-level package,
    # and `app_core.auth` is not exposed as an attribute of `app_core` unless
    # something has already imported it.
    for module in (auth_roles, auth_decorators):
        monkeypatch.setattr(module, "get_current_user", lambda: user, raising=True)

    # require_permission() routes through roles.has_permission(), which does its
    # own get_current_user() call plus a role lookup; short-circuit it so a stub
    # role without a real permission table still passes.
    monkeypatch.setattr(
        auth_roles,
        "has_permission",
        lambda _permission_name, user=None: True,
        raising=True,
    )

    yield user


# ============================================================================
# Test markers and utilities
# ============================================================================

# Marker registration lives in pyproject.toml under
# [tool.pytest.ini_options] markers, which runs with --strict-markers so an
# unregistered mark is an error rather than a silently-dropped no-op. The
# `audio`, `gpio` and `radio` marks applied below were never registered here,
# which is why every run emitted PytestUnknownMarkWarning for them.


KNOWN_FAILURES_FILE = Path(__file__).parent / "known_failures.txt"


def _load_known_failures() -> set:
    """Read tests/known_failures.txt into a set of node IDs / file paths.

    Blank lines and ``#`` comments are ignored, as is any trailing comment on
    an entry line. Entries may be either a full node ID
    (``tests/test_x.py::test_y``) or a whole file (``tests/test_x.py``).
    """
    if not KNOWN_FAILURES_FILE.is_file():
        return set()

    entries = set()
    for raw_line in KNOWN_FAILURES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


_KNOWN_FAILURES = _load_known_failures()


def _is_known_failure(node_id: str) -> bool:
    """True if *node_id* is listed directly or via its containing file."""
    if node_id in _KNOWN_FAILURES:
        return True
    file_part = node_id.split("::", 1)[0]
    return file_part in _KNOWN_FAILURES


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers automatically."""
    for item in items:
        # Known-failing tests are marked xfail rather than skipped or
        # deselected, so they still execute. A test that starts passing reports
        # XPASS, which is the signal to delete its line from
        # tests/known_failures.txt. non-strict so an XPASS does not fail the
        # run — the list is a shrinking backlog, not a contract.
        if _is_known_failure(item.nodeid):
            item.add_marker(
                pytest.mark.xfail(
                    reason="listed in tests/known_failures.txt", strict=False
                )
            )

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


# ============================================================================
# Flask application fixtures
# ============================================================================

@pytest.fixture
def app(mock_env, monkeypatch):
    """Create and configure a test Flask app instance.
    
    Args:
        mock_env: Pre-configured environment variables from conftest
        monkeypatch: Pytest fixture for modifying environment variables
    
    Returns:
        Flask app instance configured for testing
    """
    monkeypatch.setenv('SKIP_DB_INIT', '1')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    flask_app.config['SETUP_MODE'] = False
    
    return flask_app


@pytest.fixture
def app_client(app):
    """Create a test client for the Flask app.
    
    Args:
        app: Flask app instance from the app fixture
    
    Returns:
        Flask test client for making HTTP requests
    """
    return app.test_client()
