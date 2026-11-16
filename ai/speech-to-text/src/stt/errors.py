class STTError(Exception):
    """Base error for the speech-to-text module."""


class AudioNotFoundError(STTError):
    """Audio file is missing or empty."""


class ModelUnavailableError(STTError):
    """The STT model could not be loaded (missing, offline, unsupported device)."""


class TranscriptionError(STTError):
    """Transcription failed for the given audio."""
