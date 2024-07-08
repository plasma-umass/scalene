# file scalene/scalene_client_timer.py:42-64
# lines [42, 49, 50, 52, 53, 54, 55, 57, 58, 59, 60, 61, 62, 63]
# branches ['49->50', '49->57', '53->54', '53->55', '59->60', '59->61']

import pytest
from scalene.scalene_client_timer import ScaleneClientTimer
from typing import Tuple

@pytest.fixture
def scalene_client_timer():
    timer = ScaleneClientTimer()
    timer.interval = 1.0
    timer.remaining_interval = 1.0
    timer.remaining_seconds = 0.5
    timer.delay_elapsed = False
    yield timer
    # No cleanup required for this test

def test_yield_next_delay(scalene_client_timer):
    # Test the delay_elapsed branch
    scalene_client_timer.delay_elapsed = True
    is_done, next_delay = scalene_client_timer.yield_next_delay(0.3)
    assert not is_done
    assert next_delay == pytest.approx(0.7)

    is_done, next_delay = scalene_client_timer.yield_next_delay(0.7)
    assert is_done
    assert next_delay == pytest.approx(1.0)

    # Reset and test the remaining_seconds branch
    scalene_client_timer.delay_elapsed = False
    scalene_client_timer.remaining_seconds = 0.5
    is_done, next_delay = scalene_client_timer.yield_next_delay(0.3)
    assert not is_done
    assert next_delay == pytest.approx(0.2)

    is_done, next_delay = scalene_client_timer.yield_next_delay(0.2)
    assert is_done
    assert next_delay == pytest.approx(1.0)
