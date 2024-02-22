# file scalene/scalene_profiler.py:879-893
# lines [884]
# branches ['883->884']

import pytest
from scalene.scalene_profiler import Scalene

@pytest.fixture
def scalene_cleanup():
    # Store original state
    original_files_to_profile = Scalene._Scalene__files_to_profile.copy()
    yield
    # Restore original state after test
    Scalene._Scalene__files_to_profile = original_files_to_profile

def test_profile_this_code_without_files_to_profile(scalene_cleanup):
    # Ensure __files_to_profile is empty
    Scalene._Scalene__files_to_profile.clear()
    # Call the method with arbitrary arguments
    result = Scalene.profile_this_code("somefile.py", 10)
    # Assert that the result is True when __files_to_profile is empty
    assert result == True
