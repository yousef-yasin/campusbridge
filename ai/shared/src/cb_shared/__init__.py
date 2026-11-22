"""Shared CampusBridge AI utilities: the Gemini text client, the generic text-unit input,
the per-unit job loop with its reviewable cache, the checks, API keys and module paths."""
from .cache import REVIEW_STATES, ReviewCache, has_manual, merged
from .checks import missing_english, unverified_numbers
from .errors import AIBusyError, AIError, AILimitError, AIQuotaError, AIUnavailableError
from .gemini_text import DEFAULT_MODELS, GeminiText, GeminiTextConfig
from .glossary import Glossary, GlossaryError, load_glossary
from .jobs import UnitJob
from .keys import get_key, read_env_file, scrub
from .paths import use_module
from .units import TextUnit, UnitBlock, from_pages, from_transcript

__all__ = ["GeminiText", "GeminiTextConfig", "DEFAULT_MODELS", "TextUnit", "UnitBlock", "from_pages",
           "from_transcript", "UnitJob", "ReviewCache", "REVIEW_STATES", "merged", "has_manual",
           "unverified_numbers", "missing_english", "Glossary", "GlossaryError", "load_glossary", "get_key", "read_env_file", "scrub", "use_module",
           "AIError", "AIUnavailableError", "AIBusyError", "AIQuotaError", "AILimitError"]
