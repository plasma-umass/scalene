# file scalene/scalene_profiler.py:313-316
# lines [313, 314, 316]
# branches []

import pytest
import scalene.scalene_config
from scalene.scalene_profiler import Scalene

@pytest.fixture(autouse=True)
def run_around_tests():
    # Setup: Store original value
    original_trigger_length = scalene.scalene_config.NEWLINE_TRIGGER_LENGTH
    # Give a new value for the test
    scalene.scalene_config.NEWLINE_TRIGGER_LENGTH = 1
    yield
    # Teardown: Restore original value
    scalene.scalene_config.NEWLINE_TRIGGER_LENGTH = original_trigger_length

def test_update_line():
    # Call the method to test
    Scalene.update_line()
    # No direct postconditions to assert; the function's purpose is to trigger memory allocation
    # We can only assert that no exception was raised
    assert True
