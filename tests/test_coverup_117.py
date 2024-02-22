# file scalene/launchbrowser.py:55-64
# lines [58, 59, 60, 61, 62, 64]
# branches ['58->59', '58->64']

import pytest
import threading
import http.server
import socket
from scalene.launchbrowser import CustomHandler, last_heartbeat
import time

@pytest.fixture(scope="module")
def server():
    # Setup: start a simple HTTP server in a separate thread
    httpd = http.server.HTTPServer(('localhost', 0), CustomHandler)
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    yield httpd
    # Teardown: stop the server
    httpd.shutdown()
    server_thread.join()

def test_heartbeat(server):
    # Get the server address and port
    host, port = server.server_address
    # Send a GET request to the /heartbeat path
    conn = http.client.HTTPConnection(host, port)
    conn.request("GET", "/heartbeat")
    response = conn.getresponse()
    # Check that the response is OK
    assert response.status == 200
    # Check that the last_heartbeat global variable was updated
    now = time.time()
    assert last_heartbeat <= now
    # Clean up
    conn.close()
