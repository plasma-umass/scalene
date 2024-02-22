# file scalene/scalene_utility.py:21-26
# lines [23, 24, 25, 26]
# branches []

import pytest
from scalene.scalene_utility import LineNo
import inspect

# Test function to cover lines 23-26
def test_line_no_str():
    lineno = LineNo()
    # Get the current frame and check the line number before calling str(lineno)
    current_frame = inspect.currentframe()
    assert current_frame is not None
    # The line number should be the line where `str(lineno)` will be called
    expected_line_no = current_frame.f_lineno + 1
    lineno_str = str(lineno)
    assert lineno_str == str(expected_line_no)

# Clean up is not necessary as we are not modifying any global state
