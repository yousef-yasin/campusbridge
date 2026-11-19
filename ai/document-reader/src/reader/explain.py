"""Moved to ai/shared (cb_shared.explain): the explanation language shared by every AI module.

This module re-exports it so document-reader code and callers keep working unchanged, and keeps
document-reader's ConfigError for an unknown language.
"""
import sys
from pathlib import Path
from typing import Optional

_SHARED = Path(__file__).resolve().parents[3] / "shared" / "src"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from cb_shared import explain as _shared                       # noqa: E402
from cb_shared.explain import *                                 # noqa: E402,F401,F403
from cb_shared.explain import DEFAULT, ENV_VAR, INSTRUCTIONS, LANGUAGES  # noqa: E402,F401

from .errors import ConfigError                                 # noqa: E402


def explain_language(value: Optional[str] = None) -> str:
    """The mode to use: an explicit value, else CB_EXPLAIN_LANGUAGE, else 'mixed'."""
    try:
        return _shared.explain_language(value)
    except _shared.LanguageError as exc:
        raise ConfigError(str(exc)) from None
