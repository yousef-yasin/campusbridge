class ReaderError(Exception):
    """Base error for the document-reader module."""


class InputNotFoundError(ReaderError):
    """The file is missing or empty."""


class UnsupportedFormatError(ReaderError):
    """The file type cannot be read (old binary Office format, or not a document)."""


class PasswordProtectedError(ReaderError):
    """The file is encrypted and needs a password."""


class CorruptFileError(ReaderError):
    """The file looks like a supported type but cannot be opened."""


class PageNotFoundError(ReaderError):
    """The requested page, slide or sheet does not exist."""


class ConfigError(ReaderError):
    """A setting is invalid."""


class VisionError(ReaderError):
    """The vision model could not describe an image."""


class VisionUnavailableError(VisionError):
    """No API key, key rejected, no internet, or the service is down."""


class VisionBusyError(VisionUnavailableError):
    """The service is temporarily overloaded (HTTP 500/503), even after retries."""


class VisionQuotaError(VisionUnavailableError):
    """Rate limit or quota exceeded (HTTP 429)."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after
