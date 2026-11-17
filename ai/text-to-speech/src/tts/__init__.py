"""CampusBridge Arabic/English text-to-speech module."""
from .cache import AudioCache
from .config import TTSConfig
from .engines import EdgeEngine, Engine, GeminiEngine, PiperEngine, get_engine
from .errors import (ConfigError, EmptyTextError, EngineUnavailableError, InputNotFoundError,
                     PhraseError, QuotaExceededError, SynthesisError, TTSError, VoiceNotFoundError)
from .phrases import Phrase, PhraseBook
from .synthesizer import Synthesizer
from .text import Segment, prepare
from .voices import PRESET_VOICES, Voice, resolve_voice

__all__ = [
    "TTSConfig", "Synthesizer", "Engine", "GeminiEngine", "EdgeEngine", "PiperEngine", "get_engine",
    "AudioCache", "PhraseBook", "Phrase", "Segment", "prepare",
    "PRESET_VOICES", "Voice", "resolve_voice",
    "TTSError", "ConfigError", "EmptyTextError", "InputNotFoundError",
    "EngineUnavailableError", "QuotaExceededError", "VoiceNotFoundError", "SynthesisError",
    "PhraseError",
]
