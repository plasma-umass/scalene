# file scalene/scalene_gpu.py:74-95
# lines [77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 90, 91, 92, 94, 95]
# branches ['77->78', '77->79', '82->83', '82->95', '84->85', '84->90']

import pytest
from unittest.mock import patch, MagicMock
import pynvml
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture
def mock_gpu():
    with patch('scalene.scalene_gpu.pynvml') as mock_pynvml:
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value.gpu = 50
        mock_pynvml.nvml.NVMLError_Unknown = Exception
        yield mock_pynvml

@pytest.fixture
def scalene_gpu_instance(mock_gpu):
    gpu_instance = ScaleneGPU()
    gpu_instance._ScaleneGPU__ngpus = 2
    gpu_instance._ScaleneGPU__has_per_pid_accounting = False
    gpu_instance._ScaleneGPU__handle = [MagicMock(), MagicMock()]
    gpu_instance.has_gpu = MagicMock(return_value=True)
    return gpu_instance

def test_gpu_utilization_without_accounting(scalene_gpu_instance):
    assert scalene_gpu_instance.gpu_utilization(1234) == 0.5

def test_gpu_utilization_with_exception(scalene_gpu_instance, mock_gpu):
    mock_gpu.nvmlDeviceGetUtilizationRates.side_effect = mock_gpu.nvml.NVMLError_Unknown
    assert scalene_gpu_instance.gpu_utilization(1234) == 0.0
