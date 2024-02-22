# file scalene/scalene_utility.py:124-126
# lines [124, 125, 126]
# branches []

import os
import pytest
from scalene import scalene_utility

@pytest.fixture
def create_test_file(tmp_path):
    # Create a temporary directory and file for testing
    test_dir = tmp_path / "subdir"
    test_dir.mkdir()
    test_file = test_dir / "testfile.txt"
    test_file.write_text("Test content")
    return test_dir, test_file

def test_read_file_content(create_test_file, tmp_path):
    test_dir, test_file = create_test_file
    # Use the ScaleneUtility method to read the file content
    content = scalene_utility.read_file_content(str(tmp_path), "subdir", "testfile.txt")
    # Assert that the content read is correct
    assert content == "Test content"
    # Clean up is handled by pytest's tmp_path fixture
