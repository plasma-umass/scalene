# file scalene/scalene_profiler.py:1828-1831
# lines [1828, 1829, 1831]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

@pytest.fixture(scope="function")
def scalene_cleanup(monkeypatch):
    # Fixture to reset the state after the test
    # Store the original state
    original_state = getattr(Scalene, '_Scalene__initialized', False)
    yield
    # Restore the original state
    monkeypatch.setattr(Scalene, '_Scalene__initialized', original_state)

def test_set_initialized(scalene_cleanup, monkeypatch):
    # Set Scalene as not initialized
    monkeypatch.setattr(Scalene, '_Scalene__initialized', False)
    # Call the method to set Scalene as initialized
    Scalene.set_initialized()
    # Check if Scalene is now initialized
    assert getattr(Scalene, '_Scalene__initialized') == True
