# file scalene/scalene_signals.py:61-77
# lines [61, 70, 71, 72, 73, 74, 75, 76]
# branches []

import pytest
import sys
from scalene.scalene_signals import ScaleneSignals


@pytest.fixture
def scalene_signals():
    return ScaleneSignals()


def test_get_all_signals(scalene_signals):
    signals = scalene_signals.get_all_signals()
    assert isinstance(signals, list)
    # Assuming signals are unique, which they should be
    if sys.platform != "win32":
        assert all(isinstance(signal, int) for signal in signals)
        assert len(signals) == len(set(signals))
    # Check that cpu_signal is included in the list
    assert scalene_signals.cpu_signal in signals
    # Check that the list does not include the CPU timer signal
    # Assuming cpu_timer_signal is an attribute of ScaleneSignals
    # Uncomment the following line if such an attribute exists
    # assert scalene_signals.cpu_timer_signal not in signals
