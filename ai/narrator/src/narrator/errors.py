class NarratorError(Exception):
    """Base error for the narrator module."""


class ConfigError(NarratorError):
    """A setting is invalid."""


class InputError(NarratorError):
    """The platform data is missing something required or has a wrong type."""


class ReaderUnavailableError(NarratorError):
    """The document-reader module cannot be imported."""
