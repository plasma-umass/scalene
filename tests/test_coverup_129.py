# file scalene/scalene_gpu.py:101-112
# lines [104]
# branches ['103->104']

import pytest
from unittest.mock import patch
from scalene.scalene_gpu import ScaleneGPU

@pytest.fixture(scope="function")
def scalene_gpu():
    gpu = ScaleneGPU()
    yield gpu
    # Cleanup code if necessary

def test_nvml_reinit_no_gpu(scalene_gpu):
    with patch.object(ScaleneGPU, 'has_gpu', return_value=False):
        scalene_gpu.nvml_reinit()  # This should trigger line 104
        assert not hasattr(scalene_gpu, '_ScaleneGPU__handle')  # Postcondition: __handle should not be set
