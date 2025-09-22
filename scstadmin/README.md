# SCST Python Configurator Library

This document provides comprehensive documentation for the SCST Python configurator library 
architecture, designed for developers who need to understand, modify, or extend the codebase.

## Overview

The SCST Python Configurator Library is a modular system for managing SCST (SCSI Target 
Subsystem for Linux) through the kernel sysfs interface. The library provides focused, 
single-responsibility modules for improved maintainability, testability, and code review.

## Architecture

### Design Principles

1. **Separation of Concerns** - Each module has a single, well-defined responsibility
2. **Dependency Injection** - Components receive their dependencies explicitly
3. **Clean Interfaces** - Clear public APIs with comprehensive documentation
4. **Error Handling** - Consistent error propagation using custom exceptions
5. **Performance** - Optimized for single-pass configuration convergence

### Module Structure

```
scstadmin/
├── __init__.py         # Package interface and exports
├── admin.py           # High-level orchestration interface (SCSTAdmin)
├── parser.py          # Configuration file parsing (SCSTConfigParser)
├── readers/           # Current state reading modules
│   ├── __init__.py    # Reader package interface
│   ├── config_reader.py    # Main configuration reader (SCSTConfigurationReader)
│   ├── device_reader.py    # Device configuration reading
│   ├── target_reader.py    # Target and driver reading
│   └── group_reader.py     # Device group reading
├── writers/           # Configuration application modules
│   ├── __init__.py    # Writer package interface
│   ├── device_writer.py    # Device configuration writing (DeviceWriter)
│   ├── target_writer.py    # Target and driver configuration writing (TargetWriter)
│   ├── group_writer.py     # Device group configuration writing (GroupWriter)
│   └── utils.py           # Common writer utilities
├── sysfs.py           # Low-level sysfs interface (SCSTSysfs)
├── modules.py         # Kernel module management (SCSTModuleManager)
├── config.py          # Data structures and structured dataclasses
├── constants.py       # System constants and mappings
└── exceptions.py      # Error handling (SCSTError hierarchy)
```

## Core Classes

### SCSTAdmin (admin.py)

**Purpose**: High-level orchestration interface for SCST configuration management

**Responsibilities**: 
- Orchestrating complete configuration application workflow
- Managing configuration dependency order
- Coordinating between parser, readers, writers, sysfs, and module manager
- Providing convenient class methods for common operations
- Delegating specialized operations to writer classes

```python
class SCSTAdmin:
    def __init__(self, timeout=60, log_level="WARNING"):
        self.sysfs = SCSTSysfs(timeout)
        self.parser = SCSTConfigParser()
        self.module_manager = SCSTModuleManager()
        self.config_reader = SCSTConfigurationReader(self.sysfs)
        
        # Specialized writer classes for configuration application
        self.device_writer = DeviceWriter(self.sysfs, self.config_reader, self.logger)
        self.target_writer = TargetWriter(self.sysfs, self.config_reader, self.logger)
        self.group_writer = GroupWriter(self.sysfs, self.config_reader, self.logger)
    
    def apply_configuration(self, config: SCSTConfig, suspend=None):
        # Critical dependency order using specialized writers:
        # 0. Load required kernel modules
        # 1. Remove conflicts first
        # 2. Apply devices → self.device_writer.apply_config_devices()
        # 3. Apply targets & LUNs → self.target_writer.apply_config_assignments()
        # 4. Clean copy_manager duplicates → self.target_writer.cleanup_copy_manager_duplicates()
        # 5. Apply device groups → self.group_writer.apply_config_device_groups()
        # 6. Enable targets/drivers → self.target_writer.apply_config_enable_*()
        # 7. Apply final attributes → self.target_writer.apply_config_driver_attributes()
```

**Key Methods**:
- `apply_configuration()` - Main configuration application with dependency ordering
- `apply_config_file()` - Convenience class method for file-based configuration
- `check_configuration()` - Validation without application
- `clear_configuration()` - Complete SCST cleanup

### SCSTConfigParser (parser.py)

**Purpose**: Parse SCST configuration files into structured data

**Responsibilities**:
- Hierarchical block parsing (HANDLER, DEVICE, TARGET_DRIVER, etc.)
- Attribute extraction with quote handling
- LUN assignment parsing
- Error reporting with line numbers

```python
class SCSTConfigParser:
    def parse_config_file(self, filename: str) -> SCSTConfig:
        # Parse configuration file into SCSTConfig structure
    
    def _parse_blocks(self, lines: List[str]) -> SCSTConfig:
        # Main parsing logic with block structure recognition
    
    def _parse_block_generic(self, lines, start, block_type, expected_format):
        # Generic block parser with brace matching and nesting support
```

