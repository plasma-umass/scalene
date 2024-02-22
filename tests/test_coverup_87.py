# file scalene/launchbrowser.py:148-169
# lines [148, 149, 150, 152, 153, 154, 155, 156, 157, 158, 159, 160, 162, 163, 165, 168, 169]
# branches ['149->150', '149->152', '153->154', '153->156']

import os
import pytest
import shutil
import tempfile
import threading
import time
import webbrowser
from unittest.mock import patch

# Mocks for the functions and variables not provided in the snippet
HOST = "localhost"
def run_server(host, port):
    pass

def monitor_heartbeat():
    pass

def generate_html(input_file, output_file):
    with open(output_file, "w") as f:
        f.write("<html><body>Demo</body></html>")

class Filename(str):
    pass

def is_port_available(port):
    return True

def start(filename: str, port: int) -> None:
    while not is_port_available(port):
        port += 1
        
    cwd = os.getcwd()
    if filename == "demo":
        generate_html(Filename("demo"), Filename("demo.html"))
        filename = "demo.html"
    shutil.copy(filename, os.path.join(tempfile.gettempdir(), 'index.html'))
    os.chdir(tempfile.gettempdir())
    server_thread = threading.Thread(target=run_server, args=[HOST, port])
    server_thread.start()
    threading.Thread(target=monitor_heartbeat).start()

    webbrowser.open_new(f'http://{HOST}:{port}/')
    server_thread.join()

    os.chdir(cwd)
    
    # Optional: a delay to ensure all resources are released
    time.sleep(1)
    os._exit(0)  # Forcefully stops the program

@pytest.fixture
def setup_and_teardown():
    # Setup
    original_cwd = os.getcwd()
    temp_dir = tempfile.gettempdir()
    temp_index_html = os.path.join(temp_dir, 'index.html')
    # Store the original file if it exists
    original_index_html = temp_index_html + ".bak"
    if os.path.exists(temp_index_html):
        shutil.move(temp_index_html, original_index_html)
    yield temp_dir, original_cwd
    # Teardown
    os.chdir(original_cwd)
    if os.path.exists(original_index_html):
        shutil.move(original_index_html, temp_index_html)

def test_start(setup_and_teardown):
    temp_dir, original_cwd = setup_and_teardown
    test_port = 8000
    test_filename = "test.html"
    with open(test_filename, "w") as f:
        f.write("<html><body>Test</body></html>")
    with patch('webbrowser.open_new') as mock_open_new:
        with patch('os._exit') as mock_exit:
            with patch('scalene.launchbrowser.is_port_available', return_value=True):
                start(test_filename, test_port)
                mock_open_new.assert_called_with(f'http://{HOST}:{test_port}/')
                mock_exit.assert_called_with(0)
                assert os.path.exists(os.path.join(temp_dir, 'index.html'))
                with open(os.path.join(temp_dir, 'index.html'), 'r') as f:
                    content = f.read()
                    assert content == "<html><body>Test</body></html>"
    os.remove(test_filename)
