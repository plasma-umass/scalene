# file scalene/scalene_utility.py:186-211
# lines [208, 209]
# branches []

import os
import pytest
import shutil
import tempfile
import threading
import time
import webbrowser
from unittest.mock import patch
from scalene.scalene_utility import show_browser

# Mock webbrowser to raise an error
class MockWebbrowser:
    @staticmethod
    def open(url):
        raise Exception("Test exception to trigger except block")

# Test function to cover lines 208-209
def test_show_browser_exception():
    # Setup
    temp_dir = tempfile.gettempdir()
    test_file = os.path.join(temp_dir, "test_index.html")
    with open(test_file, "w") as f:
        f.write("<html><body>Test</body></html>")
    port = 8000
    orig_python = "python3"

    # Mock webbrowser.open to raise an exception
    with patch.object(webbrowser, 'open', side_effect=MockWebbrowser.open):
        # Mock os.chdir to prevent changing the current working directory
        with patch.object(os, 'chdir') as mock_chdir:
            # Call the function that should now trigger the exception block
            show_browser(test_file, port, orig_python)

            # Assertions to ensure the exception block was triggered
            mock_chdir.assert_called()  # os.chdir was called at least once
            assert mock_chdir.call_args_list[0][0][0] == temp_dir  # First call to os.chdir was to temp_dir
            assert mock_chdir.call_args_list[-1][0][0] == os.getcwd()  # Last call to os.chdir was to revert to original directory

    # Cleanup
    os.remove(test_file)
