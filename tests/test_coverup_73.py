# file scalene/scalene_profiler.py:300-311
# lines [300, 301, 302, 308, 309, 311]
# branches []

import pytest
import signal
from scalene.scalene_profiler import Scalene

def test_interruption_handler():
    with pytest.raises(KeyboardInterrupt):
        Scalene.interruption_handler(signal.SIGINT, None)

def test_cleanup():
    # This test function is used to clean up after the test_interruption_handler
    # Since the interruption handler raises an exception, there is no state to clean up.
    pass
