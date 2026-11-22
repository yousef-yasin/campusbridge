"""CampusBridge document reader: content extraction from .docx, .pdf, .pptx, .xlsx and images."""
from .config import ReaderConfig
from .describe import CATEGORIES, ImageDescriber
from .explain import explain_language
from .document import Document, detect_type, open_document
from .errors import (ConfigError, CorruptFileError, InputNotFoundError, PageNotFoundError,
                     PasswordProtectedError, ReaderError, UnsupportedFormatError, VisionBusyError,
                     VisionError, VisionQuotaError, VisionUnavailableError)
from .lang import detect_language
from .model import Block, DocumentInfo, OutlineEntry, Page, SheetInfo
from .ocr import UNCLEAR, PageOCR
from .speech import SpeechUnit, to_speech_text

__all__ = [
    "open_document", "detect_type", "Document", "ReaderConfig",
    "Block", "Page", "DocumentInfo", "OutlineEntry", "SheetInfo",
    "to_speech_text", "SpeechUnit", "detect_language",
    "ImageDescriber", "CATEGORIES", "explain_language", "PageOCR", "UNCLEAR",
    "VisionError", "VisionUnavailableError", "VisionQuotaError", "VisionBusyError",
    "ReaderError", "InputNotFoundError", "UnsupportedFormatError", "PasswordProtectedError",
    "CorruptFileError", "PageNotFoundError", "ConfigError",
]
