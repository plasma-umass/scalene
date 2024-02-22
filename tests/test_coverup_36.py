# file scalene/scalene_mapfile.py:78-81
# lines [78, 80, 81]
# branches []

import pytest
from scalene.scalene_mapfile import ScaleneMapFile

class MockScaleneMapFile(ScaleneMapFile):
    def __init__(self, buf):
        self._buf = buf

@pytest.fixture
def mock_map_file():
    buf = b"test_string\nmore_data"
    return MockScaleneMapFile(buf)

def test_get_str(mock_map_file):
    result = mock_map_file.get_str()
    assert result == "test_string", f"The get_str method returned '{result}' instead of the expected string 'test_string'."
