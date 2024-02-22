# file scalene/scalene_parseargs.py:27-31
# lines [27, 28, 30, 31]
# branches []

import pytest
from scalene.scalene_parseargs import StopJupyterExecution

def test_stop_jupyter_execution():
    # Test the instantiation and the special method _render_traceback_
    try:
        raise StopJupyterExecution()
    except StopJupyterExecution as e:
        assert e._render_traceback_() is None
