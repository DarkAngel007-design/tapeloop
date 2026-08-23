"""A task: a prompt, a workspace to set up, and how to tell whether it worked."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tapeloop.eval.base import Grader


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    prompt: str
    graders: Sequence[Grader]
    setup: Callable[[Path], None] | None = None
    """Writes the starting workspace. Runs fresh for every seed."""
    tags: tuple[str, ...] = ()
    max_steps: int = 12
    expected: str = ""
    """Passed to graders. A rubric for a judge, a literal for an exact match."""

    def prepare(self, workspace: Path) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        if self.setup is not None:
            self.setup(workspace)

    @property
    def is_judged(self) -> bool:
        """Judged and deterministic scores are reported separately (ADR-0018)."""
        return any(getattr(g, "is_judge", False) for g in self.graders)


@dataclass(slots=True)
class Suite:
    name: str
    tasks: list[Task] = field(default_factory=list[Task])

    def add(self, task: Task) -> Task:
        if any(t.id == task.id for t in self.tasks):
            raise ValueError(f"duplicate task id: {task.id}")
        self.tasks.append(task)
        return task

    def __len__(self) -> int:
        return len(self.tasks)
