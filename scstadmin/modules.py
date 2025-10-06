"""
Kernel module management for SCST.

This module handles automatic loading of kernel modules required by SCST
configurations. It analyzes configurations to determine required modules
and loads them using modprobe, similar to the SCST init script behavior.
"""

import os
import subprocess
import platform
import logging
from typing import Set

from .constants import SCSTConstants
from .config import SCSTConfig
from .exceptions import SCSTError


class SCSTModuleManager:
    """Manages kernel module loading for SCST configurations."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def determine_required_modules(self, config: SCSTConfig) -> Set[str]:
        """Map configuration components to required kernel modules.

        Analyzes the configuration to determine which kernel modules need to be loaded
        based on handlers, drivers, and architecture-specific requirements.

        Args:
            config: SCSTConfig object containing the configuration

        Returns:
            Set of module names that need to be loaded
        """
        required_modules = {'scst'}  # Base SCST module always needed

        # Map handlers to modules
        for handler_name in config.handlers:
            module = SCSTConstants.HANDLER_MODULE_MAP.get(handler_name)
            if module:
                required_modules.add(module)

        # Map drivers to modules
        for driver_name in config.drivers:
            module = SCSTConstants.DRIVER_MODULE_MAP.get(driver_name)
            if module:
                required_modules.add(module)

        # Add iSCSI-specific modules if iSCSI driver is used
        if 'iscsi' in config.drivers:
            # Add base iSCSI modules
            required_modules.update(SCSTConstants.ISCSI_OPT_MODULES)

            # Add x86-specific CRC acceleration if available
            if platform.machine() in ['x86_64', 'i686']:
                required_modules.update(SCSTConstants.ISCSI_X86_MODULES)

        return required_modules

    def is_module_loaded(self, module_name: str) -> bool:
        """Check if a kernel module is already loaded.

        Kernel modules with hyphens in their names appear in /sys/module/ with
        underscores instead of hyphens (e.g., crc32c-intel -> crc32c_intel).

        Some modules like 'crc32c' are provided by multiple implementations
        (crc32c_intel, crc32c_generic) so we check for any available implementation.

        Args:
            module_name: Name of the kernel module to check

        Returns:
            True if module is loaded, False otherwise
        """
        # Special handling for crc32c - check for any implementation
        if module_name == 'crc32c':
            crc32c_modules = ["/sys/module/crc32c_intel", "/sys/module/crc32c_generic", "/sys/module/libcrc32c"]
            return any(os.path.exists(module_path) for module_path in crc32c_modules)

        # Convert hyphens to underscores for /sys/module/ path
        sysfs_name = module_name.replace('-', '_')
        return os.path.exists(f"/sys/module/{sysfs_name}")

    def load_module(self, module_name: str) -> bool:
        """Load a single kernel module using modprobe.

        Args:
            module_name: Name of the kernel module to load

        Returns:
            True if successful, False otherwise
        """
        try:
            result = subprocess.run(
                ['modprobe', module_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                self.logger.info("Successfully loaded module: %s", module_name)
                return True
            else:
                # Don't treat optional module failures as errors
                if module_name in SCSTConstants.ISCSI_OPT_MODULES or module_name in SCSTConstants.ISCSI_X86_MODULES:
                    self.logger.debug("Optional module %s could not be loaded: %s", module_name, result.stderr)
                    return True  # Continue without optional modules
                else:
                    self.logger.error("Failed to load required module %s: %s", module_name, result.stderr)
                    return False
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout loading module: %s", module_name)
            return False
        except Exception as e:
            self.logger.error("Error loading module %s: %s", module_name, e)
            return False

    def ensure_required_modules_loaded(self, config: SCSTConfig) -> None:
        """Load kernel modules required for the given configuration.

        This method analyzes the configuration to determine which kernel modules
        are needed and loads any that aren't already loaded. This mirrors the
        behavior of the SCST init script's parse_scst_conf() function.

        Args:
            config: SCSTConfig object containing the configuration

        Raises:
            SCSTError: If required modules cannot be loaded
        """
        required_modules = self.determine_required_modules(config)
        failed_modules = []

        self.logger.info("Required modules for configuration: %s", sorted(required_modules))

        for module in required_modules:
            if not self.is_module_loaded(module):
                if not self.load_module(module):
                    # Only fail for non-optional modules
                    if module not in SCSTConstants.ISCSI_OPT_MODULES and module not in SCSTConstants.ISCSI_X86_MODULES:
                        failed_modules.append(module)
            else:
                self.logger.debug("Module already loaded: %s", module)

        if failed_modules:
            raise SCSTError(f"Failed to load required modules: {', '.join(failed_modules)}")
