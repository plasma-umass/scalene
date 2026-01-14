# Tests for IPython display import order fix (GitHub issue #951)
# Ensures that Jupyter notebook display works correctly

import importlib
import os
import sys
import tempfile
import threading
import time
import urllib.request
from unittest.mock import MagicMock, patch

from scalene.scalene_jupyter import ScaleneJupyter


def test_scalene_jupyter_module_imports():
    """Test that scalene_jupyter module can be imported successfully."""
    assert hasattr(ScaleneJupyter, 'display_profile')
    assert hasattr(ScaleneJupyter, 'find_available_port')
    assert callable(ScaleneJupyter.display_profile)
    assert callable(ScaleneJupyter.find_available_port)


def test_find_available_port():
    """Test that find_available_port finds an open port."""
    port = ScaleneJupyter.find_available_port(49152, 49160)
    if port is not None:
        assert 49152 <= port <= 49160


def test_find_available_port_returns_none_when_all_taken():
    """Test that find_available_port returns None when no ports available."""
    import socket

    # Bind to a single port range to guarantee it's taken
    port = 49200
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("", port))
        # Now try to find a port in a range of just that one port
        result = ScaleneJupyter.find_available_port(port, port)
        assert result is None
    finally:
        sock.close()


def test_display_profile_serves_html_content():
    """Test that display_profile serves the profile HTML via HTTP and displays an IFrame."""
    # Create a temporary HTML file
    html_content = "<html><body><h1>Test Profile</h1></body></html>"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html_content)
        profile_fname = f.name

    try:
        port = ScaleneJupyter.find_available_port(49300, 49400)
        assert port is not None, "Could not find available port for test"

        # Track what was displayed
        displayed_items = []

        def mock_display(item):
            displayed_items.append(item)

        # Mock IFrame to capture its arguments
        mock_iframe_instance = MagicMock()
        mock_iframe_class = MagicMock(return_value=mock_iframe_instance)

        # We need to mock sys.exit to prevent the test from exiting
        server_content = []

        def fetch_from_server():
            """Fetch content from the server before it shuts down."""
            # Retry logic for slower CI environments (especially macOS)
            max_retries = 10
            for attempt in range(max_retries):
                time.sleep(0.5)  # Give server time to start
                try:
                    with urllib.request.urlopen(f"http://localhost:{port}/", timeout=5) as response:
                        server_content.append(response.read().decode('utf-8'))
                        break  # Success, exit retry loop
                except Exception as e:
                    if attempt == max_retries - 1:
                        server_content.append(f"Error: {e}")
                    # Otherwise retry
            # Trigger server shutdown
            try:
                urllib.request.urlopen(f"http://localhost:{port}/shutdown", timeout=2)
            except Exception:
                pass

        # Create mock IPython modules
        mock_ipython = MagicMock()
        mock_ipython_display = MagicMock()
        mock_ipython_display.display = mock_display
        mock_ipython_display.IFrame = mock_iframe_class

        # Patch sys.modules to provide mock IPython
        with patch.dict(sys.modules, {
            'IPython': mock_ipython,
            'IPython.display': mock_ipython_display,
        }):
            with patch('sys.exit'):
                # Reload scalene_jupyter to pick up the mocked modules
                import scalene.scalene_jupyter
                importlib.reload(scalene.scalene_jupyter)

                # Start a thread to fetch from the server
                fetch_thread = threading.Thread(target=fetch_from_server)
                fetch_thread.start()

                # Call display_profile (this starts the server)
                scalene.scalene_jupyter.ScaleneJupyter.display_profile(port, profile_fname)

                fetch_thread.join(timeout=30)  # Allow time for retries on slow CI

        # Verify the server served the correct content
        assert len(server_content) == 1, f"Server content not fetched: {server_content}"
        assert html_content in server_content[0], "Server did not serve the profile HTML"

        # Verify IFrame was created with correct URL
        mock_iframe_class.assert_called_once()
        call_args = mock_iframe_class.call_args
        assert f"http://localhost:{port}" in str(call_args)

        # Verify display was called with the IFrame
        assert len(displayed_items) == 1
        assert displayed_items[0] is mock_iframe_instance

    finally:
        os.unlink(profile_fname)
        # Reload the original module
        importlib.reload(scalene.scalene_jupyter)


