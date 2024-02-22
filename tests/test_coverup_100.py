# file scalene/launchbrowser.py:20-22
# lines [20, 21, 22]
# branches []

import os
import pathlib
import pytest
from scalene.launchbrowser import read_file_content

@pytest.fixture
def temp_test_directory(tmp_path):
    # Create a temporary directory structure
    directory = tmp_path / "test_dir"
    subdirectory = directory / "sub_dir"
    subdirectory.mkdir(parents=True)
    # Create a test file
    test_file = subdirectory / "test_file.txt"
    test_file.write_text("Test content")
    return str(directory), "sub_dir", "test_file.txt"

def test_read_file_content(temp_test_directory):
    directory, subdirectory, filename = temp_test_directory
    # Read the content using the function
    content = read_file_content(directory, subdirectory, filename)
    # Assert that the content matches what we expect
    assert content == "Test content"
