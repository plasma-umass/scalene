# file scalene/scalene_utility.py:42-64
# lines [42, 43, 44, 45, 46, 47, 48, 49, 51, 52, 53, 54, 55, 56, 57, 58, 60, 61, 62, 63, 64]
# branches ['53->54', '53->57', '54->55', '54->56', '57->58', '57->60']

import pytest
from unittest.mock import MagicMock
from scalene.scalene_utility import add_stack

def test_add_stack():
    def should_trace_mock(filename, name):
        return True

    stacks = {}
    frame = MagicMock()
    code = MagicMock()
    code.co_filename = "test_file.py"
    code.co_name = "test_function"
    frame.f_code = code
    frame.f_lineno = 1
    frame.f_back = None

    # Add a stack
    add_stack(frame, should_trace_mock, stacks, 1.0, 0.5, 2)
    assert stacks == {(('test_file.py', 'test_function', 1),): (1, 1.0, 0.5, 2)}

    # Add the same stack to test the else branch
    add_stack(frame, should_trace_mock, stacks, 0.5, 0.25, 1)
    assert stacks == {(('test_file.py', 'test_function', 1),): (2, 1.5, 0.75, 3)}

# Run the test
def test_run():
    test_add_stack()
