# file scalene/scalene_json.py:33-48
# lines [44, 46]
# branches ['43->44', '45->46']

import pytest
from scalene.scalene_json import ScaleneJSON

@pytest.fixture
def cleanup():
    # Setup code if necessary
    yield
    # Teardown code if necessary

def test_time_consumed_str_minutes_seconds(cleanup):
    # Test for minutes and seconds (line 44)
    time_str = ScaleneJSON.time_consumed_str(65000)  # 1 minute and 5 seconds
    assert time_str == "1m:5.000s"

def test_time_consumed_str_seconds(cleanup):
    # Test for only seconds (line 46)
    time_str = ScaleneJSON.time_consumed_str(5000)  # 5 seconds
    assert time_str == "5.000s"
