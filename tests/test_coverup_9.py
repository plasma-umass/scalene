# file scalene/scalene_signals.py:32-48
# lines [32, 39, 40, 41, 42, 43, 44, 45, 47, 48]
# branches ['39->40', '39->43', '43->44', '43->47']

import pytest
import signal
import sys
from scalene.scalene_signals import ScaleneSignals

@pytest.fixture
def scalene_signals():
    return ScaleneSignals()

def test_set_timer_signals_virtual_time(scalene_signals):
    if sys.platform != "win32":
        scalene_signals.set_timer_signals(use_virtual_time=True)
        assert scalene_signals.cpu_timer_signal == signal.ITIMER_VIRTUAL
        assert scalene_signals.cpu_signal == signal.SIGVTALRM

def test_set_timer_signals_real_time(scalene_signals):
    if sys.platform != "win32":
        scalene_signals.set_timer_signals(use_virtual_time=False)
        assert scalene_signals.cpu_timer_signal == signal.ITIMER_REAL
        assert scalene_signals.cpu_signal == signal.SIGALRM

def test_set_timer_signals_windows(scalene_signals, monkeypatch):
    if hasattr(signal, "SIGBREAK"):
        monkeypatch.setattr(sys, "platform", "win32")
        scalene_signals.set_timer_signals()
        assert scalene_signals.cpu_signal == signal.SIGBREAK
        assert scalene_signals.cpu_timer_signal is None
