# file scalene/scalene_gpu.py:101-112
# lines [103, 104, 105, 106, 107, 108, 109, 110, 111]
# branches ['103->104', '103->105']

import pytest
from unittest.mock import patch
import pynvml
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture(scope="function")
def gpu_fixture():
    gpu = ScaleneGPU()
    yield gpu
    # Cleanup code if necessary

def test_nvml_reinit_has_gpu(gpu_fixture):
    with patch.object(ScaleneGPU, 'has_gpu', return_value=True):
        with patch('pynvml.nvmlInit') as mock_nvmlInit:
            with patch('pynvml.nvmlDeviceGetCount', return_value=1) as mock_nvmlDeviceGetCount:
                with patch('pynvml.nvmlDeviceGetHandleByIndex') as mock_nvmlDeviceGetHandleByIndex:
                    gpu_fixture.nvml_reinit()
                    mock_nvmlInit.assert_called_once()
                    mock_nvmlDeviceGetCount.assert_called_once()
                    mock_nvmlDeviceGetHandleByIndex.assert_called_once_with(0)
                    assert len(gpu_fixture._ScaleneGPU__handle) == 1
