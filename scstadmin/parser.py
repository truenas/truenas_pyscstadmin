"""
SCST configuration file parser.

This module provides the SCSTConfigParser class for parsing SCST configuration
files and text into structured SCSTConfig objects. The parser handles the
complete SCST configuration file format including handlers, devices, drivers,
targets, device groups, and global attributes.

Features:
- Hierarchical block parsing (HANDLER, DEVICE, TARGET_DRIVER, etc.)
- Attribute parsing with quote handling
- LUN assignment parsing
- Device group and access control parsing
- Error reporting with line numbers for debugging
"""

import logging
from typing import List, Tuple, Dict

from .config import (
    SCSTConfig, create_device_config, LunConfig, InitiatorGroupConfig,
    TargetConfig, DriverConfig, DeviceGroupConfig, TargetGroupConfig
)
from .exceptions import SCSTError


class SCSTConfigParser:
    """SCST configuration file parser for structured config processing.

    This parser handles the complete SCST configuration file format including
    handlers, devices, drivers, targets, device groups, and global attributes.
    It supports both configuration files and configuration text strings.

    The parser processes the hierarchical structure of SCST configs, handles
    quoted values, nested blocks, attributes, and provides comprehensive
    error reporting with line number context for debugging.

    Key features:
    - Hierarchical block parsing (HANDLER, DEVICE, TARGET_DRIVER, etc.)
    - Attribute parsing with quote handling
    - LUN assignment parsing
    - Device group and access control parsing
    - Error reporting with line numbers
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _strip_quotes(self, value: str) -> str:
        """Strip surrounding quotes from a value if present"""
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            return value[1:-1]
        return value

    def _add_target_attribute(self, attributes: Dict[str, str], key: str, value: str) -> None:
        """Add a target attribute, combining multiple values with semicolon separator"""
        if key in attributes:
            # If attribute already exists, append with semicolon separator
            attributes[key] = f"{attributes[key]};{value}"
        else:
            # First time seeing this attribute
            attributes[key] = value

    def parse_config_file(self, filename: str) -> SCSTConfig:
        """Parse an SCST configuration file into structured data.

        Args:
            filename: Path to the SCST configuration file

        Returns:
            SCSTConfig object containing parsed configuration

        Raises:
            SCSTError: On file access errors or parsing failures
        """
        self.logger.info("Parsing configuration file: %s", filename)
        try:
            with open(filename, 'r') as f:
                content = f.read()
        except OSError as e:
            raise SCSTError(f"Cannot read config file {filename}: {e}")

        result = self.parse_config_text(content)
        self.logger.info("Configuration file parsed successfully")
        return result

    def parse_config_text(self, content: str) -> SCSTConfig:
        """Parse SCST configuration from text content into structured data.

        This is the core parsing method that processes configuration text
        line by line, handling hierarchical blocks, attributes, and
        special SCST configuration constructs.

        Args:
            content: Raw SCST configuration text

        Returns:
            SCSTConfig object containing parsed configuration

        Raises:
            SCSTError: On parsing failures with line number context
        """
        config = SCSTConfig()

        try:
            # Remove comments and empty lines
            lines = []
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    lines.append(line)

            # Parse configuration blocks
            self._parse_blocks(lines, config)

        except Exception as e:
            self.logger.error("Configuration parsing failed: %s", e)
            self.logger.error("Failed while parsing configuration content")
            raise SCSTError(f"Configuration parsing error: {e}")

        return config

    def _parse_blocks(self, lines: List[str], config: SCSTConfig):
        """Parse configuration blocks from lines"""
        i = 0
        while i < len(lines):
            try:
                line = lines[i].strip()
                if line.startswith('HANDLER '):
                    i = self._parse_handler_block(lines, i, config)
                elif line.startswith('TARGET_DRIVER '):
                    i = self._parse_target_driver_block(lines, i, config)
                elif line.startswith('DEVICE_GROUP '):
                    i = self._parse_device_group_block(lines, i, config)
                elif '=' in line:
                    # Global SCST attribute in key=value format
                    parts = line.split('=', 1)
                    if len(parts) != 2:
                        raise SCSTError(f"Malformed global attribute at line {i+1}: '{line}'")
                    key, value = parts
                    key = key.strip()
                    value = self._strip_quotes(value)
                    config.scst_attributes[key] = value
                    i += 1
                elif ' ' in line and not line.startswith('#'):
                    # Global SCST attribute in key value format
                    parts = line.split(None, 1)  # Split on first whitespace
                    if len(parts) == 2:
                        key, value = parts
                        key = key.strip()
                        value = self._strip_quotes(value)
                        config.scst_attributes[key] = value
                        i += 1
                    else:
                        self.logger.warning("Ignoring unrecognized line %s: '%s'", i+1, line)
                        i += 1
                else:
                    self.logger.warning("Ignoring unrecognized line %s: '%s'", i+1, line)
                    i += 1
            except SCSTError:
                raise  # Re-raise SCSTError as-is
            except Exception as e:
                raise SCSTError(f"Parsing error at line {i+1}: '{lines[i] if i < len(lines) else 'EOF'}' - {e}")

    def _parse_block_generic(self, lines: List[str], start: int, block_type: str,
                             expected_format: str) -> Tuple[str, int, int]:
        """Parse a generic block structure extracting name and brace positions.

        Handles the common pattern of:
        BLOCK_TYPE block_name {
            content...
        }

        Or:
        BLOCK_TYPE block_name
        {
            content...
        }

        Args:
            lines: Configuration file lines
            start: Starting line index
            block_type: Expected block type (e.g., 'HANDLER', 'TARGET')
            expected_format: Error message format for malformed lines

        Returns:
            Tuple of (block_name, content_start_index, block_end_index)
        """
        line = lines[start]
        parts = line.split()
        if len(parts) < 2:
            raise SCSTError(f"Malformed {block_type} line at {start+1}: '{line}' - {expected_format}")

        block_name = parts[1]

        # Check if opening brace is on the same line
        if line.endswith('{'):
            content_start = start + 1
        else:
            # Opening brace should be on next line
            content_start = start + 1
            if content_start < len(lines) and lines[content_start].strip() == '{':
                content_start += 1
            else:
                # No opening brace found - treat as empty block
                return block_name, start + 1, start + 1

        # Find matching closing brace by counting ALL braces (nested blocks supported)
        brace_count = 1  # Start with 1 for the opening brace we already found
        i = content_start
        while i < len(lines) and brace_count > 0:
            line_content = lines[i].strip()
            # Count opening braces: "BLOCK_NAME {" patterns
            if line_content.endswith('{'):
                brace_count += 1
            # Count closing braces: "}" at end of line (handles both standalone and inline)
            elif line_content.endswith('}'):
                brace_count -= 1
            i += 1

        if brace_count != 0:
            raise SCSTError(f"Unmatched braces in {block_type} {block_name} starting at line {start+1}")

        return block_name, content_start, i - 1  # i-1 because we want index of closing brace

    def _parse_single_attribute_line(self, line: str, attributes: Dict[str, str],
                                     attribute_handler: callable = None) -> bool:
        """Parse a single line for key-value attributes.

        Handles both formats:
        - key=value
        - key value

        Args:
            line: Single line to parse for attributes
            attributes: Dictionary to store parsed attributes
            attribute_handler: Optional custom handler for attribute processing

        Returns:
            True if line contained an attribute, False otherwise
        """
        line = line.strip()
        if not line:
            return False

        if '=' in line:
            # Format: key=value
            key, value = line.split('=', 1)
            key = key.strip()
            value = self._strip_quotes(value)
            if attribute_handler:
                attribute_handler(attributes, key, value)
            else:
                attributes[key] = value
            return True
        elif ' ' in line:
            # Format: key value
            parts = line.split(None, 1)  # Split on first whitespace
            if len(parts) == 2:
                key, value = parts
                key = key.strip()
                value = self._strip_quotes(value)
                if attribute_handler:
                    attribute_handler(attributes, key, value)
                else:
                    attributes[key] = value
                return True

        return False

    def _parse_attributes_in_block(self, lines: List[str], start: int, end: int,
                                   attributes: Dict[str, str],
                                   attribute_handler: callable = None) -> None:
        """Parse key-value attributes within a block using single-line parsing.

        Args:
            lines: Configuration file lines
            start: Starting line index for parsing
            end: Ending line index (exclusive)
            attributes: Dictionary to store parsed attributes
            attribute_handler: Optional custom handler for attribute processing
        """
        for i in range(start, end):
            self._parse_single_attribute_line(lines[i], attributes, attribute_handler)

    def _parse_handler_block(
            self,
            lines: List[str],
            start: int,
            config: SCSTConfig) -> int:
        """Parse a HANDLER block containing device handler configuration.

        SCST handlers define how different types of storage devices are managed.
        Common handlers include dev_disk (passthrough), vdisk_blockio (block),
        and vdisk_fileio (file-backed virtual disks).

        Example configurations:
            HANDLER vdisk_blockio {
                DEVICE test1 {
                    filename /dev/zvol/dozer/test1
                    blocksize 512
                    cluster_mode 0
                    threads_num 32
                }
            }

            HANDLER dev_disk {
                DEVICE 17:0:0:1 {
                    cluster_mode 1
                }
            }
        """
        handler_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'HANDLER', 'expected HANDLER <name>'
        )

        if content_start == content_end:
            # Empty block
            config.handlers[handler_name] = {}
            return content_end + 1  # +1 to skip closing brace

        handler_config = {}

        # Parse handler contents
        i = content_start
        while i < content_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line.startswith('DEVICE '):
                # Parse device within handler
                i = self._parse_device_within_handler(lines, i, config, handler_name)
            else:
                # Parse handler-level attributes using single-line parser
                self._parse_single_attribute_line(line, handler_config)
                i += 1

        config.handlers[handler_name] = handler_config
        return content_end + 1  # +1 to skip closing brace

    def _parse_device_within_handler(
            self,
            lines: List[str],
            start: int,
            config: SCSTConfig,
            handler_name: str) -> int:
        """Parse a DEVICE block within a HANDLER block.

        Device blocks define individual storage devices managed by a handler,
        including their backing storage and comprehensive configuration parameters
        for production deployments including clustering, identification, and performance.

        Example configuration:
            DEVICE test1 {
                filename /dev/zvol/dozer/test1
                blocksize 512
                read_only 0
                usn 389e4d902ab45f5
                naa_id 0x6589cfc0000001034d2ec31a8f423877
                prod_id "iSCSI Disk"
                rotational 0
                t10_vend_id TrueNAS
                t10_dev_id 389e4d902ab45f5
                cluster_mode 0
                threads_num 32
            }
        """
        device_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'DEVICE', 'expected DEVICE <name>'
        )

        # Parse attributes into a dict first
        attributes = {}
        if content_start != content_end:
            self._parse_attributes_in_block(lines, content_start, content_end, attributes)

        # Create the appropriate DeviceConfig subclass based on handler type
        device_config = self._create_device_config(device_name, handler_name, attributes)
        config.devices[device_name] = device_config
        return content_end + 1  # +1 to skip closing brace

    def _create_device_config(self, device_name: str, handler_name: str, attributes: Dict[str, str]):
        """Create the appropriate DeviceConfig subclass based on handler type.

        Args:
            device_name: Name of the device
            handler_name: SCST handler type (e.g., 'vdisk_fileio', 'vdisk_blockio', 'dev_disk')
            attributes: Parsed attributes from the config file

        Returns:
            DeviceConfig: Appropriate subclass instance

        Raises:
            SCSTError: If handler type is unsupported or required attributes are missing
        """
        try:
            device_config = create_device_config(device_name, handler_name, attributes)
            if device_config is None:
                raise SCSTError(f"Unsupported handler type '{handler_name}' for device '{device_name}'")
            return device_config

        except (ValueError, TypeError) as e:
            raise SCSTError(f"Failed to create device config for '{device_name}' (handler: {handler_name}): {e}")

    def _parse_target_driver_block(
            self,
            lines: List[str],
            start: int,
            config: SCSTConfig) -> int:
        """Parse a TARGET_DRIVER block containing protocol-specific target configuration.

        Target drivers handle different storage protocols like iSCSI, Fibre Channel,
        SRP, etc. Each driver can have multiple targets with their own LUN assignments.

        Example configuration:
            TARGET_DRIVER iscsi {
                internal_portal 169.254.10.1
                enabled 1
                link_local 0

                TARGET iqn.2005-10.org.freenas.ctl:test1 {
                    rel_tgt_id 1
                    enabled 1
                    per_portal_acl 1
                }
            }
        """
        driver_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'TARGET_DRIVER', 'expected TARGET_DRIVER <name>'
        )

        driver_config_dict = {'targets': {}, 'attributes': {}}

        if content_start == content_end:
            # Empty block
            driver_config = DriverConfig.from_config_dict(driver_name, driver_config_dict)
            config.drivers[driver_name] = driver_config
            return content_end + 1  # +1 to skip closing brace

        # Parse driver contents
        i = content_start
        while i < content_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line.startswith('TARGET '):
                i = self._parse_target_block(lines, i, driver_config_dict['targets'])
            else:
                # Parse driver-level attributes using single-line parser
                # Use custom handler to combine multiple values (e.g., multiple IncomingUser)
                if '=' in line or ' ' in line:
                    self._parse_single_attribute_line(line, driver_config_dict['attributes'],
                                                      self._add_target_attribute)
                i += 1

        # Create DriverConfig object from parsed data
        driver_config = DriverConfig.from_config_dict(driver_name, driver_config_dict)
        config.drivers[driver_name] = driver_config
        return content_end + 1  # +1 to skip closing brace

    def _parse_target_block(
            self,
            lines: List[str],
            start: int,
            targets: Dict) -> int:
        r"""Parse a TARGET block within a driver defining a specific target endpoint.

        Targets are the endpoints that initiators connect to. Each target can
        have multiple LUNs assigned, groups for access control, authentication
        settings, and various attributes. Multiple values for the same attribute
        are combined with semicolon separators.

        Example configurations:
            TARGET iqn.2005-10.org.freenas.ctl:test1 {
                rel_tgt_id 1
                enabled 1
                per_portal_acl 1
                IncomingUser "testuser1 somesecret123"
                IncomingUser "otheruser2 otherpass123"

                GROUP security_group {
                    INITIATOR iqn.2023-01.com.example:server1\#10.220.38.206
                    LUN 0 test1
                    LUN 1 test2
                }
            }
        """
        # Use generic parser to extract target name and find block boundaries
        target_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'TARGET', 'expected TARGET <name>'
        )

        # Initialize target configuration structure
        target_config_dict = {'luns': {}, 'groups': {}, 'attributes': {}}

        if content_start == content_end:
            # Empty block - no braces found, treat as target with no configuration
            self.logger.debug("  No opening brace found for TARGET %s", target_name)
            target_config = TargetConfig.from_config_dict(target_name, target_config_dict)
            targets[target_name] = target_config
            return content_end + 1  # +1 to skip closing brace

        # Parse target contents line by line within the block boundaries
        i = content_start
        while i < content_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Handle nested blocks that have their own specialized parsers
            if line.startswith('LUN '):
                # LUN assignments: "LUN 0 device_name"
                i = self._parse_lun_block(lines, i, target_config_dict['luns'])
            elif line.startswith('GROUP '):
                # Initiator groups for access control
                i = self._parse_group_block(lines, i, target_config_dict['groups'])
            else:
                # Handle target-level attributes (may have multiple values for same key)
                if '=' in line or ' ' in line:
                    # Use custom attribute handler that supports combining multiple values
                    self._parse_single_attribute_line(line, target_config_dict['attributes'],
                                                      self._add_target_attribute)
                i += 1

        # Create TargetConfig object from parsed data
        target_config = TargetConfig.from_config_dict(target_name, target_config_dict)
        targets[target_name] = target_config
        return content_end + 1  # +1 to skip the closing brace

    def _parse_lun_block(
            self,
            lines: List[str],
            start: int,
            luns: Dict) -> int:
        """Parse a LUN block defining device-to-LUN assignments.

        LUNs (Logical Unit Numbers) map storage devices to specific numbers
        that initiators use to access them. LUNs can have per-target attributes.

        Example configurations:
            LUN 0 test1
            LUN 1 test2

            LUN 3 special_disk {
                read_only 1
                thin_provisioning 0
            }
        """
        # Parse LUN line which has format: "LUN <number> [device_name]"
        line = lines[start]
        parts = line.split()
        if len(parts) < 2:
            raise SCSTError(f"Malformed LUN line at {start+1}: '{line}' - expected 'LUN <number> [device]'")

        lun_number = parts[1]  # LUN number (e.g., "0", "1", "3")
        device_name = parts[2] if len(parts) > 2 else None  # Optional device name

        # Create initial dictionary format for attributes parsing
        lun_config_dict = {'device': device_name, 'attributes': {}}

        # Check if this LUN has an attribute block using generic parser
        # Note: We need special handling since LUN line format is "LUN num device {" not "LUN name {"
        if line.endswith('{'):
            # Attributes block starts on same line
            content_start = start + 1
            content_end = self._find_closing_brace(lines, content_start)
            if content_end == -1:
                raise SCSTError(f"Unmatched braces in LUN {lun_number} starting at line {start+1}")
        elif start + 1 < len(lines) and lines[start + 1].strip() == '{':
            # Attributes block starts on next line
            content_start = start + 2
            content_end = self._find_closing_brace(lines, start + 1)
            if content_end == -1:
                raise SCSTError(f"Unmatched braces in LUN {lun_number} starting at line {start+2}")
        else:
            # No attributes block - simple LUN assignment
            # Create LunConfig object from dictionary
            lun_config = LunConfig.from_config_dict(lun_number, lun_config_dict)
            luns[lun_number] = lun_config
            return start + 1

        # Parse LUN attributes within the block
        self._parse_attributes_in_block(lines, content_start, content_end, lun_config_dict['attributes'])

        # Create LunConfig object from dictionary
        lun_config = LunConfig.from_config_dict(lun_number, lun_config_dict)
        luns[lun_number] = lun_config
        return content_end + 1  # +1 to skip closing brace

    def _find_closing_brace(self, lines: List[str], start: int) -> int:
        """Find the matching closing brace for an opening brace at start."""
        brace_count = 1
        i = start
        while i < len(lines) and brace_count > 0:
            line_content = lines[i].strip()
            if line_content == '{':
                brace_count += 1
            elif line_content == '}':
                brace_count -= 1
            i += 1
        return i - 1 if brace_count == 0 else -1

    def _parse_group_block(
            self,
            lines: List[str],
            start: int,
            groups: Dict) -> int:
        r"""Parse a GROUP block within a target for access control.

        Groups define which initiators can access specific LUNs within a target,
        providing fine-grained access control and security.

        Example configuration:
            GROUP security_group {
                INITIATOR iqn.2023-01.com.example:server1\#10.220.38.206
                INITIATOR iqn.2023-01.com.example:server2\#10.220.38.206

                LUN 0 test1
                LUN 1 test2
            }
        """
        # Use generic parser to extract group name and block boundaries
        group_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'GROUP', 'expected GROUP <name>'
        )

        # Initialize group configuration structure for parsing
        group_config_dict = {'luns': {}, 'initiators': [], 'attributes': {}}

        if content_start == content_end:
            # Empty group block - create InitiatorGroupConfig object
            group_config = InitiatorGroupConfig.from_config_dict(group_name, group_config_dict)
            groups[group_name] = group_config
            return content_end + 1  # +1 to skip closing brace

        # Parse group contents within block boundaries
        i = content_start
        while i < content_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line.startswith('LUN '):
                # LUN assignments specific to this initiator group
                i = self._parse_lun_block(lines, i, group_config_dict['luns'])
            elif line.startswith('INITIATOR '):
                # Initiator IQN that belongs to this group
                initiator = line.split()[1]
                group_config_dict['initiators'].append(initiator)
                i += 1
            else:
                # Parse group-level attributes using single-line parser
                if '=' in line or ' ' in line:
                    self._parse_single_attribute_line(line, group_config_dict['attributes'])
                i += 1

        # Create InitiatorGroupConfig object from parsed data
        group_config = InitiatorGroupConfig.from_config_dict(group_name, group_config_dict)
        groups[group_name] = group_config
        return content_end + 1  # +1 to skip closing brace

    def _parse_device_group_block(
            self,
            lines: List[str],
            start: int,
            config: SCSTConfig) -> int:
        """Parse a DEVICE_GROUP block for device-level access control and ALUA.

        Device groups control access to devices at the device level and support
        ALUA (Asymmetric Logical Unit Access) for multipath configurations.
        They contain devices and target groups with different access states.

        Example configuration:
            DEVICE_GROUP targets {
                DEVICE test1
                DEVICE test2

                TARGET_GROUP controller_A {
                    group_id 101
                    state active
                    TARGET iqn.2005-10.org.freenas.ctl:test1
                }

                TARGET_GROUP controller_B {
                    group_id 102
                    state nonoptimized
                    TARGET iqn.2005-10.org.freenas.ctl:HA:test1
                }
            }
        """
        # Use generic parser to extract device group name and block boundaries
        group_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'DEVICE_GROUP', 'expected DEVICE_GROUP <name>'
        )

        # Initialize device group configuration structure
        group_config = {'devices': [], 'target_groups': {}, 'attributes': {}}

        if content_start == content_end:
            # Empty device group block
            self.logger.warning("Expected opening brace for device group %s", group_name)
            config.device_groups[group_name] = DeviceGroupConfig.from_config_dict(group_name, group_config)
            return content_end + 1  # +1 to skip closing brace

        # Parse device group contents within block boundaries
        i = content_start
        while i < content_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line.startswith('DEVICE '):
                # Device membership in this group
                device = line.split()[1]
                group_config['devices'].append(device)
                i += 1
            elif line.startswith('TARGET_GROUP '):
                # Nested target group for ALUA configuration
                i = self._parse_target_group_block(lines, i, group_config['target_groups'])
            else:
                # Parse device group-level attributes using single-line parser
                if '=' in line or (' ' in line and len(line.split()) == 2):
                    self._parse_single_attribute_line(line, group_config['attributes'])
                i += 1

        config.device_groups[group_name] = DeviceGroupConfig.from_config_dict(group_name, group_config)
        return content_end + 1  # +1 to skip closing brace

    def _parse_target_group_block(
            self,
            lines: List[str],
            start: int,
            target_groups: Dict) -> int:
        """Parse a TARGET_GROUP block within a device group for ALUA configuration.

        Target groups define different paths/controllers for accessing the same
        devices, with different ALUA states (active, nonoptimized, standby, etc).

        Example configuration:
            TARGET_GROUP controller_A {
                group_id 101
                state active
                TARGET iqn.2005-10.org.freenas.ctl:test1
            }
        """
        # Use generic parser to extract target group name and block boundaries
        group_name, content_start, content_end = self._parse_block_generic(
            lines, start, 'TARGET_GROUP', 'expected TARGET_GROUP <name>'
        )

        # Initialize target group configuration structure
        group_config = {'targets': [], 'target_attributes': {}, 'attributes': {}}

        if content_start == content_end:
            # Empty target group block
            self.logger.warning("Expected opening brace for target group %s", group_name)
            target_groups[group_name] = group_config
            return content_end + 1  # +1 to skip closing brace

        # Parse target group contents within block boundaries
        i = content_start
        while i < content_end:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line.startswith('TARGET '):
                # Target entries that belong to this target group (for ALUA)
                i = self._parse_target_group_target_block(
                    lines, i, group_config['targets'], group_config['target_attributes']
                )
            else:
                # Parse target group-level attributes (group_id, state, etc.)
                if '=' in line or (' ' in line and len(line.split()) == 2):
                    self._parse_single_attribute_line(line, group_config['attributes'])
                i += 1

        target_groups[group_name] = TargetGroupConfig.from_config_dict(group_name, group_config)
        return content_end + 1  # +1 to skip closing brace

    def _parse_target_group_target_block(
        self, lines: List[str], start: int, targets: List, target_attributes: Dict
    ) -> int:
        """Parse a TARGET block within a target group, supporting both simple and attribute forms.

        Handles two formats:
        1. Simple: TARGET iqn.example.test
        2. With attributes: TARGET iqn.example.test { rel_tgt_id 1 }

        Args:
            lines: Configuration file lines
            start: Starting line index
            targets: List to populate with target names
            target_attributes: Dictionary to populate with target-specific attributes

        Returns:
            Next line index to process
        """
        # Parse target line to extract target name
        line = lines[start]
        parts = line.split()
        if len(parts) < 2:
            raise SCSTError(f"Malformed TARGET line at {start+1}: '{line}' - expected 'TARGET <name>'")

        target_name = parts[1]

        # Add target name to targets list
        targets.append(target_name)

        # Check if this target has attributes (indicated by opening brace)
        if line.endswith('{'):
            # TARGET name { ... } format - target has attributes like rel_tgt_id
            target_config = {}

            # Find the closing brace for this target's attribute block
            content_start = start + 1
            content_end = self._find_closing_brace(lines, content_start)
            if content_end == -1:
                raise SCSTError(f"Unmatched braces in target {target_name} starting at line {start+1}")

            # Parse target attributes within the block using generic parser
            self._parse_attributes_in_block(lines, content_start, content_end, target_config)

            target_attributes[target_name] = target_config
            return content_end + 1  # +1 to skip closing brace
        else:
            # Simple TARGET name format - no attributes, just target membership
            return start + 1
