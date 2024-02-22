# file scalene/scalene_statistics.py:230-236
# lines [232, 233, 234, 235, 236]
# branches []

import pytest
from scalene.scalene_statistics import ScaleneStatistics

@pytest.fixture
def scalene_statistics():
    stats = ScaleneStatistics()
    stats.current_footprint = 100
    stats.max_footprint = 200
    stats.max_footprint_loc = ("some_file.py", 10)
    stats.per_line_footprint_samples[("some_file.py", 10)] = 10
    yield stats
    # Cleanup code not necessary as the fixture will provide a fresh instance for each test

def test_clear_all(scalene_statistics):
    scalene_statistics.clear_all()
    assert scalene_statistics.current_footprint == 0
    assert scalene_statistics.max_footprint == 0
    assert scalene_statistics.max_footprint_loc is None
    assert len(scalene_statistics.per_line_footprint_samples) == 0
