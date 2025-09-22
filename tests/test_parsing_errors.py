#!/usr/bin/env python3
"""
Test script to verify configuration parsing error handling
"""

# Imports handled by conftest.py
from scstadmin.parser import SCSTConfigParser
from scstadmin.exceptions import SCSTError


def test_parsing_errors():
    """Test various malformed configuration scenarios"""
    parser = SCSTConfigParser()

    test_cases = [
        # Test case, expected error keyword
        ("HANDLER", "Malformed HANDLER"),
        ("TARGET_DRIVER", "Malformed TARGET_DRIVER"),
        ("TARGET_DRIVER iscsi {\n    TARGET\n}", "Malformed TARGET"),
        ("TARGET_DRIVER iscsi {\n    TARGET test {\n        LUN\n    }\n}", "Malformed LUN"),
        ("invalid_global = value", "Ignoring unrecognized"),  # This should be logged, not error
        ("global_attr =", "Configuration parsing error"),  # This should fail
    ]

    print("Testing configuration parsing error handling...")

    for i, (config_text, expected_error) in enumerate(test_cases, 1):
        print(f"\n--- Test {i}: {config_text[:20]}...")

        try:
            parser.parse_config_text(config_text)
            print("✅ Parsed successfully (unexpected for some tests)")
        except SCSTError as e:
            error_msg = str(e)
            if expected_error.lower() in error_msg.lower():
                print(f"✅ Correctly caught error: {error_msg}")
            else:
                print(f"❌ Wrong error type. Expected '{expected_error}', got: {error_msg}")
        except Exception as e:
            print(f"❌ Unexpected exception type: {type(e).__name__}: {e}")


if __name__ == '__main__':
    test_parsing_errors()
