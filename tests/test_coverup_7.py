# file scalene/scalene_signals.py:13-30
# lines [13, 15, 17, 18, 19, 20, 22, 23, 26, 27, 28, 29, 30]
# branches ['17->18', '17->26']

import pytest
import signal
import sys
from unittest.mock import patch

# Assuming the ScaleneSignals class is in a module named scalene_signals
from scalene.scalene_signals import ScaleneSignals

@pytest.fixture
def mock_sys_platform_win32():
    with patch("sys.platform", "win32"):
        yield

@pytest.fixture
def mock_signal_module_win32():
    with patch("signal.SIGBREAK", create=True):
        yield

def test_scalene_signals_windows(mock_sys_platform_win32, mock_signal_module_win32):
    signals = ScaleneSignals()
    assert signals.start_profiling_signal is None
    assert signals.stop_profiling_signal is None
    assert signals.memcpy_signal is None
    assert signals.malloc_signal is None
    assert signals.free_signal is None

def test_scalene_signals_non_windows():
    if sys.platform == "win32":
        pytest.skip("This test is not for Windows platform")
    signals = ScaleneSignals()
    assert signals.start_profiling_signal == signal.SIGILL
    assert signals.stop_profiling_signal == signal.SIGBUS
    assert signals.memcpy_signal == signal.SIGPROF
    assert signals.malloc_signal == signal.SIGXCPU
    assert signals.free_signal == signal.SIGXFSZ
