"""Orchestration shapes, and the cost of choosing wrong.

Two ways to run items through several stages:

**Barrier** — every item finishes stage 1 before any starts stage 2. Correct only
when a later stage genuinely needs cross-item context: deduplicating across all
results, or deciding to stop because the total came to nothing.

**Pipeline** — each item flows through every stage independently. Item A can be in
stage 3 while B is still in stage 1.

Pipeline is the default because a barrier's cost is invisible: it does not fail, it
just wastes wall-clock. If the slowest item in a stage takes three times the fastest,
every fast item sits idle waiting for it, once per stage. The measurement below makes
that cost visible rather than arguable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")
Stage = Callable[[T], T]


@dataclass(slots=True)
class Trace:
    """Which stage each item was in, tick by tick. The evidence for the shape."""

    ticks: list[list[str]] = field(default_factory=list[list[str]])

    def record(self, states: Sequence[str]) -> None:
        self.ticks.append(list(states))

    @property
    def duration(self) -> int:
        return len(self.ticks)


def barrier(
    items: Sequence[T], stages: Sequence[Stage[T]], *, cost: Callable[[T, int], int] | None = None
) -> tuple[list[T], int]:
    """Every item clears stage N before any starts N+1.

    Wall-clock is the sum over stages of that stage's slowest item.
    """
    current = list(items)
    elapsed = 0
    for index, stage in enumerate(stages):
        slowest = 0
        nxt: list[T] = []
        for item in current:
            slowest = max(slowest, cost(item, index) if cost else 1)
            nxt.append(stage(item))
        elapsed += slowest
        current = nxt
    return current, elapsed


def pipeline(
    items: Sequence[T], stages: Sequence[Stage[T]], *, cost: Callable[[T, int], int] | None = None
) -> tuple[list[T], int]:
    """Each item runs every stage independently, no barrier between them.

    Wall-clock is the slowest single *chain*, not the sum of per-stage slowest.
    """
    out: list[T] = []
    longest = 0
    for item in items:
        current = item
        chain = 0
        for index, stage in enumerate(stages):
            chain += cost(item, index) if cost else 1
            current = stage(current)
        longest = max(longest, chain)
        out.append(current)
    return out, longest


@dataclass(frozen=True, slots=True)
class ShapeComparison:
    barrier_time: int
    pipeline_time: int

    @property
    def saved(self) -> int:
        return self.barrier_time - self.pipeline_time

    @property
    def ratio(self) -> float:
        return self.pipeline_time / self.barrier_time if self.barrier_time else 1.0

    def __str__(self) -> str:
        return (
            f"barrier={self.barrier_time} pipeline={self.pipeline_time} "
            f"saved={self.saved} ({1 - self.ratio:.0%})"
        )


def compare_shapes(
    items: Sequence[T], stages: Sequence[Stage[T]], *, cost: Callable[[T, int], int]
) -> ShapeComparison:
    """Run both shapes over the same work and report the difference.

    Deterministic: `cost` is a pure function of (item, stage), so the comparison is
    a property of the workload rather than of the machine it ran on.
    """
    _, b = barrier(items, stages, cost=cost)
    _, p = pipeline(items, stages, cost=cost)
    return ShapeComparison(barrier_time=b, pipeline_time=p)
