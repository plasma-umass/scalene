# file scalene/scalene_gpu.py:48-72
# lines [50, 52, 54, 56, 57, 61, 62, 63, 65, 66, 68, 70, 72]
# branches ['52->54', '52->72', '55->52', '55->61']

import pytest
from unittest.mock import patch, MagicMock
from scalene.scalene_gpu import ScaleneGPU
import pynvml

@pytest.fixture
def mock_gpu():
    with patch('pynvml.nvmlDeviceGetAccountingMode') as mock_get_accounting_mode, \
         patch('pynvml.nvmlDeviceSetPersistenceMode') as mock_set_persistence_mode, \
         patch('pynvml.nvmlDeviceSetAccountingMode') as mock_set_accounting_mode:
        mock_get_accounting_mode.return_value = pynvml.NVML_FEATURE_DISABLED
        mock_set_persistence_mode.return_value = None
        error = pynvml.NVMLError(pynvml.NVML_ERROR_UNKNOWN)
        mock_set_accounting_mode.side_effect = error
        yield

def test_set_accounting_mode_failure(mock_gpu):
    gpu = ScaleneGPU()
    gpu._ScaleneGPU__ngpus = 1  # Assuming there is at least one GPU
    gpu._ScaleneGPU__handle = [MagicMock()]  # Mock handle for the GPU
    result = gpu._set_accounting_mode()
    assert not result, "Accounting mode should not be set due to insufficient permissions."
