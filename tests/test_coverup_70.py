# file scalene/scalene_utility.py:29-35
# lines [29, 30, 31, 32, 33, 34, 35]
# branches []

import pytest
from scalene.scalene_utility import FileName
import inspect

def test_FileName_str():
    # Setup: None required for this test

    # Exercise: Create an instance of FileName and convert to string
    file_name_instance = FileName()
    file_name_str = str(file_name_instance)

    # Verify: Check if the returned string is the filename of this test script
    current_frame = inspect.currentframe()
    assert current_frame is not None
    expected_filename = current_frame.f_code.co_filename
    assert file_name_str == expected_filename

    # Cleanup: None required for this test

# Run the test
def test_wrapper():
    test_FileName_str()
