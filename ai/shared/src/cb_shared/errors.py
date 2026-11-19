class AIError(Exception):
    """A text model could not produce an answer."""


class AIUnavailableError(AIError):
    """No API key, key rejected, no internet, or the library is missing."""


class AIBusyError(AIUnavailableError):
    """Every model in the chain was overloaded (HTTP 500/503), even after retries."""


class AIQuotaError(AIUnavailableError):
    """Rate limit or quota exceeded (HTTP 429) on every model in the chain."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class AILimitError(AIError):
    """The per-run request limit was reached."""
