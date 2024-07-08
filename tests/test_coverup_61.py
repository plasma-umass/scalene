# file scalene/scalene_json.py:63-68
# lines [63, 65, 68]
# branches []

import pytest
from unittest.mock import Mock, patch

# Mock the cloudpickle import in scalene_statistics
with patch.dict('sys.modules', {'cloudpickle': Mock()}):
    from scalene.scalene_json import ScaleneJSON

@pytest.fixture
def scalene_json_cleanup():
    # Setup code if necessary
    yield
    # Cleanup code if necessary

def test_scalene_json_init(scalene_json_cleanup):
    json_obj = ScaleneJSON()
    assert json_obj.output_file == ""
    assert json_obj.gpu is False
