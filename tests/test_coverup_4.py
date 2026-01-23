# file scalene/runningstats.py:36-42
# lines [36, 38, 39, 40, 41, 42]
# branches ['38->39', '38->40']

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

    # Push another value and check if the statistics are updated correctly
    running_stats.push(20.0)
    assert running_stats._peak == 20.0
    assert running_stats._n == 2
    assert running_stats._m1 == 15.0  # mean of 10 and 20

    # Push a smaller value and check if the peak remains the same
    running_stats.push(5.0)
    assert running_stats._peak == 20.0
    assert running_stats._n == 3
    assert abs(running_stats._m1 - 35.0 / 3) < 1e-10  # mean of 10, 20, 5
