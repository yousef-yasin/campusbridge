"""CampusBridge Arabic speech-to-text module."""
from .config import STTConfig
from .errors import AudioNotFoundError, ModelUnavailableError, STTError, TranscriptionError
from .live import LiveSession
from .transcriber import Transcriber
from .transcript import Segment, Transcript

__all__ = [
    "STTConfig", "Transcriber", "LiveSession", "Segment", "Transcript",
    "STTError", "AudioNotFoundError", "ModelUnavailableError", "TranscriptionError",
]
