# file scalene/scalene_profiler.py:551-563
# lines [562, 563]
# branches []

import pytest
import signal
from scalene.scalene_profiler import Scalene
from unittest.mock import MagicMock

# Mock the __memcpy_sigq attribute in Scalene class
Scalene._Scalene__memcpy_sigq = MagicMock()

@pytest.fixture
def clean_scalene_queue():
    # Fixture to clean up the queue after the test
    yield
    Scalene._Scalene__memcpy_sigq.reset_mock()

def test_memcpy_signal_handler(clean_scalene_queue):
    # Create a fake frame object using MagicMock
    fake_frame = MagicMock(spec=[])
    # Call the signal handler with a fake signal and frame
    Scalene.memcpy_signal_handler(signal.SIGINT, fake_frame)
    # Check if the queue put method was called with the correct arguments
    Scalene._Scalene__memcpy_sigq.put.assert_called_once_with((signal.SIGINT, fake_frame))
