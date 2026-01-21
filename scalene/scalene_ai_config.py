"""
Scalene AI configuration management.

Handles reading and writing AI provider settings from ~/.scalene/config.json.
Priority order for configuration values:
1. Environment variables (highest priority)
2. Config file (~/.scalene/config.json)
3. Default values (lowest priority)
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

# Default config directory and file
SCALENE_CONFIG_DIR = Path.home() / ".scalene"
SCALENE_CONFIG_FILE = SCALENE_CONFIG_DIR / "config.json"

# Mapping of config keys to environment variables
CONFIG_TO_ENV_MAP: Dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "openai_model": "OPENAI_MODEL",
    "openai_url": "OPENAI_API_BASE",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "anthropic_model": "ANTHROPIC_MODEL",
    "anthropic_url": "ANTHROPIC_API_BASE",
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
    "azure_api_key": "AZURE_OPENAI_API_KEY",
    "azure_api_url": "AZURE_OPENAI_ENDPOINT",
    "azure_model": "AZURE_OPENAI_MODEL",
    "azure_api_version": "AZURE_OPENAI_API_VERSION",
    "aws_access_key": "AWS_ACCESS_KEY_ID",
    "aws_secret_key": "AWS_SECRET_ACCESS_KEY",
    "aws_region": "AWS_DEFAULT_REGION",
    "aws_model": "AWS_BEDROCK_MODEL",
    "ollama_host": "OLLAMA_HOST",
    "ollama_port": "OLLAMA_PORT",
    "ollama_model": "OLLAMA_MODEL",
    "default_provider": "SCALENE_AI_PROVIDER",
}

# Valid configuration keys (for validation)
VALID_CONFIG_KEYS = set(CONFIG_TO_ENV_MAP.keys())


def get_config_dir() -> Path:
    """Get the Scalene configuration directory, creating it if needed."""
    SCALENE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return SCALENE_CONFIG_DIR


def get_config_file() -> Path:
    """Get the path to the config file."""
    return SCALENE_CONFIG_FILE


def load_config() -> Dict[str, Any]:
    """Load configuration from the config file.

    Returns an empty dict if the file doesn't exist or is invalid.
    """
    config_file = get_config_file()
    if not config_file.exists():
        return {}

    try:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
            if isinstance(config, dict):
                return config
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: Dict[str, Any]) -> bool:
    """Save configuration to the config file.

    Returns True if successful, False otherwise.
    """
    try:
        get_config_dir()  # Ensure directory exists
        config_file = get_config_file()

        # Filter to only valid keys
        filtered_config = {k: v for k, v in config.items() if k in VALID_CONFIG_KEYS}

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(filtered_config, f, indent=2)
        return True
    except OSError:
        return False


def get_config_value(key: str, default: str = "") -> str:
    """Get a configuration value with priority: env var > config file > default.

    Args:
        key: The configuration key (e.g., 'openai_api_key')
        default: Default value if not found anywhere

    Returns:
        The configuration value
    """
    # First check environment variable
    env_var = CONFIG_TO_ENV_MAP.get(key)
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value:
            return env_value

    # Special case for GEMINI_API_KEY - also check GOOGLE_API_KEY
    if key == "gemini_api_key":
        google_key = os.environ.get("GOOGLE_API_KEY")
        if google_key:
            return google_key

    # Special case for AWS region - also check AWS_REGION
    if key == "aws_region":
        aws_region = os.environ.get("AWS_REGION")
        if aws_region:
            return aws_region

    # Then check config file
    config = load_config()
    if key in config and config[key]:
        return str(config[key])

    return default


def set_config_value(key: str, value: str) -> bool:
    """Set a configuration value in the config file.

    Args:
        key: The configuration key
        value: The value to set (empty string to remove)

    Returns:
        True if successful, False otherwise
    """
    if key not in VALID_CONFIG_KEYS:
        return False

    config = load_config()

    if value:
        config[key] = value
    elif key in config:
        del config[key]

    return save_config(config)


def delete_config_value(key: str) -> bool:
    """Delete a configuration value from the config file.

    Args:
        key: The configuration key to delete

    Returns:
        True if successful, False otherwise
    """
    return set_config_value(key, "")


def get_all_ai_config() -> Dict[str, str]:
    """Get all AI configuration values for template rendering.

    This is the main entry point used by scalene_utility.py.
    Returns a dict with all configuration values, using the priority:
    env var > config file > empty string.
    """
    return {
        "openai_api_key": get_config_value("openai_api_key"),
        "openai_model": get_config_value("openai_model"),
        "openai_url": get_config_value("openai_url"),
        "anthropic_api_key": get_config_value("anthropic_api_key"),
        "anthropic_model": get_config_value("anthropic_model"),
        "anthropic_url": get_config_value("anthropic_url"),
        "gemini_api_key": get_config_value("gemini_api_key"),
        "gemini_model": get_config_value("gemini_model"),
        "azure_api_key": get_config_value("azure_api_key"),
        "azure_api_url": get_config_value("azure_api_url"),
        "azure_model": get_config_value("azure_model"),
        "azure_api_version": get_config_value("azure_api_version"),
        "aws_access_key": get_config_value("aws_access_key"),
        "aws_secret_key": get_config_value("aws_secret_key"),
        "aws_region": get_config_value("aws_region"),
        "aws_model": get_config_value("aws_model"),
        "ollama_host": get_config_value("ollama_host"),
        "ollama_port": get_config_value("ollama_port"),
        "ollama_model": get_config_value("ollama_model"),
        "default_provider": get_config_value("default_provider"),
    }


def list_config() -> Dict[str, str]:
    """List all configuration values from the config file only.

    This doesn't include environment variables - it shows what's
    actually stored in the config file.
    """
    return load_config()


def clear_config() -> bool:
    """Clear all configuration from the config file.

    Returns True if successful, False otherwise.
    """
    return save_config({})


def get_config_source(key: str) -> str:
    """Get the source of a configuration value.

    Returns one of: 'env', 'config', 'default'
    """
    # Check environment variable
    env_var = CONFIG_TO_ENV_MAP.get(key)
    if env_var and os.environ.get(env_var):
        return "env"

    # Special cases
    if key == "gemini_api_key" and os.environ.get("GOOGLE_API_KEY"):
        return "env"
    if key == "aws_region" and os.environ.get("AWS_REGION"):
        return "env"

    # Check config file
    config = load_config()
    if key in config and config[key]:
        return "config"

    return "default"
