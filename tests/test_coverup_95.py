# file scalene/scalene_profiler.py:1624-1627
# lines [1624, 1625, 1627]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

@pytest.fixture(scope="function")
def scalene_cleanup():
    # Setup: None needed for this test
    yield
    # Teardown: Reset the __done flag to False after the test
    Scalene._Scalene__done = False

def test_is_done(scalene_cleanup):
    # Initially, __done should be False
    assert not Scalene.is_done()
    # Set the __done flag to True to simulate the end of profiling
    Scalene._Scalene__done = True
    # Now, is_done should return True
    assert Scalene.is_done()
