# file scalene/scalene_profiler.py:868-877
# lines [873, 874, 875, 877]
# branches []

import pytest
from scalene.scalene_profiler import Scalene
from types import FunctionType

# Create a dummy function to profile
def dummy_function():
    pass

# Add the dummy function to the __functions_to_profile dictionary
Scalene._Scalene__functions_to_profile = {'dummy_file.py': [dummy_function]}

@pytest.fixture
def cleanup_scalene():
    # Fixture to clean up changes made to the Scalene class
    yield
    # Remove the dummy function from the __functions_to_profile dictionary
    Scalene._Scalene__functions_to_profile.pop('dummy_file.py', None)

def test_get_line_info(cleanup_scalene):
    # Test the get_line_info method to ensure it covers the missing lines
    line_info_gen = Scalene.get_line_info('dummy_file.py')
    line_info = next(line_info_gen)
    assert isinstance(line_info, tuple)
    assert isinstance(line_info[0], list)
    assert isinstance(line_info[1], int)
    # The line number where dummy_function is defined might not be 1
    # So we check if the first line of the source code is the definition of dummy_function
    assert line_info[0][0].strip() == 'def dummy_function():'
