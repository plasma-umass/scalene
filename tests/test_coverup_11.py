# file scalene/runningstats.py:12-24
# lines [12, 13, 14, 15, 16, 20, 21, 23, 24]
# branches ['14->15', '14->23']

import pytest
from scalene.runningstats import RunningStats

@pytest.fixture
def cleanup():
    # No cleanup needed for this test
    yield
    # No cleanup code required

def test_runningstats_add(cleanup):
    rs1 = RunningStats()
    rs1._n = 10
    rs1._m1 = 5.0
    rs1._peak = 7.0

    rs2 = RunningStats()
    rs2._n = 20
    rs2._m1 = 3.0
    rs2._peak = 8.0

    rs3 = rs1 + rs2

    assert rs3._n == rs1._n + rs2._n
    assert rs3._m1 == (rs1._m1 * rs1._n + rs2._m1 * rs2._n) / (rs1._n + rs2._n)
    assert rs3._peak == max(rs1._peak, rs2._peak)

    # Test when other._n is 0
    rs4 = RunningStats()
    rs4._n = 0
    rs5 = rs1 + rs4

    assert rs5 is rs1