def test_display_profile_uses_modern_ipython_import():
    """Test that display_profile uses IPython.display (not deprecated IPython.core.display).

    This tests the fix for GitHub issue #951 where Jupyter notebook output
    wasn't displaying in VSCode because IPython.core.display (deprecated in
    IPython 9.2) was tried before IPython.display.
    """
    # Create a temporary HTML file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write("<html></html>")
        profile_fname = f.name

    try:
        port = ScaleneJupyter.find_available_port(49400, 49500)
        assert port is not None

        # Track which module's display was used
        new_display_called = []
        old_display_called = []

        def new_display(item):
            new_display_called.append(item)

        def old_display(item):
            old_display_called.append(item)

        # Create mock modules - new style should be preferred
        mock_ipython = MagicMock()
        mock_ipython_display = MagicMock()
        mock_ipython_display.display = new_display
        mock_ipython_display.IFrame = MagicMock()

        mock_ipython_core = MagicMock()
        mock_ipython_core_display = MagicMock()
        mock_ipython_core_display.display = old_display

        # Trigger shutdown quickly
        def quick_shutdown():
            time.sleep(0.3)
            try:
                urllib.request.urlopen(f"http://localhost:{port}/shutdown", timeout=1)
            except Exception:
                pass

        with patch.dict(sys.modules, {
            'IPython': mock_ipython,
            'IPython.display': mock_ipython_display,
            'IPython.core': mock_ipython_core,
            'IPython.core.display': mock_ipython_core_display,
        }):
            with patch('sys.exit'):
                # Reload scalene_jupyter to pick up the mocked modules
                import scalene.scalene_jupyter
                importlib.reload(scalene.scalene_jupyter)

                shutdown_thread = threading.Thread(target=quick_shutdown)
                shutdown_thread.start()

                # Call display_profile - it should use IPython.display.display (new_display)
                scalene.scalene_jupyter.ScaleneJupyter.display_profile(port, profile_fname)

                shutdown_thread.join(timeout=2)

        # Verify that IPython.display.display was called (new style)
        assert len(new_display_called) == 1, "IPython.display.display was not called"
        # Verify that IPython.core.display.display was NOT called (old deprecated style)
        assert len(old_display_called) == 0, "Deprecated IPython.core.display.display was called"

    finally:
        os.unlink(profile_fname)
        # Reload the original module
        import scalene.scalene_jupyter
        importlib.reload(scalene.scalene_jupyter)


def test_display_profile_fallback_to_old_ipython():
    """Test backwards compatibility with older IPython versions.

    When IPython.display is not available (older IPython versions),
    the code should fall back to IPython.core.display.
    """
    # Create a temporary HTML file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write("<html></html>")
        profile_fname = f.name

    try:
        port = ScaleneJupyter.find_available_port(49500, 49600)
        assert port is not None

        # Track which module's display was used
        old_display_called = []

        def old_display(item):
            old_display_called.append(item)

        # Create mock modules - only old style available (simulating older IPython)
        mock_ipython = MagicMock()
        mock_ipython_core = MagicMock()
        mock_ipython_core_display = MagicMock()
        mock_ipython_core_display.display = old_display
        mock_ipython_core_display.IFrame = MagicMock()

        # Trigger shutdown quickly
        def quick_shutdown():
            time.sleep(0.3)
            try:
                urllib.request.urlopen(f"http://localhost:{port}/shutdown", timeout=1)
            except Exception:
                pass

        # Simulate older IPython by not providing IPython.display
        # When we try to import from IPython.display, it should raise ImportError
        # and fall back to IPython.core.display
        original_modules = sys.modules.copy()

        # Remove any cached IPython modules
        modules_to_remove = [k for k in sys.modules if k.startswith('IPython')]
        for mod in modules_to_remove:
            sys.modules.pop(mod, None)

        # Set up mocks - IPython.display will raise ImportError
        sys.modules['IPython'] = mock_ipython
        sys.modules['IPython.core'] = mock_ipython_core
        sys.modules['IPython.core.display'] = mock_ipython_core_display
        # Don't add IPython.display - this simulates older IPython

        try:
            with patch('sys.exit'):
                # Reload scalene_jupyter to pick up the mocked modules
                import scalene.scalene_jupyter
                importlib.reload(scalene.scalene_jupyter)

                shutdown_thread = threading.Thread(target=quick_shutdown)
                shutdown_thread.start()

                # Call display_profile - it should fall back to IPython.core.display
                scalene.scalene_jupyter.ScaleneJupyter.display_profile(port, profile_fname)

                shutdown_thread.join(timeout=2)

            # Verify that IPython.core.display.display was called (old style fallback)
            assert len(old_display_called) == 1, "IPython.core.display.display fallback was not called"

        finally:
            # Restore original modules
            for mod in modules_to_remove:
                sys.modules.pop(mod, None)
            for k, v in original_modules.items():
                if k.startswith('IPython'):
                    sys.modules[k] = v

    finally:
        os.unlink(profile_fname)
        # Reload the original module
        import scalene.scalene_jupyter
        importlib.reload(scalene.scalene_jupyter)
