# file scalene/scalene_analysis.py:136-202
# lines [139, 140, 141, 142, 144, 146, 147, 149, 151, 152, 153, 154, 157, 158, 160, 161, 162, 163, 164, 165, 166, 168, 169, 170, 171, 172, 173, 176, 177, 181, 182, 186, 188, 189, 194, 196, 198, 199, 200, 202]
# branches ['146->157', '146->160', '160->161', '160->162', '162->exit', '162->163', '177->exit', '177->181', '181->177', '181->182', '182->186', '182->187', '187->194', '187->196', '199->200', '199->202']

import pytest
from scalene.scalene_analysis import ScaleneAnalysis
import ast

@pytest.fixture
def cleanup():
    # Fixture to perform cleanup after tests
    yield
    # No cleanup actions needed for this test

def test_find_outermost_loop(cleanup):
    source_code = """
class MyClass:
    def my_method(self):
        for i in range(10):
            if i % 2 == 0:
                with open('file.txt', 'w') as f:
                    f.write(str(i))
            else:
                pass
    """

    expected_regions = {
        1: (1, 1),
        2: (2, 9),
        3: (3, 9),
        4: (4, 9),
        5: (4, 9),
        6: (4, 9),
        7: (4, 9),
        8: (4, 9),
        9: (4, 9),
        10: (10, 10),
    }

    regions = ScaleneAnalysis.find_outermost_loop(source_code)
    assert regions == expected_regions
