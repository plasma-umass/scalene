# file scalene/scalene_statistics.py:365-374
# lines [371, 372, 373, 374]
# branches ['371->exit', '371->372', '372->371', '372->373']

import pytest
from scalene.scalene_statistics import ScaleneStatistics
from typing import Dict

@pytest.fixture
def cleanup():
    # Fixture to clean up any changes after the test
    yield
    # No specific cleanup code needed as the test does not modify any global state

def test_increment_per_line_samples(cleanup):
    # Define the source and destination dictionaries
    src = {
        "file1.py": {1: 10, 2: 20},
        "file2.py": {1: 5}
    }
    dest = {
        "file1.py": {1: 1, 2: 2},
        "file2.py": {1: 0}
    }
    
    # Expected result after incrementing
    expected_dest = {
        "file1.py": {1: 11, 2: 22},
        "file2.py": {1: 5}
    }
    
    # Call the method to test
    ScaleneStatistics.increment_per_line_samples(dest, src)
    
    # Assert that the destination has been correctly incremented
    assert dest == expected_dest
