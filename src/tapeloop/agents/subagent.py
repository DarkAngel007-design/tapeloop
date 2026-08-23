"""Subagents: a fresh context, a narrowed tool set, a structured return.

The structured return is what makes a subagent composable rather than merely
recursive. A child that hands back prose leaves the parent parsing English; one
that hands back a typed result can be counted, sorted and merged.

Each child writes its own tape (ADR-0021), because its step keys come from its own
prefix. Two key-spaces in one file would make a cache miss unexplainable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tapeloop.core.loop import Agent, RunResult
from tapeloop.record.base import Event, TranscriptStore
from tapeloop.record.jsonl import JsonlStore
from tapeloop.tools.registry import Registry


@dataclass(frozen=True, slots=True)
class SubagentResult:
    """What comes back. Deliberately narrow: the parent should not inherit the child's context."""

    label: str
    text: str
    steps: int
    input_tokens: int
    output_tokens: int
    tape: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


AgentBuilder = Callable[[Registry, Path], Agent]
"""(tools, tape) -> a configured child. The caller owns client, model and policy."""


@dataclass(slots=True)
class Spawner:
    """Creates children and records them against the parent."""

    build: AgentBuilder
    tapes: Path
    parent_store: TranscriptStore | None = None
    parent_tape: Path | None = None
    _n: int = field(default=0, init=False)

    def spawn(self, task: str, *, tools: Registry, label: str = "") -> SubagentResult:
        """Run one child to completion and return only its conclusion.

        Errors are captured, not raised. One failed child must not take down a
        fan-out -- the parent decides what a missing result means.
        """
        name = label or f"sub-{self._n:03}"
        self._n += 1
        tape = self.tapes / f"{name}.jsonl"

        child = self.build(tools, tape)
        if isinstance(child.store, JsonlStore) and self.parent_tape is not None:
            child.store.append(
                Event(kind="parent", step=0, payload={"tape": self.parent_tape.name})
            )

        try:
            result: RunResult = child.run(task)
        except Exception as e:
            outcome = SubagentResult(
                label=name,
                text="",
                steps=0,
                input_tokens=0,
                output_tokens=0,
                tape=tape,
                error=f"{type(e).__name__}: {e}",
            )
        else:
            outcome = SubagentResult(
                label=name,
                text=result.text or "",
                steps=result.steps,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                tape=tape,
            )
        self._record(outcome, task=task)
        return outcome

    def _record(self, outcome: SubagentResult, *, task: str) -> None:
        if self.parent_store is None:
            return
        self.parent_store.append(
            Event(
                kind="subagent",
                step=0,
                payload={
                    "label": outcome.label,
                    "task": task,
                    "tape": outcome.tape.name if outcome.tape else None,
                    "steps": outcome.steps,
                    "ok": outcome.ok,
                    "error": outcome.error,
                },
            )
        )


def fan_out(
    spawner: Spawner, tasks: Sequence[tuple[str, str]], *, tools: Registry
) -> list[SubagentResult]:
    """Run each (label, task) as its own child. Sequential; see `pipeline` for why."""
    return [spawner.spawn(task, tools=tools, label=label) for label, task in tasks]
