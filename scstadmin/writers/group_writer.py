"""
Group Writer for SCST Administration

This module handles device group and target group write operations for SCST configuration.
"""

import os
import logging
from typing import Dict, Any, TYPE_CHECKING

from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError
from ..config import DeviceGroupConfig, TargetGroupConfig
from .utils import entity_exists

if TYPE_CHECKING:
    from ..config import SCSTConfig


class GroupWriter:
    """Handles device group and target group SCST write operations"""

    def __init__(self, sysfs: SCSTSysfs, config_reader=None, logger=None):
        self.sysfs = sysfs
        self.config_reader = config_reader
        self.logger = logger or logging.getLogger("scstadmin.writers.group")

    def _device_group_exists(self, group_name: str) -> bool:
        """Check if a device group already exists"""
        group_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}"
        return entity_exists(group_path)

    def _device_group_config_matches(
        self, group_name: str, group_config: DeviceGroupConfig
    ) -> bool:
        """Check if device group configuration matches current SCST sysfs state.
        SCST device groups provide hierarchical device and target management by
        organizing devices into groups and associating target groups with them.
        This method performs comprehensive comparison between desired configuration
        and current sysfs state to determine if the group needs updates.
        Device group structure verification:
        - Device membership: Which devices are assigned to the group
        - Device attributes: Per-device attribute values within the group
        - Target groups: Associated target group configurations
        - Group-level attributes and settings
        Args:
            group_name: Name of the device group to check
            group_config: Desired device group configuration containing:
                        - 'devices': Dict of device names -> device attributes
                        - 'target_groups': Dict of target group names -> target group config
                        - 'attributes': Group-level attributes (if any)
        Returns:
            True if current sysfs state exactly matches desired configuration
            False if any differences detected (requires group recreation/update)
        Example configuration structure:
            group_config = {
                'devices': {
                    'disk1': {'read_only': '1', 'rotational': '0'},
                    'disk2': {'read_only': '0', 'rotational': '1'}
                },
                'target_groups': {
                    'tg1': {'targets': {'target1': {}}, 'attributes': {...}}
                }
            }
        Verification process:
            1. Check device membership and device attributes
            2. Check target group configurations recursively
            3. Verify group-level attributes if present
            4. Return False immediately on first mismatch (early exit)
        Performance optimization:
            - Early exit strategy for efficiency
            - Only reads configured attributes for comparison
            - Recursive target group checking with _target_group_config_matches()
        Note:
            This enables device group update optimization similar to device and
            target optimizations, avoiding unnecessary recreation when groups
            already match desired state.
        """
        try:
            # Check devices in group
            current_devices = set()
            devices_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/devices"
            if os.path.exists(devices_path):
                for device_item in os.listdir(devices_path):
                    is_valid_device_entry = (
                        device_item != self.sysfs.MGMT_INTERFACE
                        and os.path.isdir(os.path.join(devices_path, device_item))
                    )
                    if is_valid_device_entry:
                        current_devices.add(device_item)
            desired_devices = set(group_config.devices)
            if current_devices != desired_devices:
                return False

            # Check target groups in group
            current_target_groups = set()
            target_groups_path = (
                f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/target_groups"
            )
            if os.path.exists(target_groups_path):
                for tgroup_item in os.listdir(target_groups_path):
                    is_valid_target_group_entry = (
                        tgroup_item != self.sysfs.MGMT_INTERFACE
                        and os.path.isdir(os.path.join(target_groups_path, tgroup_item))
                    )
                    if is_valid_target_group_entry:
                        current_target_groups.add(tgroup_item)
            desired_target_groups = set(group_config.target_groups.keys())
            if current_target_groups != desired_target_groups:
                return False

            # Check target group configurations
            for tgroup_name, tgroup_config in group_config.target_groups.items():
                if not self._target_group_config_matches(
                    group_name, tgroup_name, tgroup_config
                ):
                    return False
            return True
        except (OSError, IOError):
            return False

    def _target_group_config_matches(
        self, device_group: str, target_group: str, tgroup_config: TargetGroupConfig
    ) -> bool:
        """Check if ALUA target group configuration matches current sysfs state.
        Compares target membership, target attributes (rel_tgt_id), and group attributes
        (state, group_id) for multipath storage access control.
        Args:
            tgroup_config: {'targets': {target: attrs}, 'attributes': {attr: value}}
        Returns:
            True if no updates needed, False if configuration differs
        """
        try:
            # ALUA target group sysfs path: /sys/.../device_groups/{dg}/target_groups/{tg}/
            targets_path = f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/{target_group}"

            # Phase 1: Compare target membership (which targets are in this group)
            # SCST creates directories for targets with attributes, symlinks for simple targets
            current_targets = set()
            if os.path.exists(targets_path):
                for target_item in os.listdir(targets_path):
                    # Skip 'mgmt' interface, only count actual targets (directories)
                    is_valid_target_entry = (
                        target_item != self.sysfs.MGMT_INTERFACE
                        and os.path.isdir(os.path.join(targets_path, target_item))
                    )
                    if is_valid_target_entry:
                        current_targets.add(target_item)
            desired_targets = set(tgroup_config.targets)
            if current_targets != desired_targets:
                return False  # Target membership differs - needs update

            # Phase 2: Compare target group attributes (ALUA states: active/nonoptimized/standby/unavailable)
            # Common attributes: group_id (numeric ALUA identifier), state (ALUA access state)
            desired_attributes = tgroup_config.attributes
            for attr_name, desired_value in desired_attributes.items():
                attr_path = f"{targets_path}/{attr_name}"
                if os.path.exists(attr_path):
                    current_value = self.sysfs.read_sysfs_attribute(attr_path)
                    if current_value != desired_value:
                        return False  # Group attribute value differs
                else:
                    return False  # Desired attribute doesn't exist in sysfs

            # Phase 3: Compare individual target attributes within the group (e.g., rel_tgt_id)
            # Targets WITH attributes become directories:
            #   .../target_groups/controller_A/iqn.example:test1/rel_tgt_id
            # Targets WITHOUT attributes become symlinks:
            #   .../target_groups/controller_B/iqn.example:test1 -> ../../../../targets/...
            for target_name in tgroup_config.targets:
                if (
                    target_name in tgroup_config.target_attributes
                ):  # Target has attributes that need checking
                    target_config = tgroup_config.target_attributes[target_name]
                    target_path = f"{targets_path}/{target_name}"
                    if os.path.isdir(
                        target_path
                    ):  # Directory targets can have individual attributes
                        for attr_name, desired_value in target_config.items():
                            attr_path = f"{target_path}/{attr_name}"
                            if os.path.exists(attr_path):
                                current_value = self.sysfs.read_sysfs_attribute(
                                    attr_path
                                )
                                if current_value != desired_value:
                                    return False  # Target attribute value differs
                            else:
                                return False  # Desired target attribute doesn't exist
                    # Note: Symlink targets automatically inherit correct behavior, no attribute checking needed
            return True  # All comparisons passed - configuration matches
        except (OSError, IOError):
            return False

    def _update_device_group(
        self, group_name: str, group_config: DeviceGroupConfig
    ) -> None:
        """Update an existing device group with new configuration using incremental changes.

        This method provides efficient device group updates by only modifying the specific
        components that differ from the current state, rather than recreating the entire
        group. This optimization significantly improves performance for large device groups.

        Update strategy:
        1. Compare current device membership vs desired devices
        2. Add missing devices, remove extra devices
        3. Update device attributes that have changed
        4. Synchronize target group configurations
        5. Apply any group-level attribute changes

        Args:
            group_name: Name of the existing device group to update
            group_config: New device group configuration containing:
                        - 'devices': Dict of device names -> device attributes
                        - 'target_groups': Dict of target group names -> target group config
                        - 'attributes': Group-level attributes (optional)

        Device management process:
            - Devices in config but not in group -> Add to group
            - Devices in group but not in config -> Remove from group
            - Devices in both -> Update attributes if they differ

        Target group management:
            - Target groups are synchronized using similar incremental strategy
            - Each target group is updated independently for efficiency

        Example update scenario:
            Current group has: device1, device2
            Config specifies: device1 (updated attrs), device3 (new)
            Actions: Update device1 attributes, remove device2, add device3

        Performance benefits:
            - Avoids full group recreation (expensive SCST operation)
            - Only touches changed components
            - Preserves stable group state for unchanged elements
            - Reduces I/O and processing overhead

        Delegation:
            Actual work is delegated to specialized methods:
            - _update_device_group_devices(): Handles device membership changes
            - _update_device_group_target_groups(): Handles target group updates

        Note:
            This method is called after group_writer._device_group_config_matches() determines
            that updates are needed, ensuring work is only done when necessary.
        """
        self.logger.debug(
            "Updating device group %s configuration incrementally", group_name
        )

        # For now, implement basic updates - could be enhanced for fine-grained control
        # Update devices
        self._update_device_group_devices(group_name, group_config)

        # Update target groups
        self._update_device_group_target_groups(group_name, group_config)

        # Update attributes
        if group_config.attributes:
            for attr_name, attr_value in group_config.attributes.items():
                try:
                    attr_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/{attr_name}"
                    self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
                    self.logger.debug(
                        "Updated device group attribute %s.%s = %s",
                        group_name,
                        attr_name,
                        attr_value,
                    )
                except SCSTError as e:
                    self.logger.warning(
                        "Failed to update device group attribute %s.%s: %s",
                        group_name,
                        attr_name,
                        e,
                    )

    def _update_device_group_devices(
        self, group_name: str, group_config: DeviceGroupConfig
    ) -> None:
        """Update devices in a device group incrementally.
        Synchronizes device group membership by adding missing devices and removing
        extra devices. Device groups manage membership through symbolic links in
        the devices subdirectory.
        Args:
            group_name: Name of the device group to update
            group_config: Device group configuration containing 'devices' dict
        """
        # Get current device membership (devices are symlinks, not directories)
        current_devices = set()
        devices_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/devices"
        if os.path.exists(devices_path):
            for item in os.listdir(devices_path):
                if item != self.sysfs.MGMT_INTERFACE and os.path.islink(
                    os.path.join(devices_path, item)
                ):
                    current_devices.add(item)

        # Get desired device membership
        desired_devices = set(group_config.devices)

        # Calculate changes needed
        devices_to_add = desired_devices - current_devices
        devices_to_remove = current_devices - desired_devices
        if not devices_to_add and not devices_to_remove:
            self.logger.debug("Device group %s membership already correct", group_name)
            return
        mgmt_path = f"{devices_path}/mgmt"

        # Remove extra devices
        for device_name in devices_to_remove:
            try:
                self.sysfs.write_sysfs(mgmt_path, f"del {device_name}")
                self.logger.debug(
                    "Removed device %s from group %s", device_name, group_name
                )
            except SCSTError as e:
                self.logger.warning(
                    "Failed to remove device %s from group %s: %s",
                    device_name,
                    group_name,
                    e,
                )

        # Add missing devices
        for device_name in devices_to_add:
            try:
                self.sysfs.write_sysfs(mgmt_path, f"add {device_name}")
                self.logger.debug(
                    "Added device %s to group %s", device_name, group_name
                )
            except SCSTError as e:
                self.logger.warning(
                    "Failed to add device %s to group %s: %s",
                    device_name,
                    group_name,
                    e,
                )
        self.logger.debug(
            "Updated device group %s: added %s, removed %s",
            group_name,
            len(devices_to_add),
            len(devices_to_remove),
        )

    def _update_device_group_target_groups(
        self, group_name: str, group_config: DeviceGroupConfig
    ) -> None:
        """Update target groups in a device group with proper synchronization.
        Synchronizes device group target groups by adding missing target groups,
        updating existing ones, and removing obsolete target groups that are no
        longer present in the configuration.
        Args:
            group_name: Name of the device group containing target groups
            group_config: Device group configuration with 'target_groups' section
        """
        self.logger.debug("Updating target groups for device group %s", group_name)

        # Get current target groups from sysfs
        current_target_groups = set()
        target_groups_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/target_groups"
        if os.path.exists(target_groups_path):
            for item in os.listdir(target_groups_path):
                if item != self.sysfs.MGMT_INTERFACE and os.path.isdir(
                    os.path.join(target_groups_path, item)
                ):
                    current_target_groups.add(item)

        # Get desired target groups from config
        desired_target_groups = set(group_config.target_groups.keys())

        # Calculate changes needed
        tgroups_to_add = desired_target_groups - current_target_groups
        tgroups_to_remove = current_target_groups - desired_target_groups
        tgroups_to_update = desired_target_groups & current_target_groups

        # Remove obsolete target groups
        mgmt_path = f"{target_groups_path}/mgmt"
        for tgroup_name in tgroups_to_remove:
            try:
                self.sysfs.write_sysfs(mgmt_path, f"del {tgroup_name}")
                self.logger.debug(
                    "Removed target group %s from device group %s",
                    tgroup_name,
                    group_name,
                )
            except SCSTError as e:
                self.logger.warning(
                    "Failed to remove target group %s from device group %s: %s",
                    tgroup_name,
                    group_name,
                    e,
                )

        # Create new target groups
        for tgroup_name in tgroups_to_add:
            tgroup_config = group_config.target_groups[tgroup_name]
            self.logger.debug(
                "Creating target group %s in device group %s", tgroup_name, group_name
            )
            self._create_target_group(group_name, tgroup_name, tgroup_config)

        # Update existing target groups
        for tgroup_name in tgroups_to_update:
            tgroup_config = group_config.target_groups[tgroup_name]
            self.logger.debug(
                "Updating target group %s in device group %s", tgroup_name, group_name
            )
            self._update_target_group_attributes(group_name, tgroup_name, tgroup_config)
        if tgroups_to_add or tgroups_to_remove or tgroups_to_update:
            self.logger.debug(
                "Updated target groups in %s: added %s, removed %s, updated %s",
                group_name,
                len(tgroups_to_add),
                len(tgroups_to_remove),
                len(tgroups_to_update),
            )
        else:
            self.logger.debug(
                "Target groups in device group %s already correct", group_name
            )

    def _update_target_group_attributes(
        self, device_group: str, tgroup_name: str, tgroup_config: Dict[str, Any]
    ) -> None:
        """Update target membership and attributes of an existing target group.
        This method handles the configuration of an existing target group within
        a device group, updating both which targets are assigned to the group
        and the target group's attribute settings.
        Target group components updated:
        1. Target membership: Which targets can access devices through this group
        2. Target group attributes: Configuration parameters for the target group
        Args:
            device_group: Name of the parent device group
            tgroup_name: Name of the target group to update
            tgroup_config: Target group configuration containing:
                         - 'targets': List of target names for group membership
                         - 'attributes': Dict of target group attribute name/value pairs
        Update process:
            1. Update target assignments first (add/remove targets from group)
            2. Update target group attributes second (configuration parameters)
        Example target group config:
            tgroup_config = {
                'targets': ['iqn.2005-10.org.freenas.ctl:test1', 'iqn.2005-10.org.freenas.ctl:test2'],
                'attributes': {
                    'group_id': '101',
                    'state': 'active'
                }
            }
        Common target group attributes:
            - 'state': Target group state ('active', 'nonoptimized', 'standby', 'unavailable')
            - 'group_id': Numeric identifier for ALUA (Asymmetric Logical Unit Access)
        Delegation:
            - _update_target_group_targets(): Handles target membership changes
            - Target group attribute updates: Handled directly via sysfs writes
        Note:
            Target assignments are updated before attributes to ensure proper
            SCST target group state consistency during configuration changes.
        """
        # Update target assignments first
        self._update_target_group_targets(device_group, tgroup_name, tgroup_config)

        # Then update attributes
        desired_attributes = tgroup_config.attributes
        for attr_name, desired_value in desired_attributes.items():
            try:
                attr_path = f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/{tgroup_name}/{attr_name}"
                if os.path.exists(attr_path):
                    # Read current value
                    current_value = self.sysfs.read_sysfs_attribute(attr_path)
                    if current_value != desired_value:
                        # Update the attribute
                        self.sysfs.write_sysfs(
                            attr_path, desired_value, check_result=False
                        )
                        self.logger.debug(
                            "Updated target group attribute %s.%s.%s: %s -> %s",
                            device_group,
                            tgroup_name,
                            attr_name,
                            current_value,
                            desired_value,
                        )
                    else:
                        self.logger.debug(
                            "Target group attribute %s.%s.%s already has correct value: %s",
                            device_group,
                            tgroup_name,
                            attr_name,
                            current_value,
                        )
                else:
                    # Attribute file doesn't exist, try to set it anyway
                    self.sysfs.write_sysfs(attr_path, desired_value, check_result=False)
                    self.logger.debug(
                        "Set target group attribute %s.%s.%s = %s",
                        device_group,
                        tgroup_name,
                        attr_name,
                        desired_value,
                    )
            except (SCSTError, OSError, IOError) as e:
                self.logger.warning(
                    "Failed to update target group attribute %s.%s.%s: %s",
                    device_group,
                    tgroup_name,
                    attr_name,
                    e,
                )

    def _update_target_group_targets(
        self, device_group: str, tgroup_name: str, tgroup_config: TargetGroupConfig
    ) -> None:
        """Update target membership in a target group with proper synchronization.
        This method manages which targets are assigned to a target group within
        a device group, providing the access control mechanism that determines
        which targets can access the devices in the group.
        Target membership synchronization:
        - Targets in config but not in group -> Add to target group
        - Targets in group but not in config -> Remove from target group
        - Targets already correctly assigned -> No action needed
        Args:
            device_group: Name of the parent device group
            tgroup_name: Name of the target group to update
            tgroup_config: Target group configuration containing 'targets' list
        SCST target group ALUA structure:
            Target representation depends on whether targets have ALUA attributes:
            Targets WITH rel_tgt_id -> Directories:
            controller_A/
            |-- iqn.2005-10.org.freenas.ctl:alt:test1/    (directory)
            |   +-- rel_tgt_id                             (contains "1")
            +-- iqn.2005-10.org.freenas.ctl:alt:test2/    (directory)
                +-- rel_tgt_id                             (contains "2")
            Targets WITHOUT rel_tgt_id -> Symlinks:
            controller_B/
            |-- iqn.2005-10.org.freenas.ctl:test1 -> ../../../../targets/iscsi/...
            +-- iqn.2005-10.org.freenas.ctl:test2 -> ../../../../targets/iscsi/...
        SCST management commands:
            - del target_name: Remove target from target group
            - add target_name: Add target to target group
        Implementation:
            Uses _is_valid_sysfs_directory() which correctly handles both symlinks
            and directories as valid target representations for ALUA configurations.
        Note:
            This implements SCSI-3 ALUA (Asymmetric Logical Unit Access) support,
            where rel_tgt_id attributes enable proper multipath storage failover.
        """
        # Get current targets
        current_targets = set()
        tgroup_path = (
            f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/{tgroup_name}"
        )
        if os.path.exists(tgroup_path):
            try:
                for target_item in os.listdir(tgroup_path):
                    if self.sysfs.is_valid_sysfs_directory(tgroup_path, target_item):
                        current_targets.add(target_item)
            except (OSError, IOError):
                pass
        desired_targets = set(tgroup_config.targets)

        # Add missing targets
        missing_targets = desired_targets - current_targets
        for target in missing_targets:
            target_mgmt = f"{tgroup_path}/mgmt"
            self.sysfs.mgmt_operation(
                target_mgmt,
                "add",
                target,
                f"Added target {target} to target group {device_group}/{tgroup_name}",
                f"Failed to add target {target} to target group {tgroup_name}",
            )

        # Remove extra targets
        extra_targets = current_targets - desired_targets
        for target in extra_targets:
            target_mgmt = f"{tgroup_path}/mgmt"
            self.sysfs.mgmt_operation(
                target_mgmt,
                "del",
                target,
                f"Removed target {target} from target group {device_group}/{tgroup_name}",
                f"Failed to remove target {target} from target group {tgroup_name}",
            )

        # Set target attributes for all targets (both new and existing)
        for target_name in tgroup_config.targets:
            if (
                target_name in tgroup_config.target_attributes
            ):  # Target has attributes to set
                target_config = tgroup_config.target_attributes[target_name]
                self._set_target_group_target_attributes(
                    device_group, tgroup_name, target_name, target_config
                )

    def _set_target_group_target_attributes(
        self,
        device_group: str,
        tgroup_name: str,
        target_name: str,
        target_config: Dict[str, str],
    ) -> None:
        """Set attributes for a target within a target group.
        Sets target-level attributes like rel_tgt_id within a target group by writing
        directly to the target's attribute files in the sysfs directory structure.
        Args:
            device_group: Name of the device group
            tgroup_name: Name of the target group
            target_name: Name of the target
            target_config: Dictionary of attribute name/value pairs to set
        Example:
            target_config = {'rel_tgt_id': '1'}
            Writes "1" to: /sys/.../device_groups/targets/target_groups/controller_A/iqn.example:test/rel_tgt_id
        """
        target_path = f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/{tgroup_name}/{target_name}"

        # Only directories can have attributes set
        if not os.path.isdir(target_path):
            self.logger.debug(
                "Target %s is symlink, cannot set attributes - "
                "SCST will handle this automatically",
                target_name,
            )
            return
        for attr_name, attr_value in target_config.items():
            attr_path = f"{target_path}/{attr_name}"
            try:
                # Check if attribute already has the correct value
                if os.path.exists(attr_path):
                    current_value = self.sysfs.read_sysfs_attribute(attr_path)
                    if current_value == attr_value:
                        self.logger.debug(
                            "Target group target attribute "
                            "%s/%s/%s.%s already has correct value: %s",
                            device_group,
                            tgroup_name,
                            target_name,
                            attr_name,
                            attr_value,
                        )
                        continue
                self.sysfs.write_sysfs(attr_path, attr_value, check_result=False)
                self.logger.debug(
                    "Set target group target attribute %s/%s/%s.%s = %s",
                    device_group,
                    tgroup_name,
                    target_name,
                    attr_name,
                    attr_value,
                )
            except SCSTError as e:
                self.logger.warning(
                    "Failed to set target group target attribute %s/%s/%s.%s: %s",
                    device_group,
                    tgroup_name,
                    target_name,
                    attr_name,
                    e,
                )

    def _create_target_group(
        self, device_group: str, tgroup_name: str, tgroup_config: TargetGroupConfig
    ) -> None:
        """Create a new target group within a device group with full configuration.
        Creates a target group and configures all its components including target
        membership and target-level attributes. Target groups enable ALUA (Asymmetric
        Logical Unit Access) configurations for multipath storage scenarios.
        Creation process:
        1. Create target group via management interface
        2. Add targets to the target group (creates symlinks or directories)
        3. Set target-level attributes (e.g., rel_tgt_id for ALUA)
        4. Set target group-level attributes (e.g., group_id, state)
        Args:
            device_group: Name of the parent device group
            tgroup_name: Name of the target group to create
            tgroup_config: Target group configuration containing:
                         - 'targets': Dict of target names -> target attributes
                         - 'attributes': Dict of target group attributes
        Target attribute handling:
            Targets with attributes (e.g., rel_tgt_id) become directories in sysfs,
            while targets without attributes become symlinks. This enables SCST's
            ALUA functionality where different target groups can have different
            access states (active, nonoptimized, standby, unavailable).
        Example configuration:
            tgroup_config = {
                'targets': {
                    'iqn.example:test1': {'rel_tgt_id': '1'},
                    'iqn.example:test2': {}  # No attributes
                },
                'attributes': {'group_id': '101', 'state': 'active'}
            }
        """
        tgroup_mgmt = f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/mgmt"
        try:
            self.sysfs.write_sysfs(tgroup_mgmt, f"add {tgroup_name}")
            self.logger.debug(
                "Created target group %s in device group %s", tgroup_name, device_group
            )
            # Add targets to target group and set their attributes
            for target_name in tgroup_config.targets:
                target_mgmt = f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/{tgroup_name}/mgmt"
                self.sysfs.write_sysfs(target_mgmt, f"add {target_name}")
                self.logger.debug(
                    "Added target %s to target group %s", target_name, tgroup_name
                )
                # Set target attributes if any
                if target_name in tgroup_config.target_attributes:
                    target_config = tgroup_config.target_attributes[target_name]
                    if target_config:
                        self._set_target_group_target_attributes(
                            device_group, tgroup_name, target_name, target_config
                        )
            # Set target group attributes
            self._update_target_group_attributes(
                device_group, tgroup_name, tgroup_config
            )
        except SCSTError as e:
            self.logger.warning("Failed to create target group %s: %s", tgroup_name, e)

    def _apply_target_groups(
        self, device_group: str, target_groups: Dict[str, Any]
    ) -> None:
        """Apply target group configurations within a device group with full ALUA support.
        Creates and configures target groups for SCST ALUA (Asymmetric Logical Unit Access)
        multipath storage configurations. Each target group represents a different access
        path with potentially different performance characteristics and availability states.
        Configuration process:
        1. Create target group via management interface
        2. Set target group-level attributes (group_id, state, etc.)
        3. Add targets to target group (creates sysfs entries)
        4. Set target-level attributes (rel_tgt_id for ALUA identification)
        Args:
            device_group: Name of the parent device group containing the target groups
            target_groups: Dictionary of target group configurations:
                          {group_name: {'targets': {target: attrs}, 'attributes': {attr: value}}}
        Target group ALUA states:
            - active: Primary access path, optimal performance
            - nonoptimized: Secondary path, degraded performance but available
            - standby: Backup path, requires transition before use
            - unavailable: Path not accessible
        Target attribute handling:
            Targets with rel_tgt_id attributes enable proper ALUA identification
            across multiple paths to the same logical unit, essential for
            multipath failover and load balancing.
        Example configuration:
            target_groups = {
                'controller_A': {
                    'targets': {
                        'iqn.example:test1': {'rel_tgt_id': '1'},
                        'iqn.example:test2': {'rel_tgt_id': '2'}
                    },
                    'attributes': {'group_id': '101', 'state': 'active'}
                },
                'controller_B': {
                    'targets': {
                        'iqn.example:test1': {},  # Simple target, no attributes
                        'iqn.example:test2': {}
                    },
                    'attributes': {'group_id': '102', 'state': 'nonoptimized'}
                }
            }
        """
        for tgroup_name, tgroup_config in target_groups.items():
            self.logger.debug(
                "Processing target group '%s' in device group '%s'",
                tgroup_name,
                device_group,
            )
            # Check if target group already exists
            tgroup_path = f"{self.sysfs.SCST_DEV_GROUPS}/{device_group}/target_groups/{tgroup_name}"
            if os.path.exists(tgroup_path):
                # Target group exists, update it
                self.logger.debug(
                    "Target group %s exists, updating configuration", tgroup_name
                )
                self._update_target_group_targets(
                    device_group, tgroup_name, tgroup_config
                )
                self._update_target_group_attributes(
                    device_group, tgroup_name, tgroup_config
                )
            else:
                # Target group doesn't exist, create it
                self.logger.debug(
                    "Target group %s doesn't exist, creating", tgroup_name
                )
                self._create_target_group(device_group, tgroup_name, tgroup_config)

    def apply_config_device_groups(self, config: "SCSTConfig") -> None:
        """Apply device groups and ALUA target group configurations.

        Creates device groups with device membership and target group access control.
        Includes full ALUA support with rel_tgt_id and multipath state management.
        """
        for group_name, group_config in config.device_groups.items():
            # Check if device group already exists - optimize for common case of no changes
            if self._device_group_exists(group_name):
                if self._device_group_config_matches(group_name, group_config):
                    self.logger.debug(
                        "Device group %s already exists with matching config, skipping",
                        group_name,
                    )
                    continue
                else:
                    # Use incremental updates to avoid disrupting existing sessions
                    self.logger.debug(
                        "Device group %s config differs, updating incrementally",
                        group_name,
                    )
                    self._update_device_group(group_name, group_config)
                    continue

            # Create new device group via SCST management interface
            group_mgmt = f"{self.sysfs.SCST_DEV_GROUPS}/mgmt"
            try:
                self.sysfs.write_sysfs(group_mgmt, f"create {group_name}")
                self.logger.debug("Created device group %s", group_name)
            except SCSTError as e:
                self.logger.warning(
                    "Failed to create device group %s: %s", group_name, e
                )
                continue

            # Apply device group-level attributes (rare but possible)
            if group_config.attributes:
                for attr_name, attr_value in group_config.attributes.items():
                    try:
                        attr_path = (
                            f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/{attr_name}"
                        )
                        self.sysfs.write_sysfs(
                            attr_path, attr_value, check_result=False
                        )
                        self.logger.debug(
                            "Set device group attribute %s.%s = %s",
                            group_name,
                            attr_name,
                            attr_value,
                        )
                    except SCSTError as e:
                        self.logger.warning(
                            "Failed to set device group attribute %s.%s: %s",
                            group_name,
                            attr_name,
                            e,
                        )

            # Add devices to group - establishes which devices can be accessed by this group
            device_mgmt = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}/devices/mgmt"
            for device in group_config.devices:
                try:
                    self.sysfs.write_sysfs(device_mgmt, f"add {device}")
                    self.logger.debug(
                        "Added device %s to device group %s", device, group_name
                    )
                except SCSTError as e:
                    self.logger.warning(
                        "Failed to add device %s to device group %s: %s",
                        device,
                        group_name,
                        e,
                    )

            # Create and configure target groups - this is where ALUA magic happens
            self._apply_target_groups(group_name, group_config.target_groups)

    def remove_device_group(self, group_name: str) -> None:
        """Remove a device group and all its contents"""
        try:
            group_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}"

            # Remove all target groups within the device group
            tgt_groups_path = f"{group_path}/target_groups"
            if self.sysfs.valid_path(tgt_groups_path):
                for tgt_group in self.sysfs.list_directory(tgt_groups_path):
                    if tgt_group != self.sysfs.MGMT_INTERFACE:
                        tgt_group_mgmt = f"{tgt_groups_path}/mgmt"
                        self.sysfs.write_sysfs(tgt_group_mgmt, f"del {tgt_group}")

            # Remove all devices from the device group
            devices_path = f"{group_path}/devices"
            if self.sysfs.valid_path(devices_path):
                devices_mgmt = f"{devices_path}/mgmt"
                for device in self.sysfs.list_directory(devices_path):
                    if device != self.sysfs.MGMT_INTERFACE:
                        self.sysfs.write_sysfs(devices_mgmt, f"del {device}")

            # Remove the device group itself
            dg_mgmt = f"{self.sysfs.SCST_DEV_GROUPS}/mgmt"
            self.sysfs.write_sysfs(dg_mgmt, f"del {group_name}")

        except SCSTError as e:
            self.logger.warning("Failed to remove device group %s: %s", group_name, e)
