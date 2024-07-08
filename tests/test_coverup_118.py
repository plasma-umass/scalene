# file scalene/scalene_profiler.py:1156-1181
# lines [1161, 1162, 1164, 1165, 1166, 1167, 1170, 1171, 1172, 1173, 1174, 1175, 1177, 1178, 1180, 1181]
# branches ['1166->1167', '1166->1174', '1170->1166', '1170->1171', '1174->1175', '1174->1177']

import pytest
from scalene.scalene_profiler import Scalene
from scalene.scalene_statistics import ScaleneStatistics
from unittest.mock import MagicMock

# Mock classes to simulate the behavior of Scalene's Filename and LineNumber
class Filename(str):
    pass

class LineNumber(int):
    pass

def get_fully_qualified_name(frame: MagicMock) -> str:
    return frame.f_globals.get('__name__', '') + '.' + frame.f_code.co_name

# Mock function to simulate Scalene's should_trace method
def mock_should_trace(filename: str, func_name: str) -> bool:
    return True

# Replace the actual should_trace with the mock version
Scalene.should_trace = staticmethod(mock_should_trace)

def test_enter_function_meta():
    stats = ScaleneStatistics()
    frame = MagicMock()  # Create a MagicMock frame to simulate the behavior
    frame.f_code.co_filename = "mock_filename.py"
    frame.f_code.co_name = "<mock_function>"
    frame.f_back = None  # Set f_back to None to trigger the return in line 1171

    # Call the method with the mock frame
    Scalene.enter_function_meta(frame, stats)

    # Since the frame's f_back is None, the function_map and firstline_map should remain empty
    assert not stats.function_map
    assert not stats.firstline_map

# Run the test
pytest.main(["-v", __file__])
