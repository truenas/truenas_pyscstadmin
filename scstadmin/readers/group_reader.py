"""
SCST Device Group Configuration Reader

Handles device group and target group discovery within the SCST configuration.
This module focuses on device group operations and their nested target groups.
"""

import logging
import os
from typing import Dict

from ..sysfs import SCSTSysfs
from ..exceptions import SCSTError
from ..config import DeviceGroupConfig, TargetGroupConfig


class DeviceGroupReader:
    """Reads SCST device group configuration from sysfs.

    This class handles device group discovery and target group operations
    within device groups in the SCST configuration system.
    """

    # Constants needed for reading configuration
    MGMT_INTERFACE = 'mgmt'

    def __init__(self, sysfs: SCSTSysfs):
        self.sysfs = sysfs
        self.logger = logging.getLogger(__name__)

    def read_device_groups(self) -> Dict[str, DeviceGroupConfig]:
        """Read all device groups from SCST sysfs for discovery operations.

        Returns:
            Dict mapping device group names to their configuration
        """
        device_groups = {}

        if not self.sysfs.valid_path(self.sysfs.SCST_DEV_GROUPS):
            return device_groups

        for group_name in self.sysfs.list_directory(self.sysfs.SCST_DEV_GROUPS):
            if group_name != self.MGMT_INTERFACE:
                group_config = {
                    'devices': [],
                    'target_groups': {},
                    'attributes': {}
                }

                group_path = f"{self.sysfs.SCST_DEV_GROUPS}/{group_name}"

                # Read devices in group
                devices_path = f"{group_path}/devices"
                if self.sysfs.valid_path(devices_path):
                    for device in self.sysfs.list_directory(devices_path):
                        if device != self.MGMT_INTERFACE:
                            group_config['devices'].append(device)

                # Read target groups in group
                target_groups_path = f"{group_path}/target_groups"
                if self.sysfs.valid_path(target_groups_path):
                    for tgroup_name in self.sysfs.list_directory(target_groups_path):
                        if tgroup_name != self.MGMT_INTERFACE:
                            tgroup_config = {
                                'targets': [],
                                'target_attributes': {},
                                'attributes': {}
                            }

                            tgroup_path = f"{target_groups_path}/{tgroup_name}"

                            # Read targets in target group
                            for target in self.sysfs.list_directory(tgroup_path):
                                if target != self.MGMT_INTERFACE:
                                    # Add target name to targets list
                                    tgroup_config['targets'].append(target)

                                    target_path = f"{tgroup_path}/{target}"
                                    target_attributes = {}
                                    # Check if target has attributes (is a directory)
                                    if os.path.isdir(target_path):
                                        # Read target attributes
                                        try:
                                            for attr_file in os.listdir(target_path):
                                                attr_path = f"{target_path}/{attr_file}"
                                                if os.path.isfile(attr_path) and attr_file != self.MGMT_INTERFACE:
                                                    try:
                                                        attr_value = self.sysfs.read_sysfs_attribute(attr_path)
                                                        target_attributes[attr_file] = attr_value
                                                    except SCSTError:
                                                        pass  # Skip unreadable attributes
                                        except (OSError, IOError):
                                            pass  # Skip if can't read directory

                                        # Only store target attributes if there are any
                                        if target_attributes:
                                            tgroup_config['target_attributes'][target] = target_attributes

                            group_config['target_groups'][tgroup_name] = TargetGroupConfig.from_config_dict(
                                tgroup_name, tgroup_config
                            )

                device_groups[group_name] = DeviceGroupConfig.from_config_dict(group_name, group_config)

        return device_groups
