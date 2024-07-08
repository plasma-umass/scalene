# file scalene/scalene_jupyter.py:8-28
# lines [8, 9, 21, 22, 23, 24, 25, 26, 27, 28]
# branches ['21->22', '21->28']

import pytest
import socket
from scalene.scalene_jupyter import ScaleneJupyter

@pytest.fixture(scope="function")
def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

@pytest.fixture(scope="function")
def occupied_port(free_port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", free_port))
        yield free_port

def test_find_available_port(free_port):
    # Test that the function finds an available port
    port = ScaleneJupyter.find_available_port(free_port, free_port)
    assert port == free_port

def test_find_available_port_with_occupied_port(occupied_port):
    # Test that the function skips the occupied port and finds the next available one
    port = ScaleneJupyter.find_available_port(occupied_port, occupied_port + 1)
    assert port == occupied_port + 1

def test_no_available_ports(occupied_port):
    # Test that the function returns None when no ports are available
    port = ScaleneJupyter.find_available_port(occupied_port, occupied_port)
    assert port is None
