"""Cooperative cancellation.

Killing a process mid-stream is easy; stopping *cleanly* is the work. A half-written
assistant message on the tape is worse than no message, because a later replay would
treat it as something the model actually said.

The token is checked between stream chunks and between steps. Nothing is ever killed
mid-write: the loop notices, discards the partial turn, and records that it was
cancelled — which is a fact about the run, not a gap in it.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Generator
from contextlib import contextmanager
from types import FrameType


class CancellationToken:
    """A thread-safe flag, plus the reason it was set."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> None:
        self._reason = reason
        self._event.set()

    def wait(self, timeout: float) -> bool:
        """Sleep, but wake immediately on cancellation.

        Used by the retry backoff so a Ctrl-C during a 30-second wait is felt at once
        rather than thirty seconds later.
        """
        return self._event.wait(timeout)


@contextmanager
def on_sigint(token: CancellationToken) -> Generator[CancellationToken]:
    """Route Ctrl-C into the token instead of a KeyboardInterrupt.

    A second Ctrl-C restores the default handler and re-raises, so an operator who
    means it is never trapped by a runtime that will not let go.
    """

    def handle(_signum: int, _frame: FrameType | None) -> None:
        if token.cancelled:
            signal.signal(signal.SIGINT, previous)
            raise KeyboardInterrupt
        token.cancel("interrupted by user")

    try:
        previous = signal.signal(signal.SIGINT, handle)
    except ValueError:
        # Not on the main thread; the caller sets the token itself.
        yield token
        return
    try:
        yield token
    finally:
        signal.signal(signal.SIGINT, previous)
