# file scalene/scalene_apple_gpu.py:11-20
# lines [11, 12, 13, 14, 16, 17, 20]
# branches []

import pytest
import re
import platform
from unittest.mock import patch

# Assuming the ScaleneAppleGPU class is in a module named scalene_apple_gpu
from scalene.scalene_apple_gpu import ScaleneAppleGPU

@pytest.fixture
def mock_platform_system():
    with patch("platform.system") as mock_system:
        mock_system.return_value = "Darwin"
        yield mock_system

@pytest.fixture
def mock_subprocess():
    with patch("subprocess.check_output") as mock_check_output:
        mock_check_output.return_value = b'"Device Utilization %"=50\n"In use system memory"=1024'
        yield mock_check_output

def test_scalene_apple_gpu_init(mock_platform_system, mock_subprocess):
    gpu = ScaleneAppleGPU(sampling_frequency=10)
    assert gpu.gpu_sampling_frequency == 10
    assert gpu.cmd == 'DYLD_INSERT_LIBRARIES="" ioreg -r -d 1 -w 0 -c "IOAccelerator"'
    assert isinstance(gpu.regex_util, re.Pattern)
    assert isinstance(gpu.regex_inuse, re.Pattern)
