# file scalene/scalene_signals.py:50-59
# lines [59]
# branches []

import pytest
import signal
from scalene.scalene_signals import ScaleneSignals

@pytest.fixture
def scalene_signals():
    return ScaleneSignals()

def test_get_timer_signals(scalene_signals):
    cpu_timer_signal, cpu_signal = scalene_signals.get_timer_signals()
    assert isinstance(cpu_timer_signal, int)
    assert isinstance(cpu_signal, signal.Signals)
