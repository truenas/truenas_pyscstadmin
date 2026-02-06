#!/usr/bin/env python3
"""
Test script to verify copy_manager LUN filtering behavior
"""

import os

# Imports handled by conftest.py
from scstadmin.admin import SCSTAdmin
from scstadmin.config import SCSTConfig


def test_passthrough_detection():
    """Test the passthrough device detection logic"""
    print("Testing passthrough device detection...")

    # Create admin instance (this will work even if SCST is not running)
    try:
        admin = SCSTAdmin()

        # Test with some common device names
        test_devices = [
            "sda",  # Common disk device (likely passthrough)
            "sdb",  # Common disk device (likely passthrough)
            "vdisk1",  # Virtual disk (not passthrough)
            "nullio1",  # Virtual device (not passthrough)
        ]

        for device in test_devices:
            is_passthrough = admin._is_passthrough_device(device)
            print(f"  Device '{device}': passthrough={is_passthrough}")

    except Exception as e:
        print(f"  Error testing passthrough detection: {e}")
        print("  (This is expected if SCST is not running)")


def test_config_filtering():
    """Test configuration filtering with mock data"""
    print("\nTesting configuration filtering...")

    # Create a mock configuration with copy_manager LUNs
    config = SCSTConfig()
    config.drivers = {
        "copy_manager": {
            "targets": {
                "copy_manager_tgt": {
                    "luns": {
                        "0": {"device": "sda", "attributes": {}},  # Passthrough device
                        "1": {"device": "vdisk1", "attributes": {}},  # Virtual device
                        "2": {"device": "sdb", "attributes": {}},  # Passthrough device
                    },
                    "groups": {
                        "default": {
                            "luns": {
                                "10": {
                                    "device": "sdc",
                                    "attributes": {},
                                },  # Passthrough
                                "11": {
                                    "device": "nullio1",
                                    "attributes": {},
                                },  # Virtual
                            },
                            "initiators": [],
                            "attributes": {},
                        }
                    },
                    "attributes": {},
                }
            },
            "attributes": {},
        },
        "iscsi": {
            "targets": {
                "iqn.test": {
                    "luns": {"0": {"device": "vdisk1", "attributes": {}}},
                    "groups": {},
                    "attributes": {},
                }
            },
            "attributes": {},
        },
    }

    # Test by creating admin and calling write method
    try:
        admin = SCSTAdmin()

        # Mock the passthrough detection for testing
        def mock_is_passthrough(device):
            # Mock: assume sd* devices are passthrough, others are virtual
            return device.startswith("sd")

        # Replace the method for testing
        original_method = admin._is_passthrough_device
        admin._is_passthrough_device = mock_is_passthrough

        # Test configuration writing
        test_file = "/tmp/test_scst_config.conf"

        # Mock read_current_config to return our test config
        admin.read_current_config = lambda: config

        admin.write_configuration(test_file)

        # Read and display the generated config
        print("Generated configuration (filtered):")
        with open(test_file, "r") as f:
            content = f.read()
            print(content)

        # Check if passthrough devices were filtered out
        lines = content.split("\n")
        copy_manager_luns = [
            line
            for line in lines
            if "LUN" in line and ("sda" in line or "sdb" in line or "sdc" in line)
        ]

        if copy_manager_luns:
            print("\n❌ ERROR: Found passthrough device LUNs that should be filtered:")
            for line in copy_manager_luns:
                print(f"  {line.strip()}")
        else:
            print("\n✅ SUCCESS: Passthrough device LUNs properly filtered out")

        # Check if virtual devices were preserved
        virtual_luns = [
            line
            for line in lines
            if "LUN" in line and ("vdisk1" in line or "nullio1" in line)
        ]
        if virtual_luns:
            print("✅ SUCCESS: Virtual device LUNs preserved:")
            for line in virtual_luns:
                print(f"  {line.strip()}")

        # Clean up
        os.unlink(test_file)
        admin._is_passthrough_device = original_method

    except Exception as e:
        print(f"❌ ERROR: Configuration filtering test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("Copy Manager LUN Filtering Test")
    print("=" * 40)

    test_passthrough_detection()
    test_config_filtering()

    print("\n" + "=" * 40)
    print("Test completed!")
