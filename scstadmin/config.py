"""
Configuration data structures for SCST.

This module defines the core data structures used to represent SCST configurations,
including the main SCSTConfig dataclass and related enums.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List
from abc import ABC, abstractmethod


class ConfigAction(Enum):
    """Actions that can be taken for existing SCST entities during configuration."""

    SKIP = "skip"  # Entity already matches configuration
    UPDATE = "update"  # Only post-creation attributes need updating
    RECREATE = "recreate"  # Creation attributes differ, entity must be recreated


class SCSTErrorCode(Enum):
    """SCST error codes for standardized error classification.

    These codes provide consistent error identification across the SCST
    Python configurator, enabling proper error handling and diagnostics.

    Attributes:
        BAD_ATTRIBUTES: Invalid or malformed attribute values
        ATTRIBUTE_STATIC: Attempt to modify read-only/static attributes
        SETATTR_FAIL: Failure to set sysfs attribute values
        FATAL_ERROR: Critical system or configuration errors
    """

    BAD_ATTRIBUTES = "SCST_C_BAD_ATTRIBUTES"
    ATTRIBUTE_STATIC = "SCST_C_ATTRIBUTE_STATIC"
    SETATTR_FAIL = "SCST_C_SETATTR_FAIL"
    FATAL_ERROR = "SCST_C_FATAL_ERROR"


@dataclass
class DeviceConfig(ABC):
    """Abstract base class for SCST device configurations.

    All SCST devices have a name and belong to a specific handler type.
    Subclasses define the specific attributes required for each handler.
    """

    name: str

    def __post_init__(self):
        """Initialize attributes dict and validate device configuration."""
        if not hasattr(self, "attributes"):
            self.attributes = {}
        if not self.name:
            raise ValueError("Device name cannot be empty")

    @property
    @abstractmethod
    def handler_type(self) -> str:
        """Return the SCST handler name for this device type."""
        pass


@dataclass
class VdiskFileioDeviceConfig(DeviceConfig):
    """Configuration for vdisk_fileio devices (file-backed virtual disks).

    These devices use regular files as backing storage and support
    various performance and feature options.

    Required attributes:
        filename: Path to the backing file

    Common optional attributes:
        blocksize: Block size in bytes (default: 512)
        readonly: Read-only flag (0/1, default: 0)
        removable: Removable media flag (0/1, default: 0)
        rotational: Rotational media hint (0/1, default: 1)
        thin_provisioned: Thin provisioning flag (0/1, default: 0)
    """

    # Creation-time parameters from /sys/kernel/scst_tgt/handlers/vdisk_fileio/mgmt
    _CREATION_PARAMS = {
        "active",
        "async",
        "blocksize",
        "cluster_mode",
        "dif_filename",
        "dif_mode",
        "dif_static_app_tag",
        "dif_type",
        "filename",
        "numa_node_id",
        "nv_cache",
        "o_direct",
        "read_only",
        "removable",
        "rotational",
        "thin_provisioned",
        "tst",
        "t10_dev_id",
        "write_through",
    }
    filename: str
    blocksize: Optional[str] = None
    readonly: Optional[str] = None
    removable: Optional[str] = None
    rotational: Optional[str] = None
    thin_provisioned: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def handler_type(self) -> str:
        return "vdisk_fileio"

    @property
    def creation_attributes(self) -> Dict[str, str]:
        """Return creation-time attributes for vdisk_fileio devices."""
        attrs = {}
        if self.filename:
            attrs["filename"] = self.filename
        if self.blocksize:
            attrs["blocksize"] = self.blocksize
        if self.readonly:
            attrs["read_only"] = self.readonly  # Note: read_only in SCST
        if self.removable:
            attrs["removable"] = self.removable
        if self.rotational:
            attrs["rotational"] = self.rotational
        if self.thin_provisioned:
            attrs["thin_provisioned"] = self.thin_provisioned
        # Additional creation-time parameters from attributes dict
        for param in self._CREATION_PARAMS:
            if param in self.attributes:
                attrs[param] = self.attributes[param]
        return attrs

    @property
    def post_creation_attributes(self) -> Dict[str, str]:
        """Return post-creation attributes (settable after device creation)."""
        return {
            k: v for k, v in self.attributes.items() if k not in self._CREATION_PARAMS
        }

    @classmethod
    def from_attributes(
        cls, name: str, attrs: Dict[str, str]
    ) -> "VdiskFileioDeviceConfig":
        """Create VdiskFileioDeviceConfig from flat attributes dict.

        Factory method that takes a flat dict of attributes and creates
        the appropriate DeviceConfig object with proper field mapping.

        Args:
            name: Device name
            attrs: Flat dictionary of device attributes

        Returns:
            VdiskFileioDeviceConfig instance
        """
        return cls(
            name=name,
            filename=attrs.get("filename", ""),
            blocksize=attrs.get("blocksize"),
            readonly=attrs.get("readonly"),
            removable=attrs.get("removable"),
            rotational=attrs.get("rotational"),
            thin_provisioned=attrs.get("thin_provisioned"),
            attributes={
                k: v
                for k, v in attrs.items()
                if k
                not in [
                    "filename",
                    "blocksize",
                    "readonly",
                    "removable",
                    "rotational",
                    "thin_provisioned",
                ]
            },
        )


@dataclass
class VdiskBlockioDeviceConfig(DeviceConfig):
    """Configuration for vdisk_blockio devices (block device backed).

    These devices use block devices (like /dev/sdb) as backing storage
    and provide high-performance access with various optimization options.

    Required attributes:
        filename: Path to the block device

    Common optional attributes:
        blocksize: Block size in bytes (default: device native)
        nv_cache: Non-volatile cache flag (0/1, default: 0)
        o_direct: Direct I/O flag (0/1, default: 0)
        readonly: Read-only flag (0/1, default: 0)
        rotational: Rotational media hint (0/1, default: 1)
        thin_provisioned: Thin provisioning flag (0/1, default: 0)
    """

    # Creation-time parameters from /sys/kernel/scst_tgt/handlers/vdisk_blockio/mgmt
    _CREATION_PARAMS = {
        "active",
        "bind_alua_state",
        "blocksize",
        "cluster_mode",
        "dif_filename",
        "dif_mode",
        "dif_static_app_tag",
        "dif_type",
        "filename",
        "numa_node_id",
        "nv_cache",
        "read_only",
        "removable",
        "rotational",
        "thin_provisioned",
        "tst",
        "t10_dev_id",
        "write_through",
    }
    filename: str
    blocksize: Optional[str] = None
    nv_cache: Optional[str] = None
    o_direct: Optional[str] = None
    readonly: Optional[str] = None
    rotational: Optional[str] = None
    thin_provisioned: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def handler_type(self) -> str:
        return "vdisk_blockio"

    @property
    def creation_attributes(self) -> Dict[str, str]:
        """Return creation-time attributes for vdisk_blockio devices."""
        attrs = {}
        if self.filename:
            attrs["filename"] = self.filename
        if self.blocksize:
            attrs["blocksize"] = self.blocksize
        if self.nv_cache:
            attrs["nv_cache"] = self.nv_cache
        if self.o_direct:
            attrs["o_direct"] = self.o_direct
        if self.readonly:
            attrs["read_only"] = self.readonly  # Note: read_only in SCST
        if self.rotational:
            attrs["rotational"] = self.rotational
        if self.thin_provisioned:
            attrs["thin_provisioned"] = self.thin_provisioned
        # Additional creation-time parameters from attributes dict
        for param in self._CREATION_PARAMS:
            if param in self.attributes:
                attrs[param] = self.attributes[param]
        return attrs

    @property
    def post_creation_attributes(self) -> Dict[str, str]:
        """Return post-creation attributes (settable after device creation)."""
        return {
            k: v for k, v in self.attributes.items() if k not in self._CREATION_PARAMS
        }

    @classmethod
    def from_attributes(
        cls, name: str, attrs: Dict[str, str]
    ) -> "VdiskBlockioDeviceConfig":
        """Create VdiskBlockioDeviceConfig from flat attributes dict.

        Factory method that takes a flat dict of attributes and creates
        the appropriate DeviceConfig object with proper field mapping.

        Args:
            name: Device name
            attrs: Flat dictionary of device attributes

        Returns:
            VdiskBlockioDeviceConfig instance
        """
        return cls(
            name=name,
            filename=attrs.get("filename", ""),
            blocksize=attrs.get("blocksize"),
            nv_cache=attrs.get("nv_cache"),
            o_direct=attrs.get("o_direct"),
            readonly=attrs.get("readonly"),
            rotational=attrs.get("rotational"),
            thin_provisioned=attrs.get("thin_provisioned"),
            attributes={
                k: v
                for k, v in attrs.items()
                if k
                not in [
                    "filename",
                    "blocksize",
                    "nv_cache",
                    "o_direct",
                    "readonly",
                    "rotational",
                    "thin_provisioned",
                ]
            },
        )


@dataclass
class DevDiskDeviceConfig(DeviceConfig):
    """Configuration for dev_disk devices (pass-through to real devices).

    These devices provide direct access to existing block devices
    without virtualization overhead. Primarily used for passing
    through physical disks or LUNs to targets.

    Required attributes:
        filename: Path to the block device (e.g., /dev/sda, /dev/disk/by-id/...)

    Common optional attributes:
        readonly: Read-only flag (0/1, default: 0)
        rotational: Rotational media hint (0/1, default: 1)
        thin_provisioned: Thin provisioning flag (0/1, default: 0)
    """

    # dev_disk has no creation-time parameters - only takes device name (H:C:I:L format)
    _CREATION_PARAMS = set()
    filename: str
    readonly: Optional[str] = None
    rotational: Optional[str] = None
    thin_provisioned: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def handler_type(self) -> str:
        return "dev_disk"

    @property
    def creation_attributes(self) -> Dict[str, str]:
        """Return creation-time attributes for dev_disk devices.

        dev_disk devices only take the device name at creation time - no parameters.
        """
        return {}  # No creation-time parameters

    @property
    def post_creation_attributes(self) -> Dict[str, str]:
        """Return post-creation attributes (settable after device creation)."""
        attrs = {}
        if self.readonly:
            attrs["read_only"] = self.readonly  # Note: read_only in SCST
        if self.rotational:
            attrs["rotational"] = self.rotational
        if self.thin_provisioned:
            attrs["thin_provisioned"] = self.thin_provisioned
        # Add any additional attributes
        attrs.update(self.attributes)
        return attrs

    @classmethod
    def from_attributes(cls, name: str, attrs: Dict[str, str]) -> "DevDiskDeviceConfig":
        """Create DevDiskDeviceConfig from flat attributes dict.

        Factory method that takes a flat dict of attributes and creates
        the appropriate DeviceConfig object with proper field mapping.

        Args:
            name: Device name
            attrs: Flat dictionary of device attributes

        Returns:
            DevDiskDeviceConfig instance
        """
        return cls(
            name=name,
            filename=attrs.get("filename", ""),
            readonly=attrs.get("readonly"),
            rotational=attrs.get("rotational"),
            thin_provisioned=attrs.get("thin_provisioned"),
            attributes={
                k: v
                for k, v in attrs.items()
                if k not in ["filename", "readonly", "rotational", "thin_provisioned"]
            },
        )


def create_device_config(
    name: str, handler_type: str, attrs: Dict[str, str]
) -> Optional[DeviceConfig]:
    """Factory function to create appropriate DeviceConfig subclass based on handler type.

    This function centralizes the logic for creating DeviceConfig objects from flat
    attribute dictionaries, eliminating code duplication between parser and reader.

    Args:
        name: Device name
        handler_type: SCST handler type (e.g., 'vdisk_fileio', 'vdisk_blockio', 'dev_disk')
        attrs: Flat dictionary of device attributes

    Returns:
        Appropriate DeviceConfig subclass instance or None if handler type is unsupported
    """
    if handler_type == "vdisk_fileio":
        return VdiskFileioDeviceConfig.from_attributes(name, attrs)
    elif handler_type == "vdisk_blockio":
        return VdiskBlockioDeviceConfig.from_attributes(name, attrs)
    elif handler_type == "dev_disk":
        return DevDiskDeviceConfig.from_attributes(name, attrs)
    else:
        return None


@dataclass
class LunConfig:
    """SCST LUN (Logical Unit Number) configuration.

    Represents a LUN assignment within a target, mapping a LUN number
    to a device with optional attributes like read_only access.
    """

    lun_number: str  # LUN number (e.g., "0", "1", "255")
    device: str  # Device name assigned to this LUN
    attributes: Dict[str, str] = field(
        default_factory=dict
    )  # LUN attributes (e.g., read_only)

    @classmethod
    def from_config_dict(cls, lun_number: str, lun_data: dict) -> "LunConfig":
        """Create LunConfig from parser dictionary format.

        Args:
            lun_number: LUN number as string
            lun_data: Dict with 'device' and 'attributes' keys

        Returns:
            LunConfig object
        """
        return cls(
            lun_number=lun_number,
            device=lun_data.get("device", ""),
            attributes=lun_data.get("attributes", {}).copy(),
        )


@dataclass
class InitiatorGroupConfig:
    """SCST Initiator Group configuration.

    Represents an initiator group within a target, containing a list of
    initiators (IQN/portal pairs) and their associated LUN assignments.
    """

    name: str  # Group name (e.g., "security_group")
    initiators: List[str] = field(default_factory=list)  # IQN/portal pairs
    luns: Dict[str, "LunConfig"] = field(default_factory=dict)  # LUN assignments
    attributes: Dict[str, str] = field(default_factory=dict)  # Group attributes

    @classmethod
    def from_config_dict(
        cls, group_name: str, group_data: dict
    ) -> "InitiatorGroupConfig":
        """Create InitiatorGroupConfig from parser dictionary format.

        Args:
            group_name: Name of the initiator group
            group_data: Dict with 'initiators', 'luns', and 'attributes' keys

        Returns:
            InitiatorGroupConfig object
        """
        return cls(
            name=group_name,
            initiators=group_data.get("initiators", []).copy(),
            luns={
                lun_id: lun_obj
                for lun_id, lun_obj in group_data.get("luns", {}).items()
            },
            attributes=group_data.get("attributes", {}).copy(),
        )


@dataclass
class TargetConfig:
    """SCST Target configuration.

    Represents a complete target configuration within a driver, containing
    LUN assignments, initiator groups, and target-specific attributes.

    Example:
        TARGET iqn.2024-01.com.example:test {
            LUN 0 disk1
            LUN 1 disk2 { read_only 1 }

            GROUP security_group {
                INITIATOR iqn.client:server1
                LUN 0 disk1
            }

            enabled 1
            MaxRecvDataSegmentLength 262144
        }
    """

    name: str  # Target name/IQN (e.g., "iqn.2024-01.com.example:test")
    luns: Dict[str, "LunConfig"] = field(default_factory=dict)  # LUN assignments
    groups: Dict[str, "InitiatorGroupConfig"] = field(
        default_factory=dict
    )  # Initiator groups
    attributes: Dict[str, str] = field(default_factory=dict)  # Target attributes

    @classmethod
    def from_config_dict(cls, target_name: str, target_data: dict) -> "TargetConfig":
        """Create TargetConfig from parser dictionary format.

        Args:
            target_name: Name of the target
            target_data: Dict with 'luns', 'groups', and 'attributes' keys

        Returns:
            TargetConfig object
        """
        return cls(
            name=target_name,
            luns={
                lun_id: lun_obj
                for lun_id, lun_obj in target_data.get("luns", {}).items()
            },
            groups={
                group_id: group_obj
                for group_id, group_obj in target_data.get("groups", {}).items()
            },
            attributes=target_data.get("attributes", {}).copy(),
        )


@dataclass
class DriverConfig:
    """SCST Target Driver configuration.

    Represents a complete target driver configuration containing
    multiple targets and driver-level attributes.

    Example:
        TARGET_DRIVER iscsi {
            TARGET iqn.2024-01.com.example:test {
                LUN 0 disk1
                enabled 1
            }

            isns_entity_name "Test iSNS Entity"
            enabled 1
        }
    """

    name: str  # Driver name (e.g., "iscsi", "qla2x00t", "copy_manager")
    targets: Dict[str, "TargetConfig"] = field(
        default_factory=dict
    )  # Target configurations
    attributes: Dict[str, str] = field(default_factory=dict)  # Driver attributes

    @classmethod
    def from_config_dict(cls, driver_name: str, driver_data: dict) -> "DriverConfig":
        """Create DriverConfig from parser dictionary format.

        Args:
            driver_name: Name of the target driver
            driver_data: Dict with 'targets' and 'attributes' keys

        Returns:
            DriverConfig object
        """
        return cls(
            name=driver_name,
            targets={
                target_id: target_obj
                for target_id, target_obj in driver_data.get("targets", {}).items()
            },
            attributes=driver_data.get("attributes", {}).copy(),
        )


@dataclass
class TargetGroupConfig:
    """Configuration for a target group within a device group.

    Target groups define different access paths for ALUA (Asymmetric Logical Unit Access)
    configurations, allowing for active/passive multipath setups.

    Attributes:
        name: Target group name (e.g., 'controller_A', 'controller_B')
        targets: List of target names in this group
        target_attributes: Attributes for individual targets (e.g., rel_tgt_id)
        attributes: Target group attributes (group_id, state, etc.)
    """

    name: str
    targets: List[str] = field(default_factory=list)
    target_attributes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    attributes: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config_dict(cls, group_name: str, group_data: dict) -> "TargetGroupConfig":
        """Create TargetGroupConfig from dictionary configuration.

        Args:
            group_name: Name of the target group
            group_data: Dictionary containing group configuration

        Returns:
            TargetGroupConfig object with validated attributes
        """
        return cls(
            name=group_name,
            targets=group_data.get("targets", []).copy(),
            target_attributes=group_data.get("target_attributes", {}).copy(),
            attributes=group_data.get("attributes", {}).copy(),
        )


@dataclass
class DeviceGroupConfig:
    """Configuration for an SCST device group.

    Device groups provide device-level access control and ALUA (Asymmetric Logical
    Unit Access) support for multipath configurations. They contain devices and
    target groups that define different access paths.

    Attributes:
        name: Device group name
        devices: List of device names in this group
        target_groups: Target group configurations for ALUA
        attributes: Device group level attributes
    """

    name: str
    devices: List[str] = field(default_factory=list)
    target_groups: Dict[str, TargetGroupConfig] = field(default_factory=dict)
    attributes: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config_dict(cls, group_name: str, group_data: dict) -> "DeviceGroupConfig":
        """Create DeviceGroupConfig from dictionary configuration.

        Args:
            group_name: Name of the device group
            group_data: Dictionary containing group configuration

        Returns:
            DeviceGroupConfig object with validated attributes
        """
        # Handle target groups - convert to TargetGroupConfig objects if needed
        target_groups = {}
        tg_data = group_data.get("target_groups", {})
        for tg_name, tg_config in tg_data.items():
            if isinstance(tg_config, TargetGroupConfig):
                target_groups[tg_name] = tg_config
            else:
                target_groups[tg_name] = TargetGroupConfig.from_config_dict(
                    tg_name, tg_config
                )

        return cls(
            name=group_name,
            devices=group_data.get("devices", []).copy(),
            target_groups=target_groups,
            attributes=group_data.get("attributes", {}).copy(),
        )


@dataclass
class SCSTConfig:
    """SCST configuration data structure containing all configuration components.

    This dataclass represents a complete SCST configuration parsed from
    configuration files or built programmatically. It contains all the
    components needed to configure the SCST subsystem.

    Attributes:
        handlers: Device handler configurations (e.g., dev_disk, vdisk_blockio)
        devices: Device definitions and their attributes
        drivers: Target driver configurations (iscsi, qla2x00t, etc.)
        targets: Target definitions with their LUNs and settings
        device_groups: Device group definitions for access control
        scst_attributes: Global SCST subsystem attributes

    All attributes are automatically initialized to empty dictionaries
    if not provided during instantiation.
    """

    handlers: Optional[Dict[str, Dict]] = None
    devices: Optional[Dict[str, DeviceConfig]] = None
    drivers: Optional[Dict[str, DriverConfig]] = None
    targets: Optional[Dict[str, Dict]] = None
    device_groups: Optional[Dict[str, DeviceGroupConfig]] = None
    scst_attributes: Optional[Dict[str, str]] = None

    def __post_init__(self):
        if self.handlers is None:
            self.handlers = {}
        if self.devices is None:
            self.devices = {}
        if self.drivers is None:
            self.drivers = {}
        if self.targets is None:
            self.targets = {}
        if self.device_groups is None:
            self.device_groups = {}
        if self.scst_attributes is None:
            self.scst_attributes = {}