**Parsing Strategy**:
- **Two-pass approach**: First pass identifies block structure, second extracts content
- **Brace counting**: Handles nested blocks correctly with proper brace matching
- **Error context**: Provides line numbers and context for debugging
- **Quote handling**: Properly processes quoted strings and escaping

### Configuration Readers (readers/)

**Purpose**: Modular system for reading current SCST configuration from sysfs

The readers package provides specialized readers for different SCST components:

#### SCSTConfigurationReader (readers/config_reader.py)
**Main coordinator** that orchestrates all specialized readers:

```python
class SCSTConfigurationReader:
    def __init__(self, sysfs: SCSTSysfs):
        self.sysfs = sysfs
        self.device_reader = DeviceReader(sysfs)
        self.target_reader = TargetReader(sysfs)
        self.group_reader = DeviceGroupReader(sysfs)
    
    def read_current_config(self) -> SCSTConfig:
        # Coordinates reading from all specialized readers
```

#### Specialized Readers
- **DeviceReader**: Reads device configurations and creates structured DeviceConfig objects
- **TargetReader**: Reads driver and target configurations, creates DriverConfig/TargetConfig objects
- **DeviceGroupReader**: Reads device groups and creates DeviceGroupConfig/TargetGroupConfig objects

**Reading Strategy**:
- **Component separation**: Each reader handles one SCST subsystem
- **Structured objects**: Creates type-safe dataclass objects instead of dictionaries
- **Performance optimization**: Specialized readers can optimize for their specific data patterns
- **Maintainability**: Clear separation of concerns for easier testing and debugging

### Configuration Writers (writers/)

**Purpose**: Modular system for applying SCST configuration changes to sysfs

The writers package provides specialized writers for different SCST configuration domains:

#### DeviceWriter (writers/device_writer.py)
**Handles device configuration and lifecycle**:

```python
class DeviceWriter:
    def apply_config_devices(self, config: SCSTConfig):
        # Apply all device configurations from config
    
    def remove_device_by_name(self, device_name: str):
        # Remove device by name with proper cleanup
```

**Key Responsibilities**:
- Device creation and removal across all handlers
- Device attribute configuration and validation
- Handler-specific device parameter handling
- Device lifecycle management with proper cleanup

#### TargetWriter (writers/target_writer.py)
**Handles target, driver, and LUN configuration**:

```python
class TargetWriter:
    def apply_config_assignments(self, config: SCSTConfig):
        # Apply target and LUN assignments
    
    def apply_config_enable_targets(self, config: SCSTConfig):
        # Enable targets after configuration
    
    def apply_config_enable_drivers(self, config: SCSTConfig):
        # Enable drivers after configuration
    
    def cleanup_copy_manager_duplicates(self, config: SCSTConfig):
        # Resolve copy_manager auto-assignment conflicts
```

**Key Responsibilities**:
- Target creation and configuration
- LUN assignment to targets and initiator groups
- Driver configuration and enabling
- Target attribute management (authentication, access control)
- Copy manager duplicate LUN resolution
- Session management and cleanup
- Initiator group management within targets

#### GroupWriter (writers/group_writer.py)
**Handles device group and target group configuration for ALUA**:

```python
class GroupWriter:
    def apply_config_device_groups(self, config: SCSTConfig):
        # Apply all device group configurations
    
    def remove_device_group(self, group_name: str):
        # Remove device group with proper cleanup
```

**Key Responsibilities**:
- Device group creation and management
- Target group configuration within device groups
- Target attribute configuration within target groups (rel_tgt_id, preferred)
- Device assignment to device groups
- Target assignment to target groups for ALUA configurations

**Writing Strategy**:
- **Domain separation**: Each writer handles one major SCST subsystem
- **Configuration diffing**: Only applies changes that differ from current state
- **Error isolation**: Individual operation failures don't stop entire configurations
- **Dependency awareness**: Writers coordinate for proper operation ordering

### SCSTSysfs (sysfs.py)

**Purpose**: Low-level sysfs filesystem interface

**Responsibilities**:
- Direct sysfs read/write operations
- Path validation and permission checking
- Operation result verification
- Timeout handling for async operations

```python
class SCSTSysfs:
    SCST_ROOT = "/sys/kernel/scst_tgt"
    SCST_HANDLERS = f"{SCST_ROOT}/handlers"
    # ... other paths
    
    def write_sysfs(self, path: str, data: str, check_result=True):
        # Core sysfs write with error handling and result verification
    
    def read_sysfs_attribute(self, path: str) -> str:
        # Read attributes with SCST [key] format handling
```

**Key Features**:
- **Result verification**: Uses SCST's last_sysfs_mgmt_res for operation confirmation
- **Atomic operations**: Where possible, ensures operations complete successfully
- **Error translation**: Converts filesystem errors to SCSTError exceptions
- **Timeout support**: Configurable timeouts for long operations

