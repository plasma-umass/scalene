# file scalene/scalene_utility.py (show_browser)

import os
import sys
import webbrowser

import pytest

from scalene.scalene_utility import show_browser


def test_show_browser_delegates_to_launchbrowser(tmp_path, monkeypatch):
    """show_browser only spawns launchbrowser.py, which stages the page and
    opens the browser itself on the port it actually binds. show_browser
    must not open a tab of its own (that duplicated the tab, and pointed at
    the wrong port whenever launchbrowser moved past a busy one)."""
    page = tmp_path / "index.html"
    page.write_text("<html><body><h1>Test Page</h1></body></html>")

    def fail_open(*args, **kwargs):
        pytest.fail("show_browser must not open a browser itself")

    monkeypatch.setattr(webbrowser, "open", fail_open)
    monkeypatch.setattr(webbrowser, "open_new", fail_open)

    launched = []

    class MockPopen:
        def __init__(self, args, **kwargs):
            launched.append(args)

    monkeypatch.setattr("subprocess.Popen", MockPopen)

    curr_dir = os.getcwd()
    show_browser(str(page), 12345, orig_python=sys.executable)

    assert os.getcwd() == curr_dir
    assert len(launched) == 1
    python, script, filename, port = launched[0]
    assert python == sys.executable
    assert os.path.basename(script) == "launchbrowser.py"
    assert filename == str(page)
    assert port == "12345"


def test_show_browser_ignores_launch_failure(tmp_path, monkeypatch):
    def raise_oserror(*args, **kwargs):
        raise FileNotFoundError("no python")

    monkeypatch.setattr("subprocess.Popen", raise_oserror)
    show_browser(str(tmp_path / "index.html"), 12345, orig_python="/nonexistent")
