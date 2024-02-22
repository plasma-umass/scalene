# file scalene/scalene_profiler.py:220-223
# lines [220, 221, 223]
# branches []

import threading
from unittest.mock import patch
import pytest
from scalene.scalene_profiler import Scalene

# Test function to cover Scalene.get_original_lock
def test_get_original_lock():
    # Setup: Patch the __original_lock attribute to return a mock lock
    mock_lock = threading.Lock()
    with patch.object(Scalene, '_Scalene__original_lock', return_value=mock_lock):
        # Execute the method
        result_lock = Scalene.get_original_lock()
        # Assert that the result is the mock lock
        assert result_lock is mock_lock

# Cleanup is handled by the context manager which restores the original state after the block