### SCSTModuleManager (modules.py)

**Purpose**: Automatic kernel module loading based on configuration

**Responsibilities**:
- Analyzing configuration to determine required modules
- Loading modules using modprobe with proper error handling
- Architecture-specific optimization (e.g., CRC acceleration on x86)

```python
class SCSTModuleManager:
    def determine_required_modules(self, config: SCSTConfig) -> Set[str]:
        # Map handlers/drivers to kernel modules
        
    def ensure_required_modules_loaded(self, config: SCSTConfig):
        # Load all required modules, handle optional failures gracefully
```

**Module Mapping Strategy**:
- **Handler mapping**: `dev_disk` → `scst_disk`, `vdisk_blockio` → `scst_vdisk`, etc.
- **Driver mapping**: `iscsi` → `iscsi_scst`, `qla2x00t` → `qla2x00tgt`
- **Architecture detection**: Loads `crc32c-intel` on x86 systems for performance
- **Optional module handling**: Continues without optional modules if unavailable

### SCSTConfig and Structured Objects (config.py)

**Purpose**: Type-safe structured data representation of SCST configuration
**Type**: Dataclass with structured object composition

```python
@dataclass
class SCSTConfig:
    handlers: Optional[Dict[str, Dict]] = None
    devices: Optional[Dict[str, DeviceConfig]] = None  
    drivers: Optional[Dict[str, DriverConfig]] = None
    targets: Optional[Dict[str, TargetConfig]] = None
    device_groups: Optional[Dict[str, DeviceGroupConfig]] = None
    scst_attributes: Optional[Dict[str, str]] = None
```

#### Structured Dataclasses
The configuration uses type-safe dataclasses instead of raw dictionaries:

- **DeviceConfig**: Abstract base with concrete subclasses (VdiskFileioDeviceConfig, 
  VdiskBlockioDeviceConfig, DevDiskDeviceConfig)
- **DriverConfig**: Target driver configuration with structured TargetConfig objects
- **TargetConfig**: Target configuration with LunConfig and InitiatorGroupConfig objects
- **DeviceGroupConfig**: Device group with TargetGroupConfig objects for ALUA
- **LunConfig**: LUN assignments with device and attributes
- **InitiatorGroupConfig**: Initiator groups with LUN assignments

**Design Benefits**:
- **Type safety**: IDE support, autocompletion, and compile-time validation
- **Structured access**: `.attribute` instead of `['attribute']` or `.get('attribute')`
- **Factory methods**: `from_config_dict()` for clean object creation
- **Maintainability**: Clear data structures reduce bugs and improve readability

## Configuration Flow

### Application Process

```
1. Parse Configuration
   ├── SCSTConfigParser.parse_config_file()
   ├── Block structure recognition
   ├── Attribute extraction
   └── SCSTConfig object creation

2. Module Loading
   ├── SCSTModuleManager.determine_required_modules()
   ├── Module availability checking
   └── modprobe execution with error handling

3. Current State Reading
   ├── SCSTConfigurationReader.read_current_config()
   ├── sysfs enumeration
   └── Conflict identification

4. Configuration Application (SCSTAdmin with Writers)
   ├── Remove conflicting elements (via all writers)
   ├── Apply devices → DeviceWriter.apply_config_devices()
   ├── Apply targets & LUNs → TargetWriter.apply_config_assignments()
   ├── Clean copy_manager duplicates → TargetWriter.cleanup_copy_manager_duplicates()
   ├── Apply device groups → GroupWriter.apply_config_device_groups()
   ├── Enable targets → TargetWriter.apply_config_enable_targets()
   ├── Enable drivers → TargetWriter.apply_config_enable_drivers()
   └── Apply final attributes → TargetWriter.apply_config_driver_attributes()
```

### Dependency Management

The library handles complex SCST dependencies:

1. **Kernel Modules**: Must be loaded before configuration
2. **Devices before LUNs**: Storage devices must exist before assignment
3. **Targets before Groups**: Device groups reference targets
4. **Configuration before Enabling**: Complete setup before activation
5. **Copy Manager Cleanup**: After explicit LUNs, before groups

## Error Handling

### Exception Hierarchy

```python
SCSTError (base)
├── Configuration parsing errors
├── sysfs operation failures  
├── Module loading failures
└── Validation errors
```

### Error Context

All errors include:
- **Descriptive messages** with context about what failed
- **Line numbers** for configuration parsing errors
- **sysfs paths** for filesystem operation failures
- **Module names** for loading failures

## Performance Considerations

### Optimizations

