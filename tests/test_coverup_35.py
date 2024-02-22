# file scalene/scalene_apple_gpu.py:22-25
# lines [22, 25]
# branches []

import pytest
from scalene.scalene_apple_gpu import ScaleneAppleGPU

@pytest.fixture(scope="function")
def scalene_apple_gpu():
    return ScaleneAppleGPU()

def test_has_gpu(scalene_apple_gpu):
    assert not scalene_apple_gpu.has_gpu(), "ScaleneAppleGPU should return False for has_gpu"
