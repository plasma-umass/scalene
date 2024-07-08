# file scalene/scalene_profiler.py:375-378
# lines [375, 376, 378]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

@pytest.fixture
def scalene_cleanup():
    # Fixture to clean up any modifications made to the Scalene class
    original_child_pids = Scalene.child_pids.copy()
    yield
    Scalene.child_pids = original_child_pids

def test_add_child_pid(scalene_cleanup):
    # Test to ensure that add_child_pid adds a pid to the child_pids set
    test_pid = 12345
    assert test_pid not in Scalene.child_pids
    Scalene.add_child_pid(test_pid)
    assert test_pid in Scalene.child_pids
