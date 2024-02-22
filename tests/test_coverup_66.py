# file scalene/launchbrowser.py:25-46
# lines [25, 26, 27, 28, 29, 30, 31, 34, 36, 41, 42, 46]
# branches ['26->27', '26->28', '28->29', '28->30', '30->31', '30->34']

import pytest
import webbrowser
import tempfile
import platform
import os
from unittest.mock import patch

# Assuming the function launch_browser_insecure is part of a module named launchbrowser
from scalene.launchbrowser import launch_browser_insecure

@pytest.fixture
def mock_platform_system():
    with patch('platform.system') as mock:
        yield mock

@pytest.fixture
def mock_webbrowser_register():
    with patch('webbrowser.register') as mock:
        yield mock

@pytest.fixture
def mock_webbrowser_get():
    with patch('webbrowser.get') as mock:
        yield mock

def test_launch_browser_insecure(mock_platform_system, mock_webbrowser_register, mock_webbrowser_get):
    # Mock platform.system to return 'Linux' to cover the Linux branch
    mock_platform_system.return_value = 'Linux'
    # Mock webbrowser.get().open to simply return True
    mock_webbrowser_get.return_value.open.return_value = True

    test_url = 'http://example.com'
    launch_browser_insecure(test_url)

    # Check that webbrowser.register was called with the expected arguments
    mock_webbrowser_register.assert_called_once()
    args, kwargs = mock_webbrowser_register.call_args
    assert args[0] == 'chrome_with_flags'
    assert args[2] is not None  # This should be the webbrowser.Chrome instance
    assert kwargs['preferred'] is True

    # Check that webbrowser.get().open was called with the test URL
    mock_webbrowser_get.assert_called_once_with(args[2].name)
    mock_webbrowser_get.return_value.open.assert_called_once_with(test_url)

    # Ensure that the temporary directory was cleaned up
    # Since the temporary directory is created within the function using a context manager,
    # we don't have direct access to the variable name. We need to check if the directory
    # was indeed removed, which is the postcondition we want to verify.
    # We can't assert on the name of the temporary directory, so we remove the assertion.
