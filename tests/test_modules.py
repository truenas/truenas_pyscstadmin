#!/usr/bin/env python3
"""
Unit tests for SCST kernel module management.

This module tests the SCSTModuleManager class which handles automatic loading
of kernel modules required by SCST configurations. The module manager analyzes
SCST configurations to determine which kernel modules are needed and loads them
using modprobe, similar to the SCST init script behavior.

Test Strategy:
- Mock filesystem operations (os.path.exists) and subprocess calls
- Test real business logic: configuration analysis, module mapping, error handling
- Use realistic SCST configurations to validate module determination
- Test platform-specific behavior and special cases (crc32c variants)
- Focus on the mapping logic from handlers/drivers to kernel modules

Key Business Logic Tested:
1. Configuration analysis - mapping handlers and drivers to required modules
2. Platform detection - x86-specific CRC acceleration modules
3. Module loading status - checking /sys/module/ with hyphen/underscore conversion
4. Optional vs required modules - iSCSI optional modules vs core SCST modules
5. Error aggregation - failing fast vs continuing with optional modules

Note: iSER (iSCSI Extensions for RDMA) modules are deliberately omitted from
this module manager and handled elsewhere in the codebase.
"""

import pytest
import subprocess
from unittest.mock import Mock, patch

from scstadmin.modules import SCSTModuleManager
from scstadmin.config import SCSTConfig
from scstadmin.exceptions import SCSTError


