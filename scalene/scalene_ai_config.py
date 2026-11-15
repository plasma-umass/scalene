"""AI provider settings saved in ~/.scalene/config.json (#911).

`scalene config set KEY` saves a setting; the local server started by
`scalene view` reads the file on each request and hands the values to the
GUI over the same same-origin endpoint as --api-keys-from-env, which fills
fields the user hasn't set in the browser. Nothing here is ever written
into a generated HTML file (#1095).

The file holds API keys, so it is created readable by its owner only.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

# Config key -> the GUI field name served at /env-api-keys.json (see
# persistence.ts, EnvApiKeys).
CONFIG_KEYS: dict[str, str] = {
    "openai_api_key": "openai",
    "openai_model": "openaiModel",
    "openai_url": "openaiUrl",
    "anthropic_api_key": "anthropic",
    "anthropic_model": "anthropicModel",
    "anthropic_url": "anthropicUrl",
    "gemini_api_key": "gemini",
    "gemini_model": "geminiModel",
    "gemini_url": "geminiUrl",
    "azure_api_key": "azure",
    "azure_api_url": "azureUrl",
    "azure_api_version": "azureApiVersion",
    "azure_model": "azureModel",
    "aws_access_key": "awsAccessKey",
    "aws_secret_key": "awsSecretKey",
    "aws_region": "awsRegion",
    "ollama_host": "ollamaHost",
    "ollama_port": "ollamaPort",
    "default_provider": "defaultProvider",
}

SECRET_KEYS = frozenset(
    {
        "openai_api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "azure_api_key",
        "aws_access_key",
        "aws_secret_key",
    }
)

# The GUI's provider choices (index.html.template, #service-select).
PROVIDERS = ("openai", "anthropic", "gemini", "azure-openai", "amazon", "local")


class ConfigError(Exception):
    """A setting that can't be saved, or a config file that can't be read."""


def config_file() -> Path:
    """The config file's path (looked up each time, so tests can move HOME)."""
    return Path.home() / ".scalene" / "config.json"


def load_config() -> dict[str, str]:
    """The saved settings; empty if there is no file.

    Unknown keys and non-string values are ignored. Raises ConfigError if
    the file exists but isn't a JSON object.
    """
    path = config_file()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e}") from e
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    return {
        k: v for k, v in data.items() if k in CONFIG_KEYS and isinstance(v, str) and v
    }


def save_config(config: dict[str, str]) -> None:
    """Replace the saved settings, atomically and readable only by the owner."""
    path = config_file()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".json")
    try:
        # mkstemp creates the file 0600 on every platform.
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(config.items())), f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def check_key(key: str) -> None:
    """Raise ConfigError unless KEY is a setting this file can hold."""
    if key not in CONFIG_KEYS:
        raise ConfigError(
            f"unknown key '{key}'; valid keys: {', '.join(sorted(CONFIG_KEYS))}"
        )


def validate(key: str, value: str) -> None:
    """Raise ConfigError unless KEY is known and VALUE is acceptable for it."""
    check_key(key)
    if key == "default_provider" and value not in PROVIDERS:
        raise ConfigError(f"default_provider must be one of: {', '.join(PROVIDERS)}")
    if key == "ollama_port" and not (value.isdigit() and 0 < int(value) < 65536):
        raise ConfigError("ollama_port must be a port number")


def set_value(key: str, value: str) -> None:
    validate(key, value)
    config = load_config()
    config[key] = value
    save_config(config)


def unset_value(key: str) -> bool:
    """Remove KEY; False if it wasn't set."""
    check_key(key)
    config = load_config()
    if key not in config:
        return False
    del config[key]
    save_config(config)
    return True


def gui_settings() -> dict[str, str]:
    """Saved settings keyed by GUI field name, for the local server.

    An unreadable file yields nothing: the GUI must still open.
    """
    try:
        config = load_config()
    except ConfigError:
        return {}
    return {CONFIG_KEYS[k]: v for k, v in config.items()}


def display_value(key: str, value: str) -> str:
    """VALUE as `scalene config` shows it: secrets are masked."""
    return "********" if key in SECRET_KEYS else value
