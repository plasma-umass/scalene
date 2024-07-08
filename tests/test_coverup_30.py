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
    # Fixture to clean up any state after the test
    yield
    # No specific cleanup required for this test

@patch('scalene.scalene_profiler.ScaleneMapFile')
def test_scalene_cpu_count(mock_mapfile, cleanup):
    # Test to cover the branches in Scalene class related to CPU count
    if hasattr(os, 'sched_getaffinity'):
        expected_cpus = len(os.sched_getaffinity(0))
    else:
        expected_cpus = os.cpu_count() if os.cpu_count() else 1

    # Create a ScaleneArguments object with default arguments
    args = ScaleneArguments()
    scalene_profiler = Scalene(args)
    assert scalene_profiler._Scalene__availableCPUs == expected_cpus
