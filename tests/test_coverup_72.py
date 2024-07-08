# file scalene/launchbrowser.py:84-96
# lines [84, 91, 92, 93, 94, 95, 96]
# branches []

import socket
import pytest
from scalene.launchbrowser import is_port_available

@pytest.fixture
def free_port():
    """Find a free port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

@pytest.fixture
def occupied_port():
    """Create and occupy a port for testing."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.listen(1)
    yield port
    s.close()

def test_is_port_available_with_free_port(free_port):
    """Test that is_port_available returns True for a free port."""
    assert is_port_available(free_port) == True

def test_is_port_available_with_occupied_port(occupied_port):
    """Test that is_port_available returns False for an occupied port."""
    assert is_port_available(occupied_port) == False
