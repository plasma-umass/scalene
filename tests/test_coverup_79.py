# file scalene/scalene_statistics.py:386-394
# lines [392, 393, 394]
# branches ['392->exit', '392->393', '393->392', '393->394']

import pytest
from scalene.scalene_statistics import ScaleneStatistics
from collections import defaultdict

class RunningStats:
    def __init__(self, cpu_samples=0, malloc_samples=0, free_samples=0, python_fraction=0):
        self.cpu_samples = cpu_samples
        self.malloc_samples = malloc_samples
        self.free_samples = free_samples
        self.python_fraction = python_fraction

    def __iadd__(self, other):
        self.cpu_samples += other.cpu_samples
        self.malloc_samples += other.malloc_samples
        self.free_samples += other.free_samples
        self.python_fraction += other.python_fraction
        return self

Filename = str
LineNumber = int

@pytest.fixture
def cleanup():
    # Setup code if necessary
    yield
    # Cleanup code if necessary

def test_increment_core_utilization(cleanup):
    dest = {
        Filename("file1"): {LineNumber(1): RunningStats(), LineNumber(2): RunningStats()},
        Filename("file2"): {LineNumber(1): RunningStats()}
    }
    src = {
        Filename("file1"): {LineNumber(1): RunningStats(1, 1, 1, 1), LineNumber(2): RunningStats(2, 2, 2, 2)},
        Filename("file2"): {LineNumber(1): RunningStats(3, 3, 3, 3)}
    }

    ScaleneStatistics.increment_core_utilization(dest, src)

    # Assertions to verify postconditions
    assert dest[Filename("file1")][LineNumber(1)].cpu_samples == 1
    assert dest[Filename("file1")][LineNumber(2)].cpu_samples == 2
    assert dest[Filename("file2")][LineNumber(1)].cpu_samples == 3

    # Cleanup is handled by the fixture
