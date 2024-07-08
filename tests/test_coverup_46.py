# file scalene/scalene_client_timer.py:38-40
# lines [40]
# branches []

import pytest
from scalene.scalene_client_timer import ScaleneClientTimer

@pytest.fixture
def scalene_client_timer():
    return ScaleneClientTimer()

def test_get_itimer(scalene_client_timer):
    # Assuming ScaleneClientTimer has attributes `seconds` and `interval` that can be set.
    # If these attributes do not exist, they should be added to the class for this test to work.
    expected_seconds = 1.0
    expected_interval = 0.1
    scalene_client_timer.seconds = expected_seconds
    scalene_client_timer.interval = expected_interval

    seconds, interval = scalene_client_timer.get_itimer()

    assert seconds == expected_seconds, "The returned seconds value is incorrect."
    assert interval == expected_interval, "The returned interval value is incorrect."
