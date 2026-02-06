"""
Utility functions for SCST writers
"""

import os
import logging
from typing import Dict, Set, Optional

from ..constants import SCSTConstants

logger = logging.getLogger("scstadmin.writers.utils")


def entity_exists(entity_path: str) -> bool:
    """Generic function to check if a sysfs entity exists with error handling"""
    try:
        return os.path.exists(entity_path)
    except (OSError, IOError):
        return False


def attrs_config_differs(
    desired_attrs: Dict[str, str],
    current_attrs: Dict[str, str],
    skip_attrs: Optional[Set[str]] = None,
    removable_attrs: Optional[Set[str]] = None,
    entity_type: str = "attribute",
) -> bool:
    """Compare desired configuration attributes with current live values.

    This method performs intelligent configuration comparison to determine if
    SCST entity attributes need to be updated. It's a key optimization that
    prevents unnecessary sysfs writes when configurations already match.

    The comparison includes SCST-specific logic:
    - Handles missing attributes that default to "0" (common SCST pattern)
    - Provides detailed debug logging for configuration differences
    - Allows selective attribute exclusion for comparison
    - Checks for mgmt-managed attributes that need removal

    Args:
        desired_attrs: Target attribute values from configuration
        current_attrs: Live attribute values read from sysfs
        skip_attrs: Set of attribute names to exclude from comparison
        removable_attrs: Set of mgmt-managed attributes that can be removed (e.g., IncomingUser).
                        If provided, checks if any of these exist in current but not in desired.
        entity_type: Entity type name for debug logging (e.g., "Device", "Target")

    Returns:
        True if any attributes differ and updates are needed.
        False if all compared attributes match current state.

    Example:
        desired = {'read_only': '1', 'rotational': '0'}
        current = {'read_only': '0', 'rotational': None}  # rotational not set, defaults to 0
        -> Returns True (read_only differs, rotational matches default)
    """
    if skip_attrs is None:
        skip_attrs = set()

    # Compare each desired attribute
    for attr, desired_value in desired_attrs.items():
        if attr in skip_attrs:
            continue

        current_value = current_attrs.get(attr)

        # Skip comparison if current value is undefined and desired is "0"
        if current_value is None and desired_value == SCSTConstants.SUCCESS_RESULT:
            continue

        if current_value != desired_value:
            logger.debug(
                f"{entity_type} attribute '{attr}' differs: current='{current_value}', desired='{desired_value}'"
            )
            return True

    # Check for removable attributes that exist in current but not in desired
    if removable_attrs:
        for attr in removable_attrs:
            if attr not in desired_attrs and current_attrs.get(attr) is not None:
                return True

    return False
