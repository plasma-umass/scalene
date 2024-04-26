# file scalene/scalene_analysis.py:69-99
# lines [69, 70, 82, 83, 84, 87, 88, 90, 91, 92, 94, 95, 96, 97, 99]
# branches ['87->88', '87->99', '88->90', '88->94', '90->87', '90->91', '91->90', '91->92', '94->87', '94->95', '96->87', '96->97']

import pytest
from scalene.scalene_analysis import ScaleneAnalysis
from unittest.mock import patch

@pytest.fixture
def cleanup_imports():
    # Fixture to clean up sys.modules after the test
    import sys
    before = set(sys.modules.keys())
    yield
    after = set(sys.modules.keys())
    for extra in after - before:
        del sys.modules[extra]

def test_get_native_imported_modules(cleanup_imports):
    # Mock the is_native method to control which modules are considered native
    with patch.object(ScaleneAnalysis, 'is_native', return_value=True):
        source_code = """
import math
import os
from sys import path
"""
        expected_imports = ['import math', 'import os', 'from sys import path']
        actual_imports = ScaleneAnalysis.get_native_imported_modules(source_code)
        assert set(actual_imports) == set(expected_imports), "The list of native imports does not match the expected list."

    with patch.object(ScaleneAnalysis, 'is_native', return_value=False):
        source_code = """
import math
import os
from sys import path
"""
        expected_imports = []
        actual_imports = ScaleneAnalysis.get_native_imported_modules(source_code)
        assert actual_imports == expected_imports, "The list of native imports should be empty."
