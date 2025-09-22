#!/usr/bin/env python3
"""
Quick test script for DeviceConfig classes.

This tests the new structured DeviceConfig objects before we integrate
them into the larger codebase.
"""

import sys

# Imports handled by conftest.py

from scstadmin.config import (
    DeviceConfig, VdiskFileioDeviceConfig,
    VdiskBlockioDeviceConfig, DevDiskDeviceConfig
)


def test_vdisk_fileio():
    """Test VdiskFileioDeviceConfig creation and properties."""
    print("Testing VdiskFileioDeviceConfig...")

    device = VdiskFileioDeviceConfig(
        name="disk1",
        filename="/path/to/disk1.img",
        blocksize="4096",
        readonly="0"
    )

    assert device.name == "disk1"
    assert device.handler_type == "vdisk_fileio"
    assert device.filename == "/path/to/disk1.img"
    assert device.blocksize == "4096"
    assert device.readonly == "0"
    assert isinstance(device.attributes, dict)

    print("✓ VdiskFileioDeviceConfig works correctly")


def test_vdisk_blockio():
    """Test VdiskBlockioDeviceConfig creation and properties."""
    print("Testing VdiskBlockioDeviceConfig...")

    device = VdiskBlockioDeviceConfig(
        name="block_disk",
        filename="/dev/sdb",
        nv_cache="1",
        o_direct="1"
    )

    assert device.name == "block_disk"
    assert device.handler_type == "vdisk_blockio"
    assert device.filename == "/dev/sdb"
    assert device.nv_cache == "1"
    assert device.o_direct == "1"

    print("✓ VdiskBlockioDeviceConfig works correctly")


def test_dev_disk():
    """Test DevDiskDeviceConfig creation and properties."""
    print("Testing DevDiskDeviceConfig...")

    device = DevDiskDeviceConfig(
        name="real_disk",
        filename="/dev/sda",
        readonly="1"
    )

    assert device.name == "real_disk"
    assert device.handler_type == "dev_disk"
    assert device.filename == "/dev/sda"
    assert device.readonly == "1"

    print("✓ DevDiskDeviceConfig works correctly")


def test_validation():
    """Test validation logic."""
    print("Testing validation...")

    try:
        # Empty name should fail
        VdiskFileioDeviceConfig(name="", filename="/path")
        assert False, "Should have raised ValueError for empty name"
    except ValueError:
        print("✓ Empty name validation works")


def test_polymorphism():
    """Test that all configs work as DeviceConfig instances."""
    print("Testing polymorphism...")

    devices = [
        VdiskFileioDeviceConfig(name="file_dev", filename="/tmp/file.img"),
        VdiskBlockioDeviceConfig(name="block_dev", filename="/dev/sdb"),
        DevDiskDeviceConfig(name="real_dev", filename="/dev/sda")
    ]

    for device in devices:
        assert isinstance(device, DeviceConfig)
        assert device.name  # Should have a name
        assert device.handler_type  # Should have a handler type
        print(f"✓ {device.__class__.__name__} is a DeviceConfig")


def main():
    """Run all tests."""
    try:
        test_vdisk_fileio()
        test_vdisk_blockio()
        test_dev_disk()
        test_validation()
        test_polymorphism()

        print("\n🎉 All DeviceConfig tests passed!")
        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
