"""launchbrowser must serve only the profile page and its assets.

It used to copy them into the shared system temp directory and serve that
whole directory, exposing every file in it to anything that could reach
localhost (and following any symlink another user planted at the fixed
index.html path).
"""

import http.client
import os
import socketserver
import stat
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path
from typing import Iterator, Tuple

import pytest

from scalene import launchbrowser


@pytest.fixture
def served(tmp_path: Path) -> Iterator[Tuple[str, int]]:
    page = tmp_path / "profile.html"
    page.write_text("<html>SCALENE-PAGE</html>", encoding="utf-8")
    directory = launchbrowser.prepare_serve_dir(str(page))
    handler = partial(launchbrowser.CustomHandler, directory=directory)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield directory, httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()
        launchbrowser.remove_serve_dir()


def _get(port: int, path: str) -> Tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_serve_dir_is_private_and_holds_page_and_assets(served) -> None:
    directory, _ = served
    assert os.path.dirname(directory) == tempfile.gettempdir()
    assert os.path.realpath(directory) != os.path.realpath(tempfile.gettempdir())
    assert "index.html" in os.listdir(directory)
    assert "scalene-gui-bundle.js" in os.listdir(directory)
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700


def test_page_is_served(served) -> None:
    _, port = served
    for path in ("/", "/index.html"):
        status, body = _get(port, path)
        assert status == 200
        assert b"SCALENE-PAGE" in body


def test_other_temp_files_are_not_served(served) -> None:
    _, port = served
    with tempfile.NamedTemporaryFile(
        "w", dir=tempfile.gettempdir(), suffix=".secret", delete=False
    ) as f:
        f.write("SCALENE-SECRET")
    name = os.path.basename(f.name)
    try:
        for path in (f"/{name}", f"/../{name}", f"/%2e%2e/{name}"):
            status, body = _get(port, path)
            assert status == 404, path
            assert b"SCALENE-SECRET" not in body
    finally:
        os.unlink(f.name)


def test_directory_listings_are_disabled(served) -> None:
    directory, port = served
    os.mkdir(os.path.join(directory, "sub"))
    status, _ = _get(port, "/sub/")
    assert status == 404


def test_remove_serve_dir_deletes_it(tmp_path: Path) -> None:
    page = tmp_path / "profile.html"
    page.write_text("<html></html>", encoding="utf-8")
    directory = launchbrowser.prepare_serve_dir(str(page))
    launchbrowser.remove_serve_dir()
    assert not os.path.exists(directory)
