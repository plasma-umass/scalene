# file scalene/scalene_client_timer.py:24-30
# lines [25, 26, 27, 28, 29, 30]
# branches []

import pytest
from scalene.scalene_client_timer import ScaleneClientTimer

@pytest.fixture
def timer():
    return ScaleneClientTimer()

def test_set_itimer(timer):
    seconds = 1.0
    interval = 0.1
    timer.set_itimer(seconds, interval)
    assert timer.seconds == seconds
    assert timer.interval == interval
    assert timer.remaining_seconds == seconds
    assert timer.remaining_interval == interval
    assert not timer.delay_elapsed
    assert timer.is_set
