
"""
High-level SCST administration interface.

This module provides the main SCSTAdmin class which serves as the primary interface
for SCST configuration management, combining configuration parsing with sysfs
operations to deliver a complete SCST administration solution.
"""

import os
import logging

from .constants import SCSTConstants
from .config import SCSTConfig
from .exceptions import SCSTError
from .sysfs import SCSTSysfs
from .modules import SCSTModuleManager
from .parser import SCSTConfigParser
from .readers import SCSTConfigurationReader
from .writers.device_writer import DeviceWriter
from .writers.target_writer import TargetWriter
from .writers.group_writer import GroupWriter


class SCSTAdmin:
    """Main SCST administration interface for complete SCST management.

    This class provides the primary interface for SCST configuration management,
    combining configuration parsing with sysfs operations to deliver a complete
    SCST administration solution. It handles configuration validation, application,
    and verification with comprehensive error handling and logging.

    Key capabilities:
    - Configuration file parsing and validation
    - Complete SCST subsystem configuration
    - Incremental configuration changes
    - Configuration clearing and cleanup
    - copy_manager duplicate LUN handling
    - Suspend/resume for performance optimization
    - Comprehensive error handling and logging

    The class serves as the main entry point for all SCST management operations
    and is designed to be used by both CLI tools and library consumers.
    """

    VERSION = "SCST Python Configurator v1.0.0"

    def __init__(self, timeout: int = SCSTConstants.DEFAULT_TIMEOUT, log_level: str = "WARNING"):
        self.sysfs = SCSTSysfs(timeout)
        self.parser = SCSTConfigParser()
        self.module_manager = SCSTModuleManager()
        self.config_reader = SCSTConfigurationReader(self.sysfs)

        # Initialize caches
        self._mgmt_cache = {}  # Cache for target management interface info

        # Create library-specific logger that doesn't interfere with calling app
        self.logger = logging.getLogger('scstadmin')
        self.logger.setLevel(getattr(logging, log_level.upper(), logging.WARNING))

        # Only add NullHandler if no handlers exist (prevents duplicate handlers)
        if not self.logger.handlers:
            self.logger.addHandler(logging.NullHandler())

        # Initialize writers after logger is created
        self.device_writer = DeviceWriter(self.sysfs, self.config_reader, self.logger)
        self.target_writer = TargetWriter(self.sysfs, self.config_reader, self.logger)
        self.group_writer = GroupWriter(self.sysfs, self.config_reader, self.logger)

        self.suspend_count = 0  # Track suspend nesting

    def suspend_scst_io(self, suspend_value: int = 1) -> None:
        """Suspend SCST IO processing for performance optimization

        Args:
            suspend_value: Positive integer to write to suspend file (default: 1)
        """
        if suspend_value <= 0:
            raise ValueError("suspend_value must be a positive integer")

        try:
            if self.suspend_count == 0:
                suspend_path = f"{self.sysfs.SCST_ROOT}/suspend"
                self.sysfs.write_sysfs(suspend_path, str(suspend_value), check_result=False)
                self.logger.debug("SCST IO suspended with value %s", suspend_value)
            self.suspend_count += 1
        except SCSTError as e:
            self.logger.warning("Failed to suspend SCST IO: %s", e)
            raise

    def resume_scst_io(self) -> None:
        """Resume SCST IO processing"""
        try:
            if self.suspend_count > 0:
                self.suspend_count -= 1
                if self.suspend_count == 0:
                    suspend_path = f"{self.sysfs.SCST_ROOT}/suspend"
                    self.sysfs.write_sysfs(suspend_path, "-1", check_result=False)
                    self.logger.debug("SCST IO resumed")
        except SCSTError as e:
            self.logger.warning("Failed to resume SCST IO: %s", e)
            raise

    def apply_configuration(self, config: SCSTConfig, suspend: int = None) -> None:
        """Apply complete SCST configuration with single-pass convergence.

        This method applies a complete SCST configuration in the correct dependency order
        to prevent "object doesn't exist" or "object already exists" errors common in
        storage configuration management.

        Configuration Dependency Order (Critical for SCST):
        0. Load required kernel modules -> Ensures handlers/drivers are available
        1. Remove conflicts first -> Prevents "already exists" errors when re-configuring
        2. Apply devices -> Storage devices must exist before being assigned to LUNs
        3. Apply target & LUN assignments -> Maps devices to target endpoints with LUN numbers
        4. Clean copy_manager duplicates -> Resolves auto-generated vs explicit LUN conflicts
        5. Apply device groups -> Access control requires targets to exist first
        6. Enable targets/drivers -> Activation only after complete configuration
        7. Apply final attributes -> Tuning parameters after everything is active

        Why This Order Matters:
        - Kernel modules must be loaded before handlers/drivers can be configured
        - SCST requires objects to exist before they can be referenced
        - Enabling targets before full configuration can cause client connection issues
        - copy_manager auto-assignment creates duplicate LUNs that must be cleaned up
        - Device groups use target references that must exist first
        - Attribute changes on active targets can disrupt client sessions

        Args:
            config: SCSTConfig object containing complete configuration
            suspend: Optional suspend value for IO suspension during operations

        Raises:
            SCSTError: On configuration validation or application failures
        """
        if not self.config_reader.check_scst_available():
            raise SCSTError("SCST is not available")

        # Ensure required kernel modules are loaded first
        self.module_manager.ensure_required_modules_loaded(config)

        # Handle suspend/resume if requested
        if suspend is not None:
            self.suspend_scst_io(suspend)

        try:
            # Always remove conflicting configurations first
            self.logger.info("Reading current SCST configuration")
            current_config = self.config_reader.read_current_config()
            self._remove_conflicting_config(current_config, config)

            # Apply configuration in dependency order
            self.logger.info("Applying device configurations")
            self.device_writer.apply_config_devices(config)

            self.logger.info("Applying target and LUN assignments")
            self.target_writer.apply_config_assignments(config)

            # Clean up copy_manager duplicates after assignments but before other operations
            self.target_writer.cleanup_copy_manager_duplicates(config)

            self.logger.info("Applying device group configurations")
            self.group_writer.apply_config_device_groups(config)

            self.logger.info("Enabling targets and drivers")
            self.target_writer.apply_config_enable_targets(config)
            self.target_writer.apply_config_enable_drivers(config)

            self.logger.info("Applying final attributes")
            self.target_writer.apply_config_driver_attributes(config)
            self._apply_scst_attributes(config)

            self.logger.info("Configuration applied successfully")

        except Exception as e:
            self.logger.error("Configuration application failed: %s", e)
            raise
        finally:
            # Resume SCST IO if it was suspended
            if suspend is not None:
                self.resume_scst_io()

    @classmethod
    def apply_config_file(
            cls,
            filename: str,
            suspend: int = None,
            timeout: int = SCSTConstants.DEFAULT_TIMEOUT,
            log_level: str = "WARNING") -> None:
        """Apply SCST configuration from file in a single operation.

        This is a convenience class method that combines instance creation,
        configuration parsing, kernel module loading, and application into a
        single call for the most common use case. Required kernel modules are
        automatically loaded based on handlers and drivers in the configuration.

        Args:
            filename: Path to the SCST configuration file
            suspend: Optional suspend value for IO suspension during operations
            timeout: Operation timeout in seconds (default: 60)
            log_level: Logging level (default: "WARNING")

        Raises:
            SCSTError: On configuration parsing or application failures

        Example:
            SCSTAdmin.apply_config_file('/etc/scst.conf')
        """
        admin = cls(timeout=timeout, log_level=log_level)
        config = admin.parser.parse_config_file(filename)
        admin.apply_configuration(config, suspend=suspend)

    def _apply_scst_attributes(self, config: SCSTConfig) -> None:
        """Apply global SCST attributes"""
        for attr_name, attr_value in config.scst_attributes.items():
            attr_path = f"{self.sysfs.SCST_ROOT}/{attr_name}"
            try:
                # Check if attribute already has the correct value
                if self.sysfs.valid_path(attr_path):
                    current_value = self.sysfs.read_sysfs_attribute(attr_path)
                    if current_value == attr_value:
                        self.logger.debug("SCST attribute %s already set to '%s', skipping", attr_name, attr_value)
                        continue

                self.sysfs.write_sysfs(
                    attr_path, attr_value, check_result=False)
            except SCSTError:
                pass

    def _remove_conflicting_config(
            self,
            current_config: SCSTConfig,
            new_config: SCSTConfig) -> None:
        """Remove configuration elements that conflict with new configuration.

        This method performs selective removal of SCST configuration elements
        that are not present in the new configuration. It compares the current
        live configuration against the new configuration to be applied and
        removes conflicting elements in proper dependency order.

        Elements removed:
        - Device groups not in new configuration
        - Targets not in new configuration
        - Target LUNs not in new configuration
        - Devices not in new configuration

        Args:
            current_config: Current live SCST configuration from sysfs
            new_config: New configuration to be applied
        """
        self.logger.info("Removing conflicting configuration")

        # Remove device groups not in new config
        for group_name in current_config.device_groups:
            if group_name not in new_config.device_groups:
                self.group_writer.remove_device_group(group_name)

        # Remove targets and LUNs not in new config
        for driver_name, driver_config in current_config.drivers.items():
            # Skip copy_manager - it's auto-managed by SCST kernel (matches Perl behavior)
            # copy_manager_tgt is a built-in permanent target that auto-populates with devices
            if driver_name == 'copy_manager':
                continue

            new_driver_config = new_config.drivers.get(driver_name)

            for target_name, target_config in driver_config.targets.items():
                new_target_config = new_driver_config.targets.get(target_name) if new_driver_config else None

                if new_target_config is None:
                    # Remove entire target
                    self.target_writer.remove_target(driver_name, target_name)
                else:
                    # Remove LUNs not in new config
                    self.target_writer._remove_obsolete_luns(
                        driver_name, target_name, target_config, new_target_config)
                    # Remove groups not in new config
                    self.target_writer._remove_obsolete_groups(
                        driver_name, target_name, target_config, new_target_config)

        # Remove obsolete driver attributes
        self.target_writer._remove_obsolete_driver_attributes(current_config, new_config)

        # Remove devices not in new config
        for device_name in current_config.devices:
            if device_name not in new_config.devices:
                self.device_writer.remove_device_by_name(device_name)

    def clear_configuration(self, suspend: int = None) -> None:
        """Clear all SCST configuration completely.

        Removes all SCST configuration in proper dependency order:
        1. Disables all target drivers
        2. Removes all device groups (including target groups)
        3. Removes all targets and their contents (LUNs, initiator groups)
        4. Removes all devices from handlers

        Args:
            suspend: Optional suspend value for IO suspension during operations.
                    If provided, SCST IO will be suspended during clearing.

        Raises:
            SCSTError: If SCST is not available or clearing fails

        Note:
            - No confirmation required
            - Continues on individual item failures to clear as much as possible
            - Automatically resumes IO if suspend was used
        """

        if not self.config_reader.check_scst_available():
            raise SCSTError("SCST is not available")

        self.logger.info("Clearing all SCST configuration")

        # Handle suspend/resume if requested
        if suspend is not None:
            self.suspend_scst_io(suspend)

        try:
            # Disable all drivers first
            self.logger.info("Disabling all target drivers")
            for driver in self.sysfs.list_directory(self.sysfs.SCST_TARGETS):
                enabled_path = f"{self.sysfs.SCST_TARGETS}/{driver}/enabled"
                if self.sysfs.valid_path(enabled_path):
                    try:
                        self.sysfs.write_sysfs(
                            enabled_path, '0', check_result=False)
                    except SCSTError:
                        pass

            # Clear all device groups
            self.logger.info("Removing all device groups")
            for group_name in self.sysfs.list_directory(
                    self.sysfs.SCST_DEV_GROUPS):
                if group_name != self.sysfs.MGMT_INTERFACE:
                    self.group_writer.remove_device_group(group_name)

            # Clear all targets and their contents
            self.logger.info("Removing all targets and LUNs")
            for driver in self.sysfs.list_directory(self.sysfs.SCST_TARGETS):
                driver_path = f"{self.sysfs.SCST_TARGETS}/{driver}"

                # Get known driver attributes to skip
                driver_attrs = SCSTConstants.DRIVER_ATTRIBUTES.get(driver, set())
                driver_attrs.update({self.sysfs.MGMT_INTERFACE, self.sysfs.ENABLED_ATTR})

                for item in self.sysfs.list_directory(driver_path):
                    # Skip known driver attributes (don't try to reset them)
                    if item in driver_attrs:
                        self.logger.debug("Skipping driver attribute '%s/%s'", driver, item)
                        continue

                    # Only process directories that are actual targets
                    item_path = f"{driver_path}/{item}"
                    if os.path.isdir(item_path):
                        # Check if it has target-specific subdirectories (luns, ini_groups, or sessions)
                        has_luns = self.sysfs.valid_path(f"{item_path}/luns")
                        has_ini_groups = self.sysfs.valid_path(f"{item_path}/ini_groups")
                        has_sessions = self.sysfs.valid_path(f"{item_path}/sessions")

                        if has_luns or has_ini_groups or has_sessions:
                            # Clear dynamic target attributes before removing target
                            self._clear_target_dynamic_attributes(driver, item)

                            # copy_manager_tgt is a built-in permanent target - just clear its LUNs
                            if driver == 'copy_manager' and item == 'copy_manager_tgt':
                                luns_mgmt = f"{item_path}/luns/mgmt"
                                if self.sysfs.valid_path(luns_mgmt):
                                    try:
                                        self.sysfs.write_sysfs(luns_mgmt, "clear")
                                    except SCSTError as e:
                                        self.logger.warning(
                                            "Failed to clear copy_manager_tgt LUNs: %s", e)
                            else:
                                self.target_writer.remove_target(driver, item)
                        else:
                            self.logger.debug("Skipping '%s/%s' - not a target directory", driver, item)

                # Clear driver dynamic attributes after all targets removed
                self._clear_driver_dynamic_attributes(driver)

            # Remove all devices
            self.logger.info("Removing all devices")
            for handler in self.sysfs.list_directory(self.sysfs.SCST_HANDLERS):
                handler_path = f"{self.sysfs.SCST_HANDLERS}/{handler}"
                handler_mgmt = f"{handler_path}/mgmt"
                for device in self.sysfs.list_directory(handler_path):
                    # Skip handler attributes - only remove actual devices
                    if device not in self.sysfs.HANDLER_SYSTEM_ATTRS:
                        try:
                            self.sysfs.write_sysfs(
                                handler_mgmt, f"del_device {device}")
                        except SCSTError:
                            pass

            self.logger.info("SCST configuration cleared successfully")

        except Exception as e:
            self.logger.error("Failed to clear configuration: %s", e)
            raise
        finally:
            # Resume SCST IO if it was suspended
            if suspend is not None:
                self.resume_scst_io()

    def check_configuration(self, filename: str) -> bool:
        """Validate an SCST configuration file for syntax and structure.

        Args:
            filename: Path to the SCST configuration file to validate

        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            self.parser.parse_config_file(filename)
            # Additional validation logic would go here
            return True
        except Exception as e:
            self.logger.error("Configuration check failed: %s", e)
            return False

    def _clear_target_dynamic_attributes(self, driver: str, target: str) -> None:
        """Remove all dynamic/mgmt-managed attributes from a target.

        Dynamic attributes are multi-value attributes managed through the SCST mgmt
        interface (e.g., IncomingUser, OutgoingUser, allowed_portal). These must be
        explicitly removed before target deletion.

        Args:
            driver: Target driver name
            target: Target name
        """
        try:
            mgmt_info = self.config_reader._get_target_mgmt_info(driver)
            current_attrs = self.config_reader._get_current_target_attrs(
                driver, target, mgmt_info['target_attributes'])

            for attr_name in mgmt_info['target_attributes']:
                if current_attrs.get(attr_name) is not None:
                    try:
                        self.target_writer._remove_target_mgmt_attribute(driver, target, attr_name)
                    except SCSTError:
                        pass
        except (SCSTError, KeyError):
            pass

    def _clear_driver_dynamic_attributes(self, driver: str) -> None:
        """Remove all dynamic/mgmt-managed attributes from a driver.

        Dynamic attributes are multi-value attributes managed through the SCST mgmt
        interface. These should be cleared when removing all driver configuration.

        Args:
            driver: Driver name
        """
        try:
            mgmt_info = self.config_reader._get_target_mgmt_info(driver)
            driver_path = f"{self.sysfs.SCST_TARGETS}/{driver}"

            for attr_name in mgmt_info['driver_attributes']:
                attr_path = f"{driver_path}/{attr_name}"
                if self.sysfs.valid_path(attr_path):
                    try:
                        # Read current value to see if attribute is set
                        current_value = self.sysfs.read_sysfs(attr_path)
                        if current_value and current_value.strip():
                            # Use mgmt interface to remove driver attribute
                            mgmt_path = f"{driver_path}/mgmt"
                            self.sysfs.write_sysfs(
                                mgmt_path, f"del_attribute {attr_name} {current_value.strip()}",
                                check_result=False)
                    except SCSTError:
                        pass
        except (SCSTError, KeyError):
            pass
