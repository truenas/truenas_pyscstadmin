"""
SCST Configuration Reader - Main Orchestrator

This module provides the main SCSTConfigurationReader class which coordinates
specialized readers for different domains of SCST configuration. It maintains
the same interface as the original reader while delegating to specialized
domain readers for improved organization and maintainability.
"""

import logging
import os
from typing import Optional, Set, Dict

from ..config import SCSTConfig
from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError
from .device_reader import DeviceReader
from .target_reader import TargetReader
from .group_reader import DeviceGroupReader


class SCSTConfigurationReader:
    """Main orchestrator for SCST configuration reading.

    This class coordinates specialized readers for different SCST domains:
    - DeviceReader: Device discovery and configuration
    - TargetReader: Target/driver management and LUN operations
    - DeviceGroupReader: Device group and target group discovery

    It provides the same interface as the original monolithic reader while
    benefiting from improved organization and domain separation.
    """

    def __init__(self, sysfs: SCSTSysfs):
        self.sysfs = sysfs
        self.logger = logging.getLogger(__name__)

        # Initialize specialized readers
        self.device_reader = DeviceReader(sysfs)
        self.target_reader = TargetReader(sysfs)
        self.group_reader = DeviceGroupReader(sysfs)

    def read_current_config(self) -> SCSTConfig:
        """Discover existing SCST entities for cleanup operations.

        This method performs lightweight discovery of what SCST entities currently
        exist (handlers, devices, targets, device groups) without reading their
        detailed attributes. It's primarily used by _remove_conflicting_config()
        to determine what needs to be removed before applying a new configuration.

        For detailed attribute reading and configuration validation, use the
        specific methods on the specialized readers.

        Returns:
            SCSTConfig with minimal entity discovery (names only, empty attributes)
        """
        if not self.check_scst_available():
            raise SCSTError("SCST is not available")

        config = SCSTConfig()

        # Read handlers - minimal discovery only
        handlers_path = self.sysfs.SCST_HANDLERS
        for handler in self.sysfs.list_directory(handlers_path):
            config.handlers[handler] = {}

        # Delegate device reading to DeviceReader
        config.devices = self.device_reader.read_devices()

        # Delegate driver/target reading to TargetReader
        config.drivers = self.target_reader.read_drivers()

        # Delegate device group reading to DeviceGroupReader
        config.device_groups = self.group_reader.read_device_groups()

        return config

    def _safe_read_attribute(self, attr_path: str) -> Optional[str]:
        """Safely read a sysfs attribute, returning None on any error"""
        try:
            if os.path.isfile(attr_path):
                return self.sysfs.read_sysfs_attribute(attr_path)
        except (OSError, IOError, SCSTError):
            pass
        return None

    def _read_attribute_if_non_default(self, attr_path: str) -> Optional[str]:
        """Read an attribute only if it has a non-default value (indicated by [key] suffix)

        Returns the clean attribute value if non-default, None if default or unreadable
        """
        try:
            raw_value = self.sysfs.read_sysfs(attr_path)
            raw_stripped = raw_value.strip()

            # Check if it has the [key] suffix indicating non-default value
            if raw_stripped.endswith('[key]'):
                # Strip off the [key] suffix to get clean value
                clean_value = raw_stripped[:-5].strip()
                return clean_value
            else:
                # No [key] means it's at default value
                return None
        except SCSTError:
            return None

    def check_scst_available(self) -> bool:
        """Check if SCST is loaded and available"""
        return self.sysfs.valid_path(self.sysfs.SCST_ROOT)

    # Delegate methods to specialized readers for backward compatibility
    def _get_current_device_attrs(self, handler: str, device_name: str,
                                  filter_attrs: Optional[Set[str]] = None) -> Dict[str, str]:
        """Delegate to DeviceReader for backward compatibility"""
        return self.device_reader._get_current_device_attrs(handler, device_name, filter_attrs)

    def _get_current_target_attrs(self, driver: str, target_name: str,
                                  filter_attrs: Optional[Set[str]] = None) -> Dict[str, str]:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_current_target_attrs(driver, target_name, filter_attrs)

    def _get_target_create_params(self, driver_name: str, target_attrs: Dict[str, str]) -> Dict[str, str]:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_target_create_params(driver_name, target_attrs)

    def _get_lun_create_params(self, driver: str, target: str, lun_attrs: Dict[str, str]) -> Dict[str, str]:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_lun_create_params(driver, target, lun_attrs)

    def _get_current_lun_device(self, driver: str, target: str, lun_number: str) -> str:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_current_lun_device(driver, target, lun_number)

    def _get_current_group_lun_device(self, driver: str, target: str, group_name: str, lun_number: str) -> str:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_current_group_lun_device(driver, target, group_name, lun_number)

    def _get_driver_attribute_default(self, driver_name: str, attr_name: str) -> Optional[str]:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_driver_attribute_default(driver_name, attr_name)

    def _get_target_mgmt_info(self, driver_name: str) -> Dict[str, set]:
        """Delegate to TargetReader for backward compatibility"""
        return self.target_reader._get_target_mgmt_info(driver_name)
