"""API keys: read from the environment or a .env file. Never log or print a key.

Same rules as the keys modules of document-reader and text-to-speech.
"""
import os
from pathlib import Path
from typing import Iterable, Union


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


def get_key(name: str, env_files: Union[str, Path, Iterable]) -> str:
    """The key from the process environment, else from the first .env file that has it; ''."""
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    files = [env_files] if isinstance(env_files, (str, Path)) else list(env_files)
    for path in files:
        value = read_env_file(path).get(name, "")
        if value:
            return value
    return ""


def scrub(message: str, *secrets: str) -> str:
    """Remove secrets from a message before it is logged, raised or printed."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message
