# file scalene/scalene_gpu.py:114-131
# lines [117, 118, 119, 120, 121, 122, 123, 124, 127, 130, 131]
# branches ['117->118', '117->119', '120->121', '120->131', '123->120', '123->127', '127->123', '127->130']

import pytest
from unittest.mock import patch, MagicMock
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture
def mock_pynvml():
    with patch("scalene.scalene_gpu.pynvml") as mock:
        yield mock

@pytest.fixture
def mock_gpu():
    with patch("scalene.scalene_gpu.ScaleneGPU.has_gpu", return_value=True):
        gpu = ScaleneGPU()
        gpu._ScaleneGPU__ngpus = 1
        gpu._ScaleneGPU__handle = [MagicMock()]
        yield gpu

def test_gpu_memory_usage(mock_pynvml, mock_gpu):
    mock_process = MagicMock()
    mock_process.pid = 1234
    mock_process.usedGpuMemory = 10485760  # 10 MB in bytes
    mock_pynvml.nvmlDeviceGetComputeRunningProcesses.return_value = [mock_process]

    # Test for the correct pid
    assert mock_gpu.gpu_memory_usage(1234) == 10

    # Test for a different pid
    assert mock_gpu.gpu_memory_usage(4321) == 0

    # Test for exception handling
    mock_pynvml.nvmlDeviceGetComputeRunningProcesses.side_effect = Exception
    assert mock_gpu.gpu_memory_usage(1234) == 0
