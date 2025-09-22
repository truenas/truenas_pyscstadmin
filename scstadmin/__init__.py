"""
SCST Administration Library

This module provides a comprehensive Python interface for managing SCST
(SCSI Target Subsystem for Linux) configurations through the kernel sysfs interface.

Main Classes:
    SCSTAdmin: High-level administration interface
    SCSTConfig: Configuration data structure
    SCSTConfigParser: Configuration file parser
    SCSTSysfs: Low-level sysfs interface
    SCSTModuleManager: Kernel module management

Exceptions:
    SCSTError: Base exception for SCST operations

Enums:
    ConfigAction: Actions for configuration management
    SCSTErrorCode: Error classification codes
"""

from .constants import SCSTConstants
from .exceptions import SCSTError
from .config import SCSTConfig, ConfigAction, SCSTErrorCode, LunConfig, InitiatorGroupConfig, TargetConfig, DriverConfig
from .sysfs import SCSTSysfs
from .modules import SCSTModuleManager
from .parser import SCSTConfigParser
from .readers import SCSTConfigurationReader

# Import admin last to avoid circular imports
try:
    from .admin import SCSTAdmin
except ImportError:
    # Admin not available yet during refactor
    pass

__all__ = [
    'SCSTAdmin',
    'SCSTConfig',
    'SCSTConfigParser',
    'SCSTSysfs',
    'SCSTModuleManager',
    'SCSTConfigurationReader',
    'SCSTError',
    'ConfigAction',
    'SCSTErrorCode',
    'SCSTConstants',
    'LunConfig',
    'InitiatorGroupConfig',
    'TargetConfig',
    'DriverConfig'
]
