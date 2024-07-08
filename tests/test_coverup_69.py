# file scalene/scalene_output.py:24-46
# lines [24, 27, 30, 33, 36, 39, 42, 45]
# branches []

import pytest
from scalene.scalene_output import ScaleneOutput

def test_scalene_output_attributes():
    # Test to ensure the attributes of ScaleneOutput are as expected
    assert ScaleneOutput.max_sparkline_len_file == 27
    assert ScaleneOutput.max_sparkline_len_line == 9
    assert ScaleneOutput.highlight_percentage == 33
    assert ScaleneOutput.highlight_color == "bold red"
    assert ScaleneOutput.memory_color == "dark_green"
    assert ScaleneOutput.gpu_color == "yellow4"
    assert ScaleneOutput.copy_volume_color == "yellow4"
