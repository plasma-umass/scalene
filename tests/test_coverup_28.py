# file scalene/time_info.py:8-13
# lines [8, 9, 10, 11, 12, 13]
# branches []

import pytest
from scalene.time_info import TimeInfo

@pytest.fixture
def time_info():
    return TimeInfo(virtual=1.0, wallclock=2.0, sys=3.0, user=4.0)

def test_time_info_attributes(time_info):
    assert time_info.virtual == 1.0
    assert time_info.wallclock == 2.0
    assert time_info.sys == 3.0
    assert time_info.user == 4.0

def test_time_info_defaults():
    default_time_info = TimeInfo()
    assert default_time_info.virtual == 0.0
    assert default_time_info.wallclock == 0.0
    assert default_time_info.sys == 0.0
    assert default_time_info.user == 0.0