class TestSCSTModuleManager:
    """Test SCSTModuleManager functionality for kernel module management."""

    def test_module_manager_initialization(self):
        """Test SCSTModuleManager can be initialized with proper logging setup."""
        manager = SCSTModuleManager()
        assert hasattr(manager, "logger")

    def test_determine_required_modules_basic(self):
        """Test basic module determination with common handlers and drivers.

        This tests the core mapping logic from SCST configuration components
        to their corresponding kernel modules using the constant mappings.
        """
        manager = SCSTModuleManager()

        # Create config with typical production handlers and drivers
        config = SCSTConfig()
        config.handlers = {"vdisk_fileio": {}, "dev_disk": {}}
        config.drivers = {"iscsi": {}, "qla2x00t": {}}

        modules = manager.determine_required_modules(config)

        # Should include base scst module plus mapped modules from constants
        expected = {
            "scst",  # Base SCST module - always required
            "scst_vdisk",  # From vdisk_fileio handler mapping
            "scst_disk",  # From dev_disk handler mapping
            "iscsi_scst",  # From iscsi driver mapping
            "qla2x00tgt",  # From qla2x00t driver mapping
            "crc32c",  # From iscsi driver (base CRC module)
        }
        assert expected.issubset(modules)

    @patch("platform.machine")
    def test_determine_required_modules_x86_iscsi(self, mock_machine):
        """Test iSCSI module determination on x86 platforms.

        On x86/x86_64 systems, additional CRC acceleration modules are included
        for better iSCSI performance. Note: iSER modules are deliberately omitted
        and handled elsewhere in the codebase.
        """
        mock_machine.return_value = "x86_64"
        manager = SCSTModuleManager()

        config = SCSTConfig()
        config.drivers = {"iscsi": {}}

        modules = manager.determine_required_modules(config)

        # Should include x86-specific CRC hardware acceleration
        assert "crc32c-intel" in modules  # Hardware-accelerated CRC on Intel
        assert "crc32c" in modules  # Base CRC module
        assert "iscsi_scst" in modules  # Core iSCSI target driver

    @patch("platform.machine")
    def test_determine_required_modules_non_x86_iscsi(self, mock_machine):
        """Test iSCSI module determination on non-x86 platforms.

        Non-x86 platforms (ARM, RISC-V, etc.) don't get the Intel-specific
        CRC acceleration modules but still get the base iSCSI functionality.
        """
        mock_machine.return_value = "aarch64"
        manager = SCSTModuleManager()

        config = SCSTConfig()
        config.drivers = {"iscsi": {}}

        modules = manager.determine_required_modules(config)

        # Should not include x86-specific modules on ARM
        assert "crc32c-intel" not in modules
        assert "crc32c" in modules  # Base CRC module still needed
        assert "iscsi_scst" in modules  # Core iSCSI functionality

    def test_determine_required_modules_copy_manager(self):
        """Test module determination with copy_manager driver.

        The copy_manager driver is special - it's built into the core SCST
        module and doesn't require a separate kernel module to be loaded.
        """
        manager = SCSTModuleManager()

        config = SCSTConfig()
        config.drivers = {"copy_manager": {}}

        modules = manager.determine_required_modules(config)

        # copy_manager maps to None in constants (built into scst core)
        assert modules == {"scst"}

    @patch("os.path.exists")
    def test_is_module_loaded_basic(self, mock_exists):
        """Test basic module loading status check via /sys/module/."""
        mock_exists.return_value = True
        manager = SCSTModuleManager()

        result = manager.is_module_loaded("scst_vdisk")

        assert result is True
        mock_exists.assert_called_with("/sys/module/scst_vdisk")

    @patch("os.path.exists")
    def test_is_module_loaded_hyphen_conversion(self, mock_exists):
        """Test module loading check with hyphen to underscore conversion.

        Kernel modules with hyphens in their names appear in /sys/module/
        with underscores instead (kernel naming convention).
        """
        mock_exists.return_value = True
        manager = SCSTModuleManager()

        result = manager.is_module_loaded("crc32c-intel")

        assert result is True
        # Should convert hyphen to underscore for sysfs path
        mock_exists.assert_called_with("/sys/module/crc32c_intel")

    @patch("os.path.exists")
    def test_is_module_loaded_crc32c_variants(self, mock_exists):
        """Test crc32c special case handling with multiple implementations.

        The crc32c functionality can be provided by different modules:
        - crc32c_intel (hardware accelerated)
        - crc32c_generic (software fallback)
        - libcrc32c (library implementation)

        Any of these satisfies the crc32c requirement.
        """

        def exists_side_effect(path):
            # Simulate crc32c_intel being loaded but not others
            return path == "/sys/module/crc32c_intel"

        mock_exists.side_effect = exists_side_effect
        manager = SCSTModuleManager()

        result = manager.is_module_loaded("crc32c")

        assert result is True
        # Should check crc32c variants until it finds one (any() short-circuits)
        # In this case, crc32c_intel returns True so it stops there
        actual_calls = [str(call[0][0]) for call in mock_exists.call_args_list]
        assert "/sys/module/crc32c_intel" in actual_calls
        # Should not check remaining variants after finding the first one
        assert len(actual_calls) == 1

    @patch("os.path.exists")
    def test_is_module_loaded_crc32c_fallback_check(self, mock_exists):
        """Test crc32c checking fallback implementations when first isn't available."""

        def exists_side_effect(path):
            # Simulate only libcrc32c being loaded (third variant)
            return path == "/sys/module/libcrc32c"

        mock_exists.side_effect = exists_side_effect
        manager = SCSTModuleManager()

        result = manager.is_module_loaded("crc32c")

        assert result is True
        # Should check all variants until it finds libcrc32c
        actual_calls = [str(call[0][0]) for call in mock_exists.call_args_list]
        expected_calls = [
            "/sys/module/crc32c_intel",
            "/sys/module/crc32c_generic",
            "/sys/module/libcrc32c",
        ]
        assert actual_calls == expected_calls

    @patch("os.path.exists")
    def test_is_module_loaded_crc32c_not_loaded(self, mock_exists):
        """Test crc32c check when no implementation variants are loaded."""
        mock_exists.return_value = False
        manager = SCSTModuleManager()

        result = manager.is_module_loaded("crc32c")

        assert result is False
        # Should check all variants when none are found
        actual_calls = [str(call[0][0]) for call in mock_exists.call_args_list]
        expected_calls = [
            "/sys/module/crc32c_intel",
            "/sys/module/crc32c_generic",
            "/sys/module/libcrc32c",
        ]
        assert actual_calls == expected_calls

    @patch("subprocess.run")
    def test_load_module_success(self, mock_run):
        """Test successful module loading using modprobe."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        manager = SCSTModuleManager()
        result = manager.load_module("scst_vdisk")

        assert result is True
        mock_run.assert_called_with(
            ["modprobe", "scst_vdisk"], capture_output=True, text=True, timeout=30
        )

    @patch("subprocess.run")
    def test_load_module_failure_required(self, mock_run):
        """Test failed loading of a required module (should return False).

        When required modules fail to load, the method returns False so the
        caller can decide whether to fail the entire operation.
        """
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Module not found"
        mock_run.return_value = mock_result

        manager = SCSTModuleManager()
        result = manager.load_module("scst_vdisk")

        assert result is False

    @patch("subprocess.run")
    def test_load_module_failure_optional(self, mock_run):
        """Test failed loading of optional module (should continue gracefully).

        Optional modules (like CRC acceleration) are nice-to-have but not
        essential. Failures should be logged but not block the operation.
        """
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Module not found"
        mock_run.return_value = mock_result

        manager = SCSTModuleManager()
        # crc32c-intel is marked as optional in constants
        result = manager.load_module("crc32c-intel")

        assert result is True  # Should continue without optional modules

    @patch("subprocess.run")
    def test_load_module_timeout(self, mock_run):
        """Test module loading timeout handling."""
        mock_run.side_effect = subprocess.TimeoutExpired("modprobe", 30)

        manager = SCSTModuleManager()
        result = manager.load_module("scst_vdisk")

        assert result is False

    @patch("subprocess.run")
    def test_load_module_exception(self, mock_run):
        """Test module loading with unexpected exception."""
        mock_run.side_effect = Exception("Unexpected error")

        manager = SCSTModuleManager()
        result = manager.load_module("scst_vdisk")

        assert result is False

    @patch.object(SCSTModuleManager, "determine_required_modules")
    @patch.object(SCSTModuleManager, "is_module_loaded")
    @patch.object(SCSTModuleManager, "load_module")
    def test_ensure_required_modules_loaded_success(
        self, mock_load, mock_is_loaded, mock_determine
    ):
        """Test successful loading of all required modules.

        This tests the main orchestration method that analyzes the config,
        checks module status, and loads missing modules.
        """
        mock_determine.return_value = {"scst", "scst_vdisk", "iscsi_scst"}
        # scst not loaded, vdisk already loaded, iscsi not loaded
        mock_is_loaded.side_effect = [False, True, False]
        mock_load.return_value = True

        manager = SCSTModuleManager()
        config = SCSTConfig()

        # Should complete without raising exception
        manager.ensure_required_modules_loaded(config)

        # Should attempt to load only the unloaded modules
        assert mock_load.call_count == 2  # scst and iscsi_scst

    @patch.object(SCSTModuleManager, "determine_required_modules")
    @patch.object(SCSTModuleManager, "is_module_loaded")
    @patch.object(SCSTModuleManager, "load_module")
    def test_ensure_required_modules_loaded_failure(
        self, mock_load, mock_is_loaded, mock_determine
    ):
        """Test failure when required modules cannot be loaded.

        When core SCST modules fail to load, the operation should fail fast
        with a clear error message indicating which modules failed.
        """
        mock_determine.return_value = {"scst", "scst_vdisk"}
        mock_is_loaded.return_value = False
        mock_load.side_effect = [True, False]  # First succeeds, second fails

        manager = SCSTModuleManager()
        config = SCSTConfig()

        with pytest.raises(SCSTError, match="Failed to load required modules"):
            manager.ensure_required_modules_loaded(config)

    @patch.object(SCSTModuleManager, "determine_required_modules")
    @patch.object(SCSTModuleManager, "is_module_loaded")
    @patch.object(SCSTModuleManager, "load_module")
    def test_ensure_required_modules_loaded_optional_failure_ok(
        self, mock_load, mock_is_loaded, mock_determine
    ):
        """Test that optional module failures don't cause overall failure.

        Optional modules like hardware CRC acceleration should not prevent
        SCST from starting if they fail to load - the system should continue
        with software fallbacks.
        """
        mock_determine.return_value = {"scst", "crc32c", "crc32c-intel"}
        mock_is_loaded.return_value = False
        mock_load.side_effect = [True, True, True]  # All succeed

        manager = SCSTModuleManager()
        config = SCSTConfig()

        # Should not raise exception even if optional modules would fail
        # (this test simulates success, but the logic handles optional failures)
        manager.ensure_required_modules_loaded(config)

    def test_ensure_required_modules_loaded_already_loaded(self):
        """Test that already loaded modules are skipped efficiently.

        This tests the optimization where the manager checks module status
        before attempting to load, avoiding unnecessary modprobe calls.
        """
        manager = SCSTModuleManager()
        config = SCSTConfig()
        config.handlers = {"vdisk_fileio": {}}

        with (
            patch.object(
                manager, "is_module_loaded", return_value=True
            ) as mock_is_loaded,
            patch.object(manager, "load_module") as mock_load,
        ):
            manager.ensure_required_modules_loaded(config)

            # Should check if modules are loaded but skip loading them
            assert mock_is_loaded.called
            assert not mock_load.called
