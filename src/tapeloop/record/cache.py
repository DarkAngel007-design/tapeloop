"""The step cache: what makes replay free.

A recorded run is an index from step key to model response. Re-running the same
agent produces the same keys, so every step is a hit and nothing is paid for.
Change a prompt and the keys diverge from that point on — the steps before it
still hit, the rest run live. That prefix property is the entire feature.

This does not by itself make replay *sound*: serving a cached result for a tool
that mutated something is a simulation, not a re-execution. That distinction is
ADR-0006, and it lives in the executor, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tapeloop.events import ModelResponse
from tapeloop.record.codec import decode_response
from tapeloop.record.jsonl import read_records


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


@dataclass(slots=True)
class StepCache:
    """Model responses from a previous run, indexed by step key."""

    responses: dict[str, ModelResponse] = field(default_factory=dict[str, ModelResponse])
    stats: CacheStats = field(default_factory=CacheStats)

    @classmethod
    def from_tape(cls, path: Path) -> StepCache:
        responses: dict[str, ModelResponse] = {}
        for record in read_records(path):
            if record.get("kind") == "step" and "key" in record:
                responses[record["key"]] = decode_response(record["data"])
        return cls(responses=responses)

    def get(self, key: str) -> ModelResponse | None:
        hit = self.responses.get(key)
        if hit is None:
            self.stats.misses += 1
        else:
            self.stats.hits += 1
        return hit
