# file scalene/scalene_statistics.py:376-384
# lines [382, 383, 384]
# branches ['382->exit', '382->383', '383->382', '383->384']

import pytest
from scalene.scalene_statistics import ScaleneStatistics, RunningStats

class MockRunningStats(RunningStats):
    def __init__(self):
        super().__init__()
        self.total = 0

    def __iadd__(self, other):
        self.total += other.total
        return self

@pytest.fixture
def cleanup():
    # Setup code
    yield
    # No teardown code needed for this test

def test_increment_cpu_utilization(cleanup):
    dest = {
        "file1.py": {1: MockRunningStats(), 2: MockRunningStats()},
        "file2.py": {1: MockRunningStats()}
    }
    src = {
        "file1.py": {1: MockRunningStats(), 2: MockRunningStats()},
        "file2.py": {1: MockRunningStats()}
    }

    # Simulate some CPU utilization
    src["file1.py"][1].total += 0.5
    src["file1.py"][2].total += 0.3
    src["file2.py"][1].total += 0.2

    ScaleneStatistics.increment_cpu_utilization(dest, src)

    # Assertions to check if the CPU utilization has been incremented correctly
    assert dest["file1.py"][1].total == 0.5
    assert dest["file1.py"][2].total == 0.3
    assert dest["file2.py"][1].total == 0.2
