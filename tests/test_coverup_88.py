# file scalene/scalene_profiler.py:290-293
# lines [290, 291, 293]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

@pytest.fixture(scope="function")
def scalene_cleanup():
    # Fixture to reset the state after the test
    original_in_jupyter = Scalene._Scalene__in_jupyter
    yield
    Scalene._Scalene__in_jupyter = original_in_jupyter

def test_set_in_jupyter(scalene_cleanup):
    # Ensure that __in_jupyter is initially False
    assert not Scalene._Scalene__in_jupyter
    # Call the method to set __in_jupyter to True
    Scalene.set_in_jupyter()
    # Check if __in_jupyter is now True
    assert Scalene._Scalene__in_jupyter
