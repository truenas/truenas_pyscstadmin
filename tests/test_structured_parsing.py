#!/usr/bin/env python3
"""
Test script to verify structured DeviceConfig parsing works correctly.
"""

import sys
from pathlib import Path

# Imports handled by conftest.py
from scstadmin.parser import SCSTConfigParser
from scstadmin.config import VdiskFileioDeviceConfig, DevDiskDeviceConfig


def test_structured_device_parsing():
    """Test that parser creates proper DeviceConfig objects."""
    print("Testing structured device parsing...")

    parser = SCSTConfigParser()

    # Test basic device config parsing
    config_text = '''
    HANDLER vdisk_fileio {
        DEVICE test_disk {
            filename /path/to/test.img
            blocksize 4096
            readonly 0
        }
    }

    HANDLER dev_disk {
        DEVICE physical_disk {
            filename /dev/sdb
            readonly 1
        }
    }
    '''

    config = parser.parse_config_text(config_text)

    # Verify we have devices
    assert len(config.devices) == 2, f"Expected 2 devices, got {len(config.devices)}"
    assert 'test_disk' in config.devices
    assert 'physical_disk' in config.devices

    # Verify device types
    test_disk = config.devices['test_disk']
    assert isinstance(test_disk, VdiskFileioDeviceConfig), f"Expected VdiskFileioDeviceConfig, got {type(test_disk)}"

    physical_disk = config.devices['physical_disk']
    assert isinstance(physical_disk, DevDiskDeviceConfig), f"Expected DevDiskDeviceConfig, got {type(physical_disk)}"

    # Verify device properties
    assert test_disk.name == 'test_disk'
    assert test_disk.handler_type == 'vdisk_fileio'
    assert test_disk.filename == '/path/to/test.img'
    assert test_disk.blocksize == '4096'
    assert test_disk.readonly == '0'

    assert physical_disk.name == 'physical_disk'
    assert physical_disk.handler_type == 'dev_disk'
    assert physical_disk.filename == '/dev/sdb'
    assert physical_disk.readonly == '1'

    print("✓ Structured device parsing works correctly")

    # Test with basic.conf fixture
    fixtures_dir = Path(__file__).parent / 'tests' / 'fixtures' / 'valid_configs'
    if (fixtures_dir / 'basic.conf').exists():
        print("Testing with basic.conf fixture...")
        config = parser.parse_config_file(str(fixtures_dir / 'basic.conf'))

        # Check the specific devices from basic.conf
        assert 'disk1' in config.devices
        assert 'disk2' in config.devices
        assert 'sda' in config.devices

        disk1 = config.devices['disk1']
        disk2 = config.devices['disk2']
        sda = config.devices['sda']

        # Verify types
        assert isinstance(disk1, VdiskFileioDeviceConfig)
        assert isinstance(disk2, VdiskFileioDeviceConfig)
        assert isinstance(sda, DevDiskDeviceConfig)

        # Verify attributes
        assert disk1.filename == '/path/to/disk1.img'
        assert disk1.blocksize == '4096'
        assert disk1.readonly == '0'

        assert disk2.filename == '/path with spaces/disk2.img'
        assert disk2.blocksize == '512'

        assert sda.filename == '/dev/sda'
        assert sda.handler_type == 'dev_disk'

        print("✓ basic.conf parsing works with structured objects")


def main():
    try:
        test_structured_device_parsing()
        print("\n🎉 All structured parsing tests passed!")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
