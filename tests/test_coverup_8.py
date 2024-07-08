# file scalene/scalene_analysis.py:44-67
# lines [44, 45, 57, 58, 59, 62, 64, 65, 67]
# branches ['62->64', '62->67', '64->62', '64->65']

import pytest
from scalene.scalene_analysis import ScaleneAnalysis
import ast

@pytest.fixture
def cleanup_imports():
    # Fixture to clean up any added imports after the test
    yield
    # No cleanup needed as the test does not modify any state

def test_get_imported_modules(cleanup_imports):
    source_code = """
import os
import sys as system
from collections import defaultdict
"""
    expected_imports = [
        "import os",
        "import sys as system",
        "from collections import defaultdict"
    ]
    imported_modules = ScaleneAnalysis.get_imported_modules(source_code)
    assert set(imported_modules) == set(expected_imports), "The imported modules do not match the expected imports"
