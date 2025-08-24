# file scalene/scalene_nvidia_gpu.py:133-139
# lines [133, 135, 136, 137, 138, 139]
# branches ['135->136', '135->139']

import pytest
from unittest.mock import patch, MagicMock

# Assuming ScaleneNVIDIAGPU is in the scalene_nvidia_gpu.py file within the scalene package
# and that the pynvml module is not available, we mock the entire scalene_nvidia_gpu module.
# We also assume that the __pid attribute is set somewhere within ScaleneNVIDIAGPU.

# Mocking the entire scalene_nvidia_gpu module
with patch.dict("sys.modules", {"pynvml": MagicMock()}):
    from scalene import scalene_nvidia_gpu


@pytest.fixture(scope="function")
def mock_gpu_stats():
    with patch.object(
        scalene_nvidia_gpu.ScaleneNVIDIAGPU, "has_gpu", return_value=True
    ), patch.object(
        scalene_nvidia_gpu.ScaleneNVIDIAGPU, "gpu_utilization", return_value=50.0
    ), patch.object(
        scalene_nvidia_gpu.ScaleneNVIDIAGPU, "gpu_memory_usage", return_value=1024.0
    ):
        yield


@pytest.fixture(scope="function")
def mock_no_gpu():
    with patch.object(
        scalene_nvidia_gpu.ScaleneNVIDIAGPU, "has_gpu", return_value=False
    ):
        yield


def test_get_stats_with_gpu(mock_gpu_stats):
    gpu = scalene_nvidia_gpu.ScaleneNVIDIAGPU()
    gpu._ScaleneNVIDIAGPU__pid = 1234  # Mocking the __pid attribute
    total_load, mem_used = gpu.get_stats()
    assert total_load == 50.0
    assert mem_used == 1024.0


def test_get_stats_without_gpu(mock_no_gpu):
    gpu = scalene_nvidia_gpu.ScaleneNVIDIAGPU()
    gpu._ScaleneNVIDIAGPU__pid = 1234  # Mocking the __pid attribute
    total_load, mem_used = gpu.get_stats()
    assert total_load == 0.0
    assert mem_used == 0.0
