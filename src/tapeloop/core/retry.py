"""Retry policy: exponential backoff with jitter, honouring Retry-After.

**On determinism.** AGENTS.md bans unseeded randomness in ``src/`` because it breaks
replay (Contract 1). Jitter is the exception, and the reason it is safe is specific:
retry timing is transport-level. It never reaches a prompt, never reaches a step key,
and never appears on the tape. The policy still owns a *seeded* ``random.Random``
rather than touching the global one, so two identical processes behave identically and
nothing else in the program has its random stream perturbed.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from tapeloop.core.cancel import CancellationToken
from tapeloop.core.errors import Cancelled, ProviderError

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    """How many times, how long, and on what."""

    max_attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.25
    seed: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)  # noqa: S311 - timing only, never cryptographic

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        """Seconds to wait before ``attempt`` (1-based).

        A server-supplied ``Retry-After`` always wins: it is information we do not have,
        and ignoring it is how a client gets itself rate-limited harder.
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        raw = min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)
        spread = raw * self.jitter
        return max(0.0, raw + self._rng.uniform(-spread, spread))

    def call(self, fn: Callable[[], T], *, token: CancellationToken | None = None) -> T:
        """Run ``fn``, retrying only what is worth retrying.

        Anything that is not a retryable ProviderError propagates immediately. A bad
        request retried is a bad request twice.
        """
        last: ProviderError | None = None
        for attempt in range(1, self.max_attempts + 1):
            if token and token.cancelled:
                raise Cancelled(token.reason)
            try:
                return fn()
            except ProviderError as e:
                if not e.retryable or attempt == self.max_attempts:
                    raise
                last = e
                wait = self.delay_for(attempt, retry_after=e.retry_after)
                # Sleep on the token so Ctrl-C during a long backoff is felt at once.
                if token is not None:
                    if token.wait(wait):
                        raise Cancelled(token.reason) from e
                else:
                    _sleep(wait)
        raise last if last else RuntimeError("unreachable")


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
