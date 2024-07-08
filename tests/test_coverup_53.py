# file scalene/scalene_profiler.py:1808-1826
# lines [1808, 1809, 1811, 1812, 1813, 1815, 1816, 1817, 1818, 1820, 1822, 1824, 1825, 1826]
# branches ['1816->1817', '1816->1820', '1824->exit', '1824->1825']

import argparse
import os
import pytest
import time
from unittest.mock import patch
from scalene.scalene_profiler import Scalene, ScaleneArguments

# Define a fixture to clean up state after each test
@pytest.fixture
def cleanup_scalene():
    # Setup: None needed for this test
    yield
    # Teardown: Reset class variables to initial state
    # Assuming that Scalene has a method to clean up its state, which is not the case
    # We need to manually reset the state if there are no such methods
    # The following is a placeholder for the actual reset logic
    # Replace with the actual reset logic if available
    if hasattr(Scalene, '_Scalene__args'):
        del Scalene._Scalene__args
    if hasattr(Scalene, '_Scalene__next_output_time'):
        del Scalene._Scalene__next_output_time
    if hasattr(Scalene, '_Scalene__output'):
        del Scalene._Scalene__output
    if hasattr(Scalene, '_Scalene__is_child'):
        del Scalene._Scalene__is_child
    if hasattr(Scalene, '_Scalene__parent_pid'):
        del Scalene._Scalene__parent_pid
    if hasattr(Scalene, '_Scalene__json'):
        del Scalene._Scalene__json

def test_process_args(cleanup_scalene):
    # Create a Namespace object with the necessary attributes
    args = argparse.Namespace(
        profile_interval=1,
        html=False,
        outfile='test_output.txt',
        pid=12345,
        gpu=False
    )

    # Mock time.perf_counter to return a known value
    with patch('time.perf_counter', return_value=100):
        # Call the method under test
        Scalene.process_args(args)

        # Assertions to verify postconditions
        # Accessing the private attributes directly for testing purposes
        assert Scalene._Scalene__args == args
        assert Scalene._Scalene__next_output_time == 101  # 100 + 1
        assert Scalene._Scalene__output.html == args.html
        assert Scalene._Scalene__output.output_file == os.path.abspath(os.path.expanduser(args.outfile))
        assert Scalene._Scalene__is_child == True
        assert Scalene._Scalene__parent_pid == args.pid
        assert not Scalene._Scalene__output.gpu
        assert not Scalene._Scalene__json.gpu

        # Clean up by removing the test output file if it was created
        if os.path.exists(args.outfile):
            os.remove(args.outfile)
