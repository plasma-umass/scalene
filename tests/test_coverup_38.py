# file scalene/scalene_mapfile.py:12-18
# lines [12, 17]
# branches []

import pytest
from scalene.scalene_mapfile import ScaleneMapFile

def test_scalene_mapfile_max_bufsize():
    # Test to ensure the MAX_BUFSIZE constant is accessible and correct.
    assert ScaleneMapFile.MAX_BUFSIZE == 256

# Cleanup is not necessary for this test as it does not create any side effects.
