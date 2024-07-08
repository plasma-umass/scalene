# file scalene/runningstats.py:51-53
# lines [53]
# branches []

import pytest
from scalene.runningstats import RunningStats

def test_peak():
    stats = RunningStats()
    stats.push(10)
    stats.push(20)
    stats.push(5)
    assert stats.peak() == 20, "The peak value should be the maximum value pushed"

    # Clean up
    del stats
