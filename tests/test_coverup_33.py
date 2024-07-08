# file scalene/scalene_parseargs.py:35-38
# lines [35, 36, 38]
# branches []

import pytest
from scalene.scalene_parseargs import ScaleneParseArgs

class StopJupyterExecution(Exception):
    pass

def test_clean_exit(monkeypatch):
    monkeypatch.setattr("scalene.scalene_parseargs.StopJupyterExecution", StopJupyterExecution)
    with pytest.raises(StopJupyterExecution):
        ScaleneParseArgs.clean_exit()