1. **Single-Pass Convergence**: Configuration applied in one pass without iteration
2. **Suspend/Resume**: IO can be suspended during configuration for performance
3. **Management Caching**: Target management interface results cached
4. **Selective Reading**: Only non-default attributes read to reduce overhead
5. **Batch Operations**: Where possible, multiple changes applied together

### Scalability

- **Memory usage**: Minimal - configuration held in memory briefly
- **Filesystem operations**: Optimized sysfs interaction patterns
- **Module loading**: Only loads required modules, skips already-loaded

## Testing Strategy

### Unit Testing Approach

```python
# Each module can be tested independently
def test_config_parser():
    parser = SCSTConfigParser()
    config = parser.parse_config_text(test_config_text)
    assert config.handlers['vdisk_fileio']['device1']['filename'] == '/path/to/disk'

def test_module_manager():
    manager = SCSTModuleManager()
    config = SCSTConfig(drivers={'iscsi': {}})
    modules = manager.determine_required_modules(config)
    assert 'iscsi_scst' in modules

def test_device_writer():
    writer = DeviceWriter(mock_sysfs, mock_reader, mock_logger)
    config = SCSTConfig(devices={'disk1': device_config})
    writer.apply_config_devices(config)
    # Verify expected sysfs operations

def test_target_writer():
    writer = TargetWriter(mock_sysfs, mock_reader, mock_logger)
    config = SCSTConfig(drivers={'iscsi': driver_config})
    writer.apply_config_assignments(config)
    # Verify target and LUN assignments
```

### Integration Testing

```python
# Test complete workflow with all writers
def test_full_configuration():
    admin = SCSTAdmin()
    # Test with mock sysfs or real system
    config = admin.parser.parse_config_file('test.conf')
    admin.apply_configuration(config)
    # Verify expected sysfs state via all writer classes
    
# Test individual writer integration
def test_writer_integration():
    admin = SCSTAdmin()
    config = parse_test_config()
    
    # Test each writer independently
    admin.device_writer.apply_config_devices(config)
    admin.target_writer.apply_config_assignments(config) 
    admin.group_writer.apply_config_device_groups(config)
```

## Writer-Based Architecture Benefits

The specialized writer class architecture provides several key advantages:

### Maintainability
- **Single Responsibility**: Each writer handles one domain (devices, targets, groups)
- **Focused Testing**: Writers can be tested independently with domain-specific test cases
- **Clear Boundaries**: Well-defined interfaces between different SCST subsystems
- **Easier Debugging**: Issues can be isolated to specific writer components

### Code Organization
- **Modular Design**: Specialized classes for different configuration domains
- **Logical Grouping**: Related functionality grouped together in domain-specific writers
- **Clean Orchestration**: admin.py focuses purely on workflow coordination
- **Cleaner APIs**: Each writer exposes domain-specific public methods

### Performance
- **Selective Operations**: Only affected writers need to run for partial configurations
- **Optimized Diffing**: Each writer can optimize for its specific data patterns
- **Parallel Potential**: Future enhancement could run independent writers in parallel
- **Memory Efficiency**: Writers can be instantiated only when needed

### Extensibility  
- **Domain-Specific Extensions**: New functionality can be added to appropriate writers
- **Plugin Architecture**: New writers can be added for additional SCST subsystems
- **Clean Integration**: Writers follow consistent patterns for easy extension
- **Backward Compatibility**: Orchestration interface remains unchanged

## Extension Points

### Adding New Handlers

1. Update `SCSTConstants.HANDLER_MODULE_MAP`
2. Add parsing logic if special syntax needed
3. Update module loading logic if required

### Adding New Drivers

1. Update `SCSTConstants.DRIVER_MODULE_MAP`
2. Add driver-specific attribute handling if needed
3. Update known attributes in `DRIVER_ATTRIBUTES`

### Custom Operations

```python
# Extend SCSTAdmin for custom workflows
class CustomSCSTAdmin(SCSTAdmin):
    def apply_with_backup(self, config: SCSTConfig):
        backup = self.config_reader.read_current_config()
        try:
            self.apply_configuration(config)
        except SCSTError:
            self.apply_configuration(backup)  # Rollback
            raise
```

## Development Guidelines

### Code Style

- **PEP 8 compliance** with 120-character line limit
- **Type hints** for all public interfaces
- **Docstrings** following Google/NumPy style
- **Error handling** using custom exceptions, not generic exceptions

### Testing

- **Unit tests** for individual components
- **Integration tests** for complete workflows
- **Mock sysfs** for testing without SCST system
- **Error case coverage** for robust error handling

### Documentation

- **Comprehensive docstrings** explaining purpose and usage
- **Type hints** for IDE support and validation
- **Example usage** in docstrings where helpful
- **Architecture decisions** documented in code comments

This library provides a clean, modular approach to SCST configuration management with 
excellent separation of concerns and comprehensive error handling.