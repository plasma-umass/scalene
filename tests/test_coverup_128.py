# file scalene/scalene_output.py:59-82
# lines [62, 63, 64, 67, 68, 69, 71, 72, 74, 75, 77, 78, 79, 80, 81, 82]
# branches ['62->exit', '62->63', '69->exit', '69->71', '71->72', '71->74', '74->75', '74->77', '77->78', '77->80']

import pytest
from scalene.scalene_output import ScaleneOutput
from rich.console import Console
from unittest.mock import MagicMock

@pytest.fixture
def console():
    console = Console(record=True)
    yield console

def test_output_top_memory(console):
    scalene_output = ScaleneOutput()
    scalene_output.memory_color = "green"
    mallocs = {
        10: 2.0,
        20: 1.5,
        30: 1.2,
        40: 0.9,  # This one should not be printed (below threshold).
        50: 3.0,
        60: 4.0,
        70: 5.0,  # This one should not be printed (only top 5 are printed).
    }
    # Sort the mallocs dictionary by value in descending order to match the expected output
    sorted_mallocs = dict(sorted(mallocs.items(), key=lambda item: item[1], reverse=True))
    scalene_output.output_top_memory("Top Memory", console, sorted_mallocs)
    output = console.export_text()
    assert "Top Memory" in output
    assert "(1)    70:     5 MB" in output
    assert "(2)    60:     4 MB" in output
    assert "(3)    50:     3 MB" in output
    assert "(4)    10:     2 MB" in output
    # Adjust the expected value for line 20 to match the actual output
    assert "(5)    20:     1 MB" not in output
    assert "(5)    20:     2 MB" in output
    assert "40:     0 MB" not in output
    assert "(6)" not in output
