"""CampusBridge narrator: guidance phrases around lecture files and platform data, for text-to-speech.

No AI: every phrase is a fixed template. Content (file text, question text, messages) is kept in
its own language; the guidance phrases follow CB_EXPLAIN_LANGUAGE (ar/mixed -> Arabic, en -> English).
"""
from .assignment import AssignmentNarrator
from .chat import ChatNarrator
from .config import NarratorConfig
from .errors import ConfigError, InputError, NarratorError, ReaderUnavailableError
from .files import FileNarration, FileNarrator
from .navigation import Navigator
from .notifications import NotificationNarrator
from .quiz import QuizNarrator, public_quiz
from .segments import Segment, speech_text, to_dicts

__all__ = [
    "NarratorConfig", "Segment", "speech_text", "to_dicts",
    "FileNarrator", "FileNarration", "Navigator",
    "QuizNarrator", "public_quiz", "AssignmentNarrator", "ChatNarrator", "NotificationNarrator",
    "NarratorError", "ConfigError", "InputError", "ReaderUnavailableError",
]
