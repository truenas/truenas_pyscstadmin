"""
SCST Device Configuration Reader

Handles device discovery, handler type detection, and DeviceConfig creation.
This module focuses on device-specific operations within the SCST configuration.
"""

import logging
import os
from typing import Dict, Set, Optional

from ..config import DeviceConfig, create_device_config
from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError


class DeviceReader:
    """Reads SCST device configuration from sysfs.

    This class handles device discovery, handler type detection, and creation
    of structured DeviceConfig objects from sysfs attributes.
    """

    def __init__(self, sysfs: SCSTSysfs):
        self.sysfs = sysfs
        self.logger = logging.getLogger(__name__)

    def _get_device_handler_type(self, device_name: str) -> Optional[str]:
        """Determine the handler type for a device by reading the handler symlink.

        Args:
            device_name: Name of the device

        Returns:
            Handler type (e.g., 'vdisk_fileio', 'vdisk_blockio', 'dev_disk') or None if not found
        """
        handler_link = f"{self.sysfs.SCST_DEVICES}/{device_name}/handler"
        try:
            if os.path.islink(handler_link):
                # Read the symlink target: ../../handlers/vdisk_fileio -> vdisk_fileio
                target = os.readlink(handler_link)
                # Extract handler name from path like "../../handlers/vdisk_fileio"
                handler_type = os.path.basename(target)
                return handler_type
        except (OSError, IOError) as e:
            self.logger.warning("Failed to read handler type for device '%s': %s", device_name, e)
        return None

    def _create_minimal_device_config(self, device_name: str, handler_type: str) -> Optional['DeviceConfig']:
        """Create a minimal DeviceConfig object for cleanup operations.

        Args:
            device_name: Name of the device
            handler_type: SCST handler type

        Returns:
            DeviceConfig object or None if creation fails
        """
        try:
            # Create minimal device config with empty filename for cleanup operations
            minimal_attrs = {'filename': ''}  # Required field for all device types
            device_config = create_device_config(device_name, handler_type, minimal_attrs)
            if device_config is None:
                self.logger.error("Unknown handler type '%s' for device '%s', skipping", handler_type, device_name)
            return device_config
        except (ValueError, TypeError) as e:
            self.logger.error("Failed to create DeviceConfig for '%s' (handler: %s): %s", device_name, handler_type, e)
            return None

    def _safe_read_attribute(self, attr_path: str) -> Optional[str]:
        """Safely read a sysfs attribute, returning None on any error"""
        try:
            if os.path.isfile(attr_path):
                return self.sysfs.read_sysfs_attribute(attr_path)
        except (OSError, IOError, SCSTError):
            pass
        return None

    def _get_current_device_attrs(self, handler: str, device_name: str,
                                  filter_attrs: Optional[Set[str]] = None) -> Dict[str, str]:
        """Read current device attributes from SCST sysfs interface.

        This method reads the live attribute values for an existing SCST device
        from the sysfs filesystem. It's used for configuration comparison and
        optimization (avoiding unnecessary writes when values already match).

        The method can operate in two modes:
        1. Filtered: Read only specific attributes (more efficient)
        2. Full scan: Read all available attributes (fallback mode)

        Args:
            handler: SCST handler name (e.g., 'vdisk_blockio', 'dev_disk')
            device_name: Name of the device within the handler
            filter_attrs: Optional set of specific attribute names to read.
                         If None, reads all available attributes.

        Returns:
            Dictionary mapping attribute names to their current values.
            Returns empty dict if device doesn't exist or can't be read.
            Always excludes 'handler' attribute as it's metadata.

        Example:
            _get_current_device_attrs('vdisk_blockio', 'disk1', {'read_only', 'rotational'})
            -> {'read_only': '0', 'rotational': '1'}
        """
        attrs = {}
        try:
            device_path = f"{self.sysfs.SCST_HANDLERS}/{handler}/{device_name}"
            if not os.path.exists(device_path):
                return attrs

            # If filter is provided, only read those specific attributes
            if filter_attrs:
                for attr in filter_attrs:
                    if attr == 'handler':  # Skip handler attribute
                        continue
                    attr_path = os.path.join(device_path, attr)
                    value = self._safe_read_attribute(attr_path)
                    if value is not None:
                        attrs[attr] = value
            else:
                # Read all attribute files in the device directory (fallback)
                for item in os.listdir(device_path):
                    item_path = os.path.join(device_path, item)
                    if not item.startswith('.'):
                        value = self._safe_read_attribute(item_path)
                        if value is not None:
                            attrs[item] = value
            return attrs
        except (OSError, IOError):
            return attrs

    def _parse_mgmt_parameters(self, mgmt_content: str) -> Set[str]:
        """Parse SCST management interface output to extract available parameters.

        SCST management interfaces provide help text when read, listing the available
        parameters for operations like device creation. This method extracts those
        parameter names from the formatted help output.

        The expected format is:
        "The following parameters available: param1, param2, param3."

        Args:
            mgmt_content: Raw text content from reading an SCST mgmt interface file

        Returns:
            Set of parameter names that can be used with SCST commands.
            Returns empty set if no parameter line is found.

        Example:
            Input: "Usage: add_device dev_name [parameters]\\n" +
                   "The following parameters available: filename, blocksize, read_only.\\n"
            Output: {'filename', 'blocksize', 'read_only'}
        """
        parameters = set()
        for line in mgmt_content.splitlines():
            if "The following parameters available:" in line:
                _, params_str = line.split(":", 1)
                params_str = params_str.strip().rstrip(".")

                for param in params_str.split(","):
                    param = param.strip()
                    if param:
                        parameters.add(param)
                break
        return parameters

    def read_devices(self) -> Dict[str, DeviceConfig]:
        """Read all devices from SCST sysfs for discovery operations.

        Returns:
            Dict mapping device names to minimal DeviceConfig objects
        """
        devices = {}
        devices_path = self.sysfs.SCST_DEVICES

        for device in self.sysfs.list_directory(devices_path):
            if handler_type := self._get_device_handler_type(device):
                if device_config := self._create_minimal_device_config(device, handler_type):
                    devices[device] = device_config

        return devices
