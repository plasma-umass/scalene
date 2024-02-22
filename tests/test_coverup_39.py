# file scalene/runningstats.py:59-61
# lines [61]
# branches []

import pytest
from scalene.runningstats import RunningStats

def test_running_stats_mean():
    stats = RunningStats()
    stats.push(1)
    stats.push(2)
    stats.push(3)
    mean_value = stats.mean()
    assert mean_value == 2, "Mean value should be 2 for the given inputs"
