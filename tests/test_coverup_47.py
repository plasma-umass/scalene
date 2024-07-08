# file scalene/sparkline.py:56-61
# lines [61]
# branches []

import os
import pytest
from scalene.sparkline import _in_windows_terminal

@pytest.fixture
def clean_environment():
    # Backup the original environment variables
    original_environ = os.environ.copy()
    yield
    # Restore the original environment after the test
    os.environ.clear()
    os.environ.update(original_environ)

def test_in_windows_terminal_true(clean_environment):
    # Set the environment variable to simulate Windows Terminal
    os.environ["WT_PROFILE_ID"] = "some_value"
    assert _in_windows_terminal() is True

def test_in_windows_terminal_false(clean_environment):
    # Ensure the environment variable is not set
    if "WT_PROFILE_ID" in os.environ:
        del os.environ["WT_PROFILE_ID"]
    assert _in_windows_terminal() is False
