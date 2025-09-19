#!/usr/bin/env python3
"""
Test script to verify DeviceConfig creation/post-creation attribute properties.
"""

import sys

# Imports handled by conftest.py

from scstadmin.config import VdiskFileioDeviceConfig, VdiskBlockioDeviceConfig, DevDiskDeviceConfig


def test_device_attribute_properties():
    """Test creation and post-creation attribute properties."""
    print("Testing DeviceConfig attribute properties...")

    # Test VdiskFileioDeviceConfig
    fileio_device = VdiskFileioDeviceConfig(
        name="test_fileio",
        filename="/path/to/file.img",
        blocksize="4096",
        readonly="0",
        attributes={"custom_attr": "value", "t10_dev_id": "abc123"}
    )

    creation_attrs = fileio_device.creation_attributes
    post_attrs = fileio_device.post_creation_attributes

    print(f"VdiskFileio creation attributes: {creation_attrs}")
    print(f"VdiskFileio post-creation attributes: {post_attrs}")

    # Verify creation attributes include known creation-time params
    assert 'filename' in creation_attrs
    assert 'blocksize' in creation_attrs
    assert creation_attrs['filename'] == "/path/to/file.img"
    assert creation_attrs['blocksize'] == "4096"
    assert creation_attrs['read_only'] == "0"  # Note: readonly -> read_only
    assert creation_attrs['t10_dev_id'] == "abc123"  # From attributes dict

    # Verify post-creation attributes only have non-creation params
    assert 'custom_attr' in post_attrs
    assert 'filename' not in post_attrs  # Should not be in post-creation
    assert 't10_dev_id' not in post_attrs  # Should be moved to creation

    print("✓ VdiskFileioDeviceConfig attributes work correctly")

    # Test VdiskBlockioDeviceConfig
    blockio_device = VdiskBlockioDeviceConfig(
        name="test_blockio",
        filename="/dev/sdb",
        nv_cache="1",
        attributes={"custom_attr": "value", "bind_alua_state": "1"}
    )

    creation_attrs = blockio_device.creation_attributes
    post_attrs = blockio_device.post_creation_attributes

    print(f"VdiskBlockio creation attributes: {creation_attrs}")
    print(f"VdiskBlockio post-creation attributes: {post_attrs}")

    assert 'filename' in creation_attrs
    assert 'nv_cache' in creation_attrs
    assert creation_attrs['bind_alua_state'] == "1"  # From attributes dict
    assert 'custom_attr' in post_attrs
    assert 'bind_alua_state' not in post_attrs  # Should be moved to creation

    print("✓ VdiskBlockioDeviceConfig attributes work correctly")

    # Test DevDiskDeviceConfig
    dev_disk = DevDiskDeviceConfig(
        name="test_dev_disk",
        filename="/dev/sda",
        readonly="1",
        attributes={"custom_attr": "value"}
    )

    creation_attrs = dev_disk.creation_attributes
    post_attrs = dev_disk.post_creation_attributes

    print(f"DevDisk creation attributes: {creation_attrs}")
    print(f"DevDisk post-creation attributes: {post_attrs}")

    # DevDisk has NO creation-time parameters
    assert creation_attrs == {}
    # All attributes should be post-creation
    assert 'read_only' in post_attrs  # Note: readonly -> read_only
    assert 'custom_attr' in post_attrs
    assert post_attrs['read_only'] == "1"

    print("✓ DevDiskDeviceConfig attributes work correctly")


def main():
    try:
        test_device_attribute_properties()
        print("\n🎉 All DeviceConfig attribute property tests passed!")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
