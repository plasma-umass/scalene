# file scalene/scalene_leak_analysis.py:6-45
# lines [21, 22, 23, 24, 25, 27, 28, 31, 34, 35, 37, 38, 39, 40, 41, 42, 45]
# branches ['21->22', '21->23', '25->27', '25->45', '33->25', '33->37', '37->25', '37->38']

import pytest
from collections import OrderedDict
from typing import Any, List
from scalene.scalene_statistics import ScaleneStatistics
from scalene.scalene_leak_analysis import ScaleneLeakAnalysis

class Filename(str):
    pass

class LineNumber(int):
    pass

@pytest.fixture
def scalene_statistics():
    stats = ScaleneStatistics()
    fname = Filename("test_file.py")
    line_number = LineNumber(1)
    stats.leak_score[fname][line_number] = (100, 1)  # 100 allocs, 1 free
    return stats

def test_compute_leaks(scalene_statistics):
    stats = scalene_statistics
    fname = Filename("test_file.py")
    avg_mallocs = OrderedDict({LineNumber(1): 50.0})
    growth_rate = 2.0  # 2% growth rate to exceed the threshold

    leaks = ScaleneLeakAnalysis.compute_leaks(growth_rate, stats, avg_mallocs, fname)

    assert len(leaks) == 1
    assert leaks[0][0] == LineNumber(1)  # Line number
    assert leaks[0][1] == 1.0 - (1 + 1) / (100 - 1 + 2)  # Expected leak
    assert leaks[0][2] == 50.0  # Average mallocs

    # Cleanup is not necessary as the test does not modify any global state
