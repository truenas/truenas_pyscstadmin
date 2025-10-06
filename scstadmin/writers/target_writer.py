"""
Target Writer for SCST Administration

This module handles target-specific write operations for SCST configuration.
"""
import os
import time
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError
from ..constants import SCSTConstants
from .utils import attrs_config_differs, entity_exists

if TYPE_CHECKING:
    from ..config import TargetConfig, SCSTConfig, InitiatorGroupConfig, DriverConfig


class TargetWriter:
    """Handles target-specific SCST write operations"""

    def __init__(self, sysfs: SCSTSysfs, config_reader=None, logger=None):
        self.sysfs = sysfs
        self.config_reader = config_reader
        self.logger = logger or logging.getLogger('scstadmin.writers.target')

    def set_target_attributes(self, driver_name: str, target_name: str, attributes: Dict[str, str]) -> None:
        """Set target attributes after creation using appropriate SCST management commands.

        SCST target attributes are configured through different mechanisms depending on
        their type, as determined by the target driver's management interface:

        1. Target-level mgmt attributes: Use 'add_target_attribute' commands
        2. Driver-level mgmt attributes: Use 'add_attribute' commands
        3. Direct sysfs attributes: Write directly to target sysfs files

        This method automatically determines the correct configuration method for each
        attribute and handles special cases like multi-value attributes (e.g., IncomingUser).

        Args:
            driver_name: SCST target driver name (e.g., 'iscsi', 'fc')
            target_name: Name of the target to configure
            attributes: Dictionary of attribute name/value pairs to set

        Example attribute handling:
            For iSCSI target with attributes:
            - 'IncomingUser': 'user1 secret123' -> add_target_attribute command
            - 'HeaderDigest': 'CRC32C' -> direct sysfs write to target directory
            - 'enabled': '1' -> direct sysfs write to target directory

        Multi-value attributes:
            Some attributes (like IncomingUser) can have multiple values separated by
            semicolons. Each value is sent as a separate management command.

        Note:
            - Attributes not recognized by mgmt interface are written directly to sysfs
            - Management command failures are logged but don't stop processing
            - Direct sysfs writes use check_result=False for non-critical attributes
        """
        # Get mgmt interface info to identify special attributes
        mgmt_info = self.config_reader._get_target_mgmt_info(driver_name)
        driver_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver_name}/mgmt"

        for attr_name, attr_value in attributes.items():
            if attr_name in mgmt_info['target_attributes']:
                # Use mgmt command for target-level mgmt attributes (e.g., IncomingUser)
                # Handle multiple values separated by semicolons
                values = attr_value.split(';') if ';' in attr_value else [attr_value]

                for value in values:
                    if value.strip():  # Skip empty values
                        try:
                            self.logger.debug(
                                f"Setting target mgmt attribute {driver_name}/{target_name}."
                                f"{attr_name} = {value.strip()}")
                            command = f"add_target_attribute {target_name} {attr_name} {value.strip()}"
                            self.sysfs.write_sysfs(driver_mgmt, command, check_result=False)
                        except SCSTError as e:
                            self.logger.warning(
                                f"Failed to set {driver_name}/{target_name}.{attr_name}={value.strip()} via mgmt: {e}")
            else:
                # Use direct file write for regular attributes
                attr_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}/{attr_name}"
                try:
                    self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
                except SCSTError as e:
                    self.logger.warning(f"Failed to set {driver_name}/{target_name}.{attr_name}: {e}")

    def update_target_attributes(self, driver_name: str, target_name: str,
                                 desired_attrs: Dict[str, str], current_attrs: Dict[str, str]) -> None:
        """Update target attributes with efficient change detection and proper SCST handling.

        Compares desired configuration against current sysfs values and updates only
        attributes that actually differ, providing significant performance optimization
        over full target recreation. Handles SCST management-controlled attributes
        properly by removing old values before setting new ones.

        Args:
            driver_name: SCST target driver name (e.g., 'iscsi')
            target_name: Target name within the driver
            desired_attrs: Desired attribute values from configuration
            current_attrs: Current attribute values from sysfs

        Key behaviors:
            - Skips updates where current_value == desired_value (performance optimization)
            - Treats None/missing current_value as "0" for SCST default comparison
            - For mgmt-managed attributes (e.g., IncomingUser), removes old values first
              to prevent SCST conflicts when setting new values
            - Uses appropriate update mechanism (mgmt commands vs direct sysfs writes)

        Example mgmt-managed attribute handling:
            Current IncomingUser: "olduser secret1"
            Desired IncomingUser: "newuser secret2"
            Process: 1) del_target_attribute olduser, 2) add_target_attribute newuser
        """
        # Get mgmt interface info to identify special attributes
        mgmt_info = self.config_reader._get_target_mgmt_info(driver_name)
        attrs_to_update = {}
        attrs_to_remove = []

        # Find attributes that need updating
        for attr_name, desired_value in desired_attrs.items():
            current_value = current_attrs.get(attr_name)

            # Skip if values are the same
            if current_value == desired_value:
                continue

            # Skip comparison if current value is undefined and desired is "0"
            if current_value is None and desired_value == SCSTConstants.SUCCESS_RESULT:
                continue

            attrs_to_update[attr_name] = desired_value
            self.logger.debug(
                f"Target attribute '{attr_name}' needs update: current='{current_value}' -> desired='{desired_value}'")

        # Find mgmt-managed attributes that need to be removed
        # ONLY check attributes that are in mgmt_info['target_attributes'] - these are the only
        # ones we can actually remove. All other attributes are read-only or system-managed.
        for attr_name in mgmt_info['target_attributes']:
            if attr_name not in desired_attrs and current_attrs.get(attr_name) is not None:
                attrs_to_remove.append(attr_name)
                current_val = current_attrs.get(attr_name)
                self.logger.debug(
                    f"Target mgmt attribute '{attr_name}' needs removal: current='{current_val}' -> not in desired")

        # Remove mgmt attributes that should no longer exist
        if attrs_to_remove:
            self.logger.debug(f"Removing {len(attrs_to_remove)} target mgmt attributes for {driver_name}/{target_name}")
            for attr_name in attrs_to_remove:
                self._remove_target_mgmt_attribute(driver_name, target_name, attr_name)

        # Update the attributes that differ
        if attrs_to_update:
            self.logger.debug(f"Updating {len(attrs_to_update)} target attributes for {driver_name}/{target_name}")

            # For mgmt-managed attributes, we need to remove old values first
            for attr_name, desired_value in attrs_to_update.items():
                if attr_name in mgmt_info['target_attributes']:
                    # Remove existing values for this attribute
                    self._remove_target_mgmt_attribute(driver_name, target_name, attr_name)

            # Set the new values
            self.set_target_attributes(driver_name, target_name, attrs_to_update)
        elif not attrs_to_remove:
            self.logger.debug(f"No target attribute updates needed for {driver_name}/{target_name}")

    def _remove_target_mgmt_attribute(self, driver_name: str, target_name: str, attr_name: str) -> None:
        """Remove all variants of a target management attribute using SCST mgmt commands.
        SCST management-controlled attributes (like IncomingUser, OutgoingUser) can exist
        in multiple variants:
        - Base attribute: IncomingUser
        - Numbered variants: IncomingUser1, IncomingUser2, IncomingUser3, etc.
        This method discovers all existing variants of the specified attribute and
        removes them using 'del_target_attribute' commands to ensure clean slate
        before setting new values.
        Args:
            driver_name: SCST target driver name (e.g., 'iscsi', 'fc')
            target_name: Name of the target to modify
            attr_name: Base name of management attribute to remove (e.g., 'IncomingUser')
        Discovery process:
            1. Check base attribute (e.g., IncomingUser)
            2. Check numbered variants (IncomingUser1, IncomingUser2, ...)
            3. Stop when no more numbered variants found
            4. Remove all discovered variants via mgmt commands
        Example for IncomingUser cleanup:
            Found: IncomingUser="user1 secret1", IncomingUser2="user2 secret2"
            Commands:
            - del_target_attribute target_name IncomingUser user1 secret1
            - del_target_attribute target_name IncomingUser2 user2 secret2
        Note:
            - Essential for preventing accumulation of old authentication entries
            - Used by _update_target_attributes() before setting new values
            - Removal failures are logged but don't stop processing
            - Only affects mgmt-controlled attributes discovered in target sysfs
        """
        try:
            driver_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver_name}/mgmt"
            target_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}"

            # Find all numbered variants of this attribute
            variants_to_remove = []

            # Check base attribute (e.g., IncomingUser)
            base_attr_path = os.path.join(target_path, attr_name)
            if os.path.isfile(base_attr_path):
                try:
                    value = self.sysfs.read_sysfs_attribute(base_attr_path)
                    if value:
                        variants_to_remove.append((attr_name, value))
                except SCSTError:
                    pass  # Skip unreadable attributes

            # Check numbered variants (e.g., IncomingUser1, IncomingUser2, etc.)
            counter = 1
            while True:
                numbered_attr_path = os.path.join(target_path, f"{attr_name}{counter}")
                if os.path.isfile(numbered_attr_path):
                    try:
                        value = self.sysfs.read_sysfs_attribute(numbered_attr_path)
                        if value:
                            variants_to_remove.append((f"{attr_name}{counter}", value))
                    except SCSTError:
                        pass  # Skip unreadable attributes
                    counter += 1
                else:
                    break

            # Remove all found variants
            for variant_name, value in variants_to_remove:
                try:
                    command = f"del_target_attribute {target_name} {attr_name} {value}"
                    self.sysfs.write_sysfs(driver_mgmt, command, check_result=False)
                    self.logger.debug(
                        f"Removed target mgmt attribute {driver_name}/{target_name}.{attr_name} = {value}")
                except SCSTError as e:
                    # Log warning but continue - might not exist or already removed
                    self.logger.debug(f"Could not remove {driver_name}/{target_name}.{attr_name}={value}: {e}")
        except (OSError, IOError) as e:
            self.logger.debug(f"Error reading target attributes for removal: {e}")

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

    def _direct_lun_assignments_differ(self, driver: str, target: str, target_config: 'TargetConfig') -> bool:
        """Check if current direct LUN assignments differ from desired configuration.
        Compares current direct target LUN assignments (under target/luns/) against
        the desired direct LUN configuration.
        Args:
            driver: SCST target driver name (e.g., 'iscsi')
            target: Target name within the driver
            target_config: Target configuration containing 'luns'
        Returns:
            True if direct LUN assignments differ, False if they match.
            Returns True if sysfs cannot be read (assumes difference for safety).
        """
        try:
            # Get current direct LUN assignments
            current_direct_luns = {}
            luns_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns"
            if os.path.exists(luns_path):
                for lun_item in os.listdir(luns_path):
                    if self.sysfs.is_valid_sysfs_directory(luns_path, lun_item):
                        device = self.config_reader._get_current_lun_device(driver, target, lun_item)
                        if device:
                            current_direct_luns[lun_item] = device

            # Get desired direct LUN assignments
            desired_direct_luns = {}
            for lun_number, lun_config in target_config.luns.items():
                device = lun_config.device  # LunConfig object
                if device:
                    desired_direct_luns[lun_number] = device

            # Compare
            return current_direct_luns != desired_direct_luns
        except (OSError, IOError):
            # If we can't read current state, assume they differ
            return True

    def _group_lun_assignments_differ(self, driver: str, target: str, target_config: 'TargetConfig') -> bool:
        """Check if initiator group LUN assignments need updating.
        Compares current vs desired LUN assignments within each group to determine
        if updates are needed for access control changes.
        Returns:
            True if any group's LUN assignments differ, False if all match
        """
        try:
            # Get current group LUN assignments (organized by group)
            current_group_luns = {}
            ini_groups_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups"
            if os.path.exists(ini_groups_path):
                for group_name in os.listdir(ini_groups_path):
                    group_path = os.path.join(ini_groups_path, group_name)
                    if group_name != self.sysfs.MGMT_INTERFACE and os.path.isdir(group_path):
                        group_luns_path = f"{ini_groups_path}/{group_name}/luns"
                        if os.path.exists(group_luns_path):
                            group_luns = {}
                            for lun_item in os.listdir(group_luns_path):
                                if lun_item != self.sysfs.MGMT_INTERFACE and os.path.isdir(
                                        os.path.join(group_luns_path, lun_item)):
                                    device = self.config_reader._get_current_group_lun_device(driver,
                                                                                              target,
                                                                                              group_name,
                                                                                              lun_item)
                                    if device:
                                        group_luns[lun_item] = device
                            if group_luns:
                                current_group_luns[group_name] = group_luns

            # Get desired group LUN assignments
            desired_group_luns = {}
            for group_name, group_config in target_config.groups.items():
                group_luns = {}
                for lun_number, lun_config in group_config.luns.items():
                    device = lun_config.device  # LunConfig object
                    if device:
                        group_luns[lun_number] = device
                if group_luns:
                    desired_group_luns[group_name] = group_luns

            # Compare
            return current_group_luns != desired_group_luns
        except (OSError, IOError):
            # If we can't read current state, assume they differ
            return True

    def _group_assignments_differ(self, driver: str, target: str, target_config: 'TargetConfig') -> bool:
        """Check if current initiator group assignments differ from desired configuration.
        Performs comprehensive comparison of initiator group configuration including
        both group membership (which groups exist) and individual group configurations
        (LUN assignments, initiator lists, group attributes).
        SCST sysfs structure examined:
            /sys/.../targets/{driver}/{target}/ini_groups/{group}/
        Two-phase comparison:
        1. Group membership: Compare set of current vs desired group names
        2. Group contents: For matching groups, compare internal configuration
        Args:
            driver: SCST target driver name (e.g., 'iscsi', 'fc')
            target: Target name within the driver
            target_config: Target configuration containing 'groups' section:
                          {'groups': {group_name: {group_config}}}
        Returns:
            True if initiator groups differ in membership OR configuration
            False if all groups exist with matching configurations
            True if sysfs cannot be read (assumes difference for safety)
        Example scenarios triggering True:
            - Target has extra/missing initiator groups
            - Group exists but has different LUN assignments
            - Group exists but has different initiator membership
            - Group exists but has different attributes
            - Cannot read current group state from sysfs
        Note:
            This is a comprehensive check covering both group existence and contents.
            It delegates to _group_config_matches() for detailed group comparison.
        """
        try:
            # Get current groups
            current_groups = set()
            groups_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups"
            if os.path.exists(groups_path):
                for group_item in os.listdir(groups_path):
                    if group_item != self.sysfs.MGMT_INTERFACE and os.path.isdir(os.path.join(groups_path, group_item)):
                        current_groups.add(group_item)

            # Get desired groups
            desired_groups = set(target_config.groups.keys())

            # If different groups exist, they differ
            if current_groups != desired_groups:
                return True

            # Check if any existing group configurations differ
            for group_name in desired_groups:
                if self._group_exists(driver, target, group_name):
                    group_config = target_config.groups[group_name]
                    if not self._group_config_matches(driver, target, group_name, group_config):
                        return True
            return False
        except (OSError, IOError):
            # If we can't read current state, assume they differ
            return True

    def _update_target_groups(self, driver: str, target: str, target_config: 'TargetConfig') -> None:
        """Update initiator groups for fine-grained client access control.
        Enables different client groups to see different devices or LUN mappings.
        Only updates groups that have actually changed for optimal performance.
        Args:
            target_config: {'groups': {group_name: {'luns': {...}, 'initiators': [...]}}}
        """
        for group_name, group_config in target_config.groups.items():
            mgmt_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/mgmt"

            # Check if group exists
            if self._group_exists(driver, target, group_name):
                # Group exists - check if config actually matches
                if self._group_config_matches(driver, target, group_name, group_config):
                    self.logger.debug(
                        f"Group {group_name} for {driver}/{target} already exists with matching config, skipping")
                    continue
                else:
                    self.logger.debug(
                        f"Group {group_name} for {driver}/{target} config differs, updating incrementally")
                    # Update the group configuration incrementally
                    self._update_group_config(driver, target, group_name, group_config)
                    continue
            else:
                # Group doesn't exist - create it
                self.logger.debug(f"Group {group_name} for {driver}/{target} doesn't exist, creating")

            # Create the group if it doesn't exist
            try:
                self.sysfs.write_sysfs(mgmt_path, f"create {group_name}")
                self.logger.debug(f"Created group {group_name} for {driver}/{target}")
            except SCSTError:
                pass  # Group might already exist

            # Add initiators to the group
            group_initiators_path = (f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/"
                                     f"{group_name}/initiators/mgmt")
            for initiator in group_config.initiators:  # InitiatorGroupConfig object
                try:
                    # Remove config file escape characters for sysfs
                    clean_initiator = initiator.replace('\\#', '#').replace('\\*', '*')
                    self.sysfs.write_sysfs(group_initiators_path, f"add {clean_initiator}")
                    self.logger.debug(f"Added initiator {clean_initiator} to group {group_name}")
                except SCSTError as e:
                    self.logger.warning(f"Failed to add initiator {clean_initiator} to group {group_name}: {e}")

            # Add LUN assignments to the group
            group_luns_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/{group_name}/luns/mgmt"
            for lun_number, lun_config in group_config.luns.items():  # InitiatorGroupConfig object
                lun_device = lun_config.device  # Extract device name from LunConfig
                try:
                    self.sysfs.write_sysfs(group_luns_path, f"add {lun_device} {lun_number}")
                    self.logger.debug(f"Added LUN {lun_number} ({lun_device}) to group {group_name}")
                except SCSTError as e:
                    self.logger.warning(f"Failed to add LUN {lun_number} to group {group_name}: {e}")

    def _update_group_config(self, driver: str, target: str, group_name: str,
                             group_config: 'InitiatorGroupConfig') -> None:
        """Update initiator group membership and LUN assignments incrementally.
        Updates both initiator membership (which clients can access) and LUN assignments
        (which devices they see). Only changes what's actually different for performance.
        Args:
            group_config: InitiatorGroupConfig object with initiators and luns
        """
        # Check if the group configuration actually needs updating
        if self._group_config_matches(driver, target, group_name, group_config):
            self.logger.debug(f"Group {group_name} configuration already matches, skipping update")
            return
        self.logger.debug(f"Updating group {group_name} configuration incrementally")

        # For now, implement basic updates by checking what differs
        group_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/{group_name}"

        # Phase 1: Update initiator membership (sysfs: ini_groups/{group}/initiators/{name})
        existing_initiators = set()
        initiators_path = f"{group_path}/initiators"
        if os.path.exists(initiators_path):
            try:
                for initiator_file in os.listdir(initiators_path):
                    if initiator_file != self.sysfs.MGMT_INTERFACE and os.path.isfile(
                            os.path.join(initiators_path, initiator_file)):
                        existing_initiators.add(initiator_file)
            except (OSError, IOError):
                pass
        desired_initiators = set(group_config.initiators)
        # Handle config file escaping: \\# and \\* in config become # and * in sysfs
        normalized_existing = {init.replace('\\', '') for init in existing_initiators}
        normalized_desired = {init.replace('\\', '') for init in desired_initiators}
        # Add missing initiators
        missing_initiators = normalized_desired - normalized_existing
        for initiator in missing_initiators:
            group_initiators_mgmt = f"{group_path}/initiators/mgmt"
            self.sysfs.mgmt_operation(
                group_initiators_mgmt, "add", initiator,
                f"Added initiator {initiator} to group {group_name}",
                f"Failed to add initiator {initiator} to group {group_name}"
            )

        # Remove extra initiators
        extra_initiators = normalized_existing - normalized_desired
        for initiator in extra_initiators:
            group_initiators_mgmt = f"{group_path}/initiators/mgmt"
            self.sysfs.mgmt_operation(
                group_initiators_mgmt, "del", initiator,
                f"Removed initiator {initiator} from group {group_name}",
                f"Failed to remove initiator {initiator} from group {group_name}"
            )

        # Update LUN assignments within the group
        self._update_group_lun_assignments(driver, target, group_name, group_config)

    def _update_group_lun_assignments(self, driver: str, target: str, group_name: str,
                                      group_config: 'InitiatorGroupConfig') -> None:
        """Update LUN-to-device assignments for an initiator group.
        Enables access control by allowing different groups to see different devices
        or the same devices at different LUN numbers. Only updates assignments that
        have actually changed for optimal performance.
        Args:
            group_config: InitiatorGroupConfig object with luns property
        """
        group_luns_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/{group_name}/luns"
        group_luns_mgmt = f"{group_luns_path}/mgmt"

        # Read current LUN assignments from sysfs: /sys/.../ini_groups/{group}/luns/{lun_num}/
        current_group_luns = {}
        if os.path.exists(group_luns_path):
            try:
                for lun_item in os.listdir(group_luns_path):
                    if lun_item != self.sysfs.MGMT_INTERFACE and os.path.isdir(os.path.join(group_luns_path, lun_item)):
                        device = self.config_reader._get_current_group_lun_device(driver, target, group_name, lun_item)
                        if device:
                            current_group_luns[lun_item] = device
            except (OSError, IOError):
                pass

        # Extract desired assignments from config: {lun_number: device_name}
        desired_group_luns = {}
        for lun_number, lun_config in group_config.luns.items():
            device = lun_config.device  # LunConfig object
            if device:
                desired_group_luns[lun_number] = device

        # Phase 1: Remove obsolete LUN assignments (mgmt command: "del {lun_number}")
        luns_to_remove = set(current_group_luns.keys()) - set(desired_group_luns.keys())
        for lun_number in luns_to_remove:
            try:
                self.sysfs.write_sysfs(group_luns_mgmt, f"del {lun_number}")
                self.logger.debug(f"Removed LUN {lun_number} from group {group_name}")
            except SCSTError as e:
                self.logger.warning(f"Failed to remove LUN {lun_number} from group {group_name}: {e}")

        # Add or update LUNs that should exist
        for lun_number, device in desired_group_luns.items():
            current_device = current_group_luns.get(lun_number)
            if current_device != device:
                # LUN doesn't exist or has wrong device - add/update it
                try:
                    self.sysfs.write_sysfs(group_luns_mgmt, f"add {device} {lun_number}")
                    if current_device:
                        self.logger.debug(
                            f"Updated LUN {lun_number} in group {group_name}: {current_device} → {device}")
                    else:
                        self.logger.debug(f"Added LUN {lun_number} to group {group_name}: {device}")
                except SCSTError as e:
                    self.logger.warning(f"Failed to add LUN {lun_number} ({device}) to group {group_name}: {e}")

    def _set_lun_attributes(self, driver: str, target: str, lun_number: str, attributes: Dict[str, str]) -> None:
        """Set LUN attributes after assignment"""
        for attr_name, attr_value in attributes.items():
            attr_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns/{lun_number}/{attr_name}"
            try:
                self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
            except SCSTError as e:
                self.logger.warning(f"Failed to set {driver}/{target}/lun{lun_number}.{attr_name}: {e}")

    def _target_exists(self, driver: str, target_name: str) -> bool:
        """Check if a target already exists under a driver"""
        target_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target_name}"
        return entity_exists(target_path)

    def _target_config_differs(self, desired_attrs: Dict[str, str],
                               current_attrs: Dict[str, str],
                               removable_attrs: Optional[set] = None) -> bool:
        """Compare desired target configuration with current configuration"""
        return attrs_config_differs(desired_attrs, current_attrs, removable_attrs=removable_attrs,
                                    entity_type="Target")

    def _lun_exists(self, driver: str, target: str, lun_number: str) -> bool:
        """Check if a LUN already exists for a target"""
        lun_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns/{lun_number}"
        return entity_exists(lun_path)

    def _group_exists(self, driver: str, target: str, group_name: str) -> bool:
        """Check if an initiator group already exists for a target"""
        group_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/{group_name}"
        return entity_exists(group_path)

    def _group_config_matches(self, driver: str, target: str, group_name: str,
                              group_config: 'InitiatorGroupConfig') -> bool:
        """Check if existing initiator group configuration matches desired configuration.
        Compares current initiator group settings in sysfs against desired configuration.
        Checks both initiator list and LUN assignments within the group.
        Args:
            driver: SCST target driver name (e.g., 'iscsi')
            target: Target name within the driver
            group_name: Initiator group name
            group_config: InitiatorGroupConfig object with initiators and luns
        Returns:
            True if current and desired group configurations match, False otherwise.
            Returns False if group doesn't exist or sysfs cannot be read.
        Note:
            - Compares initiator lists (handles backslash escaping differences)
            - Compares LUN number assignments (not device mappings)
            - Returns False on any sysfs read errors for safety
        """
        try:
            group_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/{group_name}"
            if not os.path.exists(group_path):
                return False

            # Check initiators
            existing_initiators = set()
            initiators_path = f"{group_path}/initiators"
            if os.path.exists(initiators_path):
                try:
                    for initiator_file in os.listdir(initiators_path):
                        if initiator_file != self.sysfs.MGMT_INTERFACE and os.path.isfile(
                                os.path.join(initiators_path, initiator_file)):
                            existing_initiators.add(initiator_file)
                except (OSError, IOError):
                    pass
            desired_initiators = set(group_config.initiators)

            # Normalize both sets to handle backslash escaping differences
            normalized_existing = {init.replace('\\', '') for init in existing_initiators}
            normalized_desired = {init.replace('\\', '') for init in desired_initiators}
            if normalized_existing != normalized_desired:
                return False

            # Check LUN assignments
            existing_luns = {}
            luns_path = f"{group_path}/luns"
            if os.path.exists(luns_path):
                try:
                    for lun_item in os.listdir(luns_path):
                        if lun_item != self.sysfs.MGMT_INTERFACE:
                            lun_path = os.path.join(luns_path, lun_item)
                            if os.path.isdir(lun_path):
                                existing_luns[lun_item] = {}
                except (OSError, IOError):
                    pass
            desired_luns = group_config.luns
            if set(existing_luns.keys()) != set(desired_luns.keys()):
                return False
            return True
        except (OSError, IOError):
            return False

    def apply_config_assignments(self, config: 'SCSTConfig') -> None:
        """Apply target configurations with optimized incremental updates.

        Creates targets, updates attributes, and configures LUN/group assignments.
        Only updates components that have actually changed for optimal performance.
        """
        for driver_name, driver_config in config.drivers.items():
            driver_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}"

            # Process each target in the driver configuration
            for target_name, target_config in driver_config.targets.items():
                mgmt_path = f"{driver_path}/mgmt"
                target_attrs = target_config.attributes

                # Existing target: perform incremental updates (attributes, LUNs, groups)
                if self._target_exists(driver_name, target_name):
                    # Get mgmt info to identify removable attributes
                    mgmt_info = self.config_reader._get_target_mgmt_info(driver_name)

                    # Read attributes: config attrs + mgmt-managed attrs (to check for removal)
                    config_attrs_to_check = set(target_attrs.keys()) | mgmt_info['target_attributes']
                    existing_target_attrs = self.config_reader._get_current_target_attrs(
                        driver_name, target_name, config_attrs_to_check)

                    # Filter out creation-time parameters (can't be changed post-creation)
                    # Examples: InitiatorName, TargetName for iSCSI targets
                    settable_target_attrs = {k: v for k, v in target_attrs.items()
                                             if k not in mgmt_info['create_params']}
                    attrs_differ = self._target_config_differs(
                        settable_target_attrs, existing_target_attrs,
                        removable_attrs=mgmt_info['target_attributes'])

                    # Phase 1: Update target attributes if they've changed
                    if attrs_differ:
                        self.logger.debug(f"Target attributes differ for {driver_name}/{target_name}, updating")
                        self.update_target_attributes(driver_name, target_name, settable_target_attrs,
                                                      existing_target_attrs)

                    # Phase 2: Check all assignment types (independent of attribute changes)
                    # Three types of LUN/access assignments that can change independently:
                    direct_luns_differ = self._direct_lun_assignments_differ(driver_name, target_name,
                                                                             target_config)  # Target-level LUNs

                    group_luns_differ = self._group_lun_assignments_differ(driver_name, target_name,
                                                                           target_config)  # Group-specific LUNs

                    groups_differ = self._group_assignments_differ(driver_name, target_name,
                                                                   target_config)  # Group membership

                    if direct_luns_differ:
                        self.logger.debug(f"Direct LUN assignments differ for {driver_name}/{target_name}, updating")
                        self.apply_lun_assignments(driver_name, target_name, target_config)

                    if group_luns_differ or groups_differ:
                        self.logger.debug(f"Group assignments differ for {driver_name}/{target_name}, updating")
                        self._update_target_groups(driver_name, target_name, target_config)

                    if not (attrs_differ or direct_luns_differ or group_luns_differ or groups_differ):
                        self.logger.debug(
                            f"Target {driver_name}/{target_name} already exists with matching config, skipping")

                    continue

                # Create the target if it doesn't exist
                creation_params = self.config_reader._get_target_create_params(driver_name, target_attrs)

                # For virtual targets (those with creation params like node_name),
                # ensure hardware targets are enabled first
                if creation_params:
                    self.ensure_hardware_targets_enabled(driver_name, config.drivers[driver_name])

                if creation_params:
                    params_str = ';'.join([f"{k}={v}" for k, v in creation_params.items()])
                    command = f"add_target {target_name} {params_str}"
                else:
                    command = f"add_target {target_name}"

                self.sysfs.write_sysfs(mgmt_path, command)

                # Set remaining target attributes after creation
                remaining_attrs = {k: v for k, v in target_attrs.items()
                                   if k not in creation_params}
                if remaining_attrs:
                    self.set_target_attributes(driver_name, target_name, remaining_attrs)

                # Apply LUN assignments
                self.apply_lun_assignments(
                    driver_name, target_name, target_config)

                # Apply group assignments
                self.apply_group_assignments(
                    driver_name, target_name, target_config)

    def cleanup_copy_manager_duplicates(self, config: 'SCSTConfig') -> None:
        """Remove duplicate copy_manager LUN assignments to prevent conflicts.

        SCST copy_manager automatically creates LUNs but explicit config may specify
        different LUN numbers. Cleans up auto-created duplicates after explicit assignment.
        """
        # Early exit if no copy_manager driver configured
        copy_manager_config = config.drivers.get('copy_manager')
        if not copy_manager_config:
            return

        # Extract explicit LUN configuration from copy_manager_tgt
        target_config = copy_manager_config.targets.get('copy_manager_tgt')
        explicit_luns = target_config.luns if target_config else {}
        if not explicit_luns:
            return  # No explicit LUNs configured, nothing to clean up

        # Build mapping of devices to their desired LUN numbers
        # Example: {'disk1': '0', 'disk2': '1'} from config LUN assignments
        explicit_devices = {}
        for lun_number, lun_config in explicit_luns.items():
            device = lun_config.device
            if device:
                explicit_devices[device] = lun_number

        if not explicit_devices:
            return  # No device mappings found

        # Scan current sysfs LUNs to find auto-created duplicates
        # copy_manager automatically creates LUNs which may conflict with explicit config
        luns_path = "/sys/kernel/scst_tgt/targets/copy_manager/copy_manager_tgt/luns"
        if not os.path.exists(luns_path):
            return

        try:
            luns_to_remove = []
            for lun_item in os.listdir(luns_path):
                if lun_item != self.sysfs.MGMT_INTERFACE and os.path.isdir(f"{luns_path}/{lun_item}"):
                    # Get device assigned to this LUN number
                    device = self.config_reader._get_current_lun_device('copy_manager', 'copy_manager_tgt', lun_item)

                    if device in explicit_devices:
                        # Check if this device should be at a different LUN number
                        if explicit_devices[device] != lun_item:
                            # Duplicate found: same device at wrong LUN number
                            # Keep the explicit assignment, remove the auto-created one
                            luns_to_remove.append(lun_item)
                            expected = explicit_devices[device]
                            self.logger.debug(
                                f"Found duplicate LUN {lun_item} for device {device} (expected: {expected})")
                    else:
                        # Device NOT in explicit config - remove it (Perl behavior for copy_manager)
                        # copy_manager auto-creates LUNs, but we only keep explicitly configured ones
                        luns_to_remove.append(lun_item)
                        self.logger.debug(f"Found LUN {lun_item} for device {device} not in config, removing")

            # Clean up duplicates using SCST management interface
            if luns_to_remove:
                mgmt_path = f"{luns_path}/mgmt"
                for lun_num in luns_to_remove:
                    try:
                        # Management command: "del {lun_number}"
                        self.sysfs.write_sysfs(mgmt_path, f"del {lun_num}")
                        self.logger.debug(f"Removed duplicate LUN {lun_num} from copy_manager_tgt")
                    except SCSTError as e:
                        self.logger.warning(f"Failed to remove duplicate LUN {lun_num}: {e}")

        except (OSError, IOError) as e:
            self.logger.warning(f"Failed to cleanup copy_manager duplicates: {e}")

    def ensure_hardware_targets_enabled(self, driver_name: str, driver_config: 'DriverConfig') -> None:
        """Enable hardware targets that should be active according to configuration.

        Hardware targets (FC, SAS) require explicit enabling to become accessible.
        Only updates targets that aren't already enabled for optimal performance.
        """
        try:
            # Scan existing targets in driver sysfs directory
            driver_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}"
            if not self.sysfs.valid_path(driver_path):
                return  # Driver not loaded or doesn't exist

            existing_targets = self.sysfs.list_directory(driver_path)
            driver_attrs = self.DRIVER_ATTRIBUTES.get(driver_name, set())

            for target in existing_targets:
                # Filter out driver-level attributes and management interfaces
                if target in driver_attrs or target == self.sysfs.MGMT_INTERFACE:
                    continue

                target_path = f"{driver_path}/{target}"
                if not os.path.isdir(target_path):
                    continue  # Skip non-directory entries

                # Hardware target detection: check for 'hw_target' attribute
                # Hardware targets (FC WWPNs, SAS addresses) vs software targets (iSCSI IQNs)
                hw_target_path = f"{target_path}/hw_target"
                if not self.sysfs.valid_path(hw_target_path):
                    continue  # Software target, no enabling needed

                try:
                    hw_target_value = self.sysfs.read_sysfs_attribute(hw_target_path)
                    if hw_target_value != "1":
                        continue  # hw_target exists but not set to "1"
                except SCSTError:
                    continue  # Can't read hw_target attribute

                # Read current enabled state from sysfs
                enabled_path = f"{target_path}/enabled"
                try:
                    current_enabled = self.sysfs.read_sysfs_attribute(enabled_path)
                except SCSTError:
                    continue  # Can't read enabled attribute

                # Determine desired state from configuration
                # Default to disabled ('0') if not explicitly configured
                target_config = driver_config.targets.get(target)
                target_attrs = target_config.attributes if target_config else {}
                should_be_enabled = target_attrs.get('enabled', '0') == '1'

                # Enable hardware target if it should be enabled but currently isn't
                if should_be_enabled and current_enabled != '1':
                    self.logger.debug(f"Enabling hardware target {driver_name}/{target} for virtual target creation")
                    try:
                        self.sysfs.write_sysfs(enabled_path, '1', check_result=False)
                    except SCSTError as e:
                        self.logger.warning(f"Failed to enable hardware target {driver_name}/{target}: {e}")

        except SCSTError as e:
            self.logger.warning(f"Failed to check hardware targets for {driver_name}: {e}")

    def apply_lun_assignments(
            self,
            driver: str,
            target: str,
            target_config: Dict[str, Any]) -> None:
        """Apply direct LUN-to-device assignments for a target.

        Creates LUN assignments with proper parameter handling and device verification.
        Only updates LUNs that have different device assignments for performance.
        """
        # Target LUN management path: /sys/.../targets/{driver}/{target}/luns/mgmt
        luns_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns/mgmt"

        # For copy_manager: pre-build mappings to avoid O(n^2) complexity during duplicate detection
        # existing_lun_map: tracks which LUN each device is currently assigned to
        # current_lun_devices: enables fast lookup of current device assignments without sysfs reads
        existing_lun_map = {}  # {device: lun_number}
        current_lun_devices = {}  # {lun_number: device}
        if driver == 'copy_manager' and target == 'copy_manager_tgt':
            luns_dir = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/luns"
            if os.path.exists(luns_dir):
                for existing_lun in os.listdir(luns_dir):
                    if existing_lun != self.sysfs.MGMT_INTERFACE and os.path.isdir(f"{luns_dir}/{existing_lun}"):
                        existing_device = self.config_reader._get_current_lun_device(driver, target, existing_lun)
                        if existing_device:
                            existing_lun_map[existing_device] = existing_lun
                            current_lun_devices[existing_lun] = existing_device

        # Cache LUN create params lookup - same for all LUNs with same driver/target (performance)
        # This avoids reading mgmt file 100 times for 100 LUNs
        lun_create_params_cache = {}

        for lun_number, lun_config in target_config.luns.items():
            device = lun_config.device  # LunConfig object
            if not device:
                continue  # Skip empty device assignments

            # Special handling for copy_manager: check if device already has a LUN assigned elsewhere
            if driver == 'copy_manager' and target == 'copy_manager_tgt':
                existing_lun = existing_lun_map.get(device)
                if existing_lun and existing_lun != lun_number:
                    # Device already assigned to different LUN, remove it first
                    self.logger.debug(
                        f"Device {device} already at LUN {existing_lun}, removing before "
                        f"assigning to LUN {lun_number}")
                    try:
                        self.sysfs.write_sysfs(luns_path, f"del {existing_lun}")
                        # Update maps since we removed it
                        del existing_lun_map[device]
                        if existing_lun in current_lun_devices:
                            del current_lun_devices[existing_lun]
                    except SCSTError as e:
                        self.logger.warning(f"Failed to remove existing LUN {existing_lun}: {e}")

            # Optimization: check if LUN assignment already correct (avoid unnecessary operations)
            lun_exists = self._lun_exists(driver, target, lun_number)
            if lun_exists:
                # For copy_manager, use cached device mapping; otherwise read from sysfs
                if driver == 'copy_manager' and target == 'copy_manager_tgt':
                    current_device = current_lun_devices.get(lun_number, "")
                else:
                    current_device = self.config_reader._get_current_lun_device(driver, target, lun_number)
                if current_device == device:
                    # LUN already correctly assigned, skip this LUN
                    self.logger.debug(
                        f"LUN {lun_number} for {driver}/{target} already assigned to correct device {device}, skipping")
                    continue
                elif current_device == "":
                    # LUN exists but device symlink is broken/stale - must recreate assignment
                    self.logger.debug(
                        f"LUN {lun_number} for {driver}/{target} has broken device symlink, removing and recreating")
                    try:
                        # Management command: "del {lun_number}"
                        self.sysfs.write_sysfs(luns_path, f"del {lun_number}")
                    except SCSTError as e:
                        self.logger.warning(f"Failed to remove existing LUN {lun_number} for {driver}/{target}: {e}")
                        # Continue anyway - the new assignment might still work
                else:
                    # LUN exists but points to wrong device - must recreate assignment
                    self.logger.debug(
                        f"LUN {lun_number} for {driver}/{target} assigned to different device "
                        f"({current_device} vs {device}), removing and recreating")
                    try:
                        # Management command: "del {lun_number}"
                        self.sysfs.write_sysfs(luns_path, f"del {lun_number}")
                    except SCSTError as e:
                        self.logger.warning(f"Failed to remove existing LUN {lun_number} for {driver}/{target}: {e}")
                        # Continue anyway - the new assignment might still work

            # Separate creation-time vs post-creation LUN parameters
            # Some attributes must be set during LUN creation, others can be set afterward
            # Use cached create params if available (same for all LUNs with same driver/target)
            if not lun_create_params_cache:
                lun_create_params_cache['params'] = self.config_reader._get_lun_create_params(
                    driver, target, lun_config.attributes)

            # Filter for this LUN's specific create params
            lun_create_params = {k: v for k, v in lun_config.attributes.items()
                                 if k in lun_create_params_cache.get('params', {})}
            lun_post_params = {k: v for k, v in lun_config.attributes.items()
                               if k not in lun_create_params}

            # Build SCST management command with creation-time parameters
            # Format: "add {device} {lun_number} param1=value1;param2=value2;"
            if lun_create_params:
                params_str = ';'.join([f"{k}={v}" for k, v in lun_create_params.items()])
                command = f"add {device} {lun_number} {params_str};"
            else:
                # Simple assignment with no creation parameters
                command = f"add {device} {lun_number}"

            # Execute LUN assignment command
            self.sysfs.write_sysfs(luns_path, command)

            # Apply post-creation attributes that couldn't be set during creation
            if lun_post_params:
                self._set_lun_attributes(driver, target, lun_number, lun_post_params)

    def apply_group_assignments(
            self,
            driver: str,
            target: str,
            target_config: Dict[str, Any]) -> None:
        """Apply initiator group configurations for access control.

        Creates groups with initiator membership and LUN assignments. Uses optimized
        checks to only update groups that have different configurations.
        """
        # Process each initiator group configuration for this target
        for group_name, group_config in target_config.groups.items():
            # Initiator group management path: /sys/.../targets/{driver}/{target}/ini_groups/mgmt
            mgmt_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/mgmt"

            # Optimization: skip groups that already have correct configuration
            if self._group_exists(driver, target, group_name):
                if self._group_config_matches(driver, target, group_name, group_config):
                    self.logger.debug(
                        f"Group {group_name} for {driver}/{target} already exists with matching config, skipping")
                    continue  # Group already correctly configured
                else:
                    self.logger.debug(f"Group {group_name} for {driver}/{target} exists but config differs")

            # Create initiator group (will be no-op if already exists)
            try:
                # Management command: "create {group_name}"
                self.sysfs.write_sysfs(mgmt_path, f"create {group_name}")
                self.logger.debug(f"Created group {group_name} for {driver}/{target}")
            except SCSTError:
                pass  # Group creation might fail if already exists

            # Phase 1: Configure initiator membership within the group
            # Each group defines which clients (initiators) can access through this path
            group_initiators_path = (f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/"
                                     f"{group_name}/initiators/mgmt")
            for initiator in group_config.initiators:  # InitiatorGroupConfig object
                try:
                    # Handle config file escaping: \\# and \\* become # and * in sysfs
                    clean_initiator = initiator.replace('\\#', '#').replace('\\*', '*')
                    # Management command: "add {initiator_name}"
                    self.sysfs.write_sysfs(group_initiators_path, f"add {clean_initiator}")
                    self.logger.debug(f"Added initiator {clean_initiator} to group {group_name}")
                except SCSTError:
                    pass  # Initiator addition might fail if already exists

            # Phase 2: Configure LUN assignments within the group
            # Each group can have different device visibility (different LUN mappings)
            group_luns_path = f"{self.sysfs.SCST_TARGETS}/{driver}/{target}/ini_groups/{group_name}/luns/mgmt"
            for lun_number, lun_config in group_config.luns.items():
                device_name = lun_config.device  # LunConfig object
                try:
                    # Management command: "add {device} {lun_number}"
                    self.sysfs.write_sysfs(group_luns_path, f"add {device_name} {lun_number}")
                    self.logger.debug(f"Added LUN {lun_number} ({device_name}) to group {group_name}")
                except SCSTError:
                    pass  # LUN assignment might fail if already exists

    def apply_config_enable_targets(self, config: 'SCSTConfig') -> None:
        """Activate configured targets to begin serving storage to initiators.

        Targets must be explicitly enabled after configuration to start accepting
        connections and serving LUNs to SCSI initiators.
        """
        for driver_name, driver_config in config.drivers.items():
            for target_name, target_config in driver_config.targets.items():
                enabled = target_config.attributes.get('enabled', '0')
                if enabled == '1':
                    enabled_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}/enabled"
                    try:
                        # Avoid unnecessary sysfs writes for performance
                        current_value = self.sysfs.read_sysfs(enabled_path)
                        if current_value != '1':
                            self.sysfs.write_sysfs(enabled_path, '1', check_result=False)
                    except SCSTError:
                        # Fallback: attempt enable even if current state unknown
                        try:
                            self.sysfs.write_sysfs(enabled_path, '1', check_result=False)
                        except SCSTError:
                            pass

    def apply_config_enable_drivers(self, config: 'SCSTConfig') -> None:
        """Activate SCST protocol drivers to accept initiator connections.

        Drivers like iSCSI, FC, and SRP must be enabled to process protocol-specific
        requests and present targets to the network.
        """
        for driver_name, driver_config in config.drivers.items():
            enabled = driver_config.attributes.get('enabled', '0')
            if enabled == '1':
                enabled_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/enabled"
                try:
                    # Avoid unnecessary sysfs writes for performance
                    current_value = self.sysfs.read_sysfs(enabled_path)
                    if current_value != '1':
                        self.sysfs.write_sysfs(enabled_path, '1', check_result=False)
                except SCSTError:
                    # Fallback: attempt enable even if current state unknown
                    try:
                        self.sysfs.write_sysfs(enabled_path, '1', check_result=False)
                    except SCSTError:
                        pass

    def apply_config_driver_attributes(self, config: 'SCSTConfig') -> None:
        """Configure protocol driver parameters for optimal performance and behavior.

        Sets driver-specific attributes like threading models, queue depths, and
        protocol parameters. Skips 'enabled' which is handled separately for proper
        initialization ordering.
        """
        for driver_name, driver_config in config.drivers.items():
            driver_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}"

            # Skip drivers not loaded in current kernel
            if not self.sysfs.valid_path(driver_path):
                self.logger.warning(f"Driver {driver_name} not available")
                continue

            # Apply configuration attributes (enabled handled separately for proper sequencing)
            for attr_name, attr_value in driver_config.attributes.items():
                if attr_name == 'enabled':
                    continue  # Skip enabled - must be set after other attributes

                attr_path = f"{driver_path}/{attr_name}"

                # Skip read-only attributes to avoid errors
                if not os.access(attr_path, os.W_OK) if os.path.exists(attr_path) else True:
                    if os.path.exists(attr_path):
                        self.logger.debug(f"Skipping non-writable attribute {driver_name}.{attr_name}")
                        continue

                try:
                    # Avoid unnecessary sysfs writes for performance
                    if self.sysfs.valid_path(attr_path):
                        current_value = self.sysfs.read_sysfs_attribute(attr_path)
                        if current_value != attr_value:
                            self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
                            self.logger.debug(f"Set driver attribute {driver_name}.{attr_name} = {attr_value}")
                    else:
                        # Fallback: attempt write even if path validation failed
                        self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
                        self.logger.debug(f"Set driver attribute {driver_name}.{attr_name} = {attr_value}")
                except SCSTError as e:
                    self.logger.warning(f"Failed to set driver attribute {driver_name}.{attr_name}: {e}")

    def _disable_target_if_possible(self, driver_name: str, target_name: str) -> None:
        """Disable target to prevent new connections if it has an enabled attribute"""
        try:
            enabled_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}/enabled"
            if self.sysfs.valid_path(enabled_path):
                self.sysfs.write_sysfs(enabled_path, "0", check_result=False)
                self.logger.debug(f"Disabled target {driver_name}/{target_name}")
        except SCSTError:
            # Some targets may not have an 'enabled' attribute - this is okay
            pass

    def _force_close_target_sessions(self, driver_name: str, target_name: str, timeout: int = 300) -> bool:
        """Force close active sessions and wait for them to terminate"""

        sessions_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}/sessions"
        if not self.sysfs.valid_path(sessions_path):
            return True  # No sessions directory means no sessions

        # Get all current sessions
        try:
            sessions = self.sysfs.list_directory(sessions_path)
            sessions = [s for s in sessions if s != self.sysfs.MGMT_INTERFACE]
        except SCSTError:
            return True  # No sessions or can't read directory

        if not sessions:
            return True  # No active sessions

        self.logger.debug(f"Found {len(sessions)} active sessions for target {driver_name}/{target_name}")

        # Try to force close sessions that support it
        force_closable_sessions = set()
        for session in sessions:
            session_path = f"{sessions_path}/{session}"
            force_close_path = f"{session_path}/force_close"

            if self.sysfs.valid_path(force_close_path):
                try:
                    self.sysfs.write_sysfs(force_close_path, "1", check_result=False)
                    force_closable_sessions.add(session)
                    self.logger.debug(f"Initiated force close for session {session}")
                except SCSTError as e:
                    self.logger.warning(f"Failed to force close session {session}: {e}")

        if not force_closable_sessions:
            self.logger.debug("No sessions support force close")
            return False

        # Wait for sessions to close (up to timeout seconds)
        start_time = time.time()
        remaining_sessions = force_closable_sessions.copy()

        while remaining_sessions and (time.time() - start_time) < timeout:
            # Check which sessions have actually closed
            try:
                current_sessions = set(self.sysfs.list_directory(sessions_path))
                current_sessions = {s for s in current_sessions if s != self.sysfs.MGMT_INTERFACE}

                # Remove sessions that are no longer active
                closed_sessions = remaining_sessions - current_sessions
                for session in closed_sessions:
                    remaining_sessions.remove(session)
                    self.logger.debug(f"Session {session} has closed")

                if remaining_sessions:
                    time.sleep(1)  # Wait 1 second before checking again

            except SCSTError:
                # If we can't read the sessions directory, assume sessions have closed
                break

        if remaining_sessions:
            self.logger.warning(f"Sessions {remaining_sessions} did not close within {timeout} seconds")
            return False

        self.logger.debug(f"All sessions closed for target {driver_name}/{target_name}")
        return True

    def remove_target(self, driver_name: str, target_name: str) -> None:
        """Remove a target and all its contents with session management"""
        try:
            target_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}"

            # First, disable the target to prevent new connections
            self._disable_target_if_possible(driver_name, target_name)

            # Force close any active sessions
            if not self._force_close_target_sessions(driver_name, target_name):
                self.logger.warning(f"Some sessions remained active for target {driver_name}/{target_name}")

            # Clear all LUNs first
            luns_mgmt = f"{target_path}/luns/mgmt"
            if self.sysfs.valid_path(luns_mgmt):
                self.sysfs.write_sysfs(luns_mgmt, "clear")

            # Remove all initiator groups
            groups_path = f"{target_path}/ini_groups"
            if self.sysfs.valid_path(groups_path):
                groups_mgmt = f"{groups_path}/mgmt"
                for group in self.sysfs.list_directory(groups_path):
                    if group != self.sysfs.MGMT_INTERFACE:
                        # Clear group LUNs first
                        group_luns_mgmt = f"{groups_path}/{group}/luns/mgmt"
                        if self.sysfs.valid_path(group_luns_mgmt):
                            self.sysfs.write_sysfs(group_luns_mgmt, "clear")
                        # Remove the group
                        self.sysfs.write_sysfs(groups_mgmt, f"del {group}")

            # Remove the target itself
            driver_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver_name}/mgmt"
            self.sysfs.write_sysfs(driver_mgmt, f"del_target {target_name}")

        except SCSTError as e:
            self.logger.warning(
                f"Failed to remove target {driver_name}/{target_name}: {e}")

    def _remove_obsolete_luns(self, driver_name: str, target_name: str,
                              current_target: 'TargetConfig', new_target: 'TargetConfig') -> None:
        """Remove LUNs that are not in the new configuration"""
        try:
            current_luns = set(current_target.luns.keys())
            new_luns = set(new_target.luns.keys())
            luns_to_remove = current_luns - new_luns

            if luns_to_remove:
                luns_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}/luns/mgmt"
                for lun_number in luns_to_remove:
                    self.sysfs.write_sysfs(luns_mgmt, f"del {lun_number}")

        except SCSTError as e:
            self.logger.warning(f"Failed to remove obsolete LUNs: {e}")

    def _remove_obsolete_groups(self, driver_name: str, target_name: str,
                                current_target: 'TargetConfig', new_target: 'TargetConfig') -> None:
        """Remove initiator groups that are not in the new configuration"""
        try:
            current_groups = set(current_target.groups.keys())
            new_groups = set(new_target.groups.keys())
            groups_to_remove = current_groups - new_groups

            if groups_to_remove:
                groups_mgmt = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}/ini_groups/mgmt"
                for group_name in groups_to_remove:
                    # Clear group LUNs first
                    group_luns_mgmt = (f"{self.sysfs.SCST_TARGETS}/{driver_name}/{target_name}"
                                       f"/ini_groups/{group_name}/luns/mgmt")
                    if self.sysfs.valid_path(group_luns_mgmt):
                        self.sysfs.write_sysfs(group_luns_mgmt, "clear")
                    # Remove the group
                    self.sysfs.write_sysfs(groups_mgmt, f"del {group_name}")

        except SCSTError as e:
            self.logger.warning(f"Failed to remove obsolete groups: {e}")

    def _remove_obsolete_driver_attributes(
            self,
            current_config: 'SCSTConfig',
            new_config: 'SCSTConfig') -> None:
        """Remove driver attributes that are no longer present in the new configuration"""
        for driver_name, current_driver_config in current_config.drivers.items():
            # Skip if driver not in new config (will be handled by driver removal)
            new_driver_config = new_config.drivers.get(driver_name)
            if new_driver_config is None:
                continue

            current_attributes = current_driver_config.attributes
            new_attributes = new_driver_config.attributes

            # Find attributes that exist in current but not in new config
            for attr_name in current_attributes:
                if attr_name not in new_attributes:
                    self._remove_driver_attribute(driver_name, attr_name)

    def _remove_driver_attribute(self, driver_name: str, attr_name: str) -> None:
        """Remove a specific driver attribute by resetting it to default value"""
        try:
            attr_path = f"{self.sysfs.SCST_TARGETS}/{driver_name}/{attr_name}"

            # Skip if attribute file doesn't exist or isn't writable
            if not self.sysfs.valid_path(attr_path) or not os.access(attr_path, os.W_OK):
                self.logger.debug(f"Cannot remove driver attribute {driver_name}.{attr_name}: not accessible")
                return

            # Get the default value for this attribute if possible
            default_value = self.config_reader._get_driver_attribute_default(driver_name, attr_name)

            if default_value is not None:
                current_value = self.sysfs.read_sysfs_attribute(attr_path)
                if current_value != default_value:
                    self.sysfs.write_sysfs(attr_path, default_value, check_result=False)
                    self.logger.info(f"Reset driver attribute {driver_name}.{attr_name} to default: {default_value}")
            else:
                # Try to reset to system default by writing newline
                self.sysfs.write_sysfs(attr_path, '\n', check_result=False)
                self.logger.debug(f"Reset driver attribute {driver_name}.{attr_name} to system default")

        except SCSTError as e:
            self.logger.warning(f"Failed to remove driver attribute {driver_name}.{attr_name}: {e}")
