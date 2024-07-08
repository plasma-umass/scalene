# file scalene/scalene_analysis.py:101-134
# lines [133]
# branches ['130->133']

import pytest
from scalene.scalene_analysis import ScaleneAnalysis

def test_find_regions_with_no_classes_functions_or_loops():
    source_code = """
# This is a simple script with no classes, functions, or loops.
x = 1
y = 2
z = x + y
print(z)
""".strip()
    expected_regions = {1: (1, 1), 2: (2, 2), 3: (3, 3), 4: (4, 4), 5: (5, 5)}
    regions = ScaleneAnalysis.find_regions(source_code)
    assert regions == expected_regions
