"""
Device Writer for SCST Administration

This module handles device-specific write operations for SCST configuration.
"""

import logging
from typing import Dict

from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError
from ..config import ConfigAction, DeviceConfig, SCSTConfig
from .utils import entity_exists, attrs_config_differs


class DeviceWriter:
    """Handles device-specific SCST write operations"""

    def __init__(self, sysfs: SCSTSysfs, config_reader=None, logger=None):
        self.sysfs = sysfs
        self.config_reader = config_reader
        self.logger = logger or logging.getLogger("scstadmin.writers.device")

    def device_exists(self, handler: str, device_name: str) -> bool:
        """Check if a device already exists under a handler"""
        device_path = f"{self.sysfs.SCST_HANDLERS}/{handler}/{device_name}"
        return entity_exists(device_path)

    def set_device_attributes(
        self, handler: str, device_name: str, attrs: Dict[str, str]
    ) -> None:
        """Set post-creation attributes on an existing device.
        Args:
            handler: SCST handler name
            device_name: Name of the device
            attrs: Dictionary of attribute name/value pairs to set
        """
        for attr_name, attr_value in attrs.items():
            attr_path = (
                f"{self.sysfs.SCST_HANDLERS}/{handler}/{device_name}/{attr_name}"
            )
            try:
                self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
                self.logger.debug(
                    "Set device attribute %s.%s = %s",
                    device_name,
                    attr_name,
                    attr_value,
                )
            except SCSTError as e:
                self.logger.warning(
                    "Failed to set device attribute %s.%s: %s",
                    device_name,
                    attr_name,
                    e,
                )

    def remove_device(self, handler: str, device_name: str) -> None:
        """Remove an existing device."""
        try:
            self.sysfs.write_sysfs(
                f"{self.sysfs.SCST_HANDLERS}/{handler}/mgmt",
                f"del_device {device_name}",
            )
        except SCSTError as e:
            self.logger.warning(
                "Failed to remove existing device %s: %s", device_name, e
            )
            # Continue anyway - the creation might still work

    def remove_device_by_name(self, device_name: str) -> None:
        """Remove a device from its handler when handler is unknown"""
        try:
            # Find which handler owns this device
            for handler in self.sysfs.list_directory(self.sysfs.SCST_HANDLERS):
                handler_path = f"{self.sysfs.SCST_HANDLERS}/{handler}"
                devices = self.sysfs.list_directory(handler_path)
                if device_name in devices:
                    handler_mgmt = f"{handler_path}/mgmt"
                    self.sysfs.write_sysfs(handler_mgmt, f"del_device {device_name}")
                    break
        except SCSTError as e:
            self.logger.warning("Failed to remove device %s: %s", device_name, e)

    def create_device(
        self,
        handler: str,
        device_name: str,
        creation_params: Dict[str, str],
        post_creation_attrs: Dict[str, str],
    ) -> None:
        """Create a new SCST device with proper parameter sequencing.

        SCST device creation follows a two-phase process:
        1. Creation phase: Send 'add_device' command with creation-time parameters
        2. Configuration phase: Set post-creation attributes via sysfs

        This separation is critical because some parameters (e.g., filename, size_mb)
        can only be set during device creation, while others (e.g., read_only, rotational)
        can be modified after creation.

        Args:
            handler: SCST handler name (e.g., 'vdisk_fileio', 'dev_disk')
            device_name: Name for the new device
            creation_params: Parameters that must be provided during 'add_device' command
            post_creation_attrs: Attributes to set after device creation via sysfs

        Special handling:
            - cluster_mode parameter is deferred to end of creation command to ensure
              proper ordering after t10_dev_id parameter

        Example:
            creation_params = {'filename': '/dev/sda', 'size_mb': '1024'}
            post_creation_attrs = {'read_only': '1', 'rotational': '0'}

            Results in:
            1. Write to handler mgmt: "add_device disk1 filename=/dev/sda;size_mb=1024;"
            2. Write to device sysfs: echo "1" > /sys/.../handlers/dev_disk/disk1/read_only
            3. Write to device sysfs: echo "0" > /sys/.../handlers/dev_disk/disk1/rotational
        """
        handler_path = f"{self.sysfs.SCST_HANDLERS}/{handler}/mgmt"

        # Build device creation command with only creation parameters
        params = []

        # Handle cluster_mode specially - set it after t10_dev_id
        cluster_mode = None
        for key, value in creation_params.items():
            if key == "cluster_mode":
                cluster_mode = value
            else:
                params.append(f"{key}={value}")

        # Add cluster_mode at the end if present
        if cluster_mode is not None:
            params.append(f"cluster_mode={cluster_mode}")

        # Create the device
        if params:
            command = f"add_device {device_name} {';'.join(params)};"
        else:
            command = f"add_device {device_name}"

        self.sysfs.write_sysfs(handler_path, command)

        # Set post-creation attributes
        if post_creation_attrs:
            self.set_device_attributes(handler, device_name, post_creation_attrs)

    def determine_device_action(
        self,
        handler: str,
        device_name: str,
        device_config: DeviceConfig,
        creation_params: Dict[str, str],
        post_creation_attrs: Dict[str, str],
    ) -> ConfigAction:
        """Determine what action to take for an existing device.

        Matches Perl scstadmin behavior: checks if any [key]-marked creation attributes
        exist in current device but not in config, which requires device recreation.

        Returns:
            ConfigAction.SKIP: Device already matches configuration
            ConfigAction.UPDATE: Only post-creation attributes need updating
            ConfigAction.RECREATE: Creation attributes differ, device must be recreated
        """
        # Get all possible creation parameters for this handler type
        all_creation_params = (
            device_config._CREATION_PARAMS
            if hasattr(device_config, "_CREATION_PARAMS")
            else set()
        )

        # Read current attributes - check all creation params, not just ones in config
        # This matches Perl's behavior of checking ALL device attributes
        config_attrs_to_check = all_creation_params | set(post_creation_attrs.keys())
        existing_device_attrs = self.config_reader._get_current_device_attrs(
            handler, device_name, config_attrs_to_check
        )

        # Check for [key]-marked creation attributes that exist in device but not in config
        # This matches Perl's compareToKeyAttribute() logic (lines 2949-2951)
        device_path = f"{self.sysfs.SCST_HANDLERS}/{handler}/{device_name}"
        for attr_name in all_creation_params:
            if attr_name not in creation_params:  # Attribute not in desired config
                attr_path = f"{device_path}/{attr_name}"
                try:
                    # Read full attribute content including [key] marker
                    full_content = self.sysfs.read_sysfs(attr_path)
                    if "[key]" in full_content:
                        # [key] attribute exists but not in config - must recreate device
                        self.logger.debug(
                            "Device %s has [key] creation attribute '%s' not in config, must recreate",
                            device_name,
                            attr_name,
                        )
                        return ConfigAction.RECREATE
                except (SCSTError, OSError, IOError):
                    # Attribute doesn't exist or can't be read - that's fine
                    pass

        # Check if creation-time attributes differ (requires device recreation)
        creation_attrs_differ = attrs_config_differs(
            creation_params, existing_device_attrs, entity_type="Device creation"
        )

        # Check if post-creation attributes differ (can be updated in place)
        post_attrs_differ = attrs_config_differs(
            post_creation_attrs,
            existing_device_attrs,
            entity_type="Device post-creation",
        )

        if not creation_attrs_differ and not post_attrs_differ:
            return ConfigAction.SKIP
        elif creation_attrs_differ:
            return ConfigAction.RECREATE
        else:
            return ConfigAction.UPDATE

    def apply_config_devices(self, config: SCSTConfig) -> None:
        """Apply device configurations with intelligent update/recreation logic.
        For each device in the configuration:
        1. If device doesn't exist → create it
        2. If device exists but creation attributes differ → recreate it
        3. If device exists but only post-creation attributes differ → update in-place
        4. If device already matches configuration → skip it
        """
        self.logger.debug(
            "Applying device configurations. Found %s devices", len(config.devices)
        )
        for device_name, device_config in config.devices.items():
            handler = device_config.handler_type

            # Get creation and post-creation attributes directly from DeviceConfig
            creation_params = device_config.creation_attributes
            post_creation_attrs = device_config.post_creation_attributes

            # Check if device already exists and determine required action
            if self.device_exists(handler, device_name):
                action = self.determine_device_action(
                    handler,
                    device_name,
                    device_config,
                    creation_params,
                    post_creation_attrs,
                )
                if action == ConfigAction.SKIP:
                    self.logger.debug(
                        "Device %s already exists with matching config, skipping",
                        device_name,
                    )
                    continue
                elif action == ConfigAction.UPDATE:
                    self.logger.debug(
                        "Device %s exists, updating post-creation attributes only",
                        device_name,
                    )
                    self.set_device_attributes(
                        handler, device_name, post_creation_attrs
                    )
                    continue
                elif action == ConfigAction.RECREATE:
                    self.logger.debug(
                        "Device %s creation attributes differ, removing and recreating",
                        device_name,
                    )
                    self.remove_device(handler, device_name)

            # Device doesn't exist or needs recreation - create it
            self.create_device(
                handler, device_name, creation_params, post_creation_attrs
            )
