# file scalene/scalene_mapfile.py:19-53
# lines [20, 21, 23, 24, 26, 27, 29, 30, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 48, 49, 50, 51, 52]
# branches []

import os
import mmap
import pytest
from scalene.scalene_mapfile import ScaleneMapFile

@pytest.fixture
def cleanup_files():
    # Setup code to create filenames
    name = "test_mapfile"
    signal_filename = f"/tmp/scalene-{name}-signal{os.getpid()}"
    lock_filename = f"/tmp/scalene-{name}-lock{os.getpid()}"
    init_filename = f"/tmp/scalene-{name}-init{os.getpid()}"

    # Create files with some content for the test
    with open(signal_filename, 'wb') as f:
        f.write(b'\0' * mmap.PAGESIZE)
    with open(lock_filename, 'wb') as f:
        f.write(b'\0' * mmap.PAGESIZE)
    with open(init_filename, 'wb') as f:
        f.write(b'\0' * mmap.PAGESIZE)

    yield signal_filename, lock_filename, init_filename

    # Cleanup code to remove files
    if os.path.exists(signal_filename):
        os.remove(signal_filename)
    if os.path.exists(lock_filename):
        os.remove(lock_filename)
    if os.path.exists(init_filename):
        os.remove(init_filename)

def test_scalene_mapfile(cleanup_files):
    signal_filename, lock_filename, init_filename = cleanup_files
    mapfile = ScaleneMapFile("test_mapfile")

    # Assertions to ensure that the mapfile object is initialized correctly
    assert mapfile._name == "test_mapfile"
    assert mapfile._signal_filename == signal_filename
    assert mapfile._lock_filename == lock_filename
    assert mapfile._init_filename == init_filename
    assert mapfile._signal_position == 0
    assert isinstance(mapfile._signal_mmap, mmap.mmap)
    assert isinstance(mapfile._lock_mmap, mmap.mmap)

    # Check that the files are unlinked (do not exist)
    assert not os.path.exists(signal_filename)
    assert not os.path.exists(lock_filename)
    # The init file is not unlinked by the __init__ method, so it should still exist
    assert os.path.exists(init_filename)
