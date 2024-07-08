# file scalene/scalene_profiler.py:380-384
# lines [380, 381, 383, 384]
# branches []

import pytest
from scalene.scalene_profiler import Scalene

# Test function to improve coverage for Scalene.remove_child_pid
def test_remove_child_pid():
    # Setup: Add a pid to the child_pids set
    test_pid = 12345
    Scalene.child_pids.add(test_pid)
    assert test_pid in Scalene.child_pids  # Precondition check

    # Exercise: Remove the pid
    Scalene.remove_child_pid(test_pid)

    # Verify: Check that the pid was removed
    assert test_pid not in Scalene.child_pids

    # Cleanup: No cleanup needed as the pid was already removed

# Test function to cover the case where the pid does not exist
def test_remove_nonexistent_child_pid():
    # Setup: Ensure the pid is not in the child_pids set
    test_pid = 54321
    Scalene.child_pids.discard(test_pid)  # Ensure pid is not present
    assert test_pid not in Scalene.child_pids  # Precondition check

    # Exercise: Attempt to remove a non-existent pid
    Scalene.remove_child_pid(test_pid)  # Should not raise an exception

    # Verify: Check that the pid is still not in the set
    assert test_pid not in Scalene.child_pids

    # Cleanup: No cleanup needed as the pid was not in the set to begin with
