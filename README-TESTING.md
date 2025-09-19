# Testing Guide

This document explains how to run tests for the SCST Python Configurator.

## Quick Start

```bash
# Navigate to the package directory
cd pyscstadmin/

# Run all tests
python -m pytest

# Run tests with verbose output  
python -m pytest -v

# Run specific test file
python -m pytest tests/test_admin.py

# Run tests with coverage
python -m pytest --cov=scstadmin
```

## Using Development Tools

### Option 1: Makefile

```bash
# Navigate to package directory first
cd pyscstadmin/

# Show available commands
make help

# Run all tests
make test

# Run specific test file
make test-specific FILE=test_admin

# Run with coverage
make test-coverage

# Run linting
make lint

# Clean cache files
make clean
```

### Option 2: Development Script

```bash
# Navigate to package directory first
cd pyscstadmin/

# Run all tests
python dev.py test

# Run specific test file  
python dev.py test --file admin

# Run with coverage
python dev.py test --coverage

# Run linting
python dev.py lint

# Clean cache files
python dev.py clean
```

## Test Organization

All tests are located in the `tests/` directory:

- `tests/test_admin.py` - Admin module functionality (target attributes, config comparison)
- `tests/test_config.py` - Structured configuration objects (DeviceConfig, etc.)
- `tests/test_copy_manager.py` - Copy manager LUN filtering
- `tests/test_device_attributes.py` - Device attribute properties
- `tests/test_logging.py` - Logging functionality
- `tests/test_modules.py` - Module functionality and imports
- `tests/test_parser.py` - Configuration file parsing
- `tests/test_parsing_errors.py` - Parser error handling
- `tests/test_readers.py` - Reader functionality (configuration reading from sysfs)
- `tests/test_structured_parsing.py` - Structured object parsing
- `tests/test_writers.py` - Writer functionality (TargetWriter, DeviceWriter, GroupWriter)

## Test Configuration

- `pytest.ini` - PyTest configuration
- `tests/conftest.py` - Shared fixtures and setup
- `tests/fixtures/` - Test data files

## Running Tests During Development

For continuous testing during development:

```bash
# Install pytest-watch (optional)
pip install pytest-watch

# Run tests in watch mode
make test-watch
# or
pytest --watch
```

## Coverage Reports

Generate test coverage reports:

```bash
# HTML coverage report (opens in browser)
make test-coverage

# Terminal coverage report
python -m pytest --cov=scstadmin --cov-report=term
```

Coverage reports are generated in `htmlcov/` directory.

## Adding New Tests

1. Create test files in `tests/` directory with `test_` prefix
2. Import modules using relative imports (handled by `conftest.py`)
3. Follow pytest naming conventions:
   - Functions: `test_function_name()`
   - Classes: `TestClassName`
   - Files: `test_module_name.py`

Example test structure:

```python
# tests/test_new_feature.py
from scstadmin.admin import SCSTAdmin
from scstadmin.config import SCSTConfig

def test_new_feature():
    """Test description."""
    admin = SCSTAdmin()
    # Test implementation
    assert True

class TestNewFeatureClass:
    def test_method_one(self):
        """Test method description."""
        pass
```

## Test Dependencies

The test suite requires:
- `pytest` - Test framework
- `pytest-cov` - Coverage reporting  
- `pytest-watch` - Watch mode (optional)

Install development dependencies:
```bash
make install-dev
# or
pip install pytest pytest-cov pytest-watch
```