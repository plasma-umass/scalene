# file scalene/scalene_gpu.py:97-99
# lines [99]
# branches []

import pytest
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture
def scalene_gpu():
    gpu = ScaleneGPU()
    yield gpu
    # No cleanup needed for this simple test

def test_has_gpu(scalene_gpu):
    # Assuming that the ScaleneGPU class has an attribute __has_gpu
    # which is set somewhere in the class (not shown in the snippet).
    # We need to set this attribute to both True and False to test both branches.
    # Since it's a private attribute, we use the built-in setattr function.
    
    # Test when __has_gpu is True
    setattr(scalene_gpu, '_ScaleneGPU__has_gpu', True)
    assert scalene_gpu.has_gpu() == True

    # Test when __has_gpu is False
    setattr(scalene_gpu, '_ScaleneGPU__has_gpu', False)
    assert scalene_gpu.has_gpu() == False
