# file scalene/scalene_utility.py:186-211
# lines [186, 187, 190, 193, 194, 195, 196, 198, 207, 208, 209, 211]
# branches []

import os
import pytest
import shutil
import tempfile
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from scalene.scalene_utility import show_browser

# Define a simple HTTP server for testing purposes
class TestHTTPServer(threading.Thread):
    # Prevent pytest from considering this class as a test
    __test__ = False

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.httpd = HTTPServer(('localhost', self.port), SimpleHTTPRequestHandler)
        self.daemon = True

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()

@pytest.fixture(scope="module")
def server():
    port = 8000  # Use a common port for testing
    server = TestHTTPServer(port)
    server.start()
    yield server
    server.stop()

@pytest.fixture(scope="module")
def temp_html_file():
    # Create a temporary HTML file
    temp_dir = tempfile.mkdtemp()  # Create a new temporary directory
    file_path = os.path.join(temp_dir, 'index.html')
    with open(file_path, 'w') as f:
        f.write('<html><body><h1>Test Page</h1></body></html>')
    yield file_path
    shutil.rmtree(temp_dir)  # Remove the temporary directory

def test_show_browser(temp_html_file, server, monkeypatch):
    # Mock webbrowser.open to prevent actually opening the browser
    def mock_open(url):
        assert url == f'http://localhost:{server.port}/'
    monkeypatch.setattr(webbrowser, 'open', mock_open)

    # Mock subprocess.Popen to prevent actually launching a server
    class MockPopen:
        def __init__(self, *args, **kwargs):
            pass
    monkeypatch.setattr('subprocess.Popen', MockPopen)

    # Save the current working directory to restore later
    curr_dir = os.getcwd()

    # Run the function to test
    show_browser(temp_html_file, server.port)

    # Check if the current directory was restored
    assert os.getcwd() == curr_dir
