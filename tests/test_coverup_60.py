# file scalene/scalene_analysis.py:136-202
# lines [196]
# branches ['187->196']

import pytest
from scalene.scalene_analysis import ScaleneAnalysis

@pytest.fixture
def cleanup():
    # Fixture to perform cleanup after tests
    yield
    # No cleanup actions needed for this test

def test_find_outermost_loop_single_line(cleanup):
    src = "x = 1"
    result = ScaleneAnalysis.find_outermost_loop(src)
    assert result == {1: (1, 1)}, "The result should map line 1 to region (1, 1)"
