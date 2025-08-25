# file scalene/scalene_profiler.py:895-897
# lines [895, 896, 897]
# branches []

import pytest
from scalene.scalene_profiler import Scalene
from scalene.scalene_statistics import StackFrame, StackStats


# Create a fixture to setup the Scalene for testing
@pytest.fixture
def scalene_profiler():
    # Setup code if necessary
    yield Scalene
    # Teardown code if necessary


def test_print_stacks(capsys, scalene_profiler):
    # Create test stacks
    stack1 = StackFrame("test_file1.py", "test_function1", 1)
    stack2 = StackFrame("test_file2.py", "test_function2", 2)
    stats1 = StackStats(1, 1.0, 0.5, 2)
    stats2 = StackStats(2, 2.0, 1.0, 4)

    # Set up test data
    scalene_profiler._Scalene__stats.stacks = {(stack1,): stats1, (stack2,): stats2}

    # Call the function
    scalene_profiler.print_stacks()

    # Capture the output
    captured = capsys.readouterr()

    # Verify the output contains the expected stack information
    assert "test_file1.py" in captured.out
    assert "test_function1" in captured.out
    assert "test_file2.py" in captured.out
    assert "test_function2" in captured.out
