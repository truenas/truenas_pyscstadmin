"""
Exception classes for SCST operations.

This module defines the exception hierarchy used throughout the SCST Python
configurator library for consistent error handling.
"""


class SCSTError(Exception):
    """Base exception class for all SCST-related errors.

    This exception is raised for all SCST operation failures including:
    - Sysfs interface errors (permission, path not found, etc.)
    - Configuration parsing errors
    - Device/target management failures
    - System state inconsistencies

    All SCST Python configurator operations should catch and handle SCSTError
    rather than generic exceptions for proper error handling.
    """

    pass
