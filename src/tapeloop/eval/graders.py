"""Graders beyond exact match.

The deterministic ones are preferred wherever a task admits them: they cost nothing,
never disagree with themselves, and cannot drift when a provider updates a model.
``LlmJudge`` exists for tasks that genuinely have no fixed correct output, under the
four conditions in ADR-0018.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from tapeloop.eval.base import Grade
from tapeloop.events import Message, ModelResponse, user
from tapeloop.providers.base import ModelClient

JUDGE_PROMPT_VERSION = "1"

JUDGE_PROMPT = """You are grading whether an AI agent completed a task.

TASK GIVEN TO THE AGENT:
{prompt}

WHAT SUCCESS REQUIRES:
{rubric}

WHAT THE AGENT PRODUCED:
{actual}

Answer with exactly one line: PASS or FAIL, then a dash and one sentence of reason.
Judge only against the requirement above. Do not reward effort, apology, or plausible
narration about work that is not evidenced."""


@dataclass(slots=True)
class FileContains:
    """A file exists under the workspace and contains a substring."""

    path: str
    needle: str = ""
    workspace: Path | None = None

    def grade(self, *, expected: str, actual: str) -> Grade:
        if self.workspace is None:
            return Grade(passed=False, reason="grader was not bound to a workspace")
        target = self.workspace / self.path
        if not target.exists():
            return Grade(passed=False, reason=f"{self.path} was not created")
        text = target.read_text(encoding="utf-8", errors="replace")
        needle = self.needle or expected
        if needle and needle not in text:
            return Grade(passed=False, reason=f"{self.path} does not contain {needle!r}")
        return Grade(passed=True, score=1.0)


@dataclass(slots=True)
class PythonBehaviour:
    """Import a file from the workspace and assert it now behaves correctly.

    Added after the machinery check caught `fix-the-bug` passing against a model
    that did nothing at all: its grader looked for text that the setup already
    contained. A substring check on a file you also seeded proves nothing. For a
    code-change task, run the code.

    **Security: this executes code the agent wrote, in this process, unsandboxed.**
    That is inherent to grading a code-change task -- you cannot check that a fix
    works without running it -- but it is arbitrary code execution and is stated
    here rather than left implicit behind a lint suppression. It is reachable only
    from the eval suite, never from the agent loop. Run evals on tasks you wrote,
    in a container, and never against a workspace you do not control. Routing this
    through the `Executor` seam is the proper fix and is not done yet.
    """

    module: str
    check: str
    """A Python expression evaluated with the module's globals. Must be truthy."""
    workspace: Path | None = None

    def grade(self, *, expected: str, actual: str) -> Grade:
        if self.workspace is None:
            return Grade(passed=False, reason="grader was not bound to a workspace")
        target = self.workspace / self.module
        if not target.exists():
            return Grade(passed=False, reason=f"{self.module} is missing")
        namespace: dict[str, object] = {}
        try:
            exec(compile(target.read_text(encoding="utf-8"), self.module, "exec"), namespace)  # noqa: S102
        except Exception as e:
            return Grade(passed=False, reason=f"{self.module} does not import: {e}")
        try:
            ok = bool(eval(self.check, namespace))  # noqa: S307
        except Exception as e:
            return Grade(passed=False, reason=f"{self.check} raised {type(e).__name__}: {e}")
        return Grade(
            passed=ok, score=1.0 if ok else 0.0, reason="" if ok else f"{self.check} false"
        )


@dataclass(slots=True)
class Contains:
    """The agent's final message mentions something. Weak; use only where apt."""

    def grade(self, *, expected: str, actual: str) -> Grade:
        ok = expected.lower() in actual.lower()
        return Grade(passed=ok, score=1.0 if ok else 0.0, reason="" if ok else "not mentioned")


