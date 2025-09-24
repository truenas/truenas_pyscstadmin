.PHONY: test test-verbose test-watch lint format clean help

# Default Python executable
PYTHON := python3

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

test:  ## Run all tests
	$(PYTHON) -m pytest

test-verbose:  ## Run tests with verbose output
	$(PYTHON) -m pytest -v

test-watch:  ## Run tests in watch mode (requires pytest-watch)
	$(PYTHON) -m pytest --watch

test-coverage:  ## Run tests with coverage report
	$(PYTHON) -m pytest --cov=scstadmin --cov-report=html --cov-report=term

test-specific:  ## Run specific test file (usage: make test-specific FILE=test_admin)
	$(PYTHON) -m pytest tests/$(FILE).py

lint:  ## Run flake8 linting
	$(PYTHON) -m flake8 --max-line-length=120 scstadmin

format:  ## Format code with black (if available)
	$(PYTHON) -m black --line-length 120 scstadmin tests

clean:  ## Clean up Python cache files and build artifacts
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + || true
	rm -rf htmlcov .coverage build dist .pybuild
	rm -rf debian/.debhelper debian/debhelper-build-stamp debian/files
	rm -rf debian/*.debhelper.log debian/*.postinst.debhelper debian/*.prerm.debhelper
	rm -rf debian/*.substvars debian/python3-truenas-pyscstadmin/

install-dev:  ## Install development dependencies
	pip install pytest pytest-cov pytest-watch flake8 black

# Examples:
# make test
# make test-specific FILE=test_admin
# make test-coverage
# make lint
