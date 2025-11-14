# EAS Station Test Suite

This directory contains the test suite for EAS Station, including unit tests, integration tests, and functional tests.

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
- `docker` - Tests requiring Docker environment

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
- May require Docker environment
- Focus on system behavior

## Continuous Integration

The test suite is designed to run in CI/CD environments:

```bash
# In CI pipeline
pytest --tb=short --strict-markers -ra
```

### Docker-based Testing

Run tests in Docker environment:
```bash
docker compose exec app pytest
```

Run specific test file in Docker:
```bash
docker compose exec app pytest tests/test_gpio_controller.py -v
```

## Writing Tests

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
