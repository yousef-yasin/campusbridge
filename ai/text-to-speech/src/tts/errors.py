class TTSError(Exception):
    """Base error for the text-to-speech module."""


class ConfigError(TTSError):
    """A setting is invalid (unknown engine or language, speed out of range)."""


class EmptyTextError(TTSError):
    """There is nothing to speak (empty text, or only symbols)."""


class InputNotFoundError(TTSError):
    """The text file to read is missing."""


class EngineUnavailableError(TTSError):
    """The TTS engine cannot be used (package not installed, no API key, or no network)."""


class QuotaExceededError(EngineUnavailableError):
    """The service refused the request because a rate limit or quota was hit (HTTP 429)."""


class VoiceNotFoundError(TTSError):
    """The voice model for the requested language is not available."""


class SynthesisError(TTSError):
    """The engine failed to produce audio for the given text."""


class PhraseError(TTSError):
    """Invalid quick-phrase operation (unknown id, empty text, editing a default)."""
