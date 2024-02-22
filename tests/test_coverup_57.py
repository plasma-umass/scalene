# file scalene/scalene_apple_gpu.py:31-64
# lines [34, 40, 62, 63, 64]
# branches ['33->34', '39->40', '46->64', '48->61', '53->55', '57->59']

import pytest
import subprocess
from unittest.mock import patch, MagicMock
from typing import Tuple
from scalene.scalene_apple_gpu import ScaleneAppleGPU

class MockedScaleneAppleGPU(ScaleneAppleGPU):
    def __init__(self, has_gpu, gpu_sampling_frequency, cmd, regex_inuse, regex_util):
        self._has_gpu = has_gpu
        self.gpu_sampling_frequency = gpu_sampling_frequency
        self.cmd = cmd
        self.regex_inuse = regex_inuse
        self.regex_util = regex_util

    def has_gpu(self) -> bool:
        return self._has_gpu

@pytest.fixture
def mock_scalene_apple_gpu():
    regex_inuse = MagicMock()
    regex_util = MagicMock()
    regex_inuse.search.return_value.group.return_value = '100'
    regex_util.search.return_value.group.return_value = '500'
    gpu = MockedScaleneAppleGPU(
        has_gpu=True,
        gpu_sampling_frequency=1,
        cmd='echo "In use system memory 100\nDevice Utilization % 500"',
        regex_inuse=regex_inuse,
        regex_util=regex_util
    )
    return gpu

def test_get_stats(mock_scalene_apple_gpu):
    with patch('random.randint', return_value=0):
        util, in_use = mock_scalene_apple_gpu.get_stats()
        assert util == 0.5
        assert in_use == 100.0

def test_get_stats_no_gpu(mock_scalene_apple_gpu):
    mock_scalene_apple_gpu._has_gpu = False
    util, in_use = mock_scalene_apple_gpu.get_stats()
    assert util == 0.0
    assert in_use == 0.0

def test_get_stats_exception(mock_scalene_apple_gpu):
    with patch('subprocess.Popen', side_effect=Exception):
        util, in_use = mock_scalene_apple_gpu.get_stats()
        assert util == 0.0
        assert in_use == 0.0

def test_get_stats_sampling(mock_scalene_apple_gpu):
    with patch('random.randint', return_value=1):
        util, in_use = mock_scalene_apple_gpu.get_stats()
        assert util == 0.0
        assert in_use == 0.0
