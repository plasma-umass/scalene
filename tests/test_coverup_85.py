# file scalene/scalene_json.py:70-90
# lines [81, 83, 85, 87, 88, 90]
# branches ['73->81', '85->87', '85->90']

import pytest
from scalene.scalene_json import ScaleneJSON
from typing import List, Any
import random

class MockScaleneJSON(ScaleneJSON):
    def __init__(self, max_sparkline_samples):
        self.max_sparkline_samples = max_sparkline_samples

@pytest.fixture
def mock_scalene_json():
    return MockScaleneJSON(max_sparkline_samples=10)

def test_compress_samples_exceeds_max_samples(mock_scalene_json):
    # Generate a list of samples that exceeds the max_sparkline_samples
    # Each sample needs to be a tuple with two elements (x, y) to be subscriptable, as expected by rdp
    samples = [(i, random.random()) for i in range(100)]  # 100 is arbitrary, but should be > max_sparkline_samples * 3
    compressed_samples = mock_scalene_json.compress_samples(samples, max_footprint=0)
    assert len(compressed_samples) <= mock_scalene_json.max_sparkline_samples
    # Check that the compressed samples are sorted by the first element of the tuple
    assert compressed_samples == sorted(compressed_samples, key=lambda x: x[0])
    # Clean up
    del mock_scalene_json
