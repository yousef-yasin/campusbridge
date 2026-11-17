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
