# file scalene/scalene_utility.py:112-121
# lines [112, 114, 115, 116, 117, 118, 119, 120, 121]
# branches ['115->116', '115->121', '116->117', '116->119']

import pytest
from scalene.scalene_utility import flamegraph_format
from scalene.scalene_statistics import StackFrame, StackStats


def test_flamegraph_format():
    stacks = {
        (StackFrame("test_file.py", "test_function", 1),): StackStats(1, 1.0, 0.5, 2)
    }
    expected_output = "test_file.py test_function:1; 1\n"
    assert flamegraph_format(stacks) == expected_output
