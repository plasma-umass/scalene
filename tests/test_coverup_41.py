# file scalene/runningstats.py:55-57
# lines [57]
# branches []

import pytest
from scalene.runningstats import RunningStats

@pytest.fixture
def running_stats():
    return RunningStats()

def test_size(running_stats):
    assert running_stats.size() == 0  # Initially, the size should be 0
    running_stats.push(1)
    assert running_stats.size() == 1  # After pushing one element, the size should be 1
    running_stats.push(2)
    assert running_stats.size() == 2  # After pushing another element, the size should be 2
