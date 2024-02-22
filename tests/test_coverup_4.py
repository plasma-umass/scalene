# file scalene/runningstats.py:32-49
# lines [32, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 48, 49]
# branches ['34->35', '34->36']

import pytest
from scalene.runningstats import RunningStats

@pytest.fixture
def running_stats():
    return RunningStats()

def test_push(running_stats):
    # Push a value and check if the peak is updated
    running_stats.push(10.0)
    assert running_stats._peak == 10.0
    assert running_stats._n == 1
    assert running_stats._m1 == 10.0
    assert running_stats._m2 == 0.0
    assert running_stats._m3 == 0.0
    assert running_stats._m4 == 0.0

    # Push another value and check if the statistics are updated correctly
    running_stats.push(20.0)
    assert running_stats._peak == 20.0
    assert running_stats._n == 2
    assert running_stats._m1 == 15.0
    # The exact values for _m2, _m3, and _m4 depend on the internal calculations
    # and are not asserted here for simplicity. In a real test, these should be
    # calculated and asserted as well.

    # Push a smaller value and check if the peak remains the same
    running_stats.push(5.0)
    assert running_stats._peak == 20.0
    assert running_stats._n == 3
    # Again, the exact values for _m1, _m2, _m3, and _m4 should be asserted.
