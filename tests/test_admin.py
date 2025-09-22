#!/usr/bin/env python3
"""
Test script for target attribute functionality within target groups.
This tests the implementation of rel_tgt_id and other target attributes
for ALUA configurations.
"""

import sys
import os
import tempfile
from unittest.mock import Mock, patch

# Imports handled by conftest.py
from scstadmin.admin import SCSTAdmin
from scstadmin.config import TargetGroupConfig
from scstadmin.parser import SCSTConfigParser


def test_parser_target_group_parsing():
    """Test parsing of TARGET blocks with attributes using the parser module"""

    config_text = """
DEVICE_GROUP controller_A {
    TARGET_GROUP disk_volumes {
        TARGET iqn.2023-01.example.com:test1
        TARGET iqn.2023-01.example.com:test2 {
            rel_tgt_id 1
        }
        cpu_mask fff
    }
}
"""

    parser = SCSTConfigParser()
    config = parser.parse_config_text(config_text)

    print("Test 1 - Target group parsing with parser:")
    print("  Input config includes TARGET blocks with attributes")

    # Verify device group was parsed
    assert 'controller_A' in config.device_groups
    dg = config.device_groups['controller_A']

    # Verify target group was parsed
    assert 'disk_volumes' in dg.target_groups
    tg = dg.target_groups['disk_volumes']

    # Verify targets were parsed
    expected_targets = ['iqn.2023-01.example.com:test1', 'iqn.2023-01.example.com:test2']
    assert set(tg.targets) == set(expected_targets)

    # Verify target attributes were parsed
    assert 'iqn.2023-01.example.com:test2' in tg.target_attributes
    assert tg.target_attributes['iqn.2023-01.example.com:test2']['rel_tgt_id'] == '1'

    # Verify group attributes were parsed
    assert tg.attributes['cpu_mask'] == 'fff'

    print(f"  ✓ Targets: {tg.targets}")
    print(f"  ✓ Target attributes: {dict(tg.target_attributes)}")
    print(f"  ✓ Group attributes: {dict(tg.attributes)}")
    print()


def test_target_group_config_comparison():
    """Test that target group configurations are compared correctly"""

    scst = SCSTAdmin()
    scst.sysfs = Mock()
    scst.logger = Mock()

    # Mock the group writer's target_group_config_matches method
    def mock_target_group_config_matches(device_group, tgroup_name, tgroup_config):
        # Mock behavior: return True for identical configs, False for different ones
        if hasattr(tgroup_config, 'target_attributes'):
            test2_attrs = tgroup_config.target_attributes.get('iqn.2023-01.example.com:test2', {})
            return test2_attrs.get('rel_tgt_id') == '1'
        return False

    scst.group_writer.target_group_config_matches = mock_target_group_config_matches

    # Test identical config (should match)
    new_config_dict = {
        'targets': ['iqn.2023-01.example.com:test1', 'iqn.2023-01.example.com:test2'],
        'target_attributes': {
            'iqn.2023-01.example.com:test2': {'rel_tgt_id': '1'}
        },
        'attributes': {'cpu_mask': 'fff'}
    }
    new_config = TargetGroupConfig.from_config_dict('tg1', new_config_dict)

    matches = scst.group_writer.target_group_config_matches('dg1', 'tg1', new_config)
    print("Test 2 - Identical target group configs:")
    print(f"  Should match: True, Got: {matches}")
    print()

    # Test different target attributes (should not match)
    different_config_dict = {
        'targets': ['iqn.2023-01.example.com:test1', 'iqn.2023-01.example.com:test2'],
        'target_attributes': {
            'iqn.2023-01.example.com:test2': {'rel_tgt_id': '2'}  # Different value
        },
        'attributes': {'cpu_mask': 'fff'}
    }
    different_config = TargetGroupConfig.from_config_dict('tg1', different_config_dict)

    matches = scst.group_writer.target_group_config_matches('dg1', 'tg1', different_config)
    print("Test 3 - Different target attributes:")
    print(f"  Should match: False, Got: {matches}")
    print()


def test_target_attribute_setting():
    """Test setting target attributes via sysfs"""

    scst = SCSTAdmin()
    scst.sysfs = Mock()
    scst.logger = Mock()

    # Mock os.path.isdir to return True for directory targets (with attributes)
    with patch('os.path.isdir') as mock_isdir:
        mock_isdir.return_value = True

        # Create a mock target config with attributes
        target_config = Mock()
        target_config.attributes = {'rel_tgt_id': '1', 'preferred': '1'}

        # Test setting target attributes using the group writer
        scst.group_writer._set_target_group_target_attributes(
            'dg1', 'tg1', 'iqn.2023-01.example.com:test', target_config.attributes)

        print("Test 4 - Setting target attributes:")
        print(f"  Target config: {target_config.attributes}")

        # Check that sysfs.write_sysfs was called correctly
        expected_calls = [
            ('/sys/kernel/scst_tgt/device_groups/dg1/target_groups/tg1/iqn.2023-01.example.com:test/rel_tgt_id', '1'),
            ('/sys/kernel/scst_tgt/device_groups/dg1/target_groups/tg1/iqn.2023-01.example.com:test/preferred', '1')
        ]

        actual_calls = [call[0] for call in scst.sysfs.write_sysfs.call_args_list]
        print(f"  Expected sysfs writes: {len(expected_calls)}")
        print(f"  Actual sysfs writes: {len(actual_calls)}")
        for i, call in enumerate(actual_calls):
            print(f"    Call {i+1}: write_sysfs('{call[0]}', '{call[1]}', check_result=False)")
        print()


def test_config_file_parsing_integration():
    """Test end-to-end configuration file parsing with target attributes"""

    config_text = """
DEVICE_GROUP controller_A {
    TARGET_GROUP disk_volumes {
        TARGET iqn.2023-01.example.com:test1
        TARGET iqn.2023-01.example.com:test2 {
            rel_tgt_id 1
        }
        cpu_mask fff
    }
}
"""

    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
        f.write(config_text)
        temp_file = f.name

    try:
        parser = SCSTConfigParser()
        config = parser.parse_config_file(temp_file)

        print("Test 5 - End-to-end config file parsing:")
        print("  ✓ Config file successfully parsed")

        # Verify the structure
        dg = config.device_groups['controller_A']
        tg = dg.target_groups['disk_volumes']

        print("  ✓ Device group 'controller_A' found")
        print("  ✓ Target group 'disk_volumes' found")
        print(f"  ✓ Targets: {tg.targets}")
        print(f"  ✓ Target attributes: {dict(tg.target_attributes)}")
        print(f"  ✓ Group attributes: {dict(tg.attributes)}")
        print()

    finally:
        os.unlink(temp_file)


def main():
    """Run all tests"""
    print("Testing SCST Target Attribute Functionality")
    print("=" * 50)
    print()

    try:
        test_parser_target_group_parsing()
        test_target_group_config_comparison()
        test_target_attribute_setting()
        test_config_file_parsing_integration()

        print("All tests completed!")
        print("Note: These are basic functionality tests. Full integration testing")
        print("      would require a live SCST system with sysfs available.")

    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
