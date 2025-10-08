"""
SCST Target Configuration Reader

Handles target/driver management, LUN operations, and target attribute discovery.
This module focuses on target-specific operations within the SCST configuration.
"""

import glob
import logging
import os
from typing import Dict, Set, Optional

from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError
from ..config import DriverConfig, TargetConfig


class TargetReader:
    """Reads SCST target and driver configuration from sysfs.

    This class handles target discovery, driver attribute management, and
    LUN operations within the SCST configuration system.
    """

    # Known driver attributes that should not be treated as targets during cleanup
    DRIVER_ATTRIBUTES = {
        'copy_manager': {'copy_manager_tgt', 'dif_capabilities', 'allow_not_connected_copy'},
        'iscsi': {'link_local', 'isns_entity_name', 'internal_portal', 'trace_level',
                  'open_state', 'version', 'iSNSServer', 'enabled', 'mgmt'}
    }

    def __init__(self, sysfs: SCSTSysfs):
        self.sysfs = sysfs
        self.logger = logging.getLogger(__name__)

        # Initialize caches
        self._mgmt_cache = {}  # Cache for target management interface info

    def _parse_target_mgmt_interface(self, driver_name: str) -> Dict[str, set]:
        """Parse SCST target driver management interface to discover available attributes.

        SCST target drivers expose their available attributes through their management
        interface help output. This method parses that help text to categorize attributes
        into driver-level vs target-level management commands.

        The mgmt interface help typically contains lines like:
        - "The following target driver attributes available: IncomingUser, OutgoingUser"
        - "The following target attributes available: IncomingUser, OutgoingUser, allowed_portal"

        Note that creation parameters are not explicitly listed in the mgmt help - they
        are inferred from the target attributes that can be set during target creation.

        Args:
            driver_name: SCST target driver name (e.g., 'iscsi', 'fc', 'srp')

        Returns:
            Dictionary with three sets:
            - 'create_params': Attributes that can be provided during 'add_target' command
                              (populated from target_attributes for this implementation)
            - 'driver_attributes': Driver-level attributes managed via 'add_attribute' commands
            - 'target_attributes': Target-level attributes managed via 'add_target_attribute' commands

        Example from iSCSI driver:
            {
                'create_params': {'IncomingUser', 'OutgoingUser', 'allowed_portal'},
                'driver_attributes': {'IncomingUser', 'OutgoingUser'},
                'target_attributes': {'IncomingUser', 'OutgoingUser', 'allowed_portal'}
            }

        Additional target configuration:
            Many target attributes (DataDigest, HeaderDigest, MaxSessions, etc.) are only
            configurable via direct sysfs writes after target creation, not through mgmt commands.

        Note:
            - Returns empty sets if mgmt interface cannot be read
            - Used to determine proper SCST target configuration sequence
            - Driver vs target attribute distinction determines command format
        """
        result = {
            'create_params': set(),        # Target creation parameters
            'driver_attributes': set(),    # Driver-level mgmt attributes
            'target_attributes': set()     # Target-level mgmt attributes
        }

        try:
            driver_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver_name}/mgmt"
            if not self.sysfs.valid_path(driver_mgmt):
                return result

            mgmt_content = self.sysfs.read_sysfs(driver_mgmt)

            # Parse different types of available attributes/parameters
            for line in mgmt_content.splitlines():
                if "The following parameters available:" in line:
                    _, params_str = line.split(":", 1)
                    params_str = params_str.strip().rstrip(".")
                    for param in params_str.split(","):
                        param = param.strip()
                        if param:
                            result['create_params'].add(param)

                elif "The following target driver attributes available:" in line:
                    _, attrs_str = line.split(":", 1)
                    attrs_str = attrs_str.strip().rstrip(".")
                    for attr in attrs_str.split(","):
                        attr = attr.strip()
                        if attr:
                            result['driver_attributes'].add(attr)

                elif "The following target attributes available:" in line:
                    _, attrs_str = line.split(":", 1)
                    attrs_str = attrs_str.strip().rstrip(".")
                    for attr in attrs_str.split(","):
                        attr = attr.strip()
                        if attr:
                            result['target_attributes'].add(attr)

        except SCSTError:
            # If we can't read mgmt interface, return empty sets
            pass

        return result

    def _get_target_mgmt_info(self, driver_name: str) -> Dict[str, set]:
        """Get target management interface info with caching.

        Caches the result of _parse_target_mgmt_interface to avoid repeated
        sysfs reads and parsing for the same target driver.

        Args:
            driver_name: SCST target driver name

        Returns:
            Cached mgmt interface info dictionary
        """
        cache_key = f"target_mgmt_{driver_name}"
        if cache_key not in self._mgmt_cache:
            self._mgmt_cache[cache_key] = self._parse_target_mgmt_interface(driver_name)

        return self._mgmt_cache[cache_key]

    def _get_target_create_params(self, driver_name: str, target_attrs: Dict[str, str]) -> Dict[str, str]:
        """Get target creation parameters from driver mgmt interface"""
        mgmt_info = self._get_target_mgmt_info(driver_name)

        # Return only attributes that are valid creation parameters
        create_params = {}
        for attr, value in target_attrs.items():
            if attr in mgmt_info['create_params']:
                create_params[attr] = value

        return create_params

    def _get_lun_create_params(self, driver: str, target: str, lun_attrs: Dict[str, str]) -> Dict[str, str]:
        """Get LUN assignment creation parameters from luns mgmt interface"""
        create_params = {}

        try:
            luns_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns/mgmt"
            if not self.sysfs.valid_path(luns_mgmt):
                return create_params

            mgmt_content = self.sysfs.read_sysfs(luns_mgmt)

            # Parse management interface for available parameters
            available_params = self._parse_mgmt_parameters(mgmt_content)

            # Return only attributes that are valid creation parameters
            for attr, value in lun_attrs.items():
                if attr in available_params:
                    create_params[attr] = value

        except SCSTError:
            # If we can't read mgmt interface, assume no creation parameters
            pass

        return create_params

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

    def _get_current_target_attrs(self, driver: str, target_name: str,
                                  filter_attrs: Optional[Set[str]] = None) -> Dict[str, str]:
        """Read current target attribute values for configuration comparison.

        Handles multi-value attributes (IncomingUser, etc.) and skips creation-time
        parameters. Only reads specified attributes for performance optimization.

        Args:
            filter_attrs: Optional set of attributes to read (e.g., {'enabled', 'IncomingUser'})
                         If None, reads all available attributes

        Returns:
            Dict mapping attribute names to values, with multi-values joined by semicolons
        """
        attrs = {}
        try:
            target_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target_name}"
            if not os.path.exists(target_path):
                return attrs

            # Filtered read: only query specific attributes for performance (vs reading all)
            if filter_attrs:
                # Query SCST management interface to understand attribute types
                mgmt_info = self._get_target_mgmt_info(driver)

                for attr in filter_attrs:
                    # Skip creation-time-only params (can't be read/compared post-creation)
                    # Matches Perl scstladmin filterCreateAttributes(TRUE) behavior
                    if attr in mgmt_info['create_params']:
                        continue

                    # Multi-value attributes: IncomingUser, OutgoingUser, etc. can have multiple entries
                    # SCST stores as: IncomingUser, IncomingUser1, IncomingUser2, IncomingUser3...
                    if attr in mgmt_info['target_attributes']:
                        collected_values = []

                        # Phase 1: Try base attribute name (IncomingUser -> /sys/.../IncomingUser)
                        attr_path = os.path.join(target_path, attr)
                        value = self._safe_read_attribute(attr_path)
                        if value:
                            collected_values.append(value)

                        # Phase 2: Collect numbered variants (IncomingUser1, IncomingUser2, ...)
                        # Continue until we hit a non-existent numbered attribute
                        counter = 1
                        while True:
                            numbered_attr_path = os.path.join(target_path, f"{attr}{counter}")
                            value = self._safe_read_attribute(numbered_attr_path)
                            if value is not None:  # Attribute file exists
                                if value:  # Non-empty value
                                    collected_values.append(value)
                                counter += 1
                            else:
                                break

                        # Store as semicolon-separated if multiple values
                        if collected_values:
                            attrs[attr] = ';'.join(collected_values)

                    else:
                        # Regular attribute - read single file
                        attr_path = os.path.join(target_path, attr)
                        if os.path.isfile(attr_path):
                            try:
                                value = self.sysfs.read_sysfs_attribute(attr_path)
                                attrs[attr] = value
                            except SCSTError:
                                continue
            else:
                # Read all attribute files in the target directory (fallback)
                for item in os.listdir(target_path):
                    item_path = os.path.join(target_path, item)
                    if not item.startswith('.') and item not in ['luns', 'ini_groups', 'sessions']:
                        value = self._safe_read_attribute(item_path)
                        if value is not None:
                            attrs[item] = value
            return attrs
        except (OSError, IOError):
            return attrs

    def _get_current_lun_device(self, driver: str, target: str, lun_number: str) -> str:
        """Get the device currently assigned to a LUN"""
        try:
            device_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns/{lun_number}/device"
            if os.path.exists(device_path) and os.path.islink(device_path):
                # Follow the symlink to get the device name
                link_target = os.readlink(device_path)
                # Extract device name from path like "../../../../../devices/test2"
                return os.path.basename(link_target)
        except (OSError, IOError):
            pass
        return ""

    def _get_current_group_lun_device(self, driver: str, target: str, group_name: str, lun_number: str) -> str:
        """Get the device currently assigned to a group LUN"""
        try:
            device_path = (f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/"
                           f"{group_name}/luns/{lun_number}/device")
            if os.path.exists(device_path) and os.path.islink(device_path):
                # Follow the symlink to get the device name
                link_target = os.readlink(device_path)
                # Extract device name from path like "../../../../../devices/test2"
                return os.path.basename(link_target)
        except (OSError, IOError):
            pass
        return ""

    def _get_driver_attribute_default(self, driver_name: str, attr_name: str) -> Optional[str]:
        """Get the default value for a driver attribute"""
        # Known defaults for common attributes
        defaults = {
            'iscsi': {
                'iSNSServer': '\n',  # Reset to system default
                'internal_portal': '\n',  # Reset to system default
                'link_local': '1',  # Default is enabled
                'trace_level': '0'  # Default trace level
            }
        }

        driver_defaults = defaults.get(driver_name, {})
        return driver_defaults.get(attr_name)

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

    def read_drivers(self) -> Dict[str, DriverConfig]:
        """Read all target drivers from SCST sysfs for discovery operations.

        Returns:
            Dict mapping driver names to DriverConfig objects
        """
        drivers = {}
        targets_path = self.sysfs.SCST_TARGETS

        for driver in self.sysfs.list_directory(targets_path):
            driver_path = f"{targets_path}/{driver}"
            driver_config = {'targets': {}, 'attributes': {}}

            # Read driver attributes from live system (only non-default values)
            driver_attrs = self.DRIVER_ATTRIBUTES.get(driver, set())
            for attr_name in driver_attrs:
                # Skip non-attribute entries
                if attr_name in {self.sysfs.MGMT_INTERFACE, 'type', 'trace_level', 'open_state', 'version'}:
                    continue

                attr_path = f"{driver_path}/{attr_name}"
                if self.sysfs.valid_path(attr_path):
                    attr_value = self._read_attribute_if_non_default(attr_path)
                    if attr_value is not None:
                        driver_config['attributes'][attr_name] = attr_value

            # Read driver mgmt attributes (IncomingUser, OutgoingUser, etc.)
            # These are dynamically created via add_attribute commands
            mgmt_info = self._get_target_mgmt_info(driver)
            driver_mgmt_attrs = mgmt_info.get('driver_attributes', set())
            for attr_name in driver_mgmt_attrs:
                # Use glob to find all variants (IncomingUser, IncomingUser1, IncomingUser2, etc.)
                # Numbered variants may have gaps (e.g., IncomingUser, IncomingUser2, IncomingUser5)
                collected_values = []
                pattern = os.path.join(driver_path, f"{attr_name}*")
                for attr_file in glob.glob(pattern):
                    if value := self._safe_read_attribute(attr_file):
                        collected_values.append(value)

                # Store as semicolon-separated if multiple values
                if collected_values:
                    driver_config['attributes'][attr_name] = ';'.join(collected_values)

            # Read targets for this driver
            # Get known driver attributes to skip for target detection
            driver_attrs_for_skip = self.DRIVER_ATTRIBUTES.get(driver, set())
            driver_attrs_for_skip.update({self.sysfs.MGMT_INTERFACE, self.sysfs.ENABLED_ATTR})  # Always skip these

            for target in self.sysfs.list_directory(driver_path):
                if target not in driver_attrs_for_skip:
                    # Only include actual targets, not driver attributes
                    target_path = f"{driver_path}/{target}"
                    if os.path.isdir(target_path):
                        # Verify it's a real target by checking for target-specific subdirectories
                        has_luns = self.sysfs.valid_path(f"{target_path}/luns")
                        has_ini_groups = self.sysfs.valid_path(f"{target_path}/ini_groups")
                        has_sessions = self.sysfs.valid_path(f"{target_path}/sessions")

                        if has_luns or has_ini_groups or has_sessions:
                            # Create TargetConfig object for this target
                            target_config_dict = {
                                'luns': {},
                                'groups': {},
                                'attributes': {}
                            }
                            driver_config['targets'][target] = TargetConfig.from_config_dict(
                                target, target_config_dict)

            # Create DriverConfig object from collected data
            drivers[driver] = DriverConfig.from_config_dict(driver, driver_config)

        return drivers
