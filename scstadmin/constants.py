"""
Constants for SCST configuration and operation.

This module contains all the constants used throughout the SCST Python configurator
library, including timeouts, module mappings, and system error codes.
"""

import errno


class SCSTConstants:
    """Constants for SCST configuration and operation."""

    # Operation timeouts and intervals
    DEFAULT_TIMEOUT = 60  # Default timeout for SCST operations (seconds)
    OPERATION_POLL_INTERVAL = 0.1  # Polling interval for operation completion (seconds)

    # SCST operation results
    SUCCESS_RESULT = "0"  # SCST success result value

    # System error codes
    EAGAIN_ERRNO = errno.EAGAIN  # Resource temporarily unavailable (errno 11)

    # Kernel module mappings (based on SCST init script)
    HANDLER_MODULE_MAP = {
        "dev_cdrom": "scst_cdrom",
        "dev_changer": "scst_changer",
        "dev_disk": "scst_disk",
        "dev_disk_perf": "scst_disk",
        "dev_modisk": "scst_modisk",
        "dev_modisk_perf": "scst_modisk",
        "dev_processor": "scst_processor",
        "dev_raid": "scst_raid",
        "dev_tape": "scst_tape",
        "dev_tape_perf": "scst_tape",
        "dev_user": "scst_user",
        "vdisk_blockio": "scst_vdisk",
        "vdisk_fileio": "scst_vdisk",
        "vdisk_nullio": "scst_vdisk",
        "vcdrom": "scst_vdisk",
    }

    DRIVER_MODULE_MAP = {
        "iscsi": "iscsi_scst",
        "qla2x00t": "qla2x00tgt",
        "copy_manager": None,  # Built into scst core
    }

    # Driver attributes that should be filtered when scanning for targets
    # These are driver-level configuration files/directories, not actual targets
    DRIVER_ATTRIBUTES = {
        "copy_manager": {
            "copy_manager_tgt",
            "dif_capabilities",
            "allow_not_connected_copy",
        },
        "iscsi": {
            "link_local",
            "isns_entity_name",
            "internal_portal",
            "trace_level",
            "open_state",
            "version",
            "iSNSServer",
            "enabled",
            "mgmt",
        },
        "qla2x00t": {"trace_level", "version", "mgmt"},
    }

    # Optional modules for specific architectures/drivers
    # Handle isert_scst elsewhere
    ISCSI_OPT_MODULES = ["crc32c"]
    ISCSI_X86_MODULES = ["crc32c-intel"]
