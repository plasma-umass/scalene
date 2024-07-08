# file scalene/scalene_profiler.py:1688-1697
# lines [1688, 1689, 1691, 1693, 1694, 1695, 1696, 1697]
# branches ['1694->1695', '1694->1696']

import os
import pytest
import tempfile
from scalene.scalene_profiler import Scalene

# Test function to improve coverage for Scalene.exit_handler
def test_exit_handler_cleanup(monkeypatch):
    # Setup a temporary directory and patch Scalene to use it
    temp_dir = tempfile.TemporaryDirectory()
    monkeypatch.setattr(Scalene, '_Scalene__python_alias_dir', temp_dir, raising=False)
    monkeypatch.setattr(Scalene, '_Scalene__pid', 0)  # Ensure the cleanup code runs

    # Create a temporary file to simulate the malloc lock file
    malloc_lock_file = f"/tmp/scalene-malloc-lock{os.getpid()}"
    with open(malloc_lock_file, 'w') as f:
        f.write('')

    # Ensure the malloc lock file exists before calling the exit handler
    assert os.path.exists(malloc_lock_file)

    # Call the exit handler
    Scalene.exit_handler()

    # Check that the malloc lock file was removed
    assert not os.path.exists(malloc_lock_file)

    # Cleanup
    temp_dir.cleanup()
