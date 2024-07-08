# file scalene/scalene_apple_gpu.py:31-64
# lines [31, 33, 34, 35, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64]
# branches ['33->34', '33->35', '39->40', '39->41', '46->47', '46->64', '48->49', '48->61', '51->52', '51->55', '53->54', '53->55', '55->56', '55->59', '57->58', '57->59', '59->48', '59->60']

import pytest
import subprocess
from unittest.mock import MagicMock
import random
import re

# Assuming the class ScaleneAppleGPU is defined elsewhere in the module
from scalene.scalene_apple_gpu import ScaleneAppleGPU

class MockScaleneAppleGPU(ScaleneAppleGPU):
    def __init__(self):
        self.gpu_sampling_frequency = 1
        self.cmd = 'echo "In use system memory 123.45\nDevice Utilization % 678"'
        self.regex_inuse = re.compile(r'(\d+\.\d+)')
        self.regex_util = re.compile(r'(\d+)')

@pytest.fixture
def mock_gpu(monkeypatch):
    # Mocking the has_gpu method to always return True
    monkeypatch.setattr(ScaleneAppleGPU, 'has_gpu', lambda self: True)
    return MockScaleneAppleGPU()

def test_get_stats(mock_gpu, monkeypatch):
    # Mocking subprocess.Popen to return a controlled output
    mock_popen = MagicMock()
    mock_popen.stdout.readlines.return_value = [
        b"In use system memory 123.45\n",
        b"Device Utilization % 678\n"
    ]
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: mock_popen)

    util, in_use = mock_gpu.get_stats()

    assert util == 0.678, "Utilization should be 0.678"
    assert in_use == 123.45, "In use memory should be 123.45"
