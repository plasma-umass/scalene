# file scalene/scalene_output.py:47-55
# lines [47, 49, 52, 55]
# branches []

import pytest
from scalene.scalene_output import ScaleneOutput

@pytest.fixture
def scalene_output_cleanup():
    # Fixture to clean up any changes made to the ScaleneOutput instance
    yield
    # No cleanup needed since we are not modifying any class attributes

def test_scalene_output_init(scalene_output_cleanup):
    output = ScaleneOutput()
    assert output.output_file == "", "The output_file should be initialized to an empty string."
    assert not output.html, "The html flag should be initialized to False."
    assert not output.gpu, "The gpu flag should be initialized to False."
