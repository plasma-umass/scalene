# file scalene/scalene_mapfile.py:55-58
# lines [55, 57, 58]
# branches []

import os
import pytest
from scalene.scalene_mapfile import ScaleneMapFile

class MockScaleneMapFile(ScaleneMapFile):
    def __init__(self, name: str) -> None:
        self._name = name
        self._signal_fd = None
        self._lock_fd = None

@pytest.fixture
def scalene_mapfile(tmp_path):
    # Setup: create a mock ScaleneMapFile instance
    mapfile = MockScaleneMapFile(name=str(tmp_path))
    signal_fd_path = tmp_path / "signal_fd"
    lock_fd_path = tmp_path / "lock_fd"
    # Create temporary files to act as signal_fd and lock_fd
    with open(signal_fd_path, "wb") as signal_fd, open(lock_fd_path, "wb") as lock_fd:
        mapfile._signal_fd = signal_fd
        mapfile._lock_fd = lock_fd
        yield mapfile
    # Teardown: files will be closed and removed by the fixture system

def test_close_scalene_mapfile(scalene_mapfile):
    # Precondition: file descriptors should be open
    assert not scalene_mapfile._signal_fd.closed
    assert not scalene_mapfile._lock_fd.closed

    # Action: close the map file
    scalene_mapfile.close()

    # Postcondition: file descriptors should be closed
    assert scalene_mapfile._signal_fd.closed
    assert scalene_mapfile._lock_fd.closed
