"""
SCST Sysfs Interface Module

This module provides the low-level sysfs interface for the SCST (SCSI Target
Subsystem for Linux) kernel module. It handles direct filesystem operations
to /sys/kernel/scst_tgt for configuring and managing SCST components.

The SCSTSysfs class implements:
- Direct sysfs read/write operations with comprehensive error handling
- Path validation and permission checking
- Operation result verification through SCST result queue
- Proper timeout handling for asynchronous operations
- Directory listing and attribute parsing

This is the foundational layer for all SCST management operations.
"""

import os
import time
import logging
from typing import List

from .constants import SCSTConstants
from .exceptions import SCSTError


class SCSTSysfs:
    """SCST sysfs interface handler for low-level SCST operations.

    This class provides the core interface to the SCST kernel module through
    the sysfs filesystem. It handles all direct filesystem operations needed
    to configure and manage SCST components including devices, targets,
    handlers, and device groups.

    The class implements proper error handling, permission checking, and
    operation result verification for robust SCST management.

    Attributes:
        SCST_ROOT: Base sysfs path for SCST (/sys/kernel/scst_tgt)
        SCST_HANDLERS: Path to device handlers
        SCST_DEVICES: Path to device definitions
        SCST_TARGETS: Path to target configurations
        SCST_DEV_GROUPS: Path to device group definitions
        SCST_QUEUE_RES: Path to operation result queue
        timeout: Operation timeout in seconds
    """

    SCST_ROOT = "/sys/kernel/scst_tgt"
    SCST_HANDLERS = f"{SCST_ROOT}/handlers"
    SCST_DEVICES = f"{SCST_ROOT}/devices"
    SCST_TARGETS = f"{SCST_ROOT}/targets"
    SCST_DEV_GROUPS = f"{SCST_ROOT}/device_groups"
    SCST_QUEUE_RES = f"{SCST_ROOT}/last_sysfs_mgmt_res"

    # SCST interface constants
    MGMT_INTERFACE = 'mgmt'
    ENABLED_ATTR = 'enabled'
    HANDLER_SYSTEM_ATTRS = {'mgmt', 'type', 'trace_level'}

    def __init__(self, timeout: int = SCSTConstants.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    def valid_path(self, path: str) -> bool:
        """Check if a sysfs path is valid and accessible"""
        return os.path.exists(path) and os.access(path, os.R_OK)

    def write_sysfs(
            self,
            path: str,
            data: str,
            check_result: bool = True,
            force_flush: bool = False) -> bool:
        """Write data to a sysfs file with comprehensive error handling.

        This is the core method for all SCST sysfs operations. It validates
        paths, checks permissions, writes data, and optionally verifies
        operation results through the SCST result queue.

        Args:
            path: Absolute sysfs path to write to
            data: Data string to write
            check_result: Whether to check operation result queue
            force_flush: Whether to force buffer flush after write

        Returns:
            True if operation succeeded, False otherwise

        Raises:
            SCSTError: On path validation, permission, or write failures
        """
        try:
            if not os.path.exists(path):
                raise SCSTError(f"Sysfs path does not exist: {path}")

            if not os.access(path, os.W_OK):
                raise SCSTError(f"No write permission for: {path}")

            # Clean up data representation for logging
            data_repr = repr(data) if '\n' in data or not data.strip() else data
            self.logger.debug("Writing %s to %s", data_repr, path)

            with open(path, 'w') as f:
                f.write(data)
                if force_flush:
                    f.flush()

            if check_result:
                return self._check_operation_result()

            return True

        except PermissionError:
            raise SCSTError(f"Permission denied writing to {path}")
        except OSError as e:
            if e.errno == SCSTConstants.EAGAIN_ERRNO:  # Resource temporarily unavailable
                if check_result:
                    return self._wait_for_completion()
                return True
            raise SCSTError(f"Error writing to {path}: {e}")

    def read_sysfs(self, path: str) -> str:
        """Read data from a sysfs file with error handling.

        Args:
            path: Absolute sysfs path to read from

        Returns:
            File contents with whitespace stripped

        Raises:
            SCSTError: On path validation or read failures
        """
        try:
            if not self.valid_path(path):
                raise SCSTError(f"Cannot read from {path}")

            with open(path, 'r') as f:
                return f.read().strip()

        except OSError as e:
            raise SCSTError(f"Error reading from {path}: {e}")

    def read_sysfs_attribute(self, path: str) -> str:
        """Read SCST attribute value handling the [key] pattern.

        SCST attributes show non-default values with a '\n[key]' suffix.
        This method returns only the actual value by reading the first line.

        Args:
            path: Absolute sysfs path to attribute file

        Returns:
            Attribute value without the [key] suffix

        Raises:
            SCSTError: On path validation or read failures
        """
        try:
            if not self.valid_path(path):
                raise SCSTError(f"Cannot read from {path}")

            with open(path, 'r') as f:
                # Read only the first line and strip trailing newline
                # This handles SCST's pattern where non-default values have '\n[key]' appended
                return f.readline().rstrip('\n')

        except OSError as e:
            raise SCSTError(f"Error reading from {path}: {e}")

    def _check_operation_result(self) -> bool:
        """Check the result of an asynchronous operation"""
        if not self.valid_path(self.SCST_QUEUE_RES):
            return True

        result = self.read_sysfs(self.SCST_QUEUE_RES)
        if result == SCSTConstants.SUCCESS_RESULT:
            return True
        else:
            raise SCSTError(f"Operation failed with result: {result}")

    def _wait_for_completion(self) -> bool:
        """Wait for asynchronous operation completion"""
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                return self._check_operation_result()
            except SCSTError:
                time.sleep(SCSTConstants.OPERATION_POLL_INTERVAL)
                continue

        raise SCSTError("Operation timed out")

    def list_directory(self, path: str) -> List[str]:
        """List contents of a sysfs directory"""
        try:
            if not self.valid_path(path):
                return []
            return [f for f in os.listdir(path) if not f.startswith('.')]
        except OSError:
            return []

    def is_valid_sysfs_directory(self, base_path: str, item_name: str,
                                 exclude_mgmt: bool = True) -> bool:
        """Check if an item represents a valid SCST sysfs directory.
        This method validates that an item within a sysfs directory is:
        1. Actually a directory (not a file/attribute)
        2. Optionally excludes SCST management interfaces
        SCST sysfs directories often contain a mix of subdirectories (representing
        entities like devices, targets, groups) and files (representing attributes
        or management interfaces). This method helps distinguish the directories
        that represent actual SCST entities.
        Args:
            base_path: Parent sysfs directory path
            item_name: Name of the item to check within base_path
            exclude_mgmt: If True, return False for 'mgmt' interface directories
        Returns:
            True if item is a valid directory and passes exclusion filters
        Example:
            base_path = "/sys/kernel/scst_tgt/handlers/vdisk_blockio"
            item_name = "device1"  -> True (device directory)
            item_name = "mgmt"     -> False (management interface, excluded by default)
            item_name = "type"     -> False (attribute file, not directory)
        """
        if exclude_mgmt and item_name == self.MGMT_INTERFACE:
            return False
        item_path = os.path.join(base_path, item_name)
        return os.path.isdir(item_path)

    def mgmt_operation(self, mgmt_path: str, command: str, item: str,
                       success_msg: str, error_msg: str) -> bool:
        """Generic method for mgmt interface operations (add/del/create)
        Args:
            mgmt_path: Path to the mgmt interface file
            command: Management command (add, del, create, etc.)
            item: Item to operate on
            success_msg: Debug message for successful operation
            error_msg: Warning message prefix for failed operation
        Returns:
            True if operation succeeded, False if it failed
        """
        try:
            self.write_sysfs(mgmt_path, f"{command} {item}")
            self.logger.debug(success_msg)
            return True
        except SCSTError as e:
            self.logger.warning("%s: %s", error_msg, e)
            return False
