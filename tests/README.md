# EAS Station™ Test Suite

This directory contains the test suite for EAS Station™, including unit tests, integration tests, and functional tests.

## Running Tests

### Prerequisites

Install test dependencies:

```bash
pip install pytest pytest-asyncio
```

Or install all project dependencies:

```bash
pip install -r requirements.txt
```

### Basic Test Execution

Run all tests:
```bash
pytest
```

No database, Redis or other service is required for a bare `pytest` run.
`conftest.py` seeds `DATABASE_URL=sqlite:///:memory:`, `SKIP_DB_INIT=1`,
`SECRET_KEY` and `TESTING` at import time. Because it uses `setdefault`, any
value you export yourself wins — which is how CI points the suite at its Redis
service container:

```bash
REDIS_HOST=localhost REDIS_PORT=6379 pytest
```

### Claude Code on the web

`.claude/hooks/session-start.sh` provisions a remote session automatically:
PostGIS and Redis are installed and started, `requirements.txt` plus
pytest/ruff/playwright are installed, the schema is built and stamped, and
`DATABASE_URL` / `SECRET_KEY` / `REDIS_*` / `CHROMIUM_BIN` are exported. A
session therefore starts with the full suite runnable — including the
database-backed tests that otherwise skip.

Schema bootstrap mirrors `install.sh`: `db.create_all()` followed by
`alembic stamp head`. A bare `alembic upgrade head` cannot build an empty
database — no migration creates the base tables, so the first one referencing
`cap_alerts` fails. Stamping means a migration added during a session applies
cleanly with `alembic upgrade head`.

The hook only runs when `CLAUDE_CODE_REMOTE=true`, so it never touches a
developer's own machine.

### Continuous Integration

`.github/workflows/tests.yml` runs this suite on every pull request and on
pushes to `main` / `develop`, across Python 3.11 and 3.13, with a Redis service
container. A separate `lint` job runs `ruff check .` against the enforced rule
set declared in `pyproject.toml`.

### Known failures

`tests/known_failures.txt` lists tests that do not currently pass in a clean
environment — mostly ones needing real hardware or a live SDR service on the
other end of Redis. `conftest.py` marks them **xfail rather than skipping
them**, so they still execute:

- a listed test that fails is reported `xfail` and does not break the build
- a listed test that *passes* is reported `XPASS` — the signal to delete its
  line from the file

Entries may be a full node ID (`tests/test_x.py::test_y`) or a whole file
(`tests/test_x.py`). `#` comments and blank lines are ignored. **This list is a
backlog and is meant to shrink to nothing** — if you fix a test, remove its
entry in the same change.

### Testing authenticated routes

Routes are protected by a deny-by-default gate, so a plain test client gets 401
from anything non-public. Use the shared `authenticated_user` fixture, which
satisfies `require_auth`, `require_role` and `require_permission`:

```python
def test_my_admin_route(client, authenticated_user):
    response = client.post('/api/something')
    assert response.status_code == 200
```

The fixture yields the stub user, so a test needing a particular role can
adjust it:

```python
def test_operator_only(client, authenticated_user):
    authenticated_user.role.name = "operator"
```

Do **not** use it in tests that are themselves asserting on authentication
behaviour (`test_public_pages_authz.py`, the RBAC suite) — those must keep
exercising the real code path.

Run tests with verbose output:
```bash
pytest -v
```

Run tests with coverage report:
```bash
pytest --cov=app_core --cov=app_utils --cov=webapp --cov-report=term-missing
```

### Run Specific Tests

Run a specific test file:
```bash
pytest tests/test_gpio_controller.py
```

Run a specific test class:
```bash
pytest tests/test_audio_pipeline_integration.py::TestAudioPipelineIntegration
```

Run a specific test function:
```bash
pytest tests/test_gpio_controller.py::test_add_pin_records_configuration_when_gpio_unavailable
```

### Filter Tests by Marker

Run only unit tests (fast, no external dependencies):
```bash
pytest -m unit
```

Run only integration tests:
```bash
pytest -m integration
```

Run only tests related to GPIO:
```bash
pytest -m gpio
```

Run only tests related to audio processing:
```bash
pytest -m audio
```

Exclude slow tests:
```bash
pytest -m "not slow"
```

Combine markers:
```bash
pytest -m "integration and not slow"
```

### Available Markers

- `unit` - Unit tests (fast, no external dependencies)
- `integration` - Integration tests (may use mocks for external services)
- `functional` - Functional tests (test complete workflows)
- `slow` - Tests that take more than 1 second
- `audio` - Tests involving audio processing
- `gpio` - Tests involving GPIO hardware
- `radio` - Tests involving radio receivers
- `database` - Tests requiring database connection
- `network` - Tests requiring network access

