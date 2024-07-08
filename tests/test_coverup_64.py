# file scalene/sparkline.py:64-75
# lines [70]
# branches ['65->70']

import pytest
from unittest.mock import patch

# Assuming the _in_wsl and _in_windows_terminal functions are in the same module
from scalene.sparkline import _get_bars

@pytest.fixture
def cleanup():
    # Fixture to clean up any state after the test
    yield
    # No cleanup actions needed for this test

def test_get_bars_in_wsl_not_in_windows_terminal(cleanup):
    with patch('scalene.sparkline._in_wsl', return_value=True):
        with patch('scalene.sparkline._in_windows_terminal', return_value=False):
            bars = _get_bars()
            assert bars == chr(0x2584) * 2 + chr(0x25A0) * 3 + chr(0x2580) * 3
