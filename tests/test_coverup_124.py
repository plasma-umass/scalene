# file scalene/scalene_gpu.py:12-31
# lines [21, 22, 23, 24, 26, 27, 28, 31]
# branches []

import os
import pytest
import pynvml
from unittest.mock import patch
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture
def mock_nvml():
    with patch('pynvml.nvmlInit'), \
         patch('pynvml.nvmlDeviceGetCount', return_value=1), \
         patch('pynvml.nvmlDeviceGetHandleByIndex', return_value='fake_handle'), \
         patch('pynvml.nvmlDeviceGetAccountingMode', return_value=1), \
         patch('pynvml.nvmlDeviceSetAccountingMode'), \
         patch('pynvml.nvmlDeviceGetAccountingStats', return_value=(0, 0, 0, 0, 0)), \
         patch('pynvml.nvmlShutdown'):
        yield

def test_scalene_gpu_init(mock_nvml):
    gpu = ScaleneGPU()
    assert gpu._ScaleneGPU__ngpus == 1
    assert gpu._ScaleneGPU__handle == ['fake_handle']
    assert gpu._ScaleneGPU__has_per_pid_accounting is True
    assert gpu._ScaleneGPU__has_gpu is True
