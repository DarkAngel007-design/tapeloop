"""The error taxonomy.

One broad ``except Exception`` around an API call is how a permanent misconfiguration
gets retried sixteen times and how a transient blip kills a forty-minute run. The only
question that matters at the call site is *is this worth trying again*, so that is what
the taxonomy encodes.
"""

from __future__ import annotations


class TapeloopError(Exception):
    """Base for everything this package raises."""


class ProviderError(TapeloopError):
    """Something went wrong talking to a model provider."""

    retryable: bool = False

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimited(ProviderError):
    """429. Retryable, and the provider usually tells us how long to wait."""

    retryable = True


class ProviderUnavailable(ProviderError):
    """5xx or a connection failure. Retryable; the provider tells us nothing."""

    retryable = True


class RequestInvalid(ProviderError):
    """4xx that is not 429. A bad request retried is a bad request twice."""


class AuthenticationFailed(ProviderError):
    """401/403. Never retryable — waiting does not produce a key."""


class Cancelled(TapeloopError):
    """The run was interrupted. Not a failure: an outcome."""


class BudgetExceeded(TapeloopError):
    """A step or token ceiling was reached."""
