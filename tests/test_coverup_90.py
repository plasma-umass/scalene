# file scalene/scalene_profiler.py:295-298
# lines [295, 296, 298]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

# Test function to check if Scalene.in_jupyter() returns the correct value
def test_in_jupyter(monkeypatch):
    # Set up the environment to simulate running inside Jupyter
    monkeypatch.setattr(Scalene, '_Scalene__in_jupyter', True)
    assert Scalene.in_jupyter() is True

    # Clean up by setting the environment to simulate not running inside Jupyter
    monkeypatch.setattr(Scalene, '_Scalene__in_jupyter', False)
    assert Scalene.in_jupyter() is False
