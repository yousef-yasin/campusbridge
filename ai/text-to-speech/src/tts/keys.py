"""API keys: read from the environment or the module's .env file. Never log or print a key."""
import os
from pathlib import Path


def read_env_file(path) -> dict:
    """Parse KEY=VALUE lines of a .env file. Missing or unreadable file -> {}."""
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[7:].strip()
        values[name] = value.strip().strip("'\"").strip()
    return values


def get_key(name: str, env_file) -> str:
    """The key from the process environment, else from the .env file; '' when not set."""
    return (os.environ.get(name) or "").strip() or read_env_file(env_file).get(name, "")


def scrub(message: str, *secrets: str) -> str:
    """Remove secrets from a message before it is logged, raised or printed."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message
