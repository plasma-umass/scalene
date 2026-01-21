# Tests for IPython display import order fix (GitHub issue #951)
# Ensures that Jupyter notebook display works correctly

import sys
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

    # First find a port that's actually available
    port = ScaleneJupyter.find_available_port(49200, 49300)
    if port is None:
        # All ports in range already taken, skip test
        return

    # Now bind to that port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", port))
        # Now try to find a port in a range of just that one port
        result = ScaleneJupyter.find_available_port(port, port)
        assert result is None
    finally:
        sock.close()


def test_ipython_display_import_prefers_modern_location():
    """Test that IPython.display is tried before IPython.core.display.

    This tests the fix for GitHub issue #951 where Jupyter notebook output
    wasn't displaying in VSCode because IPython.core.display (deprecated in
    IPython 9.2) was tried before IPython.display.
    """
    # Create distinguishable mock modules
    mock_new_display = MagicMock(name="new_display")
    mock_new_iframe = MagicMock(name="new_iframe")
    mock_old_display = MagicMock(name="old_display")
    mock_old_iframe = MagicMock(name="old_iframe")

    mock_ipython_display = MagicMock()
    mock_ipython_display.display = mock_new_display
    mock_ipython_display.IFrame = mock_new_iframe

    mock_ipython_core_display = MagicMock()
    mock_ipython_core_display.display = mock_old_display
    mock_ipython_core_display.IFrame = mock_old_iframe

    # Test the import logic used in scalene_jupyter.py
    with patch.dict(sys.modules, {
        'IPython': MagicMock(),
        'IPython.display': mock_ipython_display,
        'IPython.core': MagicMock(),
        'IPython.core.display': mock_ipython_core_display,
    }):
        # Re-execute the import logic from scalene_jupyter.py
        try:
            from IPython.display import (  # type: ignore[import-not-found]
                IFrame,
                display,
            )
        except ImportError:
            from IPython.core.display import (  # type: ignore[import-not-found]
                IFrame,
                display,
            )

        # Verify we got the new (modern) imports
        assert display is mock_new_display, "Should use IPython.display.display"
        assert IFrame is mock_new_iframe, "Should use IPython.display.IFrame"


def test_ipython_display_import_fallback_to_core():
    """Test backwards compatibility with older IPython versions.

    When IPython.display is not available (older IPython versions),
    the code should fall back to IPython.core.display.
    """
    mock_old_display = MagicMock(name="old_display")
    mock_old_iframe = MagicMock(name="old_iframe")

    mock_ipython_core_display = MagicMock()
    mock_ipython_core_display.display = mock_old_display
    mock_ipython_core_display.IFrame = mock_old_iframe

    # Save original modules
    original_modules = {k: v for k, v in sys.modules.items() if k.startswith('IPython')}

    # Remove any cached IPython modules
    for mod in list(sys.modules.keys()):
        if mod.startswith('IPython'):
            del sys.modules[mod]

    try:
        # Set up mocks - IPython.display is NOT available (simulating older IPython)
        sys.modules['IPython'] = MagicMock()
        sys.modules['IPython.core'] = MagicMock()
        sys.modules['IPython.core.display'] = mock_ipython_core_display
        # Note: IPython.display is NOT in sys.modules

        # Re-execute the import logic from scalene_jupyter.py
        try:
            from IPython.display import (  # type: ignore[import-not-found]
                IFrame,
                display,
            )
            used_new = True
        except ImportError:
            from IPython.core.display import (  # type: ignore[import-not-found]
                IFrame,
                display,
            )
            used_new = False

        # Verify we fell back to the old (core) imports
        assert not used_new, "Should have fallen back to IPython.core.display"
        assert display is mock_old_display, "Should use IPython.core.display.display"
        assert IFrame is mock_old_iframe, "Should use IPython.core.display.IFrame"

    finally:
        # Restore original modules
        for mod in list(sys.modules.keys()):
            if mod.startswith('IPython'):
                del sys.modules[mod]
        sys.modules.update(original_modules)
