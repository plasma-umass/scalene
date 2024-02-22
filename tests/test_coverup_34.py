# file scalene/sparkline.py:44-48
# lines [47]
# branches ['46->47']

import pytest
from scalene.sparkline import _get_extent

def test_get_extent_zero_extent():
    # Test to cover the case where max_ and min_ are equal, triggering the if branch
    max_val = 5.0
    min_val = 5.0
    expected_extent = 1.0
    assert _get_extent(max_val, min_val) == expected_extent, "Extent should be set to 1 when max_ and min_ are equal"
