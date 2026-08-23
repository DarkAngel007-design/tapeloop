"""Diff two runs, step by step.

Anchored on step keys rather than text. Two runs are the same until their keys
stop matching, and the *first* divergence is the only one that explains anything —
everything after it is downstream of that one change. So the report leads with it
and treats the rest as consequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tapeloop.replay.recording import Recording


class StepStatus(StrEnum):
    SAME = "same"
    CHANGED = "changed"
    ONLY_A = "only-a"
    ONLY_B = "only-b"


@dataclass(frozen=True, slots=True)
class StepDiff:
    index: int
    status: StepStatus
    a_text: str | None = None
    b_text: str | None = None
    a_tools: tuple[str, ...] = ()
    b_tools: tuple[str, ...] = ()


@dataclass(slots=True)
class DiffReport:
    a: Path
    b: Path
    steps: list[StepDiff]

    @property
    def diverged_at(self) -> int | None:
        return next((s.index for s in self.steps if s.status is not StepStatus.SAME), None)

    @property
    def identical(self) -> bool:
        return self.diverged_at is None

    def render(self) -> str:
        head = f"{self.a.name} → {self.b.name}"
        if self.identical:
            return f"{head}\n  identical: {len(self.steps)} steps, every key matched"

        lines = [head, f"  diverged at step {self.diverged_at}"]
        for step in self.steps:
            mark = {
                StepStatus.SAME: "  =",
                StepStatus.CHANGED: "  ~",
                StepStatus.ONLY_A: "  -",
                StepStatus.ONLY_B: "  +",
            }[step.status]
            if step.status is StepStatus.SAME:
                lines.append(f"{mark} {step.index}  (cached)")
                continue
            lines.append(f"{mark} {step.index}")
            if step.a_tools or step.b_tools:
                lines.append(f"      a tools: {', '.join(step.a_tools) or '—'}")
                lines.append(f"      b tools: {', '.join(step.b_tools) or '—'}")
            if step.a_text or step.b_text:
                lines.append(f"      a: {_clip(step.a_text)}")
                lines.append(f"      b: {_clip(step.b_text)}")
        return "\n".join(lines)


def _clip(text: str | None, limit: int = 90) -> str:
    if not text:
        return "—"
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def diff_tapes(a: Path, b: Path) -> DiffReport:
    left, right = Recording.load(a), Recording.load(b)
    steps: list[StepDiff] = []

    for index in range(max(len(left.steps), len(right.steps))):
        ls = left.steps[index] if index < len(left.steps) else None
        rs = right.steps[index] if index < len(right.steps) else None

        if ls and rs:
            status = StepStatus.SAME if ls.key == rs.key else StepStatus.CHANGED
        elif ls:
            status = StepStatus.ONLY_A
        else:
            status = StepStatus.ONLY_B

        steps.append(
            StepDiff(
                index=index,
                status=status,
                a_text=ls.response.message.text if ls else None,
                b_text=rs.response.message.text if rs else None,
                a_tools=tuple(c.name for c in ls.response.message.tool_calls) if ls else (),
                b_tools=tuple(c.name for c in rs.response.message.tool_calls) if rs else (),
            )
        )
    return DiffReport(a=a, b=b, steps=steps)
