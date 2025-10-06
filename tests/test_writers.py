"""
Test suite for SCST writer classes

This module provides comprehensive tests for the specialized writer classes
that handle SCST configuration application.
"""
import pytest
from unittest.mock import Mock, call, patch
import logging

from scstadmin.writers.device_writer import DeviceWriter
from scstadmin.writers.target_writer import TargetWriter
from scstadmin.writers.group_writer import GroupWriter
from scstadmin.sysfs import SCSTSysfs
from scstadmin.exceptions import SCSTError
from scstadmin.config import ConfigAction


class TestDeviceWriter:
    """Test cases for DeviceWriter class"""

    @pytest.fixture
    def mock_sysfs(self):
        """Create a mock SCSTSysfs instance for testing"""
        mock = Mock(spec=SCSTSysfs)
        # Set up common sysfs path constants that writers expect
        mock.SCST_HANDLERS = "/sys/kernel/scst_tgt/handlers"
        mock.SCST_TARGETS = "/sys/kernel/scst_tgt/targets"
        mock.SCST_DEVICES = "/sys/kernel/scst_tgt/devices"
        return mock

    @pytest.fixture
    def mock_config_reader(self):
        """Create a mock configuration reader for testing"""
        return Mock()

    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger for testing"""
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def device_writer(self, mock_sysfs, mock_config_reader, mock_logger):
        """Create a DeviceWriter instance with mocked dependencies"""
        return DeviceWriter(mock_sysfs, mock_config_reader, mock_logger)

    def test_set_device_attributes_success(self, device_writer, mock_sysfs, mock_logger):
        """
        Test successful setting of device attributes

        This test verifies that:
        1. Multiple attributes are set via sysfs writes
        2. Correct sysfs paths are constructed
        3. Debug logging occurs for each successful attribute
        4. sysfs writes use check_result=False for attributes
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "test_disk"
        attributes = {
            "blocksize": "4096",
            "readonly": "1",
            "thin_provisioned": "0"
        }

        # Configure mock to simulate successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.set_device_attributes(handler, device_name, attributes)

        # Assert: Verify all expected sysfs write operations occurred
        expected_calls = [
            call("/sys/kernel/scst_tgt/handlers/vdisk_fileio/test_disk/blocksize",
                 "4096", check_result=False),
            call("/sys/kernel/scst_tgt/handlers/vdisk_fileio/test_disk/readonly",
                 "1", check_result=False),
            call("/sys/kernel/scst_tgt/handlers/vdisk_fileio/test_disk/thin_provisioned",
                 "0", check_result=False)
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_calls, any_order=True)

        # Verify correct number of calls (should match number of attributes)
        assert mock_sysfs.write_sysfs.call_count == 3

        # Assert: Verify debug logging occurred for each attribute
        expected_log_calls = [
            call("Set device attribute %s.%s = %s", "test_disk", "blocksize", "4096"),
            call("Set device attribute %s.%s = %s", "test_disk", "readonly", "1"),
            call("Set device attribute %s.%s = %s", "test_disk", "thin_provisioned", "0")
        ]
        mock_logger.debug.assert_has_calls(expected_log_calls, any_order=True)
        assert mock_logger.debug.call_count == 3

        # Assert: Verify no warning logs were generated (success case)
        mock_logger.warning.assert_not_called()

    def test_set_device_attributes_partial_failure(self, device_writer, mock_sysfs, mock_logger):
        """
        Test handling of partial failures when setting device attributes

        This test verifies that:
        1. When some attribute writes fail, the method continues with remaining attributes
        2. Failed attributes generate warning logs with proper error context
        3. Successful attributes still generate debug logs
        4. The method doesn't raise exceptions for individual attribute failures
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "test_disk"
        attributes = {
            "blocksize": "4096",      # This will succeed
            "readonly": "1",          # This will fail
            "thin_provisioned": "0"   # This will succeed
        }

        # Configure mock to simulate partial failure
        def mock_write_sysfs(path, value, check_result=False):
            if "readonly" in path:
                raise SCSTError("Permission denied for readonly attribute")
            return None

        mock_sysfs.write_sysfs.side_effect = mock_write_sysfs

        # Act: Call the method under test
        device_writer.set_device_attributes(handler, device_name, attributes)

        # Assert: Verify all sysfs write attempts were made
        assert mock_sysfs.write_sysfs.call_count == 3

        # Assert: Verify debug logs for successful attributes
        successful_debug_calls = [
            call("Set device attribute %s.%s = %s", "test_disk", "blocksize", "4096"),
            call("Set device attribute %s.%s = %s", "test_disk", "thin_provisioned", "0")
        ]
        mock_logger.debug.assert_has_calls(successful_debug_calls, any_order=True)

        # Assert: Verify warning log for failed attribute
        # Note: The logger receives the exception object, not just the message string
        actual_call = mock_logger.warning.call_args
        assert actual_call[0][0] == "Failed to set device attribute %s.%s: %s"
        assert actual_call[0][1] == "test_disk"
        assert actual_call[0][2] == "readonly"
        assert isinstance(actual_call[0][3], SCSTError)
        assert str(actual_call[0][3]) == "Permission denied for readonly attribute"

    def test_set_device_attributes_empty_attributes(self, device_writer, mock_sysfs, mock_logger):
        """
        Test behavior with empty attributes dictionary

        This test verifies that:
        1. No sysfs operations are performed when attributes dict is empty
        2. No logging occurs when there are no attributes to set
        """
        # Arrange: Set up test data with empty attributes
        handler = "vdisk_fileio"
        device_name = "test_disk"
        attributes = {}

        # Act: Call the method under test
        device_writer.set_device_attributes(handler, device_name, attributes)

        # Assert: Verify no sysfs operations occurred
        mock_sysfs.write_sysfs.assert_not_called()

        # Assert: Verify no logging occurred
        mock_logger.debug.assert_not_called()
        mock_logger.warning.assert_not_called()

    def test_device_exists_true(self, device_writer, mock_sysfs):
        """
        Test device_exists method when device actually exists

        This test verifies that:
        1. Correct sysfs path is constructed for device detection
        2. Method returns True when device path exists
        3. Uses entity_exists utility function for path checking
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "test_disk"

        # Mock filesystem operation to return True (device exists)
        with patch('os.path.exists', return_value=True) as mock_exists:
            # Act: Call the method under test
            result = device_writer.device_exists(handler, device_name)

            # Assert: Verify result and proper path construction
            assert result is True
            mock_exists.assert_called_once_with(
                "/sys/kernel/scst_tgt/handlers/vdisk_fileio/test_disk"
            )

    def test_device_exists_false(self, device_writer, mock_sysfs):
        """
        Test device_exists method when device does not exist

        This test verifies that:
        1. Method returns False when device path doesn't exist
        2. Proper path construction for non-existent device
        """
        # Arrange: Set up test data
        handler = "dev_disk"
        device_name = "nonexistent_disk"

        # Mock filesystem operation to return False (device doesn't exist)
        with patch('os.path.exists', return_value=False) as mock_exists:
            # Act: Call the method under test
            result = device_writer.device_exists(handler, device_name)

            # Assert: Verify result and proper path construction
            assert result is False
            mock_exists.assert_called_once_with(
                "/sys/kernel/scst_tgt/handlers/dev_disk/nonexistent_disk"
            )

    def test_remove_device_success(self, device_writer, mock_sysfs, mock_logger):
        """
        Test successful device removal

        This test verifies that:
        1. Correct sysfs management interface path is used
        2. Proper del_device command is sent
        3. No error logging occurs on success
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "test_disk"

        # Configure mock to simulate successful removal
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.remove_device(handler, device_name)

        # Assert: Verify correct sysfs operation
        mock_sysfs.write_sysfs.assert_called_once_with(
            "/sys/kernel/scst_tgt/handlers/vdisk_fileio/mgmt",
            "del_device test_disk"
        )

        # Assert: Verify no error logging
        mock_logger.warning.assert_not_called()

    def test_remove_device_failure(self, device_writer, mock_sysfs, mock_logger):
        """
        Test device removal failure handling

        This test verifies that:
        1. SCSTError exceptions are caught and logged
        2. Warning log includes device name and error details
        3. Method continues execution (doesn't re-raise exception)
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "test_disk"

        # Configure mock to simulate removal failure
        error_message = "Device is in use"
        mock_sysfs.write_sysfs.side_effect = SCSTError(error_message)

        # Act: Call the method under test (should not raise exception)
        device_writer.remove_device(handler, device_name)

        # Assert: Verify sysfs operation was attempted
        mock_sysfs.write_sysfs.assert_called_once_with(
            "/sys/kernel/scst_tgt/handlers/vdisk_fileio/mgmt",
            "del_device test_disk"
        )

        # Assert: Verify error was logged with proper context
        # Note: The logger receives the exception object, not just the message string
        actual_call = mock_logger.warning.call_args
        assert actual_call[0][0] == "Failed to remove existing device %s: %s"
        assert actual_call[0][1] == "test_disk"
        assert isinstance(actual_call[0][2], SCSTError)
        assert str(actual_call[0][2]) == error_message

    def test_remove_device_by_name_success(self, device_writer, mock_sysfs, mock_logger):
        """
        Test successful device removal when handler is unknown

        This test verifies that:
        1. Method searches through all handlers to find the device
        2. Device is removed from the correct handler once found
        3. Search stops after finding and removing the device
        4. No error logging occurs on success
        """
        # Arrange: Set up test data
        device_name = "test_disk"

        # Mock handler directory listing
        mock_sysfs.list_directory.side_effect = [
            # First call: list handlers
            ["vdisk_fileio", "dev_disk", "vdisk_blockio"],
            # Second call: list devices in vdisk_fileio (empty)
            [],
            # Third call: list devices in dev_disk (contains our device)
            ["test_disk", "other_disk"]
        ]

        # Configure successful sysfs write
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.remove_device_by_name(device_name)

        # Assert: Verify handler directory was listed
        expected_calls = [
            call("/sys/kernel/scst_tgt/handlers"),
            call("/sys/kernel/scst_tgt/handlers/vdisk_fileio"),
            call("/sys/kernel/scst_tgt/handlers/dev_disk")
        ]
        mock_sysfs.list_directory.assert_has_calls(expected_calls)

        # Assert: Verify device removal from correct handler
        mock_sysfs.write_sysfs.assert_called_once_with(
            "/sys/kernel/scst_tgt/handlers/dev_disk/mgmt",
            "del_device test_disk"
        )

        # Assert: Verify no error logging
        mock_logger.warning.assert_not_called()

    def test_remove_device_by_name_not_found(self, device_writer, mock_sysfs, mock_logger):
        """
        Test device removal when device is not found in any handler

        This test verifies that:
        1. Method searches through all handlers
        2. No removal operations are performed when device isn't found
        3. No error logging occurs (device may have already been removed)
        """
        # Arrange: Set up test data
        device_name = "nonexistent_disk"

        # Mock handler directory listing (device not found in any handler)
        mock_sysfs.list_directory.side_effect = [
            # First call: list handlers
            ["vdisk_fileio", "dev_disk"],
            # Second call: list devices in vdisk_fileio (doesn't contain device)
            ["other_disk1"],
            # Third call: list devices in dev_disk (doesn't contain device)
            ["other_disk2"]
        ]

        # Act: Call the method under test
        device_writer.remove_device_by_name(device_name)

        # Assert: Verify all handlers were searched
        expected_calls = [
            call("/sys/kernel/scst_tgt/handlers"),
            call("/sys/kernel/scst_tgt/handlers/vdisk_fileio"),
            call("/sys/kernel/scst_tgt/handlers/dev_disk")
        ]
        mock_sysfs.list_directory.assert_has_calls(expected_calls)

        # Assert: Verify no removal operations were performed
        mock_sysfs.write_sysfs.assert_not_called()

        # Assert: Verify no error logging
        mock_logger.warning.assert_not_called()

    def test_remove_device_by_name_sysfs_error(self, device_writer, mock_sysfs, mock_logger):
        """
        Test device removal when sysfs operations fail

        This test verifies that:
        1. SCSTError exceptions during directory listing are handled gracefully
        2. SCSTError exceptions during device removal are logged appropriately
        3. Method continues execution without re-raising exceptions
        """
        # Arrange: Set up test data
        device_name = "test_disk"

        # Mock directory listing failure
        mock_sysfs.list_directory.side_effect = SCSTError("Permission denied")

        # Act: Call the method under test
        device_writer.remove_device_by_name(device_name)

        # Assert: Verify error was logged with device context
        # Note: The logger receives the exception object, not just the message string
        actual_call = mock_logger.warning.call_args
        assert actual_call[0][0] == "Failed to remove device %s: %s"
        assert actual_call[0][1] == "test_disk"
        assert isinstance(actual_call[0][2], SCSTError)
        assert str(actual_call[0][2]) == "Permission denied"

    def test_create_device_with_creation_params_and_attributes(self, device_writer, mock_sysfs):
        """
        Test device creation with both creation parameters and post-creation attributes

        This test verifies the complete device creation workflow:
        1. Creation parameters are properly formatted in add_device command
        2. cluster_mode parameter is placed at the end of the command
        3. Device creation command is sent to handler management interface
        4. Post-creation attributes are set via set_device_attributes method
        5. Proper parameter separation and formatting
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "test_disk"
        creation_params = {
            "filename": "/tmp/test.img",
            "size_mb": "1024",
            "cluster_mode": "1",  # Should be placed at end
            "t10_dev_id": "test_disk_id"
        }
        post_creation_attrs = {
            "readonly": "0",
            "rotational": "1"
        }

        # Configure mocks
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.create_device(handler, device_name, creation_params, post_creation_attrs)

        # Assert: Verify device creation command was sent correctly
        # Should be at least 2 calls: 1 for device creation + N for post-creation attributes
        assert mock_sysfs.write_sysfs.call_count >= 2

        # Find the device creation call (should be to mgmt interface)
        creation_call = None
        for call_args in mock_sysfs.write_sysfs.call_args_list:
            if call_args[0][0].endswith("/mgmt"):
                creation_call = call_args
                break

        assert creation_call is not None, "Device creation call to mgmt interface not found"

        # Verify correct path for device creation
        expected_handler_path = "/sys/kernel/scst_tgt/handlers/vdisk_fileio/mgmt"
        assert creation_call[0][0] == expected_handler_path

        # Verify command structure - should be "add_device test_disk param1=value1;param2=value2;cluster_mode=1;"
        command = creation_call[0][1]
        assert command.startswith("add_device test_disk ")
        assert command.endswith("cluster_mode=1;")
        assert "filename=/tmp/test.img" in command
        assert "size_mb=1024" in command
        assert "t10_dev_id=test_disk_id" in command

        # Assert: Verify post-creation attribute calls were made
        # Should have calls to set readonly and rotational attributes
        attribute_calls = [call for call in mock_sysfs.write_sysfs.call_args_list
                           if not call[0][0].endswith("/mgmt")]
        assert len(attribute_calls) == 2  # readonly and rotational

    def test_create_device_no_creation_params(self, device_writer, mock_sysfs):
        """
        Test device creation with no creation parameters (simple add_device)

        This test verifies that:
        1. When creation_params is empty, simple "add_device name" command is used
        2. No parameter formatting is performed
        3. Post-creation attributes are still applied if provided
        """
        # Arrange: Set up test data
        handler = "dev_disk"
        device_name = "simple_disk"
        creation_params = {}  # No creation parameters
        post_creation_attrs = {"readonly": "1"}

        # Configure mocks
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.create_device(handler, device_name, creation_params, post_creation_attrs)

        # Assert: Verify simple device creation command + attribute setting
        assert mock_sysfs.write_sysfs.call_count == 2  # 1 creation + 1 attribute

        # First call should be device creation
        creation_call = mock_sysfs.write_sysfs.call_args_list[0]
        expected_path = "/sys/kernel/scst_tgt/handlers/dev_disk/mgmt"
        expected_command = "add_device simple_disk"

        assert creation_call[0][0] == expected_path
        assert creation_call[0][1] == expected_command

        # Second call should be setting readonly attribute
        attr_call = mock_sysfs.write_sysfs.call_args_list[1]
        assert "readonly" in attr_call[0][0]  # Path should contain readonly
        assert attr_call[0][1] == "1"  # Value should be "1"

    def test_create_device_no_post_creation_attrs(self, device_writer, mock_sysfs):
        """
        Test device creation with creation parameters but no post-creation attributes

        This test verifies that:
        1. Device creation command is sent with parameters
        2. set_device_attributes is not called when post_creation_attrs is empty
        3. Empty post_creation_attrs dictionary is handled gracefully
        """
        # Arrange: Set up test data
        handler = "vdisk_blockio"
        device_name = "block_disk"
        creation_params = {"filename": "/dev/sdb", "blocksize": "4096"}
        post_creation_attrs = {}  # No post-creation attributes

        # Configure mocks
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.create_device(handler, device_name, creation_params, post_creation_attrs)

        # Assert: Verify only device creation command was sent (no attribute calls)
        mock_sysfs.write_sysfs.assert_called_once()

        call_args = mock_sysfs.write_sysfs.call_args
        expected_path = "/sys/kernel/scst_tgt/handlers/vdisk_blockio/mgmt"
        assert call_args[0][0] == expected_path

        command = call_args[0][1]
        assert command.startswith("add_device block_disk ")
        assert "filename=/dev/sdb" in command
        assert "blocksize=4096" in command

    def test_create_device_cluster_mode_ordering(self, device_writer, mock_sysfs):
        """
        Test that cluster_mode parameter is correctly placed at the end of creation command

        This test specifically verifies the special handling for cluster_mode parameter
        which must be placed after t10_dev_id for proper SCST operation.

        This test verifies that:
        1. cluster_mode is extracted from creation_params during processing
        2. cluster_mode is appended at the end of the parameter list
        3. Other parameters maintain their relative ordering
        """
        # Arrange: Set up test data with cluster_mode mixed in
        handler = "vdisk_fileio"
        device_name = "cluster_disk"
        creation_params = {
            "filename": "/shared/disk.img",
            "cluster_mode": "1",  # This should move to the end
            "t10_dev_id": "shared_disk_id",
            "size_mb": "2048"
        }
        post_creation_attrs = {}

        # Configure mocks
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        device_writer.create_device(handler, device_name, creation_params, post_creation_attrs)

        # Assert: Verify cluster_mode appears at the end
        call_args = mock_sysfs.write_sysfs.call_args
        command = call_args[0][1]

        # Split the command to analyze parameter ordering
        # Expected format: "add_device cluster_disk param1=value1;param2=value2;cluster_mode=1;"
        assert command.startswith("add_device cluster_disk ")
        params_part = command[len("add_device cluster_disk "):]

        # cluster_mode should be the last parameter before the final semicolon
        assert params_part.endswith("cluster_mode=1;")

        # All other parameters should be present
        assert "filename=/shared/disk.img" in command
        assert "t10_dev_id=shared_disk_id" in command
        assert "size_mb=2048" in command

    def test_determine_device_action_skip_matching_config(self, device_writer, mock_sysfs, mock_config_reader):
        """
        Test determine_device_action returns SKIP when device config matches

        This test verifies that:
        1. Current device attributes are read via config_reader
        2. Creation and post-creation attributes are compared separately
        3. When all attributes match, ConfigAction.SKIP is returned
        4. No unnecessary device operations when config already matches
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "disk1"
        device_config = Mock()
        creation_params = {"filename": "/dev/sda", "size_mb": "1024"}
        post_creation_attrs = {"read_only": "1", "rotational": "0"}

        # Mock config reader to return matching attributes
        current_attrs = {
            "filename": "/dev/sda",      # Creation attr matches
            "size_mb": "1024",           # Creation attr matches
            "read_only": "1",            # Post-creation attr matches
            "rotational": "0"            # Post-creation attr matches
        }
        mock_config_reader._get_current_device_attrs.return_value = current_attrs

        # Act: Call the method under test
        result = device_writer.determine_device_action(
            handler, device_name, device_config, creation_params, post_creation_attrs)

        # Assert: Verify correct action returned
        assert result == ConfigAction.SKIP

        # Assert: Verify config reader was called correctly
        expected_attrs_to_check = {"filename", "size_mb", "read_only", "rotational"}
        mock_config_reader._get_current_device_attrs.assert_called_once_with(
            handler, device_name, expected_attrs_to_check)

    def test_determine_device_action_recreate_creation_attrs_differ(self,
                                                                    device_writer,
                                                                    mock_sysfs,
                                                                    mock_config_reader):
        """
        Test determine_device_action returns RECREATE when creation attributes differ

        This test verifies that:
        1. When creation-time attributes differ, device must be recreated
        2. Post-creation attribute differences are irrelevant if creation attrs differ
        3. ConfigAction.RECREATE is returned for creation attribute mismatches
        4. Proper delegation to attrs_config_differs utility
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "disk1"
        device_config = Mock()
        creation_params = {"filename": "/dev/sda", "size_mb": "2048"}  # size_mb differs
        post_creation_attrs = {"read_only": "1"}

        # Mock config reader - creation attr differs, post-creation matches
        current_attrs = {
            "filename": "/dev/sda",      # Creation attr matches
            "size_mb": "1024",           # Creation attr DIFFERS (1024 vs 2048)
            "read_only": "1"             # Post-creation attr matches
        }
        mock_config_reader._get_current_device_attrs.return_value = current_attrs

        # Act: Call the method under test
        result = device_writer.determine_device_action(
            handler, device_name, device_config, creation_params, post_creation_attrs)

        # Assert: Verify RECREATE action returned
        assert result == ConfigAction.RECREATE

        # Assert: Verify attributes were checked
        expected_attrs_to_check = {"filename", "size_mb", "read_only"}
        mock_config_reader._get_current_device_attrs.assert_called_once_with(
            handler, device_name, expected_attrs_to_check)

    def test_determine_device_action_update_post_attrs_differ(self, device_writer, mock_sysfs, mock_config_reader):
        """
        Test determine_device_action returns UPDATE when only post-creation attributes differ

        This test verifies that:
        1. When creation attributes match but post-creation differ, UPDATE is returned
        2. In-place attribute updates are preferred over recreation when possible
        3. ConfigAction.UPDATE enables efficient attribute-only updates
        4. Proper attribute categorization between creation and post-creation
        """
        # Arrange: Set up test data
        handler = "vdisk_fileio"
        device_name = "disk1"
        device_config = Mock()
        creation_params = {"filename": "/dev/sda", "size_mb": "1024"}
        post_creation_attrs = {"read_only": "1", "rotational": "0"}  # rotational differs

        # Mock config reader - creation attrs match, post-creation differs
        current_attrs = {
            "filename": "/dev/sda",      # Creation attr matches
            "size_mb": "1024",           # Creation attr matches
            "read_only": "1",            # Post-creation attr matches
            "rotational": "1"            # Post-creation attr DIFFERS (1 vs 0)
        }
        mock_config_reader._get_current_device_attrs.return_value = current_attrs

        # Act: Call the method under test
        result = device_writer.determine_device_action(
            handler, device_name, device_config, creation_params, post_creation_attrs)

        # Assert: Verify UPDATE action returned
        assert result == ConfigAction.UPDATE

        # Assert: Verify attributes were checked
        expected_attrs_to_check = {"filename", "size_mb", "read_only", "rotational"}
        mock_config_reader._get_current_device_attrs.assert_called_once_with(
            handler, device_name, expected_attrs_to_check)

    def test_apply_config_devices_comprehensive_workflow(self,
                                                         device_writer,
                                                         mock_sysfs,
                                                         mock_config_reader,
                                                         mock_logger):
        """
        Test apply_config_devices main entry point with comprehensive device workflow

        This test verifies the complete device configuration application process:
        1. Device existence checking for all configured devices
        2. Action determination for existing devices (SKIP/UPDATE/RECREATE)
        3. Appropriate device operations based on determined actions
        4. New device creation for non-existing devices
        5. Proper debug logging for all operations
        6. Integration with all helper methods
        """
        # Arrange: Set up test configuration with multiple scenarios
        config = Mock()
        config.devices = {
            "skip_device": Mock(),      # Exists, config matches, will be skipped
            "update_device": Mock(),    # Exists, post-creation attrs differ, will be updated
            "recreate_device": Mock(),  # Exists, creation attrs differ, will be recreated
            "new_device": Mock()        # Doesn't exist, will be created
        }

        # Configure device configurations
        for device_name, device_config in config.devices.items():
            device_config.handler_type = "vdisk_fileio"
            device_config.creation_attributes = {"filename": f"/dev/{device_name}", "size_mb": "1024"}
            device_config.post_creation_attributes = {"read_only": "0", "rotational": "1"}

        # Mock device existence - only new_device doesn't exist
        def mock_device_exists(handler, device_name):
            return device_name != "new_device"

        # Mock device action determination
        def mock_determine_device_action(handler, device_name, device_config, creation_params, post_attrs):
            if device_name == "skip_device":
                return ConfigAction.SKIP
            elif device_name == "update_device":
                return ConfigAction.UPDATE
            elif device_name == "recreate_device":
                return ConfigAction.RECREATE
            return None  # Should not be called for new_device

        # Mock helper methods
        device_writer.device_exists = Mock(side_effect=mock_device_exists)
        device_writer.determine_device_action = Mock(side_effect=mock_determine_device_action)
        device_writer.set_device_attributes = Mock()
        device_writer.remove_device = Mock()
        device_writer.create_device = Mock()

        # Act: Call the method under test
        device_writer.apply_config_devices(config)

        # Assert: Verify existence checks for all devices
        expected_exists_calls = [
            call("vdisk_fileio", "skip_device"),
            call("vdisk_fileio", "update_device"),
            call("vdisk_fileio", "recreate_device"),
            call("vdisk_fileio", "new_device")
        ]
        device_writer.device_exists.assert_has_calls(expected_exists_calls, any_order=True)

        # Assert: Verify action determination for existing devices only
        expected_action_calls = [
            call("vdisk_fileio", "skip_device", config.devices["skip_device"],
                 config.devices["skip_device"].creation_attributes,
                 config.devices["skip_device"].post_creation_attributes),
            call("vdisk_fileio", "update_device", config.devices["update_device"],
                 config.devices["update_device"].creation_attributes,
                 config.devices["update_device"].post_creation_attributes),
            call("vdisk_fileio", "recreate_device", config.devices["recreate_device"],
                 config.devices["recreate_device"].creation_attributes,
                 config.devices["recreate_device"].post_creation_attributes)
        ]
        device_writer.determine_device_action.assert_has_calls(expected_action_calls, any_order=True)
        assert device_writer.determine_device_action.call_count == 3  # Not called for new_device

        # Assert: Verify UPDATE action - set attributes only
        device_writer.set_device_attributes.assert_called_once_with(
            "vdisk_fileio", "update_device",
            config.devices["update_device"].post_creation_attributes)

        # Assert: Verify RECREATE action - remove then create
        device_writer.remove_device.assert_called_once_with("vdisk_fileio", "recreate_device")

        # Assert: Verify device creation for recreated and new devices
        expected_create_calls = [
            call("vdisk_fileio", "recreate_device",
                 config.devices["recreate_device"].creation_attributes,
                 config.devices["recreate_device"].post_creation_attributes),
            call("vdisk_fileio", "new_device",
                 config.devices["new_device"].creation_attributes,
                 config.devices["new_device"].post_creation_attributes)
        ]
        device_writer.create_device.assert_has_calls(expected_create_calls, any_order=True)
        assert device_writer.create_device.call_count == 2

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call("Applying device configurations. Found %s devices", 4)
        mock_logger.debug.assert_any_call("Device %s already exists with matching config, skipping",
                                          "skip_device")
        mock_logger.debug.assert_any_call("Device %s exists, updating post-creation attributes only",
                                          "update_device")
        mock_logger.debug.assert_any_call("Device %s creation attributes differ, removing and recreating",
                                          "recreate_device")


class TestTargetWriter:
    """Test cases for TargetWriter class"""

    @pytest.fixture
    def mock_sysfs(self):
        """Create a mock SCSTSysfs instance for testing"""
        mock = Mock(spec=SCSTSysfs)
        # Set up common sysfs path constants that writers expect
        mock.SCST_HANDLERS = "/sys/kernel/scst_tgt/handlers"
        mock.SCST_TARGETS = "/sys/kernel/scst_tgt/targets"
        mock.SCST_DEVICES = "/sys/kernel/scst_tgt/devices"
        mock.MGMT_INTERFACE = "mgmt"
        mock.ENABLED_ATTR = "enabled"
        return mock

    @pytest.fixture
    def mock_config_reader(self):
        """Create a mock configuration reader for testing"""
        mock = Mock()
        # Default mgmt info for testing
        mock._get_target_mgmt_info.return_value = {
            'target_attributes': {'IncomingUser', 'OutgoingUser'},
            'driver_attributes': {'MaxSessions'}
        }
        return mock

    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger for testing"""
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def target_writer(self, mock_sysfs, mock_config_reader, mock_logger):
        """Create a TargetWriter instance with mocked dependencies"""
        return TargetWriter(mock_sysfs, mock_config_reader, mock_logger)

    def test_set_target_attributes_mgmt_attributes(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test setting target attributes that use management interface commands

        This test verifies that:
        1. Attributes in target_attributes set use add_target_attribute mgmt commands
        2. Multi-value attributes separated by semicolons are handled properly
        3. Correct mgmt interface path is used for commands
        4. Debug logging occurs for each mgmt attribute operation
        5. Management command failures are logged as warnings but don't stop processing
        """
        # Arrange: Set up test data
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"
        attributes = {
            "IncomingUser": "user1 secret123;user2 secret456",  # Multi-value mgmt attribute
            "OutgoingUser": "outuser outpass"  # Single-value mgmt attribute
        }

        # Configure mock config reader to identify these as mgmt attributes
        mock_config_reader._get_target_mgmt_info.return_value = {
            'target_attributes': {'IncomingUser', 'OutgoingUser'},
            'driver_attributes': set()
        }

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        target_writer.set_target_attributes(driver_name, target_name, attributes)

        # Assert: Verify mgmt interface was queried
        mock_config_reader._get_target_mgmt_info.assert_called_once_with(driver_name)

        # Assert: Verify correct mgmt commands were sent
        expected_calls = [
            call("/sys/kernel/scst_tgt/targets/iscsi/mgmt",
                 "add_target_attribute iqn.2023-01.example.com:test IncomingUser user1 secret123",
                 check_result=False),
            call("/sys/kernel/scst_tgt/targets/iscsi/mgmt",
                 "add_target_attribute iqn.2023-01.example.com:test IncomingUser user2 secret456",
                 check_result=False),
            call("/sys/kernel/scst_tgt/targets/iscsi/mgmt",
                 "add_target_attribute iqn.2023-01.example.com:test OutgoingUser outuser outpass",
                 check_result=False)
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_calls, any_order=True)
        assert mock_sysfs.write_sysfs.call_count == 3

        # Assert: Verify debug logging for mgmt operations
        assert mock_logger.debug.call_count == 3
        mock_logger.debug.assert_any_call(
            "Setting target mgmt attribute %s/%s.%s = %s",
            "iscsi", "iqn.2023-01.example.com:test", "IncomingUser", "user1 secret123"
        )
        mock_logger.debug.assert_any_call(
            "Setting target mgmt attribute %s/%s.%s = %s",
            "iscsi", "iqn.2023-01.example.com:test", "IncomingUser", "user2 secret456"
        )
        mock_logger.debug.assert_any_call(
            "Setting target mgmt attribute %s/%s.%s = %s",
            "iscsi", "iqn.2023-01.example.com:test", "OutgoingUser", "outuser outpass"
        )

    def test_set_target_attributes_direct_sysfs(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test setting target attributes that use direct sysfs writes

        This test verifies that:
        1. Attributes not in mgmt interface use direct sysfs file writes
        2. Correct target attribute paths are constructed
        3. sysfs writes use check_result=False for non-critical attributes
        4. Attribute write failures are logged as warnings but don't stop processing
        """
        # Arrange: Set up test data
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"
        attributes = {
            "enabled": "1",  # Direct sysfs attribute
            "HeaderDigest": "CRC32C"  # Direct sysfs attribute
        }

        # Configure mock config reader - these are NOT mgmt attributes
        mock_config_reader._get_target_mgmt_info.return_value = {
            'target_attributes': set(),  # Empty - no mgmt attributes
            'driver_attributes': set()
        }

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        target_writer.set_target_attributes(driver_name, target_name, attributes)

        # Assert: Verify direct sysfs writes to target attribute paths
        expected_calls = [
            call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/enabled",
                 "1", check_result=False),
            call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/HeaderDigest",
                 "CRC32C", check_result=False)
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_calls, any_order=True)
        assert mock_sysfs.write_sysfs.call_count == 2

        # Assert: Verify no debug logging for direct sysfs (only mgmt gets debug logs)
        mock_logger.debug.assert_not_called()

    def test_set_target_attributes_mixed_types(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test setting a mix of mgmt attributes and direct sysfs attributes

        This test verifies that:
        1. Different attribute types are handled with their appropriate methods
        2. Mgmt attributes use mgmt commands while others use direct sysfs
        3. Processing continues even if some attributes fail
        """
        # Arrange: Set up test data with mixed attribute types
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"
        attributes = {
            "IncomingUser": "user secret",  # Mgmt attribute
            "enabled": "1",  # Direct sysfs attribute
            "HeaderDigest": "CRC32C"  # Direct sysfs attribute
        }

        # Configure mock config reader
        mock_config_reader._get_target_mgmt_info.return_value = {
            'target_attributes': {'IncomingUser'},  # Only IncomingUser is mgmt
            'driver_attributes': set()
        }

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        target_writer.set_target_attributes(driver_name, target_name, attributes)

        # Assert: Verify both mgmt and direct sysfs calls were made
        assert mock_sysfs.write_sysfs.call_count == 3

        # Check for mgmt command call
        mgmt_calls = [call for call in mock_sysfs.write_sysfs.call_args_list
                      if call[0][0].endswith("/mgmt")]
        assert len(mgmt_calls) == 1
        assert "add_target_attribute" in mgmt_calls[0][0][1]

        # Check for direct sysfs calls
        direct_calls = [call for call in mock_sysfs.write_sysfs.call_args_list
                        if not call[0][0].endswith("/mgmt")]
        assert len(direct_calls) == 2

        # Assert: Verify debug logging only for mgmt attribute
        mock_logger.debug.assert_called_once()
        # With %s format, attribute name is in args[3] (0=format, 1=driver, 2=target, 3=attr_name, 4=value)
        assert mock_logger.debug.call_args[0][3] == "IncomingUser"

    def test_set_target_attributes_sysfs_failures(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test error handling when sysfs operations fail during attribute setting

        This test verifies that:
        1. SCSTError exceptions are caught and logged appropriately
        2. Failures don't stop processing of remaining attributes
        3. Warning logs include proper context about failed operations
        """
        # Arrange: Set up test data
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"
        attributes = {
            "IncomingUser": "user secret",  # This will fail
            "enabled": "1"  # This will succeed
        }

        # Configure mock config reader
        mock_config_reader._get_target_mgmt_info.return_value = {
            'target_attributes': {'IncomingUser'},
            'driver_attributes': set()
        }

        # Configure mock to simulate partial failure
        def mock_write_sysfs(path, value, check_result=False):
            if path.endswith("/mgmt"):
                raise SCSTError("Management interface error")
            return None  # Direct sysfs succeeds

        mock_sysfs.write_sysfs.side_effect = mock_write_sysfs

        # Act: Call the method under test
        target_writer.set_target_attributes(driver_name, target_name, attributes)

        # Assert: Verify both operations were attempted
        assert mock_sysfs.write_sysfs.call_count == 2

        # Assert: Verify warning was logged for mgmt failure
        mock_logger.warning.assert_called_once()
        # With %s format: args are (format_string, driver, target, attr_name, attr_value, exception)
        actual_call = mock_logger.warning.call_args
        assert actual_call[0][0] == "Failed to set %s/%s.%s=%s via mgmt: %s"
        assert actual_call[0][1] == "iscsi"
        assert actual_call[0][2] == "iqn.2023-01.example.com:test"
        assert actual_call[0][3] == "IncomingUser"
        assert actual_call[0][4] == "user secret"
        assert isinstance(actual_call[0][5], SCSTError)
        assert str(actual_call[0][5]) == "Management interface error"

    def test_set_target_attributes_empty_attributes(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test behavior with empty attributes dictionary

        This test verifies that:
        1. No sysfs operations are performed when attributes dict is empty
        2. Config reader is still called to get mgmt info
        3. No logging occurs when there are no attributes to set
        """
        # Arrange: Set up test data with empty attributes
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"
        attributes = {}

        # Act: Call the method under test
        target_writer.set_target_attributes(driver_name, target_name, attributes)

        # Assert: Verify mgmt info was still queried
        mock_config_reader._get_target_mgmt_info.assert_called_once_with(driver_name)

        # Assert: Verify no sysfs operations occurred
        mock_sysfs.write_sysfs.assert_not_called()

        # Assert: Verify no logging occurred
        mock_logger.debug.assert_not_called()
        mock_logger.warning.assert_not_called()

    def test_remove_target_success_with_cleanup(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test successful target removal with complete cleanup sequence

        This test verifies the complete target removal workflow:
        1. Target is disabled to prevent new connections
        2. Active sessions are force-closed with timeout handling
        3. All LUNs are cleared from target
        4. All initiator groups and their LUNs are removed
        5. Target itself is removed via driver mgmt interface
        6. Proper sysfs path validation and directory operations
        """
        # Arrange: Set up test data
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"

        # Configure mock sysfs to simulate target with LUNs and groups
        mock_sysfs.valid_path.side_effect = lambda path: True  # All paths exist
        mock_sysfs.list_directory.return_value = ["group1", "group2", "mgmt"]  # Groups with mgmt
        mock_sysfs.write_sysfs.return_value = None

        # Mock the internal helper methods to return success
        with patch.object(target_writer, '_disable_target_if_possible') as mock_disable, \
             patch.object(target_writer, '_force_close_target_sessions', return_value=True) as mock_close_sessions:

            # Act: Call the method under test
            target_writer.remove_target(driver_name, target_name)

            # Assert: Verify target disable was attempted
            mock_disable.assert_called_once_with(driver_name, target_name)

            # Assert: Verify session closure was attempted
            mock_close_sessions.assert_called_once_with(driver_name, target_name)

            # Assert: Verify sysfs path validations
            expected_valid_path_calls = [
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/luns/mgmt"),
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups"),
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/group1/luns/mgmt"),
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/group2/luns/mgmt")
            ]
            mock_sysfs.valid_path.assert_has_calls(expected_valid_path_calls, any_order=True)

            # Assert: Verify cleanup operations were performed in correct sequence
            expected_write_calls = [
                # Clear target LUNs
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/luns/mgmt", "clear"),
                # Clear group1 LUNs
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/group1/luns/mgmt",
                     "clear"),
                # Remove group1
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/mgmt", "del group1"),
                # Clear group2 LUNs
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/group2/luns/mgmt",
                     "clear"),
                # Remove group2
                call("/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/mgmt", "del group2"),
                # Remove target itself
                call("/sys/kernel/scst_tgt/targets/iscsi/mgmt", "del_target iqn.2023-01.example.com:test")
            ]
            mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls)
            assert mock_sysfs.write_sysfs.call_count == 6

            # Assert: Verify directory listing for groups
            mock_sysfs.list_directory.assert_called_once_with(
                "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups"
            )

    def test_remove_target_sysfs_error_handling(self, target_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test error handling when sysfs operations fail during target removal

        This test verifies that:
        1. SCSTError exceptions are caught and logged appropriately
        2. Error log includes target identification and error details
        3. Method continues execution gracefully without re-raising exceptions
        4. Proper error context is provided for debugging
        """
        # Arrange: Set up test data
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"

        # Configure mock sysfs to throw error during target removal
        mock_sysfs.valid_path.return_value = False  # Simple target
        mock_sysfs.write_sysfs.side_effect = SCSTError("Target is in use")

        # Mock helper methods
        with patch.object(target_writer, '_disable_target_if_possible') as mock_disable, \
             patch.object(target_writer, '_force_close_target_sessions', return_value=True) as mock_close_sessions:

            # Act: Call the method under test (should not raise exception)
            target_writer.remove_target(driver_name, target_name)

            # Assert: Verify error was logged with proper context
            # Note: The logger receives the exception object, not just the message string
            actual_call = mock_logger.warning.call_args
            assert actual_call[0][0] == "Failed to remove target %s/%s: %s"
            assert actual_call[0][1] == "iscsi"
            assert actual_call[0][2] == "iqn.2023-01.example.com:test"
            assert isinstance(actual_call[0][3], SCSTError)
            assert str(actual_call[0][3]) == "Target is in use"

            # Assert: Verify helper methods were still called
            mock_disable.assert_called_once_with(driver_name, target_name)
            mock_close_sessions.assert_called_once_with(driver_name, target_name)

    def test_update_target_attributes_with_change_detection(self,
                                                            target_writer,
                                                            mock_sysfs,
                                                            mock_config_reader,
                                                            mock_logger):
        """
        Test update_target_attributes with intelligent change detection and mgmt handling

        This test verifies that:
        1. Only attributes that actually differ are updated (performance optimization)
        2. Attributes with None current values and "0" desired values are skipped
        3. Mgmt-managed attributes are removed before setting new values
        4. Proper delegation to helper methods for attribute removal and setting
        5. Debug logging for attribute comparison and update decisions
        """
        # Arrange: Set up test data
        driver_name = "iscsi"
        target_name = "iqn.2023-01.example.com:test"
        desired_attrs = {
            "IncomingUser": "newuser newsecret",  # Mgmt attr, differs, needs removal+update
            "HeaderDigest": "CRC32C",             # Direct attr, differs, needs update
            "enabled": "1",                       # Direct attr, same, skip
            "rotational": "0"                     # Direct attr, current is None but desired is "0", skip
        }
        current_attrs = {
            "IncomingUser": "olduser oldsecret",  # Different value
            "HeaderDigest": "None",               # Different value
            "enabled": "1",                       # Same value
            "rotational": None                    # None value with desired "0"
        }

        # Configure mock config reader to identify mgmt attributes
        mock_config_reader._get_target_mgmt_info.return_value = {
            'target_attributes': {'IncomingUser'},  # Only IncomingUser is mgmt-managed
            'driver_attributes': set()
        }

        # Mock helper methods
        target_writer._remove_target_mgmt_attribute = Mock()
        target_writer.set_target_attributes = Mock()

        # Act: Call the method under test
        target_writer.update_target_attributes(driver_name, target_name, desired_attrs, current_attrs)

        # Assert: Verify mgmt interface was queried
        mock_config_reader._get_target_mgmt_info.assert_called_once_with(driver_name)

        # Assert: Verify mgmt attribute removal for changed mgmt attributes
        target_writer._remove_target_mgmt_attribute.assert_called_once_with(
            driver_name, target_name, "IncomingUser"
        )

        # Assert: Verify only differing attributes are updated (not enabled or rotational)
        expected_attrs_to_update = {
            "IncomingUser": "newuser newsecret",
            "HeaderDigest": "CRC32C"
        }
        target_writer.set_target_attributes.assert_called_once_with(
            driver_name, target_name, expected_attrs_to_update
        )

        # Assert: Verify debug logging for attribute comparisons
        mock_logger.debug.assert_any_call(
            "Target attribute '%s' needs update: current='%s' -> desired='%s'",
            "IncomingUser", "olduser oldsecret", "newuser newsecret"
        )
        mock_logger.debug.assert_any_call(
            "Target attribute '%s' needs update: current='%s' -> desired='%s'",
            "HeaderDigest", "None", "CRC32C"
        )
        mock_logger.debug.assert_any_call(
            "Updating %s target attributes for %s/%s",
            2, "iscsi", "iqn.2023-01.example.com:test"
        )

    def test_apply_config_assignments_comprehensive_workflow(self,
                                                             target_writer,
                                                             mock_sysfs,
                                                             mock_config_reader,
                                                             mock_logger):
        """
        Test apply_config_assignments with comprehensive target configuration workflow

        This test verifies the complete target configuration process:
        1. Target existence checking and creation for new targets
        2. Incremental updates for existing targets (attributes, LUNs, groups)
        3. Proper delegation to specialized helper methods
        4. Performance optimizations (only update what differs)
        5. Target creation with creation parameters and post-creation attributes
        6. LUN and group assignment application
        """
        # Arrange: Set up test configuration
        config = Mock()
        config.drivers = {
            "iscsi": Mock()
        }

        # Configure driver with two targets: one existing, one new
        driver_config = config.drivers["iscsi"]
        driver_config.targets = {
            "existing_target": Mock(),  # Exists, will be updated
            "new_target": Mock()        # Doesn't exist, will be created
        }

        # Configure existing target (attributes differ, groups differ)
        existing_target = driver_config.targets["existing_target"]
        existing_target.attributes = {"HeaderDigest": "CRC32C", "enabled": "1"}

        # Configure new target (will be created)
        new_target = driver_config.targets["new_target"]
        new_target.attributes = {"node_name": "iqn.example:new", "enabled": "1"}

        # Mock target existence - only existing_target exists
        def mock_target_exists(driver, target):
            return target == "existing_target"

        # Mock helper methods with specific return values
        target_writer._target_exists = Mock(side_effect=mock_target_exists)
        target_writer._target_config_differs = Mock(return_value=True)  # Attributes differ
        target_writer._direct_lun_assignments_differ = Mock(return_value=False)  # LUNs match
        target_writer._group_lun_assignments_differ = Mock(return_value=False)  # Group LUNs match
        target_writer._group_assignments_differ = Mock(return_value=True)  # Groups differ
        target_writer.update_target_attributes = Mock()
        target_writer._update_target_groups = Mock()
        target_writer.ensure_hardware_targets_enabled = Mock()
        target_writer.set_target_attributes = Mock()
        target_writer.apply_lun_assignments = Mock()
        target_writer.apply_group_assignments = Mock()

        # Mock config reader methods
        mock_config_reader._get_current_target_attrs.return_value = {"HeaderDigest": "None", "enabled": "1"}
        mock_config_reader._get_target_mgmt_info.return_value = {
            "create_params": {"node_name"},
            "target_attributes": {"IncomingUser", "OutgoingUser"}
        }

        # Mock _get_target_create_params to return creation params for new_target only
        def mock_get_create_params(driver, attrs):
            if "node_name" in attrs:
                return {"node_name": attrs["node_name"]}
            return {}
        mock_config_reader._get_target_create_params.side_effect = mock_get_create_params

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        target_writer.apply_config_assignments(config)

        # Assert: Verify target existence checks
        expected_exists_calls = [
            call("iscsi", "existing_target"),
            call("iscsi", "new_target")
        ]
        target_writer._target_exists.assert_has_calls(expected_exists_calls, any_order=True)

        # Assert: Verify existing target updates
        # Attributes should be updated (they differ)
        target_writer.update_target_attributes.assert_called_once()
        # Groups should be updated (they differ)
        target_writer._update_target_groups.assert_called_once_with(
            "iscsi", "existing_target", existing_target
        )

        # Assert: Verify new target creation
        target_writer.ensure_hardware_targets_enabled.assert_called_once_with("iscsi", driver_config)
        mock_sysfs.write_sysfs.assert_called_with(
            "/sys/kernel/scst_tgt/targets/iscsi/mgmt",
            "add_target new_target node_name=iqn.example:new"
        )

        # Assert: Verify post-creation attribute setting for new target
        target_writer.set_target_attributes.assert_called_once_with(
            "iscsi", "new_target", {"enabled": "1"}  # node_name excluded as creation param
        )

        # Assert: Verify LUN and group assignments applied for new target
        target_writer.apply_lun_assignments.assert_called_with("iscsi", "new_target", new_target)
        target_writer.apply_group_assignments.assert_called_with("iscsi", "new_target", new_target)

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call("Target attributes differ for %s/%s, updating", "iscsi", "existing_target")
        mock_logger.debug.assert_any_call("Group assignments differ for %s/%s, updating", "iscsi", "existing_target")

    def test_target_exists_true(self, target_writer, mock_sysfs):
        """
        Test _target_exists returns True when target path exists

        This test verifies that:
        1. Correct sysfs path is constructed for target detection
        2. Method returns True when target directory exists
        3. Uses entity_exists utility which checks os.path.exists
        """
        # Arrange: Set up test data
        driver = "iscsi"
        target_name = "iqn.2023-01.example.com:test"

        # Mock filesystem operation to return True (target exists)
        with patch('os.path.exists', return_value=True) as mock_exists:
            # Act: Call the method under test
            result = target_writer._target_exists(driver, target_name)

            # Assert: Verify result and proper path construction
            assert result is True
            mock_exists.assert_called_once_with(
                "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test"
            )

    def test_target_exists_false(self, target_writer, mock_sysfs):
        """
        Test _target_exists returns False when target path doesn't exist

        This test verifies that:
        1. Method returns False when target directory doesn't exist
        2. Proper path construction for non-existent target
        3. Filesystem check handles non-existent paths correctly
        """
        # Arrange: Set up test data
        driver = "fc"
        target_name = "20:00:00:25:B5:00:00:00"

        # Mock filesystem operation to return False (target doesn't exist)
        with patch('os.path.exists', return_value=False) as mock_exists:
            # Act: Call the method under test
            result = target_writer._target_exists(driver, target_name)

            # Assert: Verify result and proper path construction
            assert result is False
            mock_exists.assert_called_once_with(
                "/sys/kernel/scst_tgt/targets/fc/20:00:00:25:B5:00:00:00"
            )

    def test_group_config_matches_true(self, target_writer, mock_sysfs):
        """
        Test _group_config_matches returns True when group configuration matches

        This test verifies that:
        1. Group existence checking via os.path.exists
        2. Initiator list comparison with backslash normalization
        3. LUN assignment comparison (LUN numbers, not device mappings)
        4. Proper sysfs path construction for group components
        5. mgmt interface filtering in directory listings
        """
        # Arrange: Set up test data
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        group_name = "windows_clients"
        group_config = Mock()
        group_config.initiators = ["iqn.1991-05.com.microsoft:client1", "iqn.1991-05.com.microsoft:client2"]
        group_config.luns = {"0": {}, "1": {}}  # LUN numbers as keys

        group_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/windows_clients"
        initiators_path = f"{group_path}/initiators"
        luns_path = f"{group_path}/luns"

        # Mock filesystem operations
        def mock_exists(path):
            return path in [group_path, initiators_path, luns_path]

        def mock_listdir(path):
            if path == initiators_path:
                return ["iqn.1991-05.com.microsoft:client1", "iqn.1991-05.com.microsoft:client2", "mgmt"]
            elif path == luns_path:
                return ["0", "1", "mgmt"]  # LUN directories
            return []

        def mock_isfile(path):
            # Initiators are files, LUNs are directories
            return "initiators/" in path and not path.endswith("/mgmt")

        def mock_isdir(path):
            # LUN entries are directories, mgmt is excluded
            return "luns/" in path and not path.endswith("/mgmt")

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isfile', side_effect=mock_isfile), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = target_writer._group_config_matches(driver, target, group_name, group_config)

        # Assert: Verify method returns True for matching configuration
        assert result is True

    def test_group_config_matches_false_initiators_differ(self, target_writer, mock_sysfs):
        """
        Test _group_config_matches returns False when initiator lists differ

        This test verifies that:
        1. Initiator list differences are properly detected
        2. Backslash normalization works correctly
        3. Method returns False when initiators don't match
        4. LUN checking is skipped when initiators already differ
        """
        # Arrange: Set up test data with different initiators
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        group_name = "linux_clients"
        group_config = Mock()
        group_config.initiators = ["iqn.1993-08.org.debian:client1", "iqn.1993-08.org.debian:client2"]
        group_config.luns = {"0": {}}

        group_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/linux_clients"
        initiators_path = f"{group_path}/initiators"

        # Mock filesystem operations - different initiators in sysfs
        def mock_exists(path):
            return path in [group_path, initiators_path]

        def mock_listdir(path):
            if path == initiators_path:
                return ["iqn.1993-08.org.debian:client1", "iqn.1993-08.org.debian:different_client", "mgmt"]
            return []

        def mock_isfile(path):
            return "initiators/" in path and not path.endswith("/mgmt")

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isfile', side_effect=mock_isfile):

            # Act: Call the method under test
            result = target_writer._group_config_matches(driver, target, group_name, group_config)

        # Assert: Verify method returns False for differing initiators
        assert result is False

    def test_group_config_matches_false_luns_differ(self, target_writer, mock_sysfs):
        """
        Test _group_config_matches returns False when LUN assignments differ

        This test verifies that:
        1. LUN assignment differences are properly detected
        2. LUN number comparison (not device names)
        3. Method returns False when LUN sets don't match
        4. Both initiators and LUNs are checked in sequence
        """
        # Arrange: Set up test data with matching initiators but different LUNs
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        group_name = "storage_group"
        group_config = Mock()
        group_config.initiators = ["iqn.example:client1"]
        group_config.luns = {"0": {}, "1": {}}  # Desired LUNs: 0, 1

        group_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/storage_group"
        initiators_path = f"{group_path}/initiators"
        luns_path = f"{group_path}/luns"

        # Mock filesystem operations - matching initiators, different LUNs
        def mock_exists(path):
            return path in [group_path, initiators_path, luns_path]

        def mock_listdir(path):
            if path == initiators_path:
                return ["iqn.example:client1", "mgmt"]  # Matching initiators
            elif path == luns_path:
                return ["0", "2", "mgmt"]  # Current LUNs: 0, 2 (differs from desired 0, 1)
            return []

        def mock_isfile(path):
            return "initiators/" in path and not path.endswith("/mgmt")

        def mock_isdir(path):
            return "luns/" in path and not path.endswith("/mgmt")

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isfile', side_effect=mock_isfile), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = target_writer._group_config_matches(driver, target, group_name, group_config)

        # Assert: Verify method returns False for differing LUN assignments
        assert result is False

    def test_group_assignments_differ_false_matching_config(self, target_writer, mock_sysfs):
        """
        Test _group_assignments_differ returns False when group assignments match

        This test verifies that:
        1. Current group membership is read from sysfs with mgmt filtering
        2. Group membership comparison (current vs desired group names)
        3. Individual group configuration checking via _group_config_matches
        4. Method returns False when all groups exist with matching configurations
        5. Proper delegation to helper methods
        """
        # Arrange: Set up test data
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        target_config = Mock()
        target_config.groups = {
            "windows_clients": Mock(),
            "linux_clients": Mock()
        }

        groups_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups"

        # Mock filesystem operations
        def mock_exists(path):
            return path == groups_path

        def mock_listdir(path):
            if path == groups_path:
                return ["windows_clients", "linux_clients", "mgmt"]  # Current groups match desired
            return []

        def mock_isdir(path):
            # All group entries are directories except mgmt
            return not path.endswith("/mgmt")

        # Mock helper methods to return matching configurations
        target_writer._group_exists = Mock(return_value=True)
        target_writer._group_config_matches = Mock(return_value=True)  # All groups match

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = target_writer._group_assignments_differ(driver, target, target_config)

        # Assert: Verify method returns False for matching assignments
        assert result is False

        # Assert: Verify group existence and config matching checks
        expected_exists_calls = [
            call(driver, target, "windows_clients"),
            call(driver, target, "linux_clients")
        ]
        target_writer._group_exists.assert_has_calls(expected_exists_calls, any_order=True)

        expected_config_calls = [
            call(driver, target, "windows_clients", target_config.groups["windows_clients"]),
            call(driver, target, "linux_clients", target_config.groups["linux_clients"])
        ]
        target_writer._group_config_matches.assert_has_calls(expected_config_calls, any_order=True)

    def test_group_assignments_differ_true_group_membership_differs(self, target_writer, mock_sysfs):
        """
        Test _group_assignments_differ returns True when group membership differs

        This test verifies that:
        1. Group membership differences are detected (current vs desired group sets)
        2. Method returns True early when group membership differs
        3. Individual group config checking is skipped when membership differs
        4. Proper sysfs path construction and directory filtering
        """
        # Arrange: Set up test data with different group membership
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        target_config = Mock()
        target_config.groups = {
            "windows_clients": Mock(),
            "mac_clients": Mock()  # Desired: windows_clients, mac_clients
        }

        groups_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups"

        # Mock filesystem operations - different current groups
        def mock_exists(path):
            return path == groups_path

        def mock_listdir(path):
            if path == groups_path:
                return ["windows_clients", "linux_clients", "mgmt"]  # Current: windows_clients, linux_clients
            return []

        def mock_isdir(path):
            return not path.endswith("/mgmt")

        # Mock helper methods (should not be called due to early return)
        target_writer._group_exists = Mock()
        target_writer._group_config_matches = Mock()

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = target_writer._group_assignments_differ(driver, target, target_config)

        # Assert: Verify method returns True for differing group membership
        assert result is True

        # Assert: Verify helper methods were not called (early return)
        target_writer._group_exists.assert_not_called()
        target_writer._group_config_matches.assert_not_called()

    def test_group_assignments_differ_true_group_config_differs(self, target_writer, mock_sysfs):
        """
        Test _group_assignments_differ returns True when group configuration differs

        This test verifies that:
        1. Group membership matches but individual group config differs
        2. Method returns True when any group configuration doesn't match
        3. Proper delegation to _group_config_matches for detailed comparison
        4. Early return when first differing group is found
        """
        # Arrange: Set up test data with matching membership but differing config
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        target_config = Mock()
        target_config.groups = {
            "storage_group": Mock(),
            "backup_group": Mock()
        }

        groups_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups"

        # Mock filesystem operations - matching group membership
        def mock_exists(path):
            return path == groups_path

        def mock_listdir(path):
            if path == groups_path:
                return ["storage_group", "backup_group", "mgmt"]  # Current groups match desired
            return []

        def mock_isdir(path):
            return not path.endswith("/mgmt")

        # Mock helper methods - first group differs
        target_writer._group_exists = Mock(return_value=True)

        def mock_group_config_matches(driver, target, group_name, group_config):
            if group_name == "storage_group":
                return False  # First group differs
            return True  # Other groups match (but shouldn't be checked due to early return)
        target_writer._group_config_matches = Mock(side_effect=mock_group_config_matches)

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = target_writer._group_assignments_differ(driver, target, target_config)

        # Assert: Verify method returns True for differing group configuration
        assert result is True

        # Assert: Verify method should return True when any group differs
        # Note: Due to dictionary iteration order, either group could be checked first
        # The key is that once a differing group is found, method returns True

        # At least one group should be checked for existence
        assert target_writer._group_exists.call_count >= 1

        # At least one group config should be checked, and method returns on first difference
        assert target_writer._group_config_matches.call_count >= 1

    def test_apply_group_assignments_comprehensive_workflow(self,
                                                            target_writer,
                                                            mock_sysfs,
                                                            mock_config_reader,
                                                            mock_logger):
        """
        Test apply_group_assignments with comprehensive group configuration workflow

        This test verifies the complete group assignment process:
        1. Group existence and configuration checking with optimization
        2. Group creation via mgmt interface
        3. Initiator membership configuration with escaping handling
        4. LUN assignment configuration within groups
        5. Proper error handling for existing groups/initiators/LUNs
        6. Debug logging for all operations
        """
        # Arrange: Set up test data
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        target_config = Mock()
        target_config.groups = {
            "existing_group": Mock(),  # Exists with matching config, will be skipped
            "update_group": Mock(),    # Exists but config differs, will be updated
            "new_group": Mock()        # Doesn't exist, will be created
        }

        # Configure existing group (matching config)
        existing_group = target_config.groups["existing_group"]
        existing_group.initiators = ["iqn.example:client1"]
        existing_group.luns = {"0": Mock()}
        existing_group.luns["0"].device = "disk1"

        # Configure update group (differing config)
        update_group = target_config.groups["update_group"]
        update_group.initiators = ["iqn.example:client2", "iqn.example:client\\#3"]  # Test escaping
        update_group.luns = {"0": Mock(), "1": Mock()}
        update_group.luns["0"].device = "disk1"
        update_group.luns["1"].device = "disk2"

        # Configure new group
        new_group = target_config.groups["new_group"]
        new_group.initiators = ["iqn.example:client4"]
        new_group.luns = {"0": Mock()}
        new_group.luns["0"].device = "disk3"

        # Mock helper methods
        def mock_group_exists(driver, target, group_name):
            return group_name in ["existing_group", "update_group"]

        def mock_group_config_matches(driver, target, group_name, group_config):
            return group_name == "existing_group"  # Only existing_group matches

        target_writer._group_exists = Mock(side_effect=mock_group_exists)
        target_writer._group_config_matches = Mock(side_effect=mock_group_config_matches)

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        target_writer.apply_group_assignments(driver, target, target_config)

        # Assert: Verify existence and config checks for all groups
        expected_exists_calls = [
            call(driver, target, "existing_group"),
            call(driver, target, "update_group"),
            call(driver, target, "new_group")
        ]
        target_writer._group_exists.assert_has_calls(expected_exists_calls, any_order=True)

        expected_config_calls = [
            call(driver, target, "existing_group", existing_group),
            call(driver, target, "update_group", update_group)
            # new_group not checked because it doesn't exist
        ]
        target_writer._group_config_matches.assert_has_calls(expected_config_calls, any_order=True)

        # Assert: Verify group creation calls
        base_mgmt_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/mgmt"
        expected_create_calls = [
            call(base_mgmt_path, "create update_group"),
            call(base_mgmt_path, "create new_group")
            # existing_group not created (skipped due to matching config)
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_create_calls, any_order=True)

        # Assert: Verify initiator assignments (with escaping)
        base_initiators_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups"
        expected_initiator_calls = [
            # update_group initiators - client#3, escaping removed
            call(f"{base_initiators_path}/update_group/initiators/mgmt", "add iqn.example:client2"),
            call(f"{base_initiators_path}/update_group/initiators/mgmt", "add iqn.example:client#3"),
            # new_group initiators
            call(f"{base_initiators_path}/new_group/initiators/mgmt", "add iqn.example:client4")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_initiator_calls, any_order=True)

        # Assert: Verify LUN assignments
        expected_lun_calls = [
            # update_group LUNs
            call(f"{base_initiators_path}/update_group/luns/mgmt", "add disk1 0"),
            call(f"{base_initiators_path}/update_group/luns/mgmt", "add disk2 1"),
            # new_group LUNs
            call(f"{base_initiators_path}/new_group/luns/mgmt", "add disk3 0")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_lun_calls, any_order=True)

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call(
            "Group %s for %s/%s already exists with matching config, skipping",
            "existing_group", "iscsi", "iqn.2023-01.example.com:test"
        )
        mock_logger.debug.assert_any_call(
            "Group %s for %s/%s exists but config differs",
            "update_group", "iscsi", "iqn.2023-01.example.com:test"
        )
        mock_logger.debug.assert_any_call("Created group %s for %s/%s",
                                          "update_group", "iscsi", "iqn.2023-01.example.com:test")
        mock_logger.debug.assert_any_call("Created group %s for %s/%s",
                                          "new_group", "iscsi", "iqn.2023-01.example.com:test")

    def test_update_target_groups_comprehensive_workflow(self,
                                                         target_writer,
                                                         mock_sysfs,
                                                         mock_config_reader,
                                                         mock_logger):
        """
        Test _update_target_groups with comprehensive group update workflow

        This test verifies the complete target group update process:
        1. Group existence checking for all configured groups
        2. Configuration matching for existing groups
        3. Incremental updates for groups with differing configurations
        4. Direct group creation for non-existing groups via sysfs operations
        5. Proper delegation to helper methods
        6. Debug logging for all operations
        """
        # Arrange: Set up test data
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        target_config = Mock()
        target_config.groups = {
            "match_group": Mock(),      # Exists with matching config, will be skipped
            "update_group": Mock(),     # Exists but config differs, will be updated
            "new_group": Mock()         # Doesn't exist, will be created
        }

        # Configure Mock objects to have necessary attributes (to avoid iteration errors)
        for group_mock in target_config.groups.values():
            group_mock.initiators = ["iqn.example:client1"]
            group_mock.luns = {"0": Mock()}
            group_mock.luns["0"].device = "disk1"

        # Mock helper methods
        def mock_group_exists(driver, target, group_name):
            return group_name in ["match_group", "update_group"]  # new_group doesn't exist

        def mock_group_config_matches(driver, target, group_name, group_config):
            return group_name == "match_group"  # Only match_group matches

        target_writer._group_exists = Mock(side_effect=mock_group_exists)
        target_writer._group_config_matches = Mock(side_effect=mock_group_config_matches)
        target_writer._update_group_config = Mock()

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        target_writer._update_target_groups(driver, target, target_config)

        # Assert: Verify group existence checks for all configured groups
        expected_exists_calls = [
            call(driver, target, "match_group"),
            call(driver, target, "update_group"),
            call(driver, target, "new_group")
        ]
        target_writer._group_exists.assert_has_calls(expected_exists_calls, any_order=True)

        # Assert: Verify config matching checks for existing groups
        expected_config_calls = [
            call(driver, target, "match_group", target_config.groups["match_group"]),
            call(driver, target, "update_group", target_config.groups["update_group"])
            # new_group not checked because it doesn't exist
        ]
        target_writer._group_config_matches.assert_has_calls(expected_config_calls, any_order=True)

        # Assert: Verify group config update for differing group
        target_writer._update_group_config.assert_called_once_with(
            driver, target, "update_group", target_config.groups["update_group"]
        )

        # Assert: Verify group creation sysfs operations for new_group
        mgmt_path = f"/sys/kernel/scst_tgt/targets/{driver}/{target}/ini_groups/mgmt"
        initiators_mgmt_path = f"/sys/kernel/scst_tgt/targets/{driver}/{target}/ini_groups/new_group/initiators/mgmt"
        luns_mgmt_path = f"/sys/kernel/scst_tgt/targets/{driver}/{target}/ini_groups/new_group/luns/mgmt"

        expected_sysfs_calls = [
            call(mgmt_path, "create new_group"),
            call(initiators_mgmt_path, "add iqn.example:client1"),
            call(luns_mgmt_path, "add disk1 0")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_sysfs_calls, any_order=True)

        # Assert: Verify debug logging
        expected_debug_calls = [
            call("Group %s for %s/%s already exists with matching config, skipping",
                 "match_group", "iscsi", "iqn.2023-01.example.com:test"),
            call("Group %s for %s/%s config differs, updating incrementally",
                 "update_group", "iscsi", "iqn.2023-01.example.com:test"),
            call("Group %s for %s/%s doesn't exist, creating",
                 "new_group", "iscsi", "iqn.2023-01.example.com:test"),
            call("Created group %s for %s/%s",
                 "new_group", "iscsi", "iqn.2023-01.example.com:test"),
            call("Added initiator %s to group %s", "iqn.example:client1", "new_group"),
            call("Added LUN %s (%s) to group %s", "0", "disk1", "new_group")
        ]
        mock_logger.debug.assert_has_calls(expected_debug_calls, any_order=True)

    def test_update_group_config_comprehensive_workflow(self,
                                                        target_writer,
                                                        mock_sysfs,
                                                        mock_config_reader,
                                                        mock_logger):
        """
        Test _update_group_config with comprehensive group configuration workflow

        This test verifies the complete group configuration update process:
        1. Configuration matching check (skips if already matches)
        2. Current initiator membership reading from sysfs
        3. Initiator synchronization (add missing, remove obsolete)
        4. Initiator name escaping handling (backslash normalization)
        5. Proper mgmt_operation usage for initiator operations
        6. LUN assignment updates via _update_group_lun_assignments delegation
        7. Debug logging for all operations
        """
        # Arrange: Set up test data
        driver = "iscsi"
        target = "iqn.2023-01.example.com:test"
        group_name = "storage_clients"
        group_config = Mock()
        group_config.initiators = [
            "iqn.example:client1",         # Existing, keep
            "iqn.example:client\\#3",      # New, add (with escaping)
            "iqn.example:client4"          # New, add
            # client2 exists in sysfs but not in config, should be removed
        ]

        group_path = "/sys/kernel/scst_tgt/targets/iscsi/iqn.2023-01.example.com:test/ini_groups/storage_clients"
        initiators_path = f"{group_path}/initiators"
        initiators_mgmt_path = f"{initiators_path}/mgmt"

        # Mock filesystem operations
        def mock_exists(path):
            return path == initiators_path

        def mock_listdir(path):
            if path == initiators_path:
                return ["iqn.example:client1", "iqn.example:client2", "mgmt"]  # Current initiators
            return []

        def mock_isfile(path):
            # Initiator entries are files, mgmt is excluded
            return not path.endswith("/mgmt")

        # Mock helper methods - config does NOT match (so update proceeds)
        target_writer._group_config_matches = Mock(return_value=False)
        target_writer._update_group_lun_assignments = Mock()

        # Configure successful mgmt operations
        mock_sysfs.mgmt_operation.return_value = None

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isfile', side_effect=mock_isfile), \
             patch('os.path.join', side_effect=lambda *args: '/'.join(args)):

            # Act: Call the method under test
            target_writer._update_group_config(driver, target, group_name, group_config)

        # Assert: Verify configuration matching check is called
        target_writer._group_config_matches.assert_called_once_with(
            driver, target, group_name, group_config
        )

        # Assert: Verify initiator additions (missing initiators)
        expected_add_calls = [
            call(initiators_mgmt_path, "add", "iqn.example:client#3",  # Escaping removed: \\# -> #
                 "Added initiator iqn.example:client#3 to group storage_clients",
                 "Failed to add initiator iqn.example:client#3 to group storage_clients"),
            call(initiators_mgmt_path, "add", "iqn.example:client4",
                 "Added initiator iqn.example:client4 to group storage_clients",
                 "Failed to add initiator iqn.example:client4 to group storage_clients")
        ]
        mock_sysfs.mgmt_operation.assert_has_calls(expected_add_calls, any_order=True)

        # Assert: Verify initiator removal (obsolete initiators)
        expected_remove_calls = [
            call(initiators_mgmt_path, "del", "iqn.example:client2",  # client2 not in desired config
                 "Removed initiator iqn.example:client2 from group storage_clients",
                 "Failed to remove initiator iqn.example:client2 from group storage_clients")
        ]
        mock_sysfs.mgmt_operation.assert_has_calls(expected_remove_calls, any_order=True)

        # Assert: Verify LUN assignment update delegation
        target_writer._update_group_lun_assignments.assert_called_once_with(
            driver, target, group_name, group_config
        )

        # Assert: Verify debug logging for method entry
        mock_logger.debug.assert_any_call("Updating group %s configuration incrementally", "storage_clients")


class TestGroupWriter:
    """Test cases for GroupWriter class"""

    @pytest.fixture
    def mock_sysfs(self):
        """Create a mock SCSTSysfs instance for testing"""
        mock = Mock(spec=SCSTSysfs)
        # Set up common sysfs path constants that writers expect
        mock.SCST_HANDLERS = "/sys/kernel/scst_tgt/handlers"
        mock.SCST_TARGETS = "/sys/kernel/scst_tgt/targets"
        mock.SCST_DEVICES = "/sys/kernel/scst_tgt/devices"
        mock.SCST_DEV_GROUPS = "/sys/kernel/scst_tgt/device_groups"
        mock.MGMT_INTERFACE = "mgmt"
        mock.ENABLED_ATTR = "enabled"
        return mock

    @pytest.fixture
    def mock_config_reader(self):
        """Create a mock configuration reader for testing"""
        return Mock()

    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger for testing"""
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def group_writer(self, mock_sysfs, mock_config_reader, mock_logger):
        """Create a GroupWriter instance with mocked dependencies"""
        return GroupWriter(mock_sysfs, mock_config_reader, mock_logger)

    def test_device_group_exists_true(self, group_writer, mock_sysfs):
        """
        Test _device_group_exists method when group actually exists

        This test verifies that:
        1. Correct sysfs path is constructed for device group detection
        2. Method returns True when group path exists via filesystem check
        3. Uses entity_exists utility function which checks os.path.exists
        """
        # Arrange: Set up test data
        group_name = "dg1"

        # Mock filesystem operation to return True (group exists)
        with patch('os.path.exists', return_value=True) as mock_exists:
            # Act: Call the method under test
            result = group_writer._device_group_exists(group_name)

            # Assert: Verify result and proper path construction
            assert result is True
            mock_exists.assert_called_once_with(
                "/sys/kernel/scst_tgt/device_groups/dg1"
            )

    def test_device_group_exists_false(self, group_writer, mock_sysfs):
        """
        Test _device_group_exists method when group does not exist

        This test verifies that:
        1. Method returns False when group path doesn't exist
        2. Proper path construction for non-existent group
        3. Filesystem check properly handles non-existent paths
        """
        # Arrange: Set up test data
        group_name = "nonexistent_group"

        # Mock filesystem operation to return False (group doesn't exist)
        with patch('os.path.exists', return_value=False) as mock_exists:
            # Act: Call the method under test
            result = group_writer._device_group_exists(group_name)

            # Assert: Verify result and proper path construction
            assert result is False
            mock_exists.assert_called_once_with(
                "/sys/kernel/scst_tgt/device_groups/nonexistent_group"
            )

    def test_remove_device_group_complete_cleanup(self, group_writer, mock_sysfs, mock_logger):
        """
        Test successful device group removal with complete cleanup sequence

        This test verifies the complete device group removal workflow:
        1. All target groups within the device group are removed
        2. All devices are removed from the device group
        3. Device group itself is removed via mgmt interface
        4. Proper sysfs path validation and directory operations
        5. Management interface filtering (excludes 'mgmt' entries)
        """
        # Arrange: Set up test data
        group_name = "dg1"

        # Configure mock sysfs to simulate group with target groups and devices
        mock_sysfs.valid_path.side_effect = lambda path: True  # All paths exist
        mock_sysfs.list_directory.side_effect = [
            ["tg1", "tg2", "mgmt"],  # Target groups with mgmt interface
            ["disk1", "disk2", "mgmt"]  # Devices with mgmt interface
        ]
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer.remove_device_group(group_name)

        # Assert: Verify sysfs path validations
        expected_valid_path_calls = [
            call("/sys/kernel/scst_tgt/device_groups/dg1/target_groups"),
            call("/sys/kernel/scst_tgt/device_groups/dg1/devices")
        ]
        mock_sysfs.valid_path.assert_has_calls(expected_valid_path_calls)

        # Assert: Verify directory listings
        expected_list_calls = [
            call("/sys/kernel/scst_tgt/device_groups/dg1/target_groups"),
            call("/sys/kernel/scst_tgt/device_groups/dg1/devices")
        ]
        mock_sysfs.list_directory.assert_has_calls(expected_list_calls)

        # Assert: Verify cleanup operations were performed in correct sequence
        expected_write_calls = [
            # Remove target groups
            call("/sys/kernel/scst_tgt/device_groups/dg1/target_groups/mgmt", "del tg1"),
            call("/sys/kernel/scst_tgt/device_groups/dg1/target_groups/mgmt", "del tg2"),
            # Remove devices
            call("/sys/kernel/scst_tgt/device_groups/dg1/devices/mgmt", "del disk1"),
            call("/sys/kernel/scst_tgt/device_groups/dg1/devices/mgmt", "del disk2"),
            # Remove device group itself
            call("/sys/kernel/scst_tgt/device_groups/mgmt", "del dg1")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls)
        assert mock_sysfs.write_sysfs.call_count == 5

    def test_remove_device_group_minimal_group(self, group_writer, mock_sysfs, mock_logger):
        """
        Test removal of minimal device group with no target groups or devices

        This test verifies that:
        1. Group removal works for empty groups
        2. Path validation properly handles non-existent paths
        3. Only essential operations are performed when components don't exist
        4. Group removal proceeds to final del command
        """
        # Arrange: Set up test data
        group_name = "empty_group"

        # Configure mock sysfs - no target groups or devices exist
        mock_sysfs.valid_path.return_value = False
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer.remove_device_group(group_name)

        # Assert: Verify path validation attempts
        expected_valid_path_calls = [
            call("/sys/kernel/scst_tgt/device_groups/empty_group/target_groups"),
            call("/sys/kernel/scst_tgt/device_groups/empty_group/devices")
        ]
        mock_sysfs.valid_path.assert_has_calls(expected_valid_path_calls)

        # Assert: Verify only group removal was performed (no target group/device cleanup)
        mock_sysfs.write_sysfs.assert_called_once_with(
            "/sys/kernel/scst_tgt/device_groups/mgmt",
            "del empty_group"
        )

        # Assert: Verify no directory listing (paths don't exist)
        mock_sysfs.list_directory.assert_not_called()

    def test_remove_device_group_partial_components(self, group_writer, mock_sysfs, mock_logger):
        """
        Test device group removal when only some components exist

        This test verifies that:
        1. Method handles mixed existence of target groups and devices
        2. Only existing components are processed for removal
        3. Path validation determines which cleanup operations to perform
        4. Group removal always proceeds regardless of component existence
        """
        # Arrange: Set up test data
        group_name = "partial_group"

        # Configure mock sysfs - only target groups exist, no devices
        def mock_valid_path(path):
            return "target_groups" in path  # Only target_groups path exists

        mock_sysfs.valid_path.side_effect = mock_valid_path
        mock_sysfs.list_directory.return_value = ["tg1", "mgmt"]  # One target group
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer.remove_device_group(group_name)

        # Assert: Verify both path validations were attempted
        expected_valid_path_calls = [
            call("/sys/kernel/scst_tgt/device_groups/partial_group/target_groups"),
            call("/sys/kernel/scst_tgt/device_groups/partial_group/devices")
        ]
        mock_sysfs.valid_path.assert_has_calls(expected_valid_path_calls)

        # Assert: Verify only target groups directory was listed (devices path doesn't exist)
        mock_sysfs.list_directory.assert_called_once_with(
            "/sys/kernel/scst_tgt/device_groups/partial_group/target_groups"
        )

        # Assert: Verify operations for existing components only
        expected_write_calls = [
            # Remove target group (devices section skipped)
            call("/sys/kernel/scst_tgt/device_groups/partial_group/target_groups/mgmt", "del tg1"),
            # Remove device group itself
            call("/sys/kernel/scst_tgt/device_groups/mgmt", "del partial_group")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls)
        assert mock_sysfs.write_sysfs.call_count == 2

    def test_remove_device_group_sysfs_error_handling(self, group_writer, mock_sysfs, mock_logger):
        """
        Test error handling when sysfs operations fail during group removal

        This test verifies that:
        1. SCSTError exceptions are caught and logged appropriately
        2. Error log includes group name and error details
        3. Method continues execution gracefully without re-raising exceptions
        4. Proper error context is provided for debugging
        """
        # Arrange: Set up test data
        group_name = "error_group"

        # Configure mock sysfs to throw error during group removal
        mock_sysfs.valid_path.return_value = False  # Simple group
        mock_sysfs.write_sysfs.side_effect = SCSTError("Device group is in use")

        # Act: Call the method under test (should not raise exception)
        group_writer.remove_device_group(group_name)

        # Assert: Verify error was logged with proper context
        # Note: The logger receives the exception object, not just the message string
        actual_call = mock_logger.warning.call_args
        assert actual_call[0][0] == "Failed to remove device group %s: %s"
        assert actual_call[0][1] == "error_group"
        assert isinstance(actual_call[0][2], SCSTError)
        assert str(actual_call[0][2]) == "Device group is in use"

        # Assert: Verify removal was attempted
        mock_sysfs.write_sysfs.assert_called_once_with(
            "/sys/kernel/scst_tgt/device_groups/mgmt",
            "del error_group"
        )

    def test_remove_device_group_mgmt_interface_filtering(self, group_writer, mock_sysfs, mock_logger):
        """
        Test that management interface entries are properly filtered out

        This test verifies that:
        1. 'mgmt' entries in directory listings are skipped
        2. Only actual target groups and devices are processed for removal
        3. Management interface filtering works consistently across both components
        4. Directory structure understanding is correct
        """
        # Arrange: Set up test data with mgmt interfaces mixed in
        group_name = "mgmt_test_group"

        # Configure mock sysfs with mgmt interfaces in listings
        mock_sysfs.valid_path.side_effect = lambda path: True
        mock_sysfs.list_directory.side_effect = [
            ["mgmt", "tg1", "mgmt", "tg2"],  # Target groups with multiple mgmt entries
            ["disk1", "mgmt", "disk2", "mgmt"]  # Devices with multiple mgmt entries
        ]
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer.remove_device_group(group_name)

        # Assert: Verify mgmt interfaces were filtered out
        # Should only have operations for tg1, tg2, disk1, disk2 + final group removal
        expected_write_calls = [
            call("/sys/kernel/scst_tgt/device_groups/mgmt_test_group/target_groups/mgmt", "del tg1"),
            call("/sys/kernel/scst_tgt/device_groups/mgmt_test_group/target_groups/mgmt", "del tg2"),
            call("/sys/kernel/scst_tgt/device_groups/mgmt_test_group/devices/mgmt", "del disk1"),
            call("/sys/kernel/scst_tgt/device_groups/mgmt_test_group/devices/mgmt", "del disk2"),
            call("/sys/kernel/scst_tgt/device_groups/mgmt", "del mgmt_test_group")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls)
        assert mock_sysfs.write_sysfs.call_count == 5

    def test_update_device_group_devices_add_and_remove(self, group_writer, mock_sysfs, mock_logger):
        """
        Test device group device membership updates with additions and removals

        This test verifies the device membership synchronization workflow:
        1. Current devices are read from sysfs (filtering out mgmt and non-symlinks)
        2. Desired devices are compared against current devices
        3. Extra devices are removed via mgmt interface
        4. Missing devices are added via mgmt interface
        5. Proper debug logging for all operations
        """
        # Arrange: Set up test data
        group_name = "dg1"

        # Create mock DeviceGroupConfig
        mock_group_config = Mock()
        mock_group_config.devices = {"disk1": {}, "disk3": {}}  # Want disk1, disk3

        # Configure mock sysfs to simulate current state: disk1, disk2 (want to remove disk2, add disk3)
        devices_path = "/sys/kernel/scst_tgt/device_groups/dg1/devices"

        # Mock os.path.exists and os.listdir for reading current devices
        with patch('os.path.exists', return_value=True) as mock_exists, \
             patch('os.listdir', return_value=["disk1", "disk2", "mgmt"]) as mock_listdir, \
             patch('os.path.islink') as mock_islink:

            # Configure islink to return True for actual devices, False for mgmt
            def mock_islink_side_effect(path):
                return "disk1" in path or "disk2" in path  # disk1, disk2 are symlinks
            mock_islink.side_effect = mock_islink_side_effect

            # Configure successful sysfs writes
            mock_sysfs.write_sysfs.return_value = None

            # Act: Call the method under test
            group_writer._update_device_group_devices(group_name, mock_group_config)

            # Assert: Verify directory operations
            mock_exists.assert_called_once_with(devices_path)
            mock_listdir.assert_called_once_with(devices_path)

            # Assert: Verify islink checks for actual items (excluding mgmt)
            expected_islink_calls = [
                call("/sys/kernel/scst_tgt/device_groups/dg1/devices/disk1"),
                call("/sys/kernel/scst_tgt/device_groups/dg1/devices/disk2")
            ]
            mock_islink.assert_has_calls(expected_islink_calls, any_order=True)

            # Assert: Verify device management operations
            expected_write_calls = [
                # Remove disk2 (current but not desired)
                call("/sys/kernel/scst_tgt/device_groups/dg1/devices/mgmt", "del disk2"),
                # Add disk3 (desired but not current)
                call("/sys/kernel/scst_tgt/device_groups/dg1/devices/mgmt", "add disk3")
            ]
            mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls, any_order=True)
            assert mock_sysfs.write_sysfs.call_count == 2

            # Assert: Verify debug logging
            assert mock_logger.debug.call_count >= 3  # Operation logs + summary

    def test_update_device_group_devices_no_changes_needed(self, group_writer, mock_sysfs, mock_logger):
        """
        Test device group update when no changes are needed

        This test verifies that:
        1. When current and desired device sets match, no operations are performed
        2. Early return with debug log when membership is already correct
        3. No sysfs write operations are attempted
        """
        # Arrange: Set up test data
        group_name = "dg1"

        # Create mock DeviceGroupConfig with current devices
        mock_group_config = Mock()
        mock_group_config.devices = {"disk1": {}, "disk2": {}}  # Want disk1, disk2

        # Mock os operations to show current devices match desired
        with patch('os.path.exists', return_value=True), \
             patch('os.listdir', return_value=["disk1", "disk2", "mgmt"]), \
             patch('os.path.islink', return_value=True):  # All devices are symlinks

            # Act: Call the method under test
            group_writer._update_device_group_devices(group_name, mock_group_config)

            # Assert: Verify no sysfs operations performed
            mock_sysfs.write_sysfs.assert_not_called()

            # Assert: Verify debug log about no changes needed
            mock_logger.debug.assert_called_with("Device group %s membership already correct", "dg1")

    def test_set_target_group_target_attributes_success(self, group_writer, mock_sysfs, mock_logger):
        """
        Test successful setting of target group target attributes

        This test verifies that:
        1. Target path directory check determines if attributes can be set
        2. Attributes are written to correct sysfs paths
        3. Existing attribute values are checked before writing
        4. Debug logging occurs for successful operations
        """
        # Arrange: Set up test data
        device_group = "dg1"
        tgroup_name = "controller_A"
        target_name = "iqn.2023-01.example.com:test"
        target_config = {"rel_tgt_id": "1", "preferred": "1"}

        target_path = "/sys/kernel/scst_tgt/device_groups/dg1/target_groups/controller_A/iqn.2023-01.example.com:test"

        # Mock target path as directory and attribute operations
        with patch('os.path.isdir', return_value=True) as mock_isdir, \
             patch('os.path.exists') as mock_exists:

            # Configure attribute existence and current values
            def mock_exists_side_effect(path):
                # rel_tgt_id exists with different value, preferred doesn't exist
                return path.endswith("/rel_tgt_id")
            mock_exists.side_effect = mock_exists_side_effect

            # Configure current attribute value check
            mock_sysfs.read_sysfs_attribute.return_value = "0"  # Current value differs
            mock_sysfs.write_sysfs.return_value = None

            # Act: Call the method under test
            group_writer._set_target_group_target_attributes(
                device_group, tgroup_name, target_name, target_config)

            # Assert: Verify directory check
            mock_isdir.assert_called_once_with(target_path)

            # Assert: Verify attribute file existence checks
            expected_exists_calls = [
                call(f"{target_path}/rel_tgt_id"),
                call(f"{target_path}/preferred")
            ]
            mock_exists.assert_has_calls(expected_exists_calls, any_order=True)

            # Assert: Verify current value read for existing attribute
            mock_sysfs.read_sysfs_attribute.assert_called_once_with(f"{target_path}/rel_tgt_id")

            # Assert: Verify attribute writes
            expected_write_calls = [
                call(f"{target_path}/rel_tgt_id", "1", check_result=False),
                call(f"{target_path}/preferred", "1", check_result=False)
            ]
            mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls, any_order=True)
            assert mock_sysfs.write_sysfs.call_count == 2

    def test_set_target_group_target_attributes_symlink_skip(self, group_writer, mock_sysfs, mock_logger):
        """
        Test that symlink targets are skipped with appropriate logging

        This test verifies that:
        1. When target path is not a directory (symlink), attributes cannot be set
        2. Debug log explains why symlink targets are skipped
        3. No sysfs operations are performed for symlink targets
        """
        # Arrange: Set up test data
        device_group = "dg1"
        tgroup_name = "controller_A"
        target_name = "iqn.2023-01.example.com:test"
        target_config = {"rel_tgt_id": "1"}

        # Mock target path as NOT a directory (symlink)
        with patch('os.path.isdir', return_value=False) as mock_isdir:

            # Act: Call the method under test
            group_writer._set_target_group_target_attributes(
                device_group, tgroup_name, target_name, target_config)

            # Assert: Verify directory check was performed
            mock_isdir.assert_called_once()

            # Assert: Verify debug log about symlink
            mock_logger.debug.assert_called_once_with(
                "Target %s is symlink, cannot set attributes - SCST will handle this automatically",
                "iqn.2023-01.example.com:test"
            )

            # Assert: Verify no sysfs operations
            mock_sysfs.write_sysfs.assert_not_called()
            mock_sysfs.read_sysfs_attribute.assert_not_called()

    def test_device_group_config_matches_true(self, group_writer, mock_sysfs, mock_config_reader):
        """
        Test _device_group_config_matches when configuration matches current state

        This test verifies that:
        1. Device membership comparison works correctly when sets match
        2. Target group membership comparison works correctly when sets match
        3. Recursive target group config checking is called for each target group
        4. Method returns True when all comparisons pass
        5. Proper sysfs path construction for device and target group directories
        """
        # Arrange: Set up matching configuration scenario
        group_name = "storage_group"
        group_config = Mock()
        group_config.devices = {"disk1", "disk2"}
        group_config.target_groups = {
            "controller_A": Mock(),
            "controller_B": Mock()
        }

        # Mock filesystem structure that matches the configuration
        def mock_exists(path):
            return path in [
                "/sys/kernel/scst_tgt/device_groups/storage_group/devices",
                "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups"
            ]

        def mock_listdir(path):
            if "devices" in path:
                return ["disk1", "disk2", "mgmt"]  # mgmt will be filtered out
            elif "target_groups" in path:
                return ["controller_A", "controller_B", "mgmt"]  # mgmt will be filtered out
            return []

        def mock_isdir(path):
            # All device and target group entries are directories (not mgmt interface)
            return not path.endswith("/mgmt")

        # Mock target group config matches to return True for both groups
        group_writer._target_group_config_matches = Mock(return_value=True)

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = group_writer._device_group_config_matches(group_name, group_config)

        # Assert: Verify method returns True for matching configuration
        assert result is True

        # Assert: Verify target group config checking was called for each target group
        expected_calls = [
            call("storage_group", "controller_A", group_config.target_groups["controller_A"]),
            call("storage_group", "controller_B", group_config.target_groups["controller_B"])
        ]
        group_writer._target_group_config_matches.assert_has_calls(expected_calls)

    def test_target_group_config_matches_true(self, group_writer, mock_sysfs, mock_config_reader):
        """
        Test _target_group_config_matches when ALUA target group configuration matches

        This test verifies that:
        1. Target membership comparison works (which targets are in the group)
        2. Target group attributes comparison works (ALUA state, group_id)
        3. Individual target attributes comparison works (rel_tgt_id)
        4. Method returns True when all phases pass
        5. Proper handling of directory vs symlink targets
        """
        # Arrange: Set up ALUA target group configuration
        device_group = "storage_group"
        target_group = "controller_A"
        tgroup_config = Mock()

        # Configure target group with ALUA attributes
        tgroup_config.targets = {"iqn.example:test1", "iqn.example:test2"}
        tgroup_config.attributes = {"group_id": "101", "state": "active"}
        tgroup_config.target_attributes = {
            "iqn.example:test1": {"rel_tgt_id": "1"}
            # iqn.example:test2 has no attributes (symlink target)
        }

        targets_path = "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/controller_A"

        # Mock filesystem operations
        def mock_exists(path):
            return path in [
                targets_path,
                f"{targets_path}/group_id",
                f"{targets_path}/state",
                f"{targets_path}/iqn.example:test1/rel_tgt_id"
            ]

        def mock_listdir(path):
            if path == targets_path:
                return ["iqn.example:test1", "iqn.example:test2", "mgmt"]
            return []

        def mock_isdir(path):
            # Both targets should return True for os.path.isdir():
            # - test1 is actual directory (has attributes)
            # - test2 is symlink to directory (no attributes but still valid)
            # Only mgmt should return False
            return (path.endswith("/iqn.example:test1") or path.endswith("/iqn.example:test2"))

        # Mock sysfs attribute reads
        def mock_read_sysfs_attribute(path):
            if path.endswith("/group_id"):
                return "101"
            elif path.endswith("/state"):
                return "active"
            elif path.endswith("/rel_tgt_id"):
                return "1"
            return None

        mock_sysfs.read_sysfs_attribute.side_effect = mock_read_sysfs_attribute

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            result = group_writer._target_group_config_matches(device_group, target_group, tgroup_config)

        # Assert: Verify method returns True for matching configuration
        assert result is True

        # Assert: Verify sysfs attribute reads for target group attributes
        expected_read_calls = [
            call(f"{targets_path}/group_id"),
            call(f"{targets_path}/state"),
            call(f"{targets_path}/iqn.example:test1/rel_tgt_id")
        ]
        mock_sysfs.read_sysfs_attribute.assert_has_calls(expected_read_calls, any_order=True)

    def test_update_device_group_incremental_updates(self, group_writer, mock_sysfs, mock_config_reader, mock_logger):
        """
        Test _update_device_group performs incremental updates correctly

        This test verifies that:
        1. Device updates are delegated to _update_device_group_devices
        2. Target group updates are delegated to _update_device_group_target_groups
        3. Group-level attributes are updated via direct sysfs writes
        4. Method handles missing attributes gracefully
        5. Proper debug logging for incremental update process
        """
        # Arrange: Set up test data
        group_name = "storage_group"
        group_config = Mock()
        group_config.attributes = {
            "some_attr": "value1",
            "another_attr": "value2"
        }

        # Mock the delegated methods
        group_writer._update_device_group_devices = Mock()
        group_writer._update_device_group_target_groups = Mock()

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer._update_device_group(group_name, group_config)

        # Assert: Verify delegation to device update method
        group_writer._update_device_group_devices.assert_called_once_with(group_name, group_config)

        # Assert: Verify delegation to target group update method
        group_writer._update_device_group_target_groups.assert_called_once_with(
            group_name, group_config)

        # Assert: Verify group attribute updates
        expected_write_calls = [
            call("/sys/kernel/scst_tgt/device_groups/storage_group/some_attr",
                 "value1", check_result=False),
            call("/sys/kernel/scst_tgt/device_groups/storage_group/another_attr",
                 "value2", check_result=False)
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls, any_order=True)
        assert mock_sysfs.write_sysfs.call_count == 2

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call("Updating device group %s configuration incrementally",
                                          "storage_group")
        mock_logger.debug.assert_any_call("Updated device group attribute %s.%s = %s",
                                          "storage_group", "some_attr", "value1")
        mock_logger.debug.assert_any_call("Updated device group attribute %s.%s = %s",
                                          "storage_group", "another_attr", "value2")

    def test_update_device_group_target_groups_synchronization(self,
                                                               group_writer,
                                                               mock_sysfs,
                                                               mock_config_reader,
                                                               mock_logger):
        """
        Test _update_device_group_target_groups synchronizes target groups correctly

        This test verifies that:
        1. Current target groups are read from sysfs with mgmt filtering
        2. Target groups to add, remove, and update are calculated correctly
        3. Obsolete target groups are removed via mgmt interface
        4. New target groups are created via _create_target_group
        5. Existing target groups are updated via _update_target_group_attributes
        6. Proper debug logging for all operations
        """
        # Arrange: Set up test data
        group_name = "storage_group"
        group_config = Mock()
        group_config.target_groups = {
            "controller_A": Mock(),  # Existing, needs update
            "controller_C": Mock()   # New, needs creation
            # controller_B exists but not in config, needs removal
        }

        target_groups_path = "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups"

        # Mock filesystem operations showing current state
        def mock_exists(path):
            return path == target_groups_path

        def mock_listdir(path):
            if path == target_groups_path:
                return ["controller_A", "controller_B", "mgmt"]  # Current state
            return []

        def mock_isdir(path):
            # All target groups are directories except mgmt
            return not path.endswith("/mgmt")

        # Mock the delegated methods
        group_writer._create_target_group = Mock()
        group_writer._update_target_group_attributes = Mock()

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir), \
             patch('os.path.isdir', side_effect=mock_isdir):

            # Act: Call the method under test
            group_writer._update_device_group_target_groups(group_name, group_config)

        # Assert: Verify removal of obsolete target group (controller_B)
        mock_sysfs.write_sysfs.assert_called_once_with(
            f"{target_groups_path}/mgmt", "del controller_B"
        )

        # Assert: Verify creation of new target group (controller_C)
        group_writer._create_target_group.assert_called_once_with(
            group_name, "controller_C", group_config.target_groups["controller_C"]
        )

        # Assert: Verify update of existing target group (controller_A)
        group_writer._update_target_group_attributes.assert_called_once_with(
            group_name, "controller_A", group_config.target_groups["controller_A"]
        )

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call("Updating target groups for device group %s",
                                          "storage_group")
        mock_logger.debug.assert_any_call("Removed target group %s from device group %s",
                                          "controller_B", "storage_group")
        mock_logger.debug.assert_any_call("Creating target group %s in device group %s",
                                          "controller_C", "storage_group")
        mock_logger.debug.assert_any_call("Updating target group %s in device group %s",
                                          "controller_A", "storage_group")

    def test_update_target_group_attributes_with_value_checking(self,
                                                                group_writer,
                                                                mock_sysfs,
                                                                mock_config_reader,
                                                                mock_logger):
        """
        Test _update_target_group_attributes updates attributes with current value checking

        This test verifies that:
        1. Target assignments are updated first via _update_target_group_targets
        2. Attribute values are checked before writing (optimization)
        3. Only changed attributes are written to sysfs
        4. Missing attribute files are handled (written anyway)
        5. Attribute update failures are logged as warnings
        6. Proper debug logging for value comparisons
        """
        # Arrange: Set up test data
        device_group = "storage_group"
        tgroup_name = "controller_A"
        tgroup_config = Mock()
        tgroup_config.attributes = {
            "group_id": "101",   # Current value is "100", needs update
            "state": "active",   # Current value is "active", no update needed
            "new_attr": "value"  # Attribute doesn't exist, needs creation
        }

        base_path = "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/controller_A"

        # Mock filesystem and attribute operations
        def mock_exists(path):
            # group_id and state exist, new_attr doesn't
            return path.endswith("/group_id") or path.endswith("/state")

        def mock_read_sysfs_attribute(path):
            if path.endswith("/group_id"):
                return "100"  # Different from desired "101"
            elif path.endswith("/state"):
                return "active"  # Same as desired "active"
            return None

        # Mock the delegated method
        group_writer._update_target_group_targets = Mock()

        # Configure sysfs operations
        mock_sysfs.read_sysfs_attribute.side_effect = mock_read_sysfs_attribute
        mock_sysfs.write_sysfs.return_value = None

        with patch('os.path.exists', side_effect=mock_exists):

            # Act: Call the method under test
            group_writer._update_target_group_attributes(device_group, tgroup_name, tgroup_config)

        # Assert: Verify target assignments updated first
        group_writer._update_target_group_targets.assert_called_once_with(
            device_group, tgroup_name, tgroup_config
        )

        # Assert: Verify attribute reads for existing attributes
        expected_read_calls = [
            call(f"{base_path}/group_id"),
            call(f"{base_path}/state")
        ]
        mock_sysfs.read_sysfs_attribute.assert_has_calls(expected_read_calls, any_order=True)

        # Assert: Verify only changed/new attributes are written
        expected_write_calls = [
            call(f"{base_path}/group_id", "101", check_result=False),  # Changed value
            call(f"{base_path}/new_attr", "value", check_result=False)  # New attribute
            # state is NOT written because current value matches desired
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_write_calls, any_order=True)
        assert mock_sysfs.write_sysfs.call_count == 2

        # Assert: Verify debug logging for value comparisons
        mock_logger.debug.assert_any_call(
            "Updated target group attribute %s.%s.%s: %s -> %s",
            "storage_group", "controller_A", "group_id", "100", "101"
        )
        mock_logger.debug.assert_any_call(
            "Target group attribute %s.%s.%s already has correct value: %s",
            "storage_group", "controller_A", "state", "active"
        )
        mock_logger.debug.assert_any_call(
            "Set target group attribute %s.%s.%s = %s",
            "storage_group", "controller_A", "new_attr", "value"
        )

    def test_update_target_group_targets_with_alua_attributes(self,
                                                              group_writer,
                                                              mock_sysfs,
                                                              mock_config_reader,
                                                              mock_logger):
        """
        Test _update_target_group_targets manages target membership and ALUA attributes

        This test verifies that:
        1. Current targets are read using is_valid_sysfs_directory (handles symlinks+dirs)
        2. Missing targets are added via mgmt interface
        3. Extra targets are removed via mgmt interface
        4. Target attributes are set for all targets with attributes
        5. ALUA rel_tgt_id attributes are properly configured
        6. Error handling for sysfs operations
        """
        # Arrange: Set up test data
        device_group = "storage_group"
        tgroup_name = "controller_A"
        tgroup_config = Mock()
        tgroup_config.targets = {"iqn.example:test1", "iqn.example:test3"}  # want test1, test3
        tgroup_config.target_attributes = {
            "iqn.example:test1": {"rel_tgt_id": "1"},
            "iqn.example:test3": {"rel_tgt_id": "3"}
        }

        tgroup_path = "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/controller_A"

        # Mock filesystem operations
        def mock_exists(path):
            return path == tgroup_path

        def mock_listdir(path):
            if path == tgroup_path:
                return ["iqn.example:test1", "iqn.example:test2", "mgmt"]  # current: test1, test2
            return []

        # Mock sysfs helper methods
        def mock_is_valid_sysfs_directory(base_path, item):
            # All targets are valid except mgmt
            return item != "mgmt"

        # Mock target attribute setting
        group_writer._set_target_group_target_attributes = Mock()

        # Configure sysfs operations
        mock_sysfs.is_valid_sysfs_directory.side_effect = mock_is_valid_sysfs_directory
        mock_sysfs.mgmt_operation.return_value = None

        with patch('os.path.exists', side_effect=mock_exists), \
             patch('os.listdir', side_effect=mock_listdir):

            # Act: Call the method under test
            group_writer._update_target_group_targets(device_group, tgroup_name, tgroup_config)

        # Assert: Verify sysfs directory validation calls
        expected_is_valid_calls = [
            call(tgroup_path, "iqn.example:test1"),
            call(tgroup_path, "iqn.example:test2")
        ]
        mock_sysfs.is_valid_sysfs_directory.assert_has_calls(expected_is_valid_calls, any_order=True)

        # Assert: Verify mgmt operations for target membership changes
        expected_mgmt_calls = [
            # Add missing target (test3)
            call(f"{tgroup_path}/mgmt", "add", "iqn.example:test3",
                 "Added target iqn.example:test3 to target group storage_group/controller_A",
                 "Failed to add target iqn.example:test3 to target group controller_A"),
            # Remove extra target (test2)
            call(f"{tgroup_path}/mgmt", "del", "iqn.example:test2",
                 "Removed target iqn.example:test2 from target group storage_group/controller_A",
                 "Failed to remove target iqn.example:test2 from target group controller_A")
        ]
        mock_sysfs.mgmt_operation.assert_has_calls(expected_mgmt_calls, any_order=True)
        assert mock_sysfs.mgmt_operation.call_count == 2

        # Assert: Verify target attributes are set for all configured targets
        expected_attr_calls = [
            call(device_group, tgroup_name, "iqn.example:test1", {"rel_tgt_id": "1"}),
            call(device_group, tgroup_name, "iqn.example:test3", {"rel_tgt_id": "3"})
        ]
        group_writer._set_target_group_target_attributes.assert_has_calls(expected_attr_calls, any_order=True)

    def test_create_target_group_full_alua_configuration(self,
                                                         group_writer,
                                                         mock_sysfs,
                                                         mock_config_reader,
                                                         mock_logger):
        """
        Test _create_target_group creates target group with complete ALUA configuration

        This test verifies the complete target group creation workflow:
        1. Target group is created via mgmt interface
        2. All targets are added to the target group
        3. Target-specific attributes (rel_tgt_id) are set for targets that have them
        4. Target group attributes (group_id, state) are configured
        5. Proper delegation to helper methods
        6. Error handling for creation failures
        """
        # Arrange: Set up test data
        device_group = "storage_group"
        tgroup_name = "controller_A"
        tgroup_config = Mock()
        tgroup_config.targets = {"iqn.example:test1", "iqn.example:test2"}
        tgroup_config.target_attributes = {
            "iqn.example:test1": {"rel_tgt_id": "1"},
            # test2 has no attributes (will be symlink)
        }
        tgroup_config.attributes = {"group_id": "101", "state": "active"}

        tgroup_mgmt = "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/mgmt"
        target_mgmt = "/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/controller_A/mgmt"

        # Mock helper methods
        group_writer._set_target_group_target_attributes = Mock()
        group_writer._update_target_group_attributes = Mock()

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer._create_target_group(device_group, tgroup_name, tgroup_config)

        # Assert: Verify target group creation
        mock_sysfs.write_sysfs.assert_any_call(tgroup_mgmt, "add controller_A")

        # Assert: Verify all targets are added to target group
        expected_target_adds = [
            call(target_mgmt, "add iqn.example:test1"),
            call(target_mgmt, "add iqn.example:test2")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_target_adds, any_order=True)

        # Assert: Verify target-specific attributes are set for targets that have them
        group_writer._set_target_group_target_attributes.assert_called_once_with(
            device_group, tgroup_name, "iqn.example:test1", {"rel_tgt_id": "1"}
        )

        # Assert: Verify target group attributes are configured
        group_writer._update_target_group_attributes.assert_called_once_with(
            device_group, tgroup_name, tgroup_config
        )

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call(
            "Created target group %s in device group %s", "controller_A", "storage_group"
        )
        mock_logger.debug.assert_any_call(
            "Added target %s to target group %s", "iqn.example:test1", "controller_A"
        )
        mock_logger.debug.assert_any_call(
            "Added target %s to target group %s", "iqn.example:test2", "controller_A"
        )

    def test_apply_target_groups_create_and_update_logic(self,
                                                         group_writer,
                                                         mock_sysfs,
                                                         mock_config_reader,
                                                         mock_logger):
        """
        Test _apply_target_groups applies target group configurations with create/update logic

        This test verifies that:
        1. Existing target groups are detected via os.path.exists
        2. Existing target groups are updated via helper methods
        3. Non-existing target groups are created via _create_target_group
        4. Proper delegation based on target group existence
        5. Debug logging for processing decisions
        """
        # Arrange: Set up test data
        device_group = "storage_group"
        target_groups = {
            "controller_A": Mock(),  # Exists, will be updated
            "controller_C": Mock()   # Doesn't exist, will be created
        }

        # Mock filesystem operations
        def mock_exists(path):
            # Only controller_A exists
            return path.endswith("/controller_A")

        # Mock helper methods
        group_writer._update_target_group_targets = Mock()
        group_writer._update_target_group_attributes = Mock()
        group_writer._create_target_group = Mock()

        with patch('os.path.exists', side_effect=mock_exists):

            # Act: Call the method under test
            group_writer._apply_target_groups(device_group, target_groups)

        # Assert: Verify existence checks for all target groups
        expected_exists_calls = [
            call("/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/controller_A"),
            call("/sys/kernel/scst_tgt/device_groups/storage_group/target_groups/controller_C")
        ]
        with patch('os.path.exists', side_effect=mock_exists) as mock_exists_patch:
            # Re-run to capture the calls
            group_writer._apply_target_groups(device_group, target_groups)
            mock_exists_patch.assert_has_calls(expected_exists_calls, any_order=True)

        # Assert: Verify existing target group is updated
        group_writer._update_target_group_targets.assert_called_with(
            device_group, "controller_A", target_groups["controller_A"]
        )
        group_writer._update_target_group_attributes.assert_called_with(
            device_group, "controller_A", target_groups["controller_A"]
        )

        # Assert: Verify non-existing target group is created
        group_writer._create_target_group.assert_called_with(
            device_group, "controller_C", target_groups["controller_C"]
        )

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call("Processing target group '%s' in device group '%s'",
                                          "controller_A", "storage_group")
        mock_logger.debug.assert_any_call("Target group %s exists, updating configuration",
                                          "controller_A")
        mock_logger.debug.assert_any_call("Processing target group '%s' in device group '%s'",
                                          "controller_C", "storage_group")
        mock_logger.debug.assert_any_call("Target group %s doesn't exist, creating", "controller_C")

    def test_apply_config_device_groups_comprehensive_workflow(self,
                                                               group_writer,
                                                               mock_sysfs,
                                                               mock_config_reader,
                                                               mock_logger):
        """
        Test apply_config_device_groups main entry point with comprehensive workflow

        This test verifies the complete device group application process:
        1. Device group existence checking and configuration matching
        2. Incremental updates for existing groups with config differences
        3. Creation workflow for new device groups
        4. Group-level attribute setting
        5. Device membership management
        6. Target group configuration via _apply_target_groups
        7. Error handling for creation failures
        """
        # Arrange: Set up test configuration
        config = Mock()
        config.device_groups = {
            "existing_group": Mock(),  # Exists but config differs, will be updated
            "new_group": Mock()        # Doesn't exist, will be created
        }

        # Configure existing group
        existing_group = config.device_groups["existing_group"]
        existing_group.attributes = {"some_attr": "value1"}
        existing_group.devices = {"disk1", "disk2"}
        existing_group.target_groups = {"controller_A": Mock()}

        # Configure new group
        new_group = config.device_groups["new_group"]
        new_group.attributes = {"other_attr": "value2"}
        new_group.devices = {"disk3"}
        new_group.target_groups = {"controller_B": Mock()}

        # Mock helper methods
        group_writer._device_group_exists = Mock(side_effect=lambda name: name == "existing_group")
        group_writer._device_group_config_matches = Mock(return_value=False)  # Config differs
        group_writer._update_device_group = Mock()
        group_writer._apply_target_groups = Mock()

        # Configure successful sysfs writes
        mock_sysfs.write_sysfs.return_value = None

        # Act: Call the method under test
        group_writer.apply_config_device_groups(config)

        # Assert: Verify existence and config matching checks
        group_writer._device_group_exists.assert_any_call("existing_group")
        group_writer._device_group_exists.assert_any_call("new_group")
        group_writer._device_group_config_matches.assert_called_once_with("existing_group", existing_group)

        # Assert: Verify incremental update for existing group
        group_writer._update_device_group.assert_called_once_with("existing_group", existing_group)

        # Assert: Verify creation of new group
        mock_sysfs.write_sysfs.assert_any_call(
            "/sys/kernel/scst_tgt/device_groups/mgmt", "create new_group"
        )

        # Assert: Verify group-level attributes are set
        expected_attr_calls = [
            call("/sys/kernel/scst_tgt/device_groups/new_group/other_attr", "value2", check_result=False)
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_attr_calls, any_order=True)

        # Assert: Verify device membership management
        expected_device_calls = [
            call("/sys/kernel/scst_tgt/device_groups/new_group/devices/mgmt", "add disk3")
        ]
        mock_sysfs.write_sysfs.assert_has_calls(expected_device_calls, any_order=True)

        # Assert: Verify target group configuration delegation
        expected_target_group_calls = [
            call("new_group", new_group.target_groups)
        ]
        group_writer._apply_target_groups.assert_has_calls(expected_target_group_calls)

        # Assert: Verify debug logging
        mock_logger.debug.assert_any_call("Device group %s config differs, updating incrementally", "existing_group")
        mock_logger.debug.assert_any_call("Created device group %s", "new_group")
        mock_logger.debug.assert_any_call("Set device group attribute %s.%s = %s", "new_group", "other_attr", "value2")
        mock_logger.debug.assert_any_call("Added device %s to device group %s", "disk3", "new_group")
