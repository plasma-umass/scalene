# file scalene/sparkline.py:10-21
# lines [10, 11, 12, 13, 14, 15, 16, 17, 20, 21]
# branches ['16->17', '16->20']

import pytest
from typing import List, Optional, Tuple
from scalene.sparkline import generate

def test_generate_all_zeros():
    # Test with all zeros
    arr = [0, 0, 0]
    min_val, max_val, sparkline_str = generate(arr)
    assert min_val == 0
    assert max_val == 0
    assert sparkline_str == ""

def test_generate_negative_values():
    # Test with negative values
    arr = [-1, -2, -3, 0, 1, 2, 3]
    min_val, max_val, sparkline_str = generate(arr)
    assert min_val >= 0
    assert max_val >= 0
    assert sparkline_str != ""
    # No need to assert on sparkline_str content as it's a graphical representation

@pytest.fixture(autouse=True)
def run_around_tests():
    # Setup code if needed
    yield
    # Teardown code if needed

# Run the tests
def test_generate():
    test_generate_all_zeros()
    test_generate_negative_values()
