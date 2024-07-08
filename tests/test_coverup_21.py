# file scalene/scalene_preload.py:57-117
# lines [67, 68, 69, 71, 72, 73, 76, 77, 79, 80, 81, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 96, 98, 99, 100, 102, 103, 105, 106, 107, 108, 109, 110, 111, 112, 114, 115, 117]
# branches ['67->71', '67->76', '79->80', '79->85', '86->87', '86->117', '96->98', '96->105', '109->110', '109->114']

import argparse
import os
import platform
import struct
import subprocess
import sys
from unittest.mock import patch

import pytest

from scalene.scalene_preload import ScalenePreload


@pytest.fixture
def cleanup_env():
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


def test_setup_preload_full_coverage(cleanup_env):
    args = argparse.Namespace(memory=True, allocation_sampling_window=1)
    with patch.object(platform, 'machine', return_value='x86_64'), \
         patch.object(struct, 'calcsize', return_value=8), \
         patch.object(os, 'environ', new_callable=dict), \
         patch.object(subprocess, 'Popen') as mock_popen, \
         patch.object(sys, 'argv', ['scalene', 'test_script.py']), \
         patch.object(sys, 'exit') as mock_exit:
        mock_popen.return_value.pid = 1234
        mock_popen.return_value.returncode = 0
        mock_popen.return_value.wait = lambda: None

        # Simulate the environment not having the required variables
        os.environ.clear()
        result = ScalenePreload.setup_preload(args)
        assert result is True
        mock_popen.assert_called_once()
        mock_exit.assert_called_once_with(0)
