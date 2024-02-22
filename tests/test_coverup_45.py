# file scalene/scalene_utility.py:112-121
# lines [112, 114, 115, 116, 117, 118, 119, 120, 121]
# branches ['115->116', '115->121', '116->117', '116->119']

import pytest
from scalene.scalene_utility import flamegraph_format

def test_flamegraph_format():
    stacks = {
        (('file1.py', 'function1', 10), ('file2.py', 'function2', 20)): [1],
        (('file3.py', 'function3', 30),): [2]
    }
    expected_output = (
        "file1.py function1:10;file2.py function2:20; 1\n"
        "file3.py function3:30; 2\n"
    )
    assert flamegraph_format(stacks) == expected_output
