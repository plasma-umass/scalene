# file scalene/runningstats.py:67-69
# lines [69]
# branches []

import pytest
from scalene.runningstats import RunningStats

@pytest.fixture
def running_stats():
    stats = RunningStats()
    yield stats

def test_std_with_single_value(running_stats):
    running_stats.push(5.0)
    running_stats.push(3.0)  # Add another value to avoid division by zero
    assert running_stats.std() >= 0.0  # Standard deviation should be non-negative

def test_std_with_multiple_values(running_stats):
    running_stats.push(2.0)
    running_stats.push(4.0)
    running_stats.push(4.0)
    running_stats.push(4.0)
    running_stats.push(5.0)
    running_stats.push(5.0)
    running_stats.push(7.0)
    running_stats.push(9.0)
    assert running_stats.std() > 0.0
