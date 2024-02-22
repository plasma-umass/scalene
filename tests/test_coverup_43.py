# file scalene/scalene_apple_gpu.py:27-29
# lines [27, 29]
# branches []

import pytest
from scalene.scalene_apple_gpu import ScaleneAppleGPU

@pytest.fixture(scope="function")
def scalene_apple_gpu():
    return ScaleneAppleGPU()

def test_nvml_reinit(scalene_apple_gpu):
    # Call the method to ensure it is covered
    scalene_apple_gpu.nvml_reinit()
    # Since the method is a no-op, there are no postconditions to assert
