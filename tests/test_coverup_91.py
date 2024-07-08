# file scalene/scalene_profiler.py:402-426
# lines [402, 403, 417, 422, 423, 424, 426]
# branches []

import pytest
from unittest.mock import MagicMock
from scalene.scalene_profiler import Scalene

def test_scalene_shim():
    # Create a mock function to be decorated
    mock_func = MagicMock()

    # Decorate the mock function using Scalene.shim
    decorated_func = Scalene.shim(mock_func)

    # Call the decorated function
    result = decorated_func(Scalene)

    # Assert that the original function was called with Scalene as argument
    mock_func.assert_called_with(Scalene)

    # Assert that the result of the decorated function is as expected
    # Since the mock_func does not have a return_value set, it will return another MagicMock instance
    assert isinstance(result, MagicMock)

    # Clean up by deleting the mock function
    del mock_func
    del decorated_func

# Run the test
def test_scalene_shim_coverage():
    test_scalene_shim()
