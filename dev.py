#!/usr/bin/env python3
"""
Development helper script for SCST Python Configurator.

Usage:
    python dev.py test                  # Run all tests
    python dev.py test --file admin     # Run specific test file
    python dev.py test --coverage       # Run with coverage
    python dev.py lint                  # Run linting
    python dev.py clean                 # Clean cache files
"""

import argparse
import subprocess
import sys
import shutil
from pathlib import Path


def run_command(cmd, description=""):
    """Run a command and handle errors."""
    if description:
        print(f"🔄 {description}")

    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=False)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {cmd}")
        print(f"   Exit code: {e.returncode}")
        return False


def run_tests(args):
    """Run tests with various options."""
    cmd = "python -m pytest"

    if args.file:
        cmd += f" tests/test_{args.file}.py"

    if args.coverage:
        cmd += " --cov=scstadmin --cov-report=html --cov-report=term"

    if args.verbose:
        cmd += " -v"

    return run_command(cmd, "Running tests")


def run_lint(args):
    """Run linting."""
    cmd = "python -m flake8 --max-line-length=120 scstadmin"
    return run_command(cmd, "Running flake8 linting")


def clean_cache(args):
    """Clean Python cache files."""
    print("🧹 Cleaning cache files...")

    # Remove __pycache__ directories
    for pycache in Path(".").rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache)
            print(f"   Removed {pycache}")

    # Remove .pyc files
    for pyc in Path(".").rglob("*.pyc"):
        pyc.unlink()
        print(f"   Removed {pyc}")

    # Remove all .pytest_cache directories recursively
    for pytest_cache in Path(".").rglob(".pytest_cache"):
        if pytest_cache.is_dir():
            shutil.rmtree(pytest_cache)
            print(f"   Removed {pytest_cache}")

    # Remove other cache directories
    cache_items = ["htmlcov", ".coverage"]
    for cache_item in cache_items:
        cache_path = Path(cache_item)
        if cache_path.exists():
            if cache_path.is_dir():
                shutil.rmtree(cache_path)
            else:
                cache_path.unlink()
            print(f"   Removed {cache_path}")

    print("✅ Cache cleanup complete")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Development helper for SCST Python Configurator"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Test command
    test_parser = subparsers.add_parser("test", help="Run tests")
    test_parser.add_argument(
        "--file", help="Run specific test file (e.g., 'admin' for test_admin.py)"
    )
    test_parser.add_argument(
        "--coverage", action="store_true", help="Run with coverage report"
    )
    test_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output"
    )

    # Lint command
    subparsers.add_parser("lint", help="Run linting")

    # Clean command
    subparsers.add_parser("clean", help="Clean cache files")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to appropriate function
    commands = {
        "test": run_tests,
        "lint": run_lint,
        "clean": clean_cache,
    }

    if args.command in commands:
        success = commands[args.command](args)
        return 0 if success else 1
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
