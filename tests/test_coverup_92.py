# file scalene/scalene_profiler.py:118-121
# lines [118, 119, 120, 121]
# branches []

import sys
from unittest.mock import patch
import pytest

# Assuming the correct import based on the error message
from scalene import scalene_profiler

def test_require_python():
    # Save the original version info
    original_version_info = sys.version_info

    # Test with a version that should pass
    with patch.object(sys, 'version_info', (3, 8)):
        scalene_profiler.require_python((3, 6))  # Should not raise an assertion error

    # Test with a version that should fail and raise an assertion error
    with patch.object(sys, 'version_info', (3, 5)), pytest.raises(AssertionError):
        scalene_profiler.require_python((3, 6))

    # Clean up by restoring the original version info
    sys.version_info = original_version_info

# Ensure that the test does not affect other tests by checking the version after the test
def test_version_info_unchanged():
    assert sys.version_info >= (3, 6), "sys.version_info should be unchanged after tests"
