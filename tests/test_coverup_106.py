# file scalene/scalene_profiler.py:282-288
# lines [282, 283, 288]
# branches []

import pytest
import signal
from scalene.scalene_profiler import Scalene

@pytest.fixture(scope="function")
def cleanup_signals():
    # Store the original signal state
    original_signals = Scalene.get_timer_signals()
    yield
    # Restore the original signal state after the test
    signal.signal(original_signals[0], signal.SIG_IGN)

def test_get_timer_signals(cleanup_signals):
    # Set a timer signal to test
    signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
    # Call the method to test
    timer_signals = Scalene.get_timer_signals()
    # Check if the signal.SIGVTALRM is in the returned tuple
    assert signal.SIGVTALRM in timer_signals
    # Check if the returned tuple only contains timer signals
    assert isinstance(timer_signals[0], int)
    assert isinstance(timer_signals[1], signal.Signals)
