# file scalene/launchbrowser.py:25-46
# lines [27, 30, 31]
# branches ['26->27', '28->30', '30->31', '30->34']

import pytest
import platform
from unittest.mock import patch
from scalene.launchbrowser import launch_browser_insecure

@pytest.fixture
def mock_platform_system():
    with patch('platform.system') as mock:
        yield mock

def test_launch_browser_insecure_on_mac(mock_platform_system):
    mock_platform_system.return_value = 'Darwin'
    with patch('webbrowser.register') as mock_register, \
         patch('webbrowser.get') as mock_get, \
         patch('tempfile.TemporaryDirectory') as mock_temp_dir:
        mock_temp_dir.return_value.__enter__.return_value = '/tmp'
        launch_browser_insecure('http://example.com')
        mock_register.assert_called_once()
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0].startswith('/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome')

def test_launch_browser_insecure_on_windows(mock_platform_system):
    mock_platform_system.return_value = 'Windows'
    with patch('webbrowser.register') as mock_register, \
         patch('webbrowser.get') as mock_get, \
         patch('tempfile.TemporaryDirectory') as mock_temp_dir:
        mock_temp_dir.return_value.__enter__.return_value = 'C:\\Temp'
        launch_browser_insecure('http://example.com')
        mock_register.assert_called_once()
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0].startswith('C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe')
