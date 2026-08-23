"""Seam 3 — TranscriptStore.

The real tape is M3: append-only JSONL with a versioned schema and content-addressed
step keys. This seam exists now so the loop already writes through it, and M3 swaps
the backend instead of threading recording into code that never had it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened. The unit the tape is made of."""

    kind: str
    step: int
    payload: dict[str, Any] = field(default_factory=dict[str, Any])


@runtime_checkable
class TranscriptStore(Protocol):
    def append(self, event: Event) -> None: ...

    def events(self) -> Iterator[Event]: ...


class InMemoryStore:
    """M1 placeholder. Holds events for the life of the process, then forgets them.

    Deliberately not durable: a half-finished JSONL format now would become a
    compatibility promise (ADR-0010) before the format was thought through.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, event: Event) -> None:
        self._events.append(event)

    def events(self) -> Iterator[Event]:
        yield from self._events

    @property
    def collected(self) -> Sequence[Event]:
        return tuple(self._events)
