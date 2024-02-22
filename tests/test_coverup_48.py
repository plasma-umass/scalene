# file scalene/runningstats.py:63-65
# lines [65]
# branches []

import pytest
from scalene.runningstats import RunningStats

def test_running_stats_variance():
    stats = RunningStats()
    stats.push(1.0)
    stats.push(2.0)
    # Pushing more than one value to ensure n > 1 for variance calculation
    variance = stats.var()
    # Variance of [1.0, 2.0] is 0.5
    assert variance == 0.5, "Variance calculation is incorrect."

def test_running_stats_variance_with_single_value():
    stats = RunningStats()
    stats.push(1.0)
    # Expecting an exception because variance cannot be computed with a single value
    with pytest.raises(ZeroDivisionError):
        _ = stats.var()
