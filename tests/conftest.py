"""
Pytest configuration and shared fixtures for SCST Python Configurator tests.
"""

import pytest
import sys
from pathlib import Path

# Add the package to Python path for testing
test_dir = Path(__file__).parent
package_root = test_dir.parent  # This is now pyscstadmin/
sys.path.insert(0, str(package_root))


@pytest.fixture(scope="session")
def project_root():
    """Path to the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def fixtures_dir():
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_basic_config():
    """Return a basic SCST configuration as text."""
    return """
    HANDLER vdisk_fileio {
        DEVICE test_disk {
            filename /tmp/test.img
            blocksize 4096
        }
    }

    TARGET_DRIVER iscsi {
        TARGET iqn.2024-01.test:target1 {
            LUN 0 test_disk
            enabled 1
        }
        enabled 1
    }

    setup_id 12345
    """


@pytest.fixture
def sample_complex_config():
    """Return a more complex SCST configuration for testing."""
    return """
    HANDLER vdisk_fileio {
        DEVICE disk1 {
            filename /path/to/disk1.img
            blocksize 4096
            readonly 0
        }
        DEVICE disk2 {
            filename "/path with spaces/disk2.img"
            blocksize 512
        }
    }

    HANDLER dev_disk {
        DEVICE sda {
            filename /dev/sda
        }
    }

    TARGET_DRIVER iscsi {
        TARGET iqn.2024-01.test:complex {
            LUN 0 disk1
            LUN 1 disk2 {
                read_only 1
            }
            LUN 255 sda
            enabled 1
        }

        TARGET iqn.2024-01.test:simple {
            LUN 0 disk1
            enabled 1
        }

        enabled 1
    }

    DEVICE_GROUP production {
        DEVICE disk1
        DEVICE disk2

        TARGET_GROUP servers {
            TARGET iqn.2024-01.test:complex

            LUN 0 disk1
            LUN 1 disk2 {
                read_only 0
            }
        }
    }

    setup_id 67890
    max_tasklet_cmd 32
    """
