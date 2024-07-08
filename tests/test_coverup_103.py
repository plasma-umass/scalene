# file scalene/scalene_profiler.py:895-897
# lines [895, 896, 897]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

# Create a fixture to setup the Scalene for testing
@pytest.fixture
def scalene_profiler():
    # Setup code if necessary
    yield Scalene
    # Teardown code if necessary

def test_print_stacks(capsys, scalene_profiler):
    # Assuming __stats is accessible and has a stacks attribute.
    # If it's not accessible, the test needs to be adjusted accordingly.
    # For the purpose of this test, we will mock __stats.stacks
    scalene_profiler._Scalene__stats = type('', (), {})()  # Create a mock object for __stats
    scalene_profiler._Scalene__stats.stacks = ["stack1", "stack2"]
    scalene_profiler.print_stacks()
    captured = capsys.readouterr()
    assert "stack1" in captured.out
    assert "stack2" in captured.out