@dataclass(slots=True)
class NoFileChanged:
    """Nothing was written. For tasks whose correct answer is to decline."""

    workspace: Path | None = None
    before: dict[str, float] = field(default_factory=dict[str, float])

    def snapshot(self) -> None:
        if self.workspace is None:
            return
        self.before = {
            str(p.relative_to(self.workspace)): p.stat().st_mtime
            for p in self.workspace.rglob("*")
            if p.is_file()
        }

    def grade(self, *, expected: str, actual: str) -> Grade:
        if self.workspace is None:
            return Grade(passed=False, reason="grader was not bound to a workspace")
        now = {
            str(p.relative_to(self.workspace)): p.stat().st_mtime
            for p in self.workspace.rglob("*")
            if p.is_file()
        }
        if now != self.before:
            changed = set(now) ^ set(self.before)
            return Grade(passed=False, reason=f"workspace changed: {sorted(changed) or 'in place'}")
        return Grade(passed=True, score=1.0)


@dataclass(frozen=True, slots=True)
class Judgment:
    passed: bool
    reason: str


@dataclass(slots=True)
class LlmJudge:
    """ADR-0018: pinned, recorded, measured, and reported separately.

    ``k`` judgments are taken per grade. The majority decides, and the spread is
    surfaced as agreement — a judge that disagrees with itself is a fact about the
    result, not something to average away.
    """

    client: ModelClient
    model: str
    """Pinned. A results table that cannot name its judge is not a baseline."""
    rubric: str = ""
    k: int = 3
    is_judge: bool = True
    prompt_version: str = JUDGE_PROMPT_VERSION
    judgments: list[Judgment] = field(default_factory=list[Judgment])

    def grade(self, *, expected: str, actual: str) -> Grade:
        rubric = self.rubric or expected
        verdicts: list[Judgment] = []
        for _ in range(self.k):
            verdicts.append(self._judge_once(prompt=expected, rubric=rubric, actual=actual))
        self.judgments = verdicts

        passes = sum(1 for v in verdicts if v.passed)
        agreement = max(passes, len(verdicts) - passes) / len(verdicts)
        majority = passes * 2 > len(verdicts)
        reason = "; ".join(dict.fromkeys(v.reason for v in verdicts if v.reason))
        return Grade(
            passed=majority,
            score=passes / len(verdicts),
            reason=f"agreement={agreement:.2f} :: {reason}"[:400],
        )

    def _judge_once(self, *, prompt: str, rubric: str, actual: str) -> Judgment:
        messages: Sequence[Message] = [
            user(JUDGE_PROMPT.format(prompt=prompt, rubric=rubric, actual=actual or "(nothing)"))
        ]
        response: ModelResponse = self.client.complete(
            model=self.model, messages=messages, max_tokens=200
        )
        text = (response.message.text or "").strip()
        head = text.splitlines()[0] if text else ""
        # Unparseable is a FAIL, never a silent pass: a judge that returned
        # something unexpected has not agreed that the task succeeded.
        passed = head.upper().startswith("PASS")
        return Judgment(passed=passed, reason=head[:200])


@runtime_checkable
class WorkspaceAware(Protocol):
    """A grader that inspects the workspace rather than the agent's final message."""

    workspace: Path | None


@runtime_checkable
class Snapshotting(Protocol):
    """A grader that must observe the workspace *before* the run to grade after it."""

    def snapshot(self) -> None: ...


def bind_workspace(graders: Sequence[object], workspace: Path) -> None:
    """Point workspace-aware graders at this run's directory, before the agent starts."""
    for grader in graders:
        if isinstance(grader, WorkspaceAware):
            grader.workspace = workspace
        if isinstance(grader, Snapshotting):
            grader.snapshot()


__all__ = [
    "JUDGE_PROMPT",
    "JUDGE_PROMPT_VERSION",
    "Contains",
    "FileContains",
    "Judgment",
    "LlmJudge",
    "NoFileChanged",
    "PythonBehaviour",
    "Snapshotting",
    "WorkspaceAware",
    "bind_workspace",
]
