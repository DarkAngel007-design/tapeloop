"""Running a suite: every task, several seeds, one row each.

The seeds are the point. A single agent run is high-variance, so one pass proves
nothing and a lucky pass is worse than nothing — it is a number you will quote.
Every task runs `repeats` times against a fresh workspace, and the report carries
the spread rather than hiding it behind a mean.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tapeloop.core.loop import Agent
from tapeloop.eval.base import Grade
from tapeloop.eval.graders import LlmJudge, bind_workspace
from tapeloop.eval.task import Suite, Task
from tapeloop.record.jsonl import JsonlStore
from tapeloop.tools import builtin

AgentFactory = Callable[[Path, Path], Agent]
"""(workspace, tape) -> a configured Agent. The caller owns client and policy."""


@dataclass(slots=True)
class Attempt:
    task_id: str
    seed: int
    passed: bool
    grades: list[Grade] = field(default_factory=list[Grade])
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tape: Path | None = None
    error: str | None = None
    judge_agreement: float | None = None

    @property
    def score(self) -> float:
        return 1.0 if self.passed else 0.0


@dataclass(slots=True)
class SuiteRun:
    suite: str
    attempts: list[Attempt] = field(default_factory=list[Attempt])
    judge_model: str | None = None
    judge_prompt_version: str | None = None
    model: str = ""
    provider: str = ""


def default_factory(model: str, client_factory: Callable[[], object]) -> AgentFactory:
    def make(workspace: Path, tape: Path) -> Agent:
        return Agent(
            client=client_factory(),  # pyright: ignore[reportArgumentType]
            registry=builtin.build(workspace),
            model=model,
            store=JsonlStore(tape),
        )

    return make


def run_task(
    task: Task,
    *,
    factory: AgentFactory,
    root: Path,
    seed: int,
) -> Attempt:
    """One attempt: a fresh workspace, a fresh tape, then grade."""
    workspace = root / "workspaces" / f"{task.id}-s{seed}"
    tape = root / "tapes" / f"{task.id}-s{seed}.jsonl"
    task.prepare(workspace)
    # Graders bind *before* the agent runs: NoFileChanged has to see the starting state.
    bind_workspace(task.graders, workspace)

    attempt = Attempt(task_id=task.id, seed=seed, passed=False, tape=tape)
    agent = factory(workspace, tape)
    agent.max_steps = task.max_steps
    try:
        result = agent.run(task.prompt)
    except Exception as e:  # a crashed run is a failed attempt, not a crashed suite
        attempt.error = f"{type(e).__name__}: {e}"
        return attempt

    attempt.steps = result.steps
    attempt.input_tokens = result.usage.input_tokens
    attempt.output_tokens = result.usage.output_tokens

    actual = result.text or ""
    for grader in task.graders:
        grade = grader.grade(expected=task.expected or task.prompt, actual=actual)
        attempt.grades.append(grade)
        if isinstance(grader, LlmJudge):
            attempt.judge_agreement = _agreement(grade)
    # Every grader must pass. A task with two requirements is not half-done.
    attempt.passed = bool(attempt.grades) and all(g.passed for g in attempt.grades)
    return attempt


def _agreement(grade: Grade) -> float | None:
    marker = "agreement="
    if marker not in grade.reason:
        return None
    try:
        return float(grade.reason.split(marker, 1)[1].split()[0])
    except (IndexError, ValueError):
        return None


def run_suite(
    suite: Suite,
    *,
    factory: AgentFactory,
    root: Path,
    repeats: int = 5,
    model: str = "",
    provider: str = "",
    judge: LlmJudge | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
) -> SuiteRun:
    run = SuiteRun(
        suite=suite.name,
        model=model,
        provider=provider,
        judge_model=judge.model if judge else None,
        judge_prompt_version=judge.prompt_version if judge else None,
    )
    for task in suite.tasks:
        for seed in range(repeats):
            attempt = run_task(task, factory=factory, root=root, seed=seed)
            run.attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
    return run