## Test Organization

### Directory Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── test_audio_*.py          # Audio system tests
├── test_gpio_*.py           # GPIO and hardware control tests
├── test_radio_*.py          # Radio receiver tests
├── test_eas_*.py            # EAS encoding/decoding tests
├── test_*_integration.py    # Integration tests
└── test_data/               # Test data files
```

### Test Categories

#### Unit Tests
- Fast execution (< 1 second per test)
- No external dependencies
- Mock all external services
- Focus on single components

Example: `test_gpio_controller.py`

#### Integration Tests
- Test multiple components working together
- May use mocked external services
- Test realistic scenarios
- Focus on component interactions

Example: `test_audio_pipeline_integration.py`

#### Functional Tests
- End-to-end workflow testing
- Test complete user scenarios
- Focus on system behavior

## Continuous Integration

The test suite is designed to run in CI/CD environments:

```bash
# In CI pipeline
pytest --tb=short --strict-markers -ra
```

### Test Naming Convention

- Test files: `test_<module_name>.py`
- Test classes: `Test<ComponentName>`
- Test functions: `test_<behavior_being_tested>`

### Using Fixtures

Common fixtures are available in `conftest.py`:

```python
def test_example(temp_dir, mock_gpio_controller):
    """Test using shared fixtures."""
    # temp_dir is a Path to temporary directory
    # mock_gpio_controller is a mocked GPIO controller
    
    config_file = temp_dir / "config.txt"
    config_file.write_text("test config")
    
    mock_gpio_controller.add_pin(17, "Test Pin")
    assert mock_gpio_controller.get_state(17) == "inactive"
```

Available fixtures:
- `temp_dir` - Temporary directory (auto-cleanup)
- `temp_file` - Temporary file (auto-cleanup)
- `mock_env` - Clean test environment variables
- `mock_database` - Mocked database connection
- `mock_gpio_controller` - Mocked GPIO controller
- `mock_audio_source` - Mocked audio source
- `mock_radio_receiver` - Mocked radio receiver
- `sample_wav_header` - Valid WAV file header bytes
- `sample_env_config` - Sample .env configuration file

### Adding Test Markers

Mark tests with appropriate markers:

```python
import pytest

@pytest.mark.unit
def test_simple_function():
    """Fast unit test."""
    assert True

@pytest.mark.integration
@pytest.mark.audio
def test_audio_pipeline():
    """Integration test for audio pipeline."""
    pass

@pytest.mark.slow
@pytest.mark.functional
def test_complete_workflow():
    """Slow end-to-end test."""
    pass
```

## Debugging Tests

### Run with Debugging Output

```bash
# Show local variables on failure
pytest --showlocals

# Show full traceback
pytest --tb=long

# Drop into debugger on failure
pytest --pdb

# Drop into debugger on first failure
pytest -x --pdb
```

### Enable Logging

```bash
# Show log output during test execution
pytest --log-cli-level=DEBUG

# Save logs to file
pytest --log-file=tests/logs/test_run.log
```

## Test Coverage

### Generate Coverage Report

```bash
# Terminal report with missing lines
pytest --cov=app_core --cov=app_utils --cov=webapp --cov-report=term-missing

# HTML report (opens in browser)
pytest --cov=app_core --cov=app_utils --cov=webapp --cov-report=html
open htmlcov/index.html
```

### Coverage Goals

- Unit tests: > 80% coverage
- Integration tests: > 60% coverage
- Overall: > 70% coverage

## Troubleshooting

### Common Issues

**Import errors:**
```bash
# Ensure project root is in Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest
```

**Missing dependencies:**
```bash
pip install -r requirements.txt
```

**Tests hanging:**
```bash
# Set timeout for tests (requires pytest-timeout)
pytest --timeout=30
```

**Database connection errors:**
- Ensure PostgreSQL is running
- Check connection settings in mock_env fixture
- Use database mocks for unit tests

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [Python unittest.mock](https://docs.python.org/3/library/unittest.mock.html)

## Contributing

When adding new features:

1. Write tests first (TDD approach)
2. Ensure tests are well-documented
3. Add appropriate markers
4. Run full test suite before committing
5. Maintain or improve test coverage

```bash
# Pre-commit checklist
pytest                          # All tests pass
pytest --cov --cov-report=term  # Coverage maintained
pytest -m integration           # Integration tests pass
```
