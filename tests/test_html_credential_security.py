import http.client
import json
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

import pytest

from scalene import launchbrowser
from scalene.scalene_utility import Filename, generate_html

SENSITIVE_ENVIRONMENT_VARIABLES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "AWS_REGION",
)


@pytest.mark.parametrize("standalone", [False, True])
def test_generate_html_does_not_embed_environment_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, standalone: bool
) -> None:
    marker = "SCALENE_TEST_CREDENTIAL_MUST_NOT_APPEAR"
    for variable in SENSITIVE_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(variable, marker)

    profile = tmp_path / "profile.json"
    output = tmp_path / "profile.html"
    profile.write_text("{}", encoding="utf-8")

    generate_html(Filename(str(profile)), Filename(str(output)), standalone=standalone)

    rendered = output.read_text(encoding="utf-8")
    assert marker not in rendered


# --- `scalene view --api-keys-from-env` -------------------------------------
#
# Opting in must not put credentials back into the HTML; they are served from
# memory by launchbrowser's local server, to same-origin requests only.

@pytest.fixture
def key_server(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Tuple[int, pytest.MonkeyPatch]]:
    for variable in SENSITIVE_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), launchbrowser.CustomHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], monkeypatch
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get_keys(
    port: int, host: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> Tuple[int, Dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("GET", launchbrowser.ENV_API_KEYS_PATH, skip_host=True)
        conn.putheader("Host", host if host is not None else f"localhost:{port}")
        for name, value in (headers or {}).items():
            conn.putheader(name, value)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_key_endpoint_is_empty_without_opt_in(key_server) -> None:
    port, monkeypatch = key_server
    monkeypatch.setattr(launchbrowser.CustomHandler, "serve_env_api_keys", False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-served")

    status, _, body = _get_keys(port)

    assert status == 200
    assert json.loads(body) == {}


def test_key_endpoint_serves_environment_keys_with_opt_in(key_server) -> None:
    port, monkeypatch = key_server
    monkeypatch.setattr(launchbrowser.CustomHandler, "serve_env_api_keys", True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-fallback")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    status, headers, body = _get_keys(port)

    assert status == 200
    assert json.loads(body) == {
        "openai": "sk-openai",
        "gemini": "google-fallback",
        "awsAccessKey": "AKIA-test",
        "awsSecretKey": "aws-secret",
        "awsRegion": "us-west-2",
    }
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    # No CORS grant: other origins must not be able to read the response.
    assert "Access-Control-Allow-Origin" not in headers


@pytest.mark.parametrize(
    "host, headers",
    [
        # DNS rebinding: an attacker's domain resolving to 127.0.0.1.
        ("attacker.example:8080", {}),
        ("", {}),
        # Browsers label requests initiated by other sites.
        (None, {"Sec-Fetch-Site": "cross-site"}),
        (None, {"Sec-Fetch-Site": "same-site"}),
    ],
)
def test_key_endpoint_rejects_foreign_requests(
    key_server, host: Optional[str], headers: Dict[str, str]
) -> None:
    port, monkeypatch = key_server
    monkeypatch.setattr(launchbrowser.CustomHandler, "serve_env_api_keys", True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    status, _, body = _get_keys(port, host=host, headers=headers)

    assert status == 403
    assert b"sk-openai" not in body


@pytest.mark.parametrize("mode", ["--cli", "--html", "--standalone"])
def test_view_rejects_api_keys_from_env_for_file_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    marker = "SCALENE_TEST_CREDENTIAL_MUST_NOT_APPEAR"
    monkeypatch.setenv("OPENAI_API_KEY", marker)
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "scalene", "view", "--api-keys-from-env", mode, str(profile)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "--api-keys-from-env" in result.stderr
    assert not (tmp_path / "scalene-profile.html").exists()
