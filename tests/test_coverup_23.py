# file scalene/find_browser.py:4-18
# lines [4, 8, 12, 14, 15, 16, 18]
# branches []

import pytest
import webbrowser
from unittest.mock import patch
from scalene.find_browser import find_browser

@pytest.fixture
def mock_webbrowser_error():
    with patch('webbrowser.get', side_effect=webbrowser.Error):
        yield

@pytest.fixture
def mock_webbrowser_text_browser():
    class MockBrowser:
        def __init__(self, name):
            self.name = name
    with patch('webbrowser.get', return_value=MockBrowser('lynx')):
        yield

def test_find_browser_with_error(mock_webbrowser_error):
    assert find_browser() is None

def test_find_browser_with_text_browser(mock_webbrowser_text_browser):
    assert find_browser() is None
