# file scalene/scalene_statistics.py:238-240
# lines [240]
# branches []

import time
from scalene.scalene_statistics import ScaleneStatistics
import pytest

@pytest.fixture
def scalene_statistics():
    stats = ScaleneStatistics()
    yield stats
    # No specific cleanup needed after the test

def test_start_clock(scalene_statistics):
    before_time = time.time()
    scalene_statistics.start_clock()
    after_time = time.time()
    # Assert that start_time is between before_time and after_time
    assert before_time <= scalene_statistics.start_time <= after_time
