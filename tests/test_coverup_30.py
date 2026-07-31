# file scalene/scalene_profiler.py:153-173
# lines [153, 154, 157, 158, 159, 160, 161, 162, 164, 165, 166, 168, 170, 171, 172, 173]
# branches []

import os
import pytest
import sys
from scalene.scalene_profiler import Scalene
from scalene.scalene_arguments import ScaleneArguments
from unittest.mock import patch


@pytest.fixture
def cleanup():
    # Constructing Scalene(args) runs the full profiler __init__, which calls
    # scalene.redirect_python.redirect_python -- production behavior that
    # rewrites sys.executable / sys.path / PATH to a /tmp/scalene*/python
    # wrapper so child processes re-enter through Scalene. That is correct for
    # a real one-shot `scalene run` process, but here it leaks into the shared
    # pytest interpreter: later tests that spawn [sys.executable, "-m",
    # "scalene", ...] would launch the wrapper instead of real Python and fail
    # to profile. Snapshot and restore the mutated global state.
    orig_executable = sys.executable
    orig_path = list(sys.path)
    orig_environ_path = os.environ.get("PATH")
    yield
    sys.executable = orig_executable
    sys.path[:] = orig_path
    if orig_environ_path is not None:
        os.environ["PATH"] = orig_environ_path


@patch("scalene.scalene_profiler.ScaleneMapFile")
def test_scalene_cpu_count(mock_mapfile, cleanup):
    # Test to cover the branches in Scalene class related to CPU count
    if hasattr(os, "sched_getaffinity"):
        expected_cpus = len(os.sched_getaffinity(0))
    else:
        expected_cpus = os.cpu_count() if os.cpu_count() else 1

    # Create a ScaleneArguments object with default arguments
    args = ScaleneArguments()
    scalene_profiler = Scalene(args)
    assert scalene_profiler._Scalene__availableCPUs == expected_cpus
