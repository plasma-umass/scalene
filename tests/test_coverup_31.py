# file scalene/scalene_client_timer.py:32-36
# lines [34, 35, 36]
# branches []

import pytest
from scalene.scalene_client_timer import ScaleneClientTimer

@pytest.fixture
def timer():
    return ScaleneClientTimer()

def test_reset(timer):
    # Set attributes to non-default values
    timer.seconds = 10.0
    timer.interval = 5.0
    timer.is_set = True

    # Call the reset method
    timer.reset()

    # Check if the attributes are reset to their default values
    assert timer.seconds == 0.0
    assert timer.interval == 0.0
    assert timer.is_set == False
