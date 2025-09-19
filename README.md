# SCST Python Configurator

A comprehensive Python library and CLI tool for managing SCST (SCSI Target Subsystem for Linux) through the kernel sysfs interface. This tool provides complete SCST configuration management with single-pass convergence, automatic kernel module loading, and robust error handling.

## Quick Start

### Basic Usage

```bash
# Apply configuration from file
./pyscstadmin -config /etc/scst.conf

# Check configuration validity without applying
./pyscstadmin -check_config /etc/scst.conf

# Clear all SCST configuration
./pyscstadmin -clear_config

# Apply with performance optimization (suspend IO during config)
./pyscstadmin -config /etc/scst.conf -suspend 1

# Enable detailed logging
./pyscstadmin -config /etc/scst.conf -log INFO
```

### Command Line Options

- `-config FILE` - Apply SCST configuration from FILE
- `-check_config FILE` - Validate configuration FILE without applying
- `-clear_config` - Remove all SCST configuration
- `-suspend N` - Suspend SCST IO with value N during operations (improves performance)
- `-timeout SECONDS` - Operation timeout (default: 60s)
- `-log_level LEVEL` - Logging level: DEBUG, INFO, WARNING, ERROR (default: WARNING)
- `-version` - Show version information

## Library Usage

The tool can also be used as a Python library:

```python
from scstadmin import SCSTAdmin

# One-line configuration application
SCSTAdmin.apply_config_file('/etc/scst.conf')

# More control
admin = SCSTAdmin(log_level='INFO')
config = admin.parser.parse_config_file('/etc/scst.conf')
admin.apply_configuration(config, suspend=1)

# Configuration validation
admin = SCSTAdmin()
is_valid = admin.check_configuration('/etc/scst.conf')
```

## Features

### Core Capabilities
- **Complete SCST Management** - Handles handlers, devices, drivers, targets, device groups, and global attributes
- **Single-Pass Convergence** - Applies configurations in correct dependency order to prevent conflicts
- **Automatic Module Loading** - Detects and loads required kernel modules based on configuration
- **Performance Optimization** - Suspend/resume support for minimal IO disruption
- **Robust Error Handling** - Comprehensive error reporting with context

### Advanced Features
- **Copy Manager Cleanup** - Automatically resolves duplicate LUN assignments from auto-generated copy_manager LUNs
- **Configuration Reading** - Can read and analyze current SCST state from sysfs
- **Incremental Updates** - Smart detection of configuration changes to minimize disruption
- **Library Design** - Clean Python API for integration with other tools

## Configuration Format

The tool uses the standard SCST configuration format:

```
HANDLER vdisk_fileio {
    DEVICE disk1 {
        filename /path/to/disk1.img
        blocksize 4096
    }
}

TARGET_DRIVER iscsi {
    TARGET iqn.2024-01.com.example:target1 {
        LUN 0 disk1
        enabled 1
    }
    enabled 1
}
```

## Architecture Overview

```
pyscstadmin/
├── pyscstadmin          # CLI executable
└── scstadmin/          # Python library package
    ├── admin.py        # High-level orchestration interface
    ├── parser.py       # Configuration file parsing
    ├── readers/        # Current configuration reading modules
    │   ├── config_reader.py   # Main configuration reader
    │   ├── device_reader.py   # Device configuration reading
    │   ├── target_reader.py   # Target and driver reading
    │   └── group_reader.py    # Device group reading
    ├── writers/        # Configuration application modules
    │   ├── device_writer.py   # Device configuration writing
    │   ├── target_writer.py   # Target and driver configuration writing
    │   ├── group_writer.py    # Device group configuration writing
    │   └── utils.py           # Common writer utilities
    ├── sysfs.py        # Low-level sysfs interface
    ├── modules.py      # Kernel module management
    ├── config.py       # Structured configuration dataclasses
    ├── constants.py    # System constants and mappings
    └── exceptions.py   # Error handling
```

## Requirements

- **Linux system** with SCST kernel modules available
- **Python 3.6+** with standard library
- **Root privileges** for SCST configuration changes
- **modprobe** available for automatic module loading

## License

GPLv2 - Based on the original scstadmin Perl script by Mark R. Buechler

## Support

For detailed library documentation and code architecture, see `scstadmin/README.md`.

For issues and contributions: https://github.com/truenas/truenas_pyscstadmin