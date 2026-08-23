"""Effect classes (ADR-0005).

Replay is only sound if the runtime knows which tools touch the world.
"""

from __future__ import annotations

from enum import StrEnum


class Effect(StrEnum):
    """How a tool interacts with the world, and therefore how replay treats it."""

    PURE = "pure"
    """Same input, same output. No observation, no mutation. Always cache on replay."""

    READ = "read"
    """Observes external state, mutates nothing. Cached by default; --fresh re-executes."""

    WRITE = "write"
    """Mutates filesystem, network, or database. Cache / reexecute / halt, by policy."""

    @property
    def replay_is_sound_from_cache(self) -> bool:
        """True when serving a cached result cannot mislead.

        WRITE is False not because caching it is forbidden — that is the default
        policy — but because doing so makes the run a *simulation*, which is the
        whole of ADR-0006. Callers use this to decide whether to say so.
        """
        return self is not Effect.WRITE
