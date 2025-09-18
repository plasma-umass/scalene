# file scalene/scalene_profiler.py:565-579
# lines [565, 566, 567, 568, 569, 570, 571, 574, 575, 576, 577, 578, 579]
# branches []

import pytest
import sys
import threading
from unittest.mock import patch
from scalene.scalene_profiler import Scalene


@pytest.fixture(scope="function")
def scalene_cleanup():
    # Fixture to clean up state after tests
    yield
    Scalene.__windows_queue = None
    Scalene.timer_signals = False
