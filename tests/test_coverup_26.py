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

@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows")
def test_enable_signals_win32(scalene_cleanup):
    with patch.object(Scalene, '_Scalene__orig_signal') as mock_orig_signal:
        with patch.object(Scalene, 'cpu_signal_handler'):
            with patch.object(Scalene, 'windows_timer_loop'):
                with patch.object(Scalene, 'start_signal_queues'):
                    Scalene.enable_signals_win32()
                    mock_orig_signal.assert_called_once()
                    assert Scalene.timer_signals is True
