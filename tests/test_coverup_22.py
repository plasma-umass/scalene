# file scalene/time_info.py:16-29
# lines [16, 17, 20, 22, 23, 24, 26, 27, 28, 29]
# branches ['17->20', '17->26']

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Assuming the function get_times is in the module scalene.time_info
from scalene.time_info import get_times

class MockResourceUsage:
    def __init__(self, stime, utime):
        self.ru_stime = stime
        self.ru_utime = utime

@pytest.fixture
def mock_resource_module():
    with patch("resource.getrusage", return_value=MockResourceUsage(1.23, 4.56)) as mock_resource:
        yield mock_resource

def test_get_times_linux_mac(mock_resource_module):
    if sys.platform == "win32":
        pytest.skip("This test is for Linux/Mac platforms only.")
    now_sys, now_user = get_times()
    assert now_sys == 1.23
    assert now_user == 4.56

@pytest.fixture
def mock_os_times():
    with patch("os.times", return_value=MagicMock(system=2.34, user=5.67)) as mock_times:
        yield mock_times

def test_get_times_win32(mock_os_times):
    with patch("sys.platform", "win32"):
        now_sys, now_user = get_times()
        assert now_sys == 2.34
        assert now_user == 5.67
