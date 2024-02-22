# file scalene/scalene_gpu.py:33-35
# lines [35]
# branches []

import pytest
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture
def scalene_gpu():
    gpu = ScaleneGPU()
    # Assuming ScaleneGPU has an attribute `__has_gpu` to indicate GPU status
    # We need to set it to True to test the disable function
    # Since it's a private attribute, we use the built-in `setattr` function
    setattr(gpu, '_ScaleneGPU__has_gpu', True)
    return gpu

def test_disable_gpu(scalene_gpu):
    # Check if the `__has_gpu` attribute is True before calling disable
    assert getattr(scalene_gpu, '_ScaleneGPU__has_gpu') == True
    scalene_gpu.disable()
    # Check if the `__has_gpu` attribute is False after calling disable
    assert getattr(scalene_gpu, '_ScaleneGPU__has_gpu') == False
