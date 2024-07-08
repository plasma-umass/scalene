# file scalene/scalene_arguments.py:6-49
# lines [10, 11, 12, 13, 14, 15, 17, 19, 20, 23, 24, 25, 26, 28, 29, 30, 32, 34, 36, 38, 40, 42, 44, 45, 46, 47, 48, 49]
# branches []

import argparse
import platform
import sys
from unittest.mock import patch
import pytest
from scalene.scalene_arguments import ScaleneArguments

@pytest.fixture
def clean_scalene_arguments():
    # Fixture to create a clean ScaleneArguments instance
    yield ScaleneArguments()
    # No cleanup needed as each test gets a fresh instance

def test_scalene_arguments_initialization(clean_scalene_arguments):
    args = clean_scalene_arguments
    assert args.cpu == True
    assert args.gpu == (platform.system() != "Darwin")
    assert args.memory == (sys.platform != "win32")
    assert args.stacks == False
    assert args.cpu_percent_threshold == 1
    assert args.cpu_sampling_rate == 0.01
    assert args.allocation_sampling_window == 10485767
    assert args.html == False
    assert args.json == False
    assert args.column_width == 132
    assert args.malloc_threshold == 100
    assert args.outfile == None
    assert args.pid == 0
    assert args.profile_all == False
    assert args.profile_interval == float("inf")
    assert args.profile_only == ""
    assert args.profile_exclude == ""
    assert args.program_path == ""
    assert args.reduced_profile == False
    assert args.use_virtual_time == False
    assert args.memory_leak_detector == True
    assert args.web == True
    assert args.no_browser == False
    assert args.port == 8088
    assert args.cli == False
