"""`scalene config`: AI provider settings saved for the GUI (#911)."""

import json
import os
import site
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scalene import scalene_ai_config as ai_config


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def test_settings_round_trip(home: Path) -> None:
    ai_config.set_value("anthropic_api_key", "sk-ant")
    ai_config.set_value("ollama_port", "11434")
    assert ai_config.load_config() == {
        "anthropic_api_key": "sk-ant",
        "ollama_port": "11434",
    }
    assert ai_config.gui_settings() == {"anthropic": "sk-ant", "ollamaPort": "11434"}
    assert ai_config.unset_value("anthropic_api_key")
    assert not ai_config.unset_value("anthropic_api_key")
    assert ai_config.load_config() == {"ollama_port": "11434"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_file_is_readable_only_by_its_owner(home: Path) -> None:
    ai_config.set_value("openai_api_key", "sk-secret")
    path = ai_config.config_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # Rewriting keeps it private (the file is replaced, not reopened).
    ai_config.set_value("openai_model", "some-model")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "key, value",
    [
        ("not_a_key", "x"),
        ("default_provider", "not-a-provider"),
        ("ollama_port", "abc"),
        ("ollama_port", "70000"),
    ],
)
def test_bad_settings_are_rejected(home: Path, key: str, value: str) -> None:
    with pytest.raises(ai_config.ConfigError):
        ai_config.set_value(key, value)
    assert not ai_config.config_file().exists()


def test_unknown_entries_are_ignored_and_bad_files_reported(home: Path) -> None:
    path = ai_config.config_file()
    path.parent.mkdir()
    path.write_text(json.dumps({"openai_api_key": "sk", "other": "x", "aws_region": 3}))
    assert ai_config.load_config() == {"openai_api_key": "sk"}
    path.write_text("not json")
    with pytest.raises(ai_config.ConfigError):
        ai_config.load_config()
    # The GUI still opens.
    assert ai_config.gui_settings() == {}


def test_every_setting_has_a_gui_field() -> None:
    # Every served name must be one persistence.ts reads (EnvApiKeys).
    ts = (
        Path(ai_config.__file__).parent / "scalene-gui" / "persistence.ts"
    ).read_text()
    interface = ts.split("export interface EnvApiKeys {", 1)[1].split("}", 1)[0]
    for field in ai_config.CONFIG_KEYS.values():
        assert f"  {field}?: string;" in interface, field


def _scalene_config(home: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    # A new HOME would also move the user site-packages; keep the real one.
    env = dict(
        os.environ,
        HOME=str(home),
        USERPROFILE=str(home),
        PYTHONUSERBASE=site.getuserbase(),
    )
    return subprocess.run(
        [sys.executable, "-m", "scalene", "config", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_reads_secret_from_stdin_and_masks_it(tmp_path: Path) -> None:
    r = _scalene_config(tmp_path, "set", "openai_api_key", stdin="sk-from-stdin\n")
    assert r.returncode == 0, r.stderr
    assert "sk-from-stdin" not in r.stdout
    saved = json.loads((tmp_path / ".scalene" / "config.json").read_text())
    assert saved == {"openai_api_key": "sk-from-stdin"}

    r = _scalene_config(tmp_path, "set", "default_provider", "openai")
    assert r.returncode == 0, r.stderr

    r = _scalene_config(tmp_path)  # list
    assert r.returncode == 0, r.stderr
    assert "sk-from-stdin" not in r.stdout
    assert "openai_api_key = ********" in r.stdout
    assert "default_provider = openai" in r.stdout

    r = _scalene_config(tmp_path, "set", "nope", "x")
    assert r.returncode == 1
    assert "unknown key" in r.stderr

    r = _scalene_config(tmp_path, "unset", "openai_api_key")
    assert r.returncode == 0, r.stderr
    saved = json.loads((tmp_path / ".scalene" / "config.json").read_text())
    assert saved == {"default_provider": "openai"}
